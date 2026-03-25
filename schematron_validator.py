"""
schematron_validator.py
-----------------------
Valide une facture Factur-X (CII) contre les règles officielles
EN 16931 du CEN/TC 434 via le fichier XSLT officiel (v1.3.15).

Moteur XSLT : Saxon-C HE (XSLT 3.0) via saxonche
— nécessaire car le schematron CEN utilise XPath 2.0+ (xs:decimal, upper-case…)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

try:
    from saxonche import PySaxonProcessor
    SAXON_AVAILABLE = True
except ImportError:
    SAXON_AVAILABLE = False

SVRL       = "http://purl.oclc.org/dsdl/svrl"
DEFAULT_XSLT = Path(__file__).parent / "schematron" / "EN16931-CII-validation.xslt"
XSLT_URL   = (
    "https://raw.githubusercontent.com/ConnectingEurope/"
    "eInvoicing-EN16931/master/cii/xslt/EN16931-CII-validation.xslt"
)


@dataclass
class SchematronIssue:
    rule_id:  str
    message:  str
    severity: str   # "ERROR" | "WARNING"
    location: str = ""
    source:   str = "EN16931 CEN/TC 434 v1.3.15"


@dataclass
class SchematronResult:
    issues: list[SchematronIssue] = field(default_factory=list)

    @property
    def errors(self)   -> list[SchematronIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> list[SchematronIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _ensure_xslt(xslt_path: Path) -> None:
    """Télécharge le XSLT si absent."""
    if not xslt_path.exists():
        import requests
        xslt_path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(XSLT_URL, timeout=15)
        r.raise_for_status()
        xslt_path.write_bytes(r.content)


def _parse_svrl(svrl_xml: str) -> list[SchematronIssue]:
    """Extrait les issues depuis la sortie SVRL."""
    issues = []
    try:
        root = etree.fromstring(svrl_xml.encode("utf-8"))
    except Exception:
        return issues

    for node in root.iter(f"{{{SVRL}}}failed-assert"):
        text_el  = node.find(f"{{{SVRL}}}text")
        message  = (text_el.text or "").strip() if text_el is not None else ""
        severity = "ERROR" if node.get("flag") == "fatal" else "WARNING"
        issues.append(SchematronIssue(
            rule_id  = node.get("id", "BR-??"),
            message  = message,
            severity = severity,
            location = node.get("location", ""),
        ))

    for node in root.iter(f"{{{SVRL}}}successful-report"):
        if node.get("flag") == "fatal":
            text_el = node.find(f"{{{SVRL}}}text")
            message = (text_el.text or "").strip() if text_el is not None else ""
            issues.append(SchematronIssue(
                rule_id  = node.get("id", "BR-??"),
                message  = message,
                severity = "ERROR",
                location = node.get("location", ""),
            ))
    return issues


def validate_en16931(
    xml_path:  str,
    xslt_path: Path = DEFAULT_XSLT,
) -> SchematronResult:
    """
    Valide le XML CII contre les ~120 règles BR-* officielles CEN/TC 434.
    Utilise Saxon-C HE (XSLT 3.0) si disponible.
    """
    result = SchematronResult()

    if not SAXON_AVAILABLE:
        result.issues.append(SchematronIssue(
            rule_id  = "SETUP-ERR",
            message  = "saxonche non installé — pip install saxonche",
            severity = "ERROR",
        ))
        return result

    try:
        _ensure_xslt(xslt_path)

        with PySaxonProcessor(license=False) as proc:
            xslt_proc  = proc.new_xslt30_processor()
            executable = xslt_proc.compile_stylesheet(
                stylesheet_file=str(xslt_path.resolve())
            )
            svrl_output = executable.transform_to_string(
                source_file=str(Path(xml_path).resolve())
            )

        if svrl_output:
            result.issues = _parse_svrl(svrl_output)
        else:
            result.issues.append(SchematronIssue(
                rule_id  = "XSLT-EMPTY",
                message  = "Le moteur XSLT n'a retourné aucun résultat",
                severity = "WARNING",
            ))

    except Exception as e:
        result.issues.append(SchematronIssue(
            rule_id  = "XSLT-ERR",
            message  = f"Erreur Schematron : {e}",
            severity = "ERROR",
        ))

    return result