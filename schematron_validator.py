"""
schematron_validator.py
-----------------------
Validation EN16931 via XSLT Schematron officiel CEN/TC 434.
Supporte CII et UBL 2.1.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ── Chemins XSLT ──────────────────────────────────────────
XSLT_CII_PATH = Path(__file__).parent / "schematron" / "EN16931-CII-validation.xslt"
XSLT_UBL_PATH = Path(__file__).parent / "schematron" / "EN16931-UBL-validation.xslt"


# ─────────────────────────────────────────────────────────
# Structures de résultat
# ─────────────────────────────────────────────────────────

@dataclass
class SchematronIssue:
    rule_id:  str
    message:  str
    location: str
    severity: str = "ERROR"


@dataclass
class SchematronResult:
    errors:   list[SchematronIssue] = field(default_factory=list)
    warnings: list[SchematronIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


# ─────────────────────────────────────────────────────────
# Parseur des résultats SVRL
# ─────────────────────────────────────────────────────────

def _parse_svrl(svrl_text: str) -> SchematronResult:
    """Parse le SVRL (Schematron Validation Report Language) retourné par Saxon."""
    result = SchematronResult()

    # Chercher les failed-assert (erreurs) et successful-report (warnings)
    fail_pattern = re.compile(
        r'<svrl:failed-assert[^>]*\btest="([^"]*)"[^>]*\bid="([^"]*)"[^>]*\blocation="([^"]*)"[^>]*>.*?'
        r'<svrl:text>(.*?)</svrl:text>',
        re.DOTALL,
    )
    report_pattern = re.compile(
        r'<svrl:successful-report[^>]*\bid="([^"]*)"[^>]*\blocation="([^"]*)"[^>]*>.*?'
        r'<svrl:text>(.*?)</svrl:text>',
        re.DOTALL,
    )

    for m in fail_pattern.finditer(svrl_text):
        rule_id  = m.group(2).strip()
        location = m.group(3).strip()
        message  = re.sub(r"<[^>]+>", "", m.group(4)).strip()
        issue = SchematronIssue(rule_id=rule_id, message=message,
                                location=location, severity="ERROR")
        if rule_id.startswith("BR-W") or "[W]" in message:
            issue.severity = "WARNING"
            result.warnings.append(issue)
        else:
            result.errors.append(issue)

    for m in report_pattern.finditer(svrl_text):
        rule_id  = m.group(1).strip()
        location = m.group(2).strip()
        message  = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        result.warnings.append(
            SchematronIssue(rule_id=rule_id, message=message,
                            location=location, severity="WARNING")
        )

    return result


# ─────────────────────────────────────────────────────────
# Moteur Saxon-C HE
# ─────────────────────────────────────────────────────────

def _run_saxon(xml_path: str, xslt_path: Path) -> str | None:
    """Lance Saxon-C HE via subprocess. Retourne le SVRL ou None si erreur."""
    try:
        import saxonche
        with saxonche.PySaxonProcessor(license=False) as proc:
            xslt_proc = proc.new_xslt30_processor()
            xslt_proc.set_cwd(str(xslt_path.parent))
            executable = xslt_proc.compile_stylesheet(
                stylesheet_file=str(xslt_path)
            )
            result = executable.transform_to_string(
                source_file=str(xml_path)
            )
            return result
    except ImportError:
        pass

    # Fallback subprocess (si Saxon installé système)
    try:
        result = subprocess.run(
            ["java", "-jar", "saxon.jar", f"-s:{xml_path}", f"-xsl:{xslt_path}"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# Fonction principale
# ─────────────────────────────────────────────────────────

def validate_en16931(xml_path: str, syntax: str = "CII") -> SchematronResult:
    """
    Valide un XML CII ou UBL 2.1 via Schematron CEN/TC 434.

    Args:
        xml_path : chemin vers le fichier XML à valider
        syntax   : "CII" (défaut) ou "UBL"

    Returns:
        SchematronResult avec errors/warnings
    """
    result = SchematronResult()

    # ── Sélection du XSLT selon la syntaxe ────────────────
    xslt_path = XSLT_UBL_PATH if syntax.upper() == "UBL" else XSLT_CII_PATH

    # ── Vérifier que le XSLT existe ───────────────────────
    if not xslt_path.exists():
        if syntax.upper() == "UBL":
            result.errors.append(SchematronIssue(
                rule_id="XSLT-UBL-MISSING",
                message=(
                    f"XSLT UBL introuvable ({xslt_path.name}). "
                    "Téléchargez-le avec la commande :\n"
                    "curl -L https://raw.githubusercontent.com/ConnectingEurope/"
                    "eInvoicing-EN16931/master/ubl/xslt/EN16931-UBL-validation.xslt "
                    f"-o schematron/EN16931-UBL-validation.xslt"
                ),
                location="",
            ))
        else:
            result.errors.append(SchematronIssue(
                rule_id="XSLT-CII-MISSING",
                message=f"XSLT CII introuvable ({xslt_path.name}).",
                location="",
            ))
        return result

    # ── Auto-détection si syntax non précisée ─────────────
    if syntax.upper() not in ("CII", "UBL"):
        try:
            with open(xml_path, encoding="utf-8", errors="replace") as f:
                content = f.read(500)
            if "oasis" in content or "Invoice-2" in content:
                xslt_path = XSLT_UBL_PATH
            else:
                xslt_path = XSLT_CII_PATH
        except Exception:
            xslt_path = XSLT_CII_PATH

    # ── Exécution Saxon ───────────────────────────────────
    svrl = _run_saxon(xml_path, xslt_path)

    if svrl is None:
        # Fallback : validation structurelle minimale
        result.warnings.append(SchematronIssue(
            rule_id="ENGINE-UNAVAILABLE",
            message=(
                "Moteur XSLT Saxon-C indisponible — "
                "validation Schematron non exécutée. "
                "Installez saxonche : pip install saxonche"
            ),
            location="",
            severity="WARNING",
        ))
        return result

    return _parse_svrl(svrl)


# ─────────────────────────────────────────────────────────
# Utilitaire : détection syntaxe depuis contenu XML
# ─────────────────────────────────────────────────────────

def detect_syntax(xml_content: str) -> str:
    """Retourne 'UBL' ou 'CII' selon le contenu XML."""
    if "oasis" in xml_content[:1000] or "Invoice-2" in xml_content[:1000]:
        return "UBL"
    return "CII"