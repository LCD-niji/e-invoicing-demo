"""
ubl_mapper.py
-------------
Extrait les valeurs BT depuis un XML UBL 2.1.
Permet au moteur Annexe 7 (ai_validator.py) de traiter UBL
sans modification — même interface que BT_XPATH pour CII.
"""
from lxml import etree

NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

# Mapping BT → XPath UBL (symétrique du BT_XPATH CII dans ai_validator.py)
BT_XPATH_UBL: dict[str, str] = {
    "BT-1":   "//cbc:ID[1]",
    "BT-2":   "//cbc:IssueDate",
    "BT-3":   "//cbc:InvoiceTypeCode",
    "BT-5":   "//cbc:DocumentCurrencyCode",
    "BT-9":   "//cbc:DueDate",
    "BT-10":  "//cbc:BuyerReference",
    "BT-12":  "//cac:ContractDocumentReference/cbc:ID",
    "BT-13":  "//cac:OrderReference/cbc:ID",
    "BT-22":  "//cbc:Note",
    "BT-24":  "//cbc:CustomizationID",
    # Vendeur
    "BT-27":  "//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name",
    "BT-28":  "//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name",
    "BT-30":  "//cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyID",
    "BT-31":  "//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
    "BT-35":  "//cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:StreetName",
    "BT-37":  "//cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:CityName",
    "BT-38":  "//cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:PostalZone",
    "BT-40":  "//cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cac:Country/cbc:IdentificationCode",
    # Acheteur
    "BT-44":  "//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name",
    "BT-47":  "//cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyID",
    "BT-48":  "//cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
    "BT-53":  "//cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cbc:PostalZone",
    "BT-55":  "//cac:AccountingCustomerParty/cac:Party/cac:PostalAddress/cac:Country/cbc:IdentificationCode",
    # Paiement
    "BT-81":  "//cac:PaymentMeans/cbc:PaymentMeansCode",
    "BT-84":  "//cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID",
    # TVA
    "BT-110": "//cac:TaxTotal/cbc:TaxAmount",
    "BT-116": "//cac:TaxTotal/cac:TaxSubtotal/cbc:TaxableAmount",
    "BT-117": "//cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount",
    "BT-118": "//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID",
    "BT-119": "//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent",
    # Totaux
    "BT-106": "//cac:LegalMonetaryTotal/cbc:LineExtensionAmount",
    "BT-109": "//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
    "BT-112": "//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount",
    "BT-115": "//cac:LegalMonetaryTotal/cbc:PayableAmount",
    # Ligne
    "BT-126": "//cac:InvoiceLine/cbc:ID",
    "BT-129": "//cac:InvoiceLine/cbc:InvoicedQuantity",
    "BT-131": "//cac:InvoiceLine/cbc:LineExtensionAmount",
    "BT-146": "//cac:InvoiceLine/cac:Price/cbc:PriceAmount",
    "BT-151": "//cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:ID",
    "BT-153": "//cac:InvoiceLine/cac:Item/cbc:Name",
}


def extract_bt_values(xml_path: str) -> dict[str, str]:
    """
    Extrait les valeurs BT depuis un XML UBL 2.1.
    Retourne {bt_code: valeur_str} — même interface que le moteur CII.
    """
    tree   = etree.parse(xml_path)
    values = {}
    for bt, xpath in BT_XPATH_UBL.items():
        try:
            results = tree.xpath(xpath, namespaces=NS)
            if results:
                el = results[0]
                values[bt] = el.text.strip() if hasattr(el, "text") else str(el)
        except Exception:
            pass
    return values


def is_ubl(xml_path: str) -> bool:
    """Détecte si le fichier est du UBL 2.1."""
    try:
        tree = etree.parse(xml_path)
        root = tree.getroot()
        return "oasis" in root.tag or "Invoice-2" in root.tag
    except Exception:
        return False