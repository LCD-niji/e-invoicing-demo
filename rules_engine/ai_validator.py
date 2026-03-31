"""
rules_engine/ai_validator.py
----------------------------
Moteur de validation basé sur rules.json (Annexe 7 DGFiP v1.8).
Supporte CII (XPath natif) et UBL 2.1 (via bt_override depuis ubl_mapper).
Couverture :
  - Présence     : nœud XPath existe et a une valeur
  - Format       : SIRET (14 chiffres), TVA FR, date YYYYMMDD ou YYYY-MM-DD, ISO
  - Codelist     : TypeCode, CategoryCode TVA, CountryID
  - Conditionnel : TypeCode, catégorie TVA, BT trigger absent
  - Calcul       : délégués au Schematron CEN (champ "formula" présent)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree

# ── Namespaces CII ─────────────────────────────────────────
NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

DEFAULT_RULES = Path(__file__).parent / "rules.json"

# ── Table BT → XPath CII ───────────────────────────────────
BT_XPATH: dict[str, str] = {
    "BT-1":   "//rsm:ExchangedDocument/ram:ID",
    "BT-2":   "//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString",
    "BT-3":   "//rsm:ExchangedDocument/ram:TypeCode",
    "BT-5":   "//ram:ApplicableHeaderTradeSettlement/ram:InvoiceCurrencyCode",
    "BT-9":   "//ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString",
    "BT-10":  "//ram:ApplicableHeaderTradeAgreement/ram:BuyerReference",
    "BT-12":  "//ram:ApplicableHeaderTradeAgreement/ram:ContractReferencedDocument/ram:IssuerAssignedID",
    "BT-13":  "//ram:ApplicableHeaderTradeAgreement/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID",
    "BT-24":  "//rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
    "BT-25":  "//ram:ApplicableHeaderTradeAgreement/ram:InvoiceReferencedDocument/ram:IssuerAssignedID",
    # Vendeur
    "BT-27":  "//ram:SellerTradeParty/ram:Name",
    "BT-28":  "//ram:SellerTradeParty/ram:TradeName",
    "BT-29":  "//ram:SellerTradeParty/ram:ID",
    "BT-30":  "//ram:SellerTradeParty/ram:SpecifiedLegalOrganization/ram:ID",
    "BT-31":  "//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID",
    "BT-34":  "//ram:SellerTradeParty/ram:URIUniversalCommunication/ram:URIID",
    "BT-35":  "//ram:SellerTradeParty/ram:PostalTradeAddress/ram:LineOne",
    "BT-38":  "//ram:SellerTradeParty/ram:PostalTradeAddress/ram:CityName",
    "BT-39":  "//ram:SellerTradeParty/ram:PostalTradeAddress/ram:PostcodeCode",
    "BT-40":  "//ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID",
    # Acheteur
    "BT-44":  "//ram:BuyerTradeParty/ram:Name",
    "BT-47":  "//ram:BuyerTradeParty/ram:SpecifiedLegalOrganization/ram:ID",
    "BT-48":  "//ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID",
    "BT-49":  "//ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID",
    "BT-50":  "//ram:BuyerTradeParty/ram:PostalTradeAddress/ram:LineOne",
    "BT-53":  "//ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CityName",
    "BT-54":  "//ram:BuyerTradeParty/ram:PostalTradeAddress/ram:PostcodeCode",
    "BT-55":  "//ram:BuyerTradeParty/ram:PostalTradeAddress/ram:CountryID",
    # Livraison / Période
    "BT-72":  "//ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString",
    "BT-73":  "//ram:BillingSpecifiedPeriod/ram:StartDateTime/udt:DateTimeString",
    "BT-74":  "//ram:BillingSpecifiedPeriod/ram:EndDateTime/udt:DateTimeString",
    # Paiement
    "BT-81":  "//ram:SpecifiedTradeSettlementPaymentMeans/ram:TypeCode",
    "BT-84":  "//ram:PayeePartyCreditorFinancialAccount/ram:IBANID",
    "BT-86":  "//ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID",
    # TVA
    "BT-95":  "//ram:ApplicableTradeTax/ram:CategoryCode",
    "BT-102": "//ram:ApplicableTradeTax/ram:ExemptionReasonCode",
    "BT-116": "//ram:ApplicableTradeTax/ram:BasisAmount",
    "BT-117": "//ram:ApplicableTradeTax/ram:CalculatedAmount",
    "BT-118": "//ram:ApplicableTradeTax/ram:CategoryCode",
    "BT-119": "//ram:ApplicableTradeTax/ram:RateApplicablePercent",
    "BT-120": "//ram:ApplicableTradeTax/ram:ExemptionReason",
    "BT-121": "//ram:ApplicableTradeTax/ram:ExemptionReasonCode",
    # Totaux
    "BT-106": "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:LineTotalAmount",
    "BT-109": "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxBasisTotalAmount",
    "BT-110": "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount",
    "BT-112": "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount",
    "BT-115": "//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount",
    # Lignes
    "BT-126": "//ram:AssociatedDocumentLineDocument/ram:LineID",
    "BT-129": "//ram:SpecifiedLineTradeDelivery/ram:BilledQuantity",
    "BT-131": "//ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
    "BT-146": "//ram:NetPriceProductTradePrice/ram:ChargeAmount",
    "BT-151": "//ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode",
    "BT-153": "//ram:SpecifiedTradeProduct/ram:Name",
    "BT-154": "//ram:SpecifiedTradeProduct/ram:Description",
}

# ── Codelists ──────────────────────────────────────────────
CODELISTS: dict[str, set] = {
    "BT-3":   {"380","381","384","386","389","393","82","83","261","295","296","308","325","326","331"},
    "BT-118": {"S","E","AE","K","G","O","Z","L","M"},
    "BT-95":  {"S","E","AE","K","G","O","Z","L","M"},
    "BT-40":  {"FR","DE","GB","ES","IT","BE","NL","CH","PT","PL","SE","NO","DK","FI","LU","AT","IE"},
    "BT-55":  {"FR","DE","GB","ES","IT","BE","NL","CH","PT","PL","SE","NO","DK","FI","LU","AT","IE"},
}

# ── Patterns de format ─────────────────────────────────────
FORMAT_CHECKS: dict[str, tuple[str, str]] = {
    "siret":  (r"^\d{14}$",                          "14 chiffres (SIREN 9 + NIC 5)"),
    "tva_fr": (r"^FR[A-Z0-9]{2}\d{9}$",              "FR + 2 caractères + 9 chiffres"),
    "date8":  (r"^\d{8}$|^\d{4}-\d{2}-\d{2}$",       "Format YYYYMMDD ou YYYY-MM-DD"),
    "iso3":   (r"^[A-Z]{3}$",                         "Code 3 lettres ISO"),
    "iso2":   (r"^[A-Z]{2}$",                         "Code 2 lettres ISO"),
    "iban":   (r"^[A-Z]{2}\d{2}[A-Z0-9]+$",          "Format IBAN"),
}

def _detect_format(bt: str, desc: str) -> Optional[str]:
    d = desc.lower()
    if bt in ("BT-30", "BT-47") or "siret" in d:               return "siret"
    if bt in ("BT-31", "BT-48") or ("tva" in d and "fr" in d): return "tva_fr"
    if bt in ("BT-2", "BT-72", "BT-73", "BT-74"):              return "date8"
    if bt in ("BT-5",):                                         return "iso3"
    if bt in ("BT-40", "BT-55"):                                return "iso2"
    if bt in ("BT-84",) or "iban" in d:                         return "iban"
    return None

# ── Tables de conditions ───────────────────────────────────
SKIP_IF_BT_ABSENT: dict[str, str] = {
    "BR-55":    "BT-25",
    "BR-29":    "BT-73",
    "G6.25":    "BT-73",
    "BR-CO-19": "BT-73",
    "G6.21":    "BT-121",
    "BR-CL-22": "BT-121",
    "G1.39":    "BT-72",
    "BR-32":    "BT-95",
}

SKIP_IF_NOT_TYPE: dict[str, set] = {
    "G1.31": {"381", "384"},
}

SKIP_IF_VAT_NOT: dict[str, str] = {
    "G1.41":     "E",
    "BR-AE-10":  "AE",
    "BR-G-10":   "G",
    "BR-IC-10":  "K",
    "BR-IC-11":  "K",
    "BR-IC-12":  "K",
    "BR-S-10":   "S",
}

INVERT_CHECK: set[str] = {"BR-S-10"}


# ── Sous-types de SKIPPED ──────────────────────────────────
# FIX BUG 4 : on catégorise explicitement chaque motif de skip
# pour ne plus dépendre du texte du message dans app.py

SKIP_REASON_XSLT       = "xslt"      # déjà couverte par Contrôle 1 (Schematron CEN)
SKIP_REASON_BT_ABSENT  = "bt_absent" # BT non mappé dans BT_XPATH → nécessite PPF
SKIP_REASON_CONDITION  = "condition" # condition métier non remplie sur cette facture
SKIP_REASON_PPF        = "ppf"       # nécessite annuaire / historique PPF


# ── Structures de résultat ─────────────────────────────────
@dataclass
class AiIssue:
    rule_id:     str
    message:     str
    severity:    str            # ERROR | WARNING | INFO | SKIPPED
    bt:          str = ""
    source:      str = "Annexe 7 DGFiP v1.8"
    # FIX BUG 4 : sous-type explicite pour les SKIPPED
    # Valeurs : None (non skippé), "xslt", "bt_absent", "condition", "ppf"
    skip_reason: Optional[str] = None


@dataclass
class AiResult:
    issues: list[AiIssue] = field(default_factory=list)

    @property
    def errors(self)   -> list[AiIssue]: return [i for i in self.issues if i.severity == "ERROR"]
    @property
    def warnings(self) -> list[AiIssue]: return [i for i in self.issues if i.severity == "WARNING"]
    @property
    def infos(self)    -> list[AiIssue]: return [i for i in self.issues if i.severity == "INFO"]
    @property
    def skipped(self)  -> list[AiIssue]: return [i for i in self.issues if i.severity == "SKIPPED"]

    # ── Accesseurs par sous-type de SKIPPED ───────────────
    @property
    def skipped_xslt(self) -> list[AiIssue]:
        """Règles déjà couvertes par le Contrôle 1 (Schematron CEN EN16931)."""
        return [i for i in self.skipped if i.skip_reason == SKIP_REASON_XSLT]

    @property
    def skipped_condition(self) -> list[AiIssue]:
        """Règles non applicables à cette facture (TypeCode, TVA, BT trigger)."""
        return [i for i in self.skipped if i.skip_reason == SKIP_REASON_CONDITION]

    @property
    def skipped_out_of_scope(self) -> list[AiIssue]:
        """Règles hors portée standalone : BT absent du mapping ou nécessite PPF."""
        return [i for i in self.skipped
                if i.skip_reason in (SKIP_REASON_BT_ABSENT, SKIP_REASON_PPF)]

    @property
    def is_valid(self) -> bool: return len(self.errors) == 0


class AiValidator:

    def __init__(self, rules_path = DEFAULT_RULES):
        rules_path = Path(rules_path)
        if not rules_path.exists():
            raise FileNotFoundError(f"rules.json introuvable : {rules_path}")
        with open(rules_path, encoding="utf-8") as f:
            data = json.load(f)
        self.rules: list[dict] = []
        for key, val in data.items():
            if key == "meta":
                continue
            if isinstance(val, list):
                for rule in val:
                    if rule.get("f1", False):
                        self.rules.append(rule)

    # ── FIX BUG 1 : méthode exposée pour que app.py puisse
    # obtenir le vrai total f1=True sans re-parser le JSON ──
    @property
    def total_f1_rules(self) -> int:
        """Nombre de règles f1=True effectivement chargées."""
        return len(self.rules)

    def _get_value(self, tree, xpath: str) -> Optional[str]:
        if not xpath:
            return None
        try:
            nodes = tree.xpath(xpath, namespaces=NS)
            if not nodes:
                return None
            n = nodes[0]
            return (n.text or "").strip() if hasattr(n, "text") else str(n).strip()
        except Exception:
            return None

    def validate(
        self,
        xml_path: str,
        schematron_ran: bool = False,
        bt_override: dict | None = None,
    ) -> AiResult:
        result = AiResult()

        try:
            tree = etree.parse(xml_path)
        except Exception as e:
            result.issues.append(AiIssue("PARSE-ERR", f"XML invalide : {e}", "ERROR"))
            return result

        def _get(bt_code: str) -> Optional[str]:
            if bt_override and bt_code in bt_override:
                return bt_override[bt_code] or None
            xpath = BT_XPATH.get(bt_code, "")
            return self._get_value(tree, xpath)

        type_code = _get("BT-3")   or ""
        vat_code  = _get("BT-118") or ""

        for rule in self.rules:
            rule_id  = rule.get("id", "?")
            desc     = rule.get("desc", "")
            bt_raw   = rule.get("bt", "")
            category = rule.get("source", "Annexe 7 DGFiP v1.8")
            severity = "ERROR" if rule_id.startswith(("BR-", "G")) else "WARNING"
            covered  = rule.get("covered_by", "")

            # ── FIX BUG 4 : SKIP avec sous-type explicite ──

            # Chemin 1 : déjà couverte par Schematron CEN
            if schematron_ran and covered == "schematron":
                result.issues.append(AiIssue(
                    rule_id=rule_id,
                    message=f"{desc} — couverte par Contrôle 1 (EN16931 XSLT)",
                    severity="SKIPPED",
                    bt=bt_raw,
                    skip_reason=SKIP_REASON_XSLT,
                ))
                continue

            # Chemin 2 : condition TypeCode non satisfaite
            if rule_id in SKIP_IF_NOT_TYPE:
                if type_code not in SKIP_IF_NOT_TYPE[rule_id]:
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} — non applicable (TypeCode={type_code or '?'})",
                        severity="SKIPPED",
                        bt=bt_raw,
                        skip_reason=SKIP_REASON_CONDITION,
                    ))
                    continue

            # Chemin 3 : condition catégorie TVA non satisfaite
            if rule_id in SKIP_IF_VAT_NOT:
                if vat_code != SKIP_IF_VAT_NOT[rule_id]:
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} — non applicable (BT-118={vat_code or '?'})",
                        severity="SKIPPED",
                        bt=bt_raw,
                        skip_reason=SKIP_REASON_CONDITION,
                    ))
                    continue

            # Chemin 4 : BT non mappé dans BT_XPATH
            bt = bt_raw.split(",")[0].strip()
            has_override = bt_override and bt in bt_override
            has_xpath    = bt in BT_XPATH

            if not has_override and not has_xpath:
                result.issues.append(AiIssue(
                    rule_id=rule_id,
                    message=f"{desc} — {bt} non mappé localement (vérification PPF/annuaire)",
                    severity="SKIPPED",
                    bt=bt_raw,
                    skip_reason=SKIP_REASON_BT_ABSENT,
                ))
                continue

            # Chemin 5 : BT trigger absent sur cette facture
            if rule_id in SKIP_IF_BT_ABSENT:
                trigger_bt    = SKIP_IF_BT_ABSENT[rule_id]
                trigger_value = _get(trigger_bt)
                if not trigger_value:
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} — non applicable ({trigger_bt} absent de cette facture)",
                        severity="SKIPPED",
                        bt=bt_raw,
                        skip_reason=SKIP_REASON_CONDITION,
                    ))
                    continue

            value = _get(bt)

            # ── Check inversé ──────────────────────────────
            if rule_id in INVERT_CHECK:
                if value:
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} — '{bt}' ne doit pas être renseigné",
                        severity="ERROR", bt=bt_raw, source=category,
                    ))
                else:
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} ✓ (absent comme attendu)",
                        severity="INFO", bt=bt_raw, source=category,
                    ))
                continue

            # ── Codelist ───────────────────────────────────
            if bt in CODELISTS:
                if not value:
                    result.issues.append(AiIssue(
                        rule_id=rule_id, message=desc,
                        severity="ERROR", bt=bt_raw, source=category,
                    ))
                elif value not in CODELISTS[bt]:
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} — valeur '{value}' non autorisée",
                        severity="ERROR", bt=bt_raw, source=category,
                    ))
                else:
                    result.issues.append(AiIssue(
                        rule_id=rule_id, message=f"{desc} ✓ ({value})",
                        severity="INFO", bt=bt_raw, source=category,
                    ))
                continue

            # ── Format ─────────────────────────────────────
            fmt = _detect_format(bt, desc)
            if fmt and value:
                pattern, hint = FORMAT_CHECKS[fmt]
                if not re.match(pattern, value):
                    result.issues.append(AiIssue(
                        rule_id=rule_id,
                        message=f"{desc} — format invalide : '{value}' ({hint})",
                        severity="WARNING", bt=bt_raw, source=category,
                    ))
                else:
                    result.issues.append(AiIssue(
                        rule_id=rule_id, message=f"{desc} ✓ ({value})",
                        severity="INFO", bt=bt_raw, source=category,
                    ))
                continue

            # ── Présence ───────────────────────────────────
            if not value:
                result.issues.append(AiIssue(
                    rule_id=rule_id, message=desc,
                    severity=severity, bt=bt_raw, source=category,
                ))
            else:
                result.issues.append(AiIssue(
                    rule_id=rule_id, message=f"{desc} ✓",
                    severity="INFO", bt=bt_raw, source=category,
                ))

        return result