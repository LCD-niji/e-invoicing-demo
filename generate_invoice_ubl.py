"""
generate_invoice_ubl.py
-----------------------
Génère un XML UBL 2.1 conforme EN16931 / Peppol BIS Billing 3.0
depuis le modèle Invoice (même objet que pour CII).
"""
from __future__ import annotations

from decimal import Decimal
from lxml import etree
from generate_invoice import Invoice, InvoiceLine

# ── Namespaces UBL 2.1 ────────────────────────────────────
NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

UBL_CUSTOMIZATION = (
    "urn:cen.eu:en16931:2017#compliant"
    "#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
)
UBL_PROFILE = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"

VAT_CATEGORY_MAP = {
    Decimal("20"): "S", Decimal("10"): "S", Decimal("5.5"): "S",
    Decimal("0"):  "Z",
}


def _el(parent: etree._Element, ns: str, tag: str, text: str | None = None,
        **attribs) -> etree._Element:
    """Crée un élément enfant avec namespace."""
    e = etree.SubElement(parent, f"{{{NS[ns]}}}{tag}", **attribs)
    if text is not None:
        e.text = str(text)
    return e


def generate_ubl_xml(invoice: Invoice) -> str:
    """Retourne un XML UBL 2.1 (str UTF-8) depuis un objet Invoice."""

    # ── Racine ────────────────────────────────────────────
    root = etree.Element(
        f"{{{NS['ubl']}}}Invoice",
        nsmap={None: NS["ubl"], "cac": NS["cac"], "cbc": NS["cbc"]},
    )

    # ── Entête ────────────────────────────────────────────
    _el(root, "cbc", "CustomizationID", UBL_CUSTOMIZATION)
    _el(root, "cbc", "ProfileID",       UBL_PROFILE)
    _el(root, "cbc", "ID",              invoice.number)                       # BT-1
    _el(root, "cbc", "IssueDate",       invoice.issue_date.isoformat())       # BT-2
    _el(root, "cbc", "DueDate",         invoice.due_date.isoformat())         # BT-9
    _el(root, "cbc", "InvoiceTypeCode", "380")                                # BT-3
    if invoice.notes:
        _el(root, "cbc", "Note", invoice.notes)                               # BT-22
    _el(root, "cbc", "DocumentCurrencyCode", "EUR")                           # BT-5
    if invoice.buyer.name:
        _el(root, "cbc", "BuyerReference", invoice.buyer.name)               # BT-10

    # ── Référence contrat (BT-12) ─────────────────────────
    if getattr(invoice, "contract_ref", None):
        cdr = _el(root, "cac", "ContractDocumentReference")
        _el(cdr, "cbc", "ID", invoice.contract_ref)

    # ── Vendeur (BT-27 à BT-44) ───────────────────────────
    asp = _el(root, "cac", "AccountingSupplierParty")
    party_s = _el(asp, "cac", "Party")

    pn_s = _el(party_s, "cac", "PartyName")
    _el(pn_s, "cbc", "Name", invoice.seller.name)                            # BT-27

    addr_s = _el(party_s, "cac", "PostalAddress")
    if invoice.seller.address:
        _el(addr_s, "cbc", "StreetName",  invoice.seller.address.street)     # BT-35
        _el(addr_s, "cbc", "CityName",    invoice.seller.address.city)       # BT-37
        _el(addr_s, "cbc", "PostalZone",  invoice.seller.address.postal_code)# BT-38
    country_s = _el(addr_s, "cac", "Country")
    _el(country_s, "cbc", "IdentificationCode", "FR")                        # BT-40

    if invoice.seller.vat_number:
        pts = _el(party_s, "cac", "PartyTaxScheme")
        _el(pts, "cbc", "CompanyID", invoice.seller.vat_number)              # BT-31
        ts = _el(pts, "cac", "TaxScheme")
        _el(ts, "cbc", "ID", "VAT")

    ple_s = _el(party_s, "cac", "PartyLegalEntity")
    _el(ple_s, "cbc", "RegistrationName", invoice.seller.name)
    if invoice.seller.siret:
        _el(ple_s, "cbc", "CompanyID", invoice.seller.siret,
            schemeID="0002")                                                  # BT-30

    # ── Acheteur (BT-44 à BT-55) ──────────────────────────
    acp = _el(root, "cac", "AccountingCustomerParty")
    party_b = _el(acp, "cac", "Party")

    pn_b = _el(party_b, "cac", "PartyName")
    _el(pn_b, "cbc", "Name", invoice.buyer.name)                             # BT-44

    addr_b = _el(party_b, "cac", "PostalAddress")
    if invoice.buyer.address:
        _el(addr_b, "cbc", "StreetName",  invoice.buyer.address.street)      # BT-50
        _el(addr_b, "cbc", "CityName",    invoice.buyer.address.city)        # BT-52
        _el(addr_b, "cbc", "PostalZone",  invoice.buyer.address.postal_code) # BT-53
    country_b = _el(addr_b, "cac", "Country")
    _el(country_b, "cbc", "IdentificationCode", "FR")                        # BT-55

    if invoice.buyer.siret:
        ple_b = _el(party_b, "cac", "PartyLegalEntity")
        _el(ple_b, "cbc", "RegistrationName", invoice.buyer.name)
        _el(ple_b, "cbc", "CompanyID", invoice.buyer.siret,
            schemeID="0002")                                                  # BT-47

    # ── Moyen de paiement (BT-81 / BT-84) ─────────────────
    if invoice.seller.iban:
        pm = _el(root, "cac", "PaymentMeans")
        _el(pm, "cbc", "PaymentMeansCode", "30")                             # BT-81
        pfa = _el(pm, "cac", "PayeeFinancialAccount")
        _el(pfa, "cbc", "ID", invoice.seller.iban)                           # BT-84

    # ── Calculs totaux ────────────────────────────────────
    total_ht  = sum(
        l.quantity * l.unit_price for l in invoice.lines
    )
    total_vat = sum(
        l.quantity * l.unit_price * l.vat_rate / 100 for l in invoice.lines
    )
    total_ttc = total_ht + total_vat

    # Groupes TVA (BG-23)
    vat_groups: dict[Decimal, dict] = {}
    for line in invoice.lines:
        rate = line.vat_rate
        if rate not in vat_groups:
            vat_groups[rate] = {"base": Decimal("0"), "vat": Decimal("0")}
        base = line.quantity * line.unit_price
        vat_groups[rate]["base"] += base
        vat_groups[rate]["vat"]  += base * rate / 100

    # ── TaxTotal ──────────────────────────────────────────
    tt = _el(root, "cac", "TaxTotal")
    _el(tt, "cbc", "TaxAmount", f"{float(total_vat):.2f}", currencyID="EUR") # BT-110

    for rate, amounts in vat_groups.items():
        ts_sub = _el(tt, "cac", "TaxSubtotal")
        _el(ts_sub, "cbc", "TaxableAmount",
            f"{float(amounts['base']):.2f}", currencyID="EUR")               # BT-116
        _el(ts_sub, "cbc", "TaxAmount",
            f"{float(amounts['vat']):.2f}",  currencyID="EUR")               # BT-117
        tc = _el(ts_sub, "cac", "TaxCategory")
        category = VAT_CATEGORY_MAP.get(rate, "S")
        _el(tc, "cbc", "ID",      category)                                  # BT-118
        _el(tc, "cbc", "Percent", str(float(rate)))                          # BT-119
        tsc = _el(tc, "cac", "TaxScheme")
        _el(tsc, "cbc", "ID", "VAT")

    # ── LegalMonetaryTotal ────────────────────────────────
    lmt = _el(root, "cac", "LegalMonetaryTotal")
    _el(lmt, "cbc", "LineExtensionAmount",
        f"{float(total_ht):.2f}",  currencyID="EUR")                         # BT-106
    _el(lmt, "cbc", "TaxExclusiveAmount",
        f"{float(total_ht):.2f}",  currencyID="EUR")                         # BT-109
    _el(lmt, "cbc", "TaxInclusiveAmount",
        f"{float(total_ttc):.2f}", currencyID="EUR")                         # BT-112
    _el(lmt, "cbc", "PayableAmount",
        f"{float(total_ttc):.2f}", currencyID="EUR")                         # BT-115

    # ── Lignes (BG-25) ────────────────────────────────────
    for i, line in enumerate(invoice.lines, start=1):
        line_total = line.quantity * line.unit_price
        il = _el(root, "cac", "InvoiceLine")
        _el(il, "cbc", "ID", str(i))                                         # BT-126
        _el(il, "cbc", "InvoicedQuantity",
            str(float(line.quantity)), unitCode="C62")                        # BT-129
        _el(il, "cbc", "LineExtensionAmount",
            f"{float(line_total):.2f}", currencyID="EUR")                    # BT-131

        item = _el(il, "cac", "Item")
        _el(item, "cbc", "Name", line.description)                           # BT-153

        ctc = _el(item, "cac", "ClassifiedTaxCategory")
        category = VAT_CATEGORY_MAP.get(line.vat_rate, "S")
        _el(ctc, "cbc", "ID",      category)                                 # BT-151
        _el(ctc, "cbc", "Percent", str(float(line.vat_rate)))                # BT-152
        tsc2 = _el(ctc, "cac", "TaxScheme")
        _el(tsc2, "cbc", "ID", "VAT")

        price = _el(il, "cac", "Price")
        _el(price, "cbc", "PriceAmount",
            f"{float(line.unit_price):.2f}", currencyID="EUR")               # BT-146

    return etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    ).decode("utf-8")