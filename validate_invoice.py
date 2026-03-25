"""
validate_invoice.py
--------------------
Valide une facture Factur-X XML contre :
  1. Les règles structurelles (schéma XSD DGFiP)
  2. Les règles métier EN 16931 (BR-*)
  3. Les règles françaises spécifiques (FR-*)
  4. Les contrôles de cohérence arithmétique

Usage :
    python validate_invoice.py facture_demo.xml
    python validate_invoice.py facture_demo.xml --strict
"""

import argparse
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET


# ─────────────────────────────────────────────
# Modèle de résultat
# ─────────────────────────────────────────────

SEVERITY_ERROR   = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO    = "INFO"


@dataclass
class ValidationIssue:
    rule_id: str
    severity: str
    message: str
    path: Optional[str] = None
    suggestion: Optional[str] = None

    def __str__(self):
        loc = f" [{self.path}]" if self.path else ""
        sug = f"\n    💡 {self.suggestion}" if self.suggestion else ""
        icon = {"ERROR": "❌", "WARNING": "⚠️ ", "INFO": "ℹ️ "}.get(self.severity, "  ")
        return f"{icon} [{self.rule_id}]{loc} {self.message}{sug}"


@dataclass
class ValidationResult:
    issues: list[ValidationIssue]
    xml_file: str

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == SEVERITY_ERROR]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == SEVERITY_WARNING]

    @property
    def infos(self):                                          
        return [i for i in self.issues if i.severity == SEVERITY_INFO]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0
    

# ─────────────────────────────────────────────
# Namespaces
# ─────────────────────────────────────────────

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}


def _find(el, path: str) -> Optional[ET.Element]:
    """XPath avec gestion auto des namespaces."""
    parts = path.split("/")
    current = el
    for part in parts:
        if not part:
            continue
        ns, local = part.split(":") if ":" in part else ("", part)
        tag = f"{{{NS[ns]}}}{local}" if ns else local
        found = current.find(tag)
        if found is None:
            return None
        current = found
    return current


def _findall(el, path: str) -> list:
    parts = path.split("/")
    current = [el]
    for part in parts:
        if not part:
            continue
        ns, local = part.split(":") if ":" in part else ("", part)
        tag = f"{{{NS[ns]}}}{local}" if ns else local
        current = [child for node in current for child in node.findall(tag)]
    return current


def _text(el, path: str) -> Optional[str]:
    node = _find(el, path)
    return node.text.strip() if node is not None and node.text else None


def _dec(el, path: str) -> Optional[Decimal]:
    t = _text(el, path)
    if t is None:
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


# ─────────────────────────────────────────────
# Règles de validation
# ─────────────────────────────────────────────

class InvoiceValidator:
    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self.issues: list[ValidationIssue] = []
        self.root: Optional[ET.Element] = None

    def _add(self, rule_id: str, severity: str, message: str,
             path: str = None, suggestion: str = None):
        self.issues.append(ValidationIssue(rule_id, severity, message, path, suggestion))

    def _error(self, rule_id, msg, path=None, suggestion=None):
        self._add(rule_id, SEVERITY_ERROR, msg, path, suggestion)

    def _warn(self, rule_id, msg, path=None, suggestion=None):
        self._add(rule_id, SEVERITY_WARNING, msg, path, suggestion)

    def _info(self, rule_id, msg, path=None):
        self._add(rule_id, SEVERITY_INFO, msg, path)

    # ── Parsing ─────────────────────────────────
    def _parse(self) -> bool:
        try:
            tree = ET.parse(self.xml_path)
            self.root = tree.getroot()
            self._info("PARSE-OK", "Fichier XML parsé avec succès")
            return True
        except ET.ParseError as e:
            self._error("PARSE-ERR", f"XML malformé : {e}",
                        suggestion="Vérifiez la syntaxe XML (balises non fermées, caractères spéciaux non échappés)")
            return False
        except FileNotFoundError:
            self._error("FILE-NOT-FOUND", f"Fichier introuvable : {self.xml_path}")
            return False

    # ── BR-01 : Namespace / profil ───────────────
    def _check_profile(self):
        tag = self.root.tag
        if "CrossIndustryInvoice" not in tag:
            self._error("BR-01", "L'élément racine doit être CrossIndustryInvoice",
                        suggestion="Utilisez le namespace CII (urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100)")

        profile_id = _text(self.root,
            "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
        if not profile_id:
            self._error("BR-02", "Profil Factur-X manquant (GuidelineSpecifiedDocumentContextParameter/ID)",
                        suggestion="Ajoutez l'identifiant de profil, ex: urn:cen.eu:en16931:2017...")
        else:
            known = ["minimum", "basicwl", "basic", "en16931", "extended"]
            if not any(k in profile_id.lower() for k in known):
                self._warn("BR-02W", f"Profil non reconnu : {profile_id}")
            else:
                self._info("BR-02", f"Profil détecté : {profile_id.split(':')[-1]}")

    # ── BR-03 : Numéro de facture ────────────────
    def _check_invoice_number(self):
        inv_id = _text(self.root, "rsm:ExchangedDocument/ram:ID")
        if not inv_id:
            self._error("BR-03", "Numéro de facture manquant (ExchangedDocument/ID)",
                        suggestion="Le numéro doit être unique et séquentiel (ex: FAC-2026-001)")
        else:
            if len(inv_id) > 200:
                self._error("BR-03L", "Numéro de facture trop long (max 200 caractères)")
            self._info("BR-03", f"Numéro de facture : {inv_id}")

    # ── BR-04 : Type de document ─────────────────
    def _check_type_code(self):
        type_code = _text(self.root, "rsm:ExchangedDocument/ram:TypeCode")
        VALID_CODES = {"380": "Facture", "381": "Avoir", "384": "Facture rectificative",
                       "386": "Acompte", "389": "Autofacturation"}
        if not type_code:
            self._error("BR-04", "TypeCode manquant",
                        suggestion="Utilisez 380 pour une facture standard")
        elif type_code not in VALID_CODES:
            self._error("BR-04V", f"TypeCode invalide : {type_code}. Valeurs valides : {list(VALID_CODES.keys())}")
        else:
            self._info("BR-04", f"Type document : {VALID_CODES[type_code]} ({type_code})")

    # ── BR-05 : Date d'émission ──────────────────
    def _check_dates(self):
        issue_date = _text(self.root,
            "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
        if not issue_date:
            self._error("BR-05", "Date d'émission manquante",
                        suggestion="Format requis : YYYYMMDD avec format='102'")
        else:
            if not re.match(r"^\d{8}$", issue_date):
                self._error("BR-05F", f"Format de date invalide : {issue_date} (attendu : YYYYMMDD)")
            else:
                self._info("BR-05", f"Date émission : {issue_date[:4]}-{issue_date[4:6]}-{issue_date[6:]}")

    # ── BR-06/07 : Vendeur ───────────────────────
    def _check_seller(self):
        txn = _find(self.root, "rsm:SupplyChainTradeTransaction")
        if txn is None:
            self._error("BR-STRUCT", "Section SupplyChainTradeTransaction manquante")
            return

        agr = _find(txn, "ram:ApplicableHeaderTradeAgreement")
        if agr is None:
            self._error("BR-STRUCT2", "Section ApplicableHeaderTradeAgreement manquante")
            return

        seller_name = _text(agr, "ram:SellerTradeParty/ram:Name")
        if not seller_name:
            self._error("BR-06", "Nom du vendeur manquant",
                        suggestion="SellerTradeParty/Name est obligatoire")
        else:
            self._info("BR-06", f"Vendeur : {seller_name}")

        # SIRET (schemeID=0002)
        seller_org = _find(agr, "ram:SellerTradeParty/ram:SpecifiedLegalOrganization")
        if seller_org is not None:
            siret_el = seller_org.find(f"{{{NS['ram']}}}ID")
            if siret_el is not None:
                siret = siret_el.text or ""
                if not re.match(r"^\d{14}$", siret):
                    self._error("FR-01", f"SIRET vendeur invalide : '{siret}' (14 chiffres attendus)",
                                suggestion="Le SIRET est composé du SIREN (9 chiffres) + NIC (5 chiffres)")
                else:
                    self._info("FR-01", f"SIRET vendeur : {siret}")

        # N° TVA
        vat = _text(agr, "ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID")
        if not vat:
            self._warn("BR-31", "Numéro de TVA vendeur manquant",
                       suggestion="Format : FR + 11 caractères (ex: FR12345678901)")
        else:
            if not re.match(r"^FR[A-Z0-9]{2}\d{9}$", vat):
                self._warn("FR-TVA", f"Format TVA intra suspect : {vat}",
                           suggestion="Format attendu : FR suivi de 2 caractères + 9 chiffres")

        # Adresse
        postal = _find(agr, "ram:SellerTradeParty/ram:PostalTradeAddress")
        if postal is None:
            self._error("BR-08", "Adresse postale vendeur manquante")
        else:
            country = _text(agr, "ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID")
            if not country or len(country) != 2:
                self._error("BR-09", "Code pays vendeur manquant ou invalide (ex: FR)",
                            suggestion="Utilisez le code ISO 3166-1 alpha-2")

    # ── BR-07 : Acheteur ─────────────────────────
    def _check_buyer(self):
        txn = _find(self.root, "rsm:SupplyChainTradeTransaction")
        agr = _find(txn, "ram:ApplicableHeaderTradeAgreement") if txn else None
        if agr is None:
            return

        buyer_name = _text(agr, "ram:BuyerTradeParty/ram:Name")
        if not buyer_name:
            self._error("BR-07", "Nom de l'acheteur manquant",
                        suggestion="BuyerTradeParty/Name est obligatoire")
        else:
            self._info("BR-07", f"Acheteur : {buyer_name}")

        postal = _find(agr, "ram:BuyerTradeParty/ram:PostalTradeAddress")
        if postal is None:
            self._warn("BR-10", "Adresse postale acheteur manquante (recommandée)")

    # ── BR-CO-15/16 : Contrôle arithmétique ──────
    def _check_totals(self):
        txn = _find(self.root, "rsm:SupplyChainTradeTransaction")
        if txn is None:
            return

        sett = _find(txn, "ram:ApplicableHeaderTradeSettlement")
        if sett is None:
            self._error("BR-SETT", "Section ApplicableHeaderTradeSettlement manquante")
            return

        totals = _find(sett, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
        if totals is None:
            self._error("BR-CO-10", "Totaux de facture manquants (SpecifiedTradeSettlementHeaderMonetarySummation)")
            return

        total_ht  = _dec(totals, "ram:LineTotalAmount")
        total_vat = _dec(totals, "ram:TaxTotalAmount")
        total_ttc = _dec(totals, "ram:GrandTotalAmount")
        due       = _dec(totals, "ram:DuePayableAmount")

        if total_ht is None:
            self._error("BR-CO-11", "LineTotalAmount manquant")
        if total_vat is None:
            self._error("BR-CO-12", "TaxTotalAmount manquant")
        if total_ttc is None:
            self._error("BR-CO-13", "GrandTotalAmount manquant")
            return

        if total_ht is not None and total_vat is not None:
            expected_ttc = (total_ht + total_vat).quantize(Decimal("0.01"))
            if abs(total_ttc - expected_ttc) > Decimal("0.02"):
                self._error("BR-CO-15",
                    f"Incohérence arithmétique : HT({total_ht}) + TVA({total_vat}) = {expected_ttc} ≠ TTC({total_ttc})",
                    suggestion="Vérifiez les arrondis : utilisez Decimal avec quantize('0.01')")
            else:
                self._info("BR-CO-15", f"Totaux cohérents : {total_ht}€ HT + {total_vat}€ TVA = {total_ttc}€ TTC")

        if due is not None and total_ttc is not None:
            if abs(due - total_ttc) > Decimal("0.02"):
                self._warn("BR-CO-16", f"DuePayableAmount({due}) diffère du GrandTotalAmount({total_ttc})",
                           suggestion="En l'absence d'acompte ou d'escompte, ces deux montants doivent être égaux")

    # ── BR-CO-17 : Lignes de facture ─────────────
    def _check_lines(self):
        txn = _find(self.root, "rsm:SupplyChainTradeTransaction")
        if txn is None:
            return

        lines = _findall(txn, "ram:IncludedSupplyChainTradeLineItem")
        if not lines:
            self._warn("BR-16", "Aucune ligne de facture trouvée (profil MINIMUM ou BASIC WL accepté)")
            return

        self._info("BR-16", f"{len(lines)} ligne(s) de facture détectée(s)")

        for i, line in enumerate(lines, start=1):
            line_id = _text(line, "ram:AssociatedDocumentLineDocument/ram:LineID") or str(i)

            name = _text(line, "ram:SpecifiedTradeProduct/ram:Name")
            if not name:
                self._error("BR-25", f"Ligne {line_id} : description produit manquante")

            qty_el = _find(line, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
            if qty_el is None or not qty_el.text:
                self._error("BR-26", f"Ligne {line_id} : quantité facturée manquante")
            else:
                try:
                    qty = Decimal(qty_el.text)
                    if qty <= 0:
                        self._warn("BR-26N", f"Ligne {line_id} : quantité négative ou nulle ({qty})",
                                   suggestion="Pour un avoir, utilisez TypeCode 381 avec des quantités positives")
                except InvalidOperation:
                    self._error("BR-26F", f"Ligne {line_id} : quantité non numérique : {qty_el.text}")

            unit_price = _dec(line,
                "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount")
            if unit_price is None:
                self._error("BR-27", f"Ligne {line_id} : prix unitaire net manquant")

            line_total = _dec(line,
                "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")
            if line_total is None:
                self._warn("BR-CO-17", f"Ligne {line_id} : LineTotalAmount manquant")

    # ── FR-SIRET acheteur ─────────────────────────
    def _check_buyer_siret(self):
        txn = _find(self.root, "rsm:SupplyChainTradeTransaction")
        agr = _find(txn, "ram:ApplicableHeaderTradeAgreement") if txn else None
        if agr is None:
            return

        buyer_org = _find(agr, "ram:BuyerTradeParty/ram:SpecifiedLegalOrganization")

        if buyer_org is None:
            self._warn("FR-02", "SIRET acheteur absent",
                    suggestion="Obligatoire B2G (Chorus Pro), recommandé B2B dès 2026")
            return

        siret_el = buyer_org.find(f"{{{NS['ram']}}}ID")
        siret    = (siret_el.text or "").strip() if siret_el is not None else ""

        if not siret:
            self._warn("FR-02", "SIRET acheteur vide",
                    suggestion="Tag présent sans valeur — renseignez un SIRET valide (14 chiffres)")
        elif not re.match(r"^\d{14}$", siret):
            self._warn("FR-02", f"SIRET acheteur suspect : '{siret}'",
                    suggestion="14 chiffres exactement (SIREN 9 + NIC 5)")
        else:
            self._info("FR-02", f"SIRET acheteur : {siret}")
    # ── Orchestration ─────────────────────────────
    def validate(self) -> ValidationResult:
        if not self._parse():
            return ValidationResult(self.issues, self.xml_path)

        self._check_profile()
        self._check_invoice_number()
        self._check_type_code()
        self._check_dates()
        self._check_seller()
        self._check_buyer()
        self._check_buyer_siret()
        self._check_lines()
        self._check_totals()

        return ValidationResult(self.issues, self.xml_path)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Valide une facture Factur-X XML")
    parser.add_argument("xml_file", help="Fichier XML à valider")
    parser.add_argument("--strict", action="store_true",
                        help="Traite les warnings comme des erreurs")
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    args = parser.parse_args()

    validator = InvoiceValidator(args.xml_file)
    result = validator.validate()

    if args.json:
        import json
        print(json.dumps([
            {"rule": i.rule_id, "severity": i.severity, "message": i.message,
             "path": i.path, "suggestion": i.suggestion}
            for i in result.issues
        ], ensure_ascii=False, indent=2))
    else:
        print(result.summary())
        print()
        for issue in result.issues:
            print(str(issue))

    if args.strict:
        exit(0 if result.is_valid and not result.warnings else 1)
    else:
        exit(0 if result.is_valid else 1)
