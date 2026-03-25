"""
schematron_validator.py
-----------------------
Valide une facture Factur-X (CII) contre les règles officielles
EN 16931 du CEN/TC 434 via le fichier XSLT officiel.

Sources :
  - XSLT : https://github.com/ConnectingEurope/eInvoicing-EN16931
  - Spec  : CEN/TC 434 — EN 16931-1:2017+A1:2019

Résultat : liste de SchematronIssue (rule_id, message, severity, location)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

# ─── Namespace SVRL (Schematron Validation Reporting Language) ───
SVRL = "http://purl.oclc.org/dsdl/svrl"

# ─── Chemin par défaut du XSLT (dans le repo) ───
DEFAULT_XSLT = Path(__file__).parent / "schematron" / "EN16931-CII-validation.xslt"

# ─── URL de fallback si le fichier local est absent ───
XSLT_URL = (
    "https://raw.githubusercontent.com/ConnectingEurope/"
    "eInvoicing-EN16931/master/cii/xslt/EN16931-CII-validation.xslt"
)


@dataclass
class SchematronIssue:
    rule_id: str
    message: str
    severity: str          # "ERROR" | "WARNING"
    location: str = ""
    source: str = "EN16931 CEN/TC 434"


@dataclass
class SchematronResult:
    issues: list[SchematronIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[SchematronIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> list[SchematronIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _load_transform(xslt_path: Path) -> etree.XSLT:
    """Charge le XSLT, avec téléchargement automatique si absent."""
    if not xslt_path.exists():
        import requests
        xslt_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"📥 Téléchargement du XSLT EN16931 depuis GitHub...")
        r = requests.get(XSLT_URL, timeout=15)
        r.raise_for_status()
        xslt_path.write_bytes(r.content)
        print(f"✅ XSLT sauvegardé : {xslt_path}")

    xslt_doc = etree.parse(str(xslt_path))
    return etree.XSLT(xslt_doc)


def validate_en16931(
    xml_path: str,
    xslt_path: Path = DEFAULT_XSLT,
) -> SchematronResult:
    """
    Valide le fichier XML CII contre les ~120 règles BR-* officielles.

    Params
    ------
    xml_path  : chemin vers la facture XML à valider
    xslt_path : chemin local vers le fichier XSLT (auto-téléchargé si absent)

    Returns
    -------
    SchematronResult avec la liste des issues BR-*
    """
    result = SchematronResult()

    # Charger et transformer
    try:
        transform = _load_transform(xslt_path)
        xml_doc = etree.parse(xml_path)
        svrl_doc = transform(xml_doc)
    except Exception as e:
        result.issues.append(SchematronIssue(
            rule_id="XSLT-ERR",
            message=f"Erreur lors de l'exécution du Schematron : {e}",
            severity="ERROR",
        ))
        return result

    # Parser les assertions échouées (règles violées)
    for node in svrl_doc.getroot().iter(f"{{{SVRL}}}failed-assert"):
        text_el = node.find(f"{{{SVRL}}}text")
        message = text_el.text.strip() if text_el is not None and text_el.text else "(sans message)"

        # flag="fatal" → ERROR, sinon WARNING
        flag = node.get("flag", "warning")
        severity = "ERROR" if flag == "fatal" else "WARNING"

        result.issues.append(SchematronIssue(
            rule_id=node.get("id", "BR-??"),
            message=message,
            severity=severity,
            location=node.get("location", ""),
        ))

    # Parser les rapports déclenchés (certains indiquent aussi des erreurs)
    for node in svrl_doc.getroot().iter(f"{{{SVRL}}}successful-report"):
        flag = node.get("flag", "")
        if flag == "fatal":
            text_el = node.find(f"{{{SVRL}}}text")
            message = text_el.text.strip() if text_el is not None and text_el.text else "(sans message)"
            result.issues.append(SchematronIssue(
                rule_id=node.get("id", "BR-??"),
                message=message,
                severity="ERROR",
                location=node.get("location", ""),
            ))

    return result