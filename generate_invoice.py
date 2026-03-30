"""
generate_invoice.py
-------------------
Génère une facture électronique conforme Factur-X (EN 16931 / FR 2026).
Factur-X = PDF/A-3 avec XML CII (Cross Industry Invoice) embarqué.

Formats supportés :
  - MINIMUM    : données minimales (B2G / Chorus Pro basique)
  - BASIC WL   : sans lignes de détail
  - BASIC      : avec lignes de détail
  - EN 16931   : profil complet (recommandé PME)
  - EXTENDED   : extensions nationales

Usage :
    python generate_invoice.py --output facture_test.xml
    python generate_invoice.py --profile EN16931 --output ma_facture.xml
"""

import argparse
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional
from xml.dom import minidom
import xml.etree.ElementTree as ET


# ─────────────────────────────────────────────
# Modèles de données
# ─────────────────────────────────────────────

@dataclass
class Address:
    street: str
    city: str
    postal_code: str
    country_code: str = "FR"


@dataclass
class Party:
    name: str
    siret: str          # 14 chiffres
    vat_number: str     # FR + 11 chiffres
    address: Address
    iban: Optional[str] = None
    bic: Optional[str] = None


@dataclass
class InvoiceLine:
    description: str
    quantity: Decimal
    unit_price: Decimal  # HT
    vat_rate: Decimal    # ex: Decimal("20")
    unit_code: str = "C62"  # C62 = unité, HUR = heure, DAY = jour

    @property
    def line_total_ht(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))

    @property
    def vat_amount(self) -> Decimal:
        return (self.line_total_ht * self.vat_rate / 100).quantize(Decimal("0.01"))

    @property
    def line_total_ttc(self) -> Decimal:
        return self.line_total_ht + self.vat_amount


@dataclass
class Invoice:
    number: str
    issue_date: date
    due_date: date
    seller: Party
    buyer: Party
    lines: list[InvoiceLine]
    currency: str = "EUR"
    profile: str = "EN16931"
    notes: Optional[str] = None
    contract_ref: Optional[str] = None    
    purchase_order: Optional[str] = None   

    # Calculés automatiquement
    @property
    def total_ht(self) -> Decimal:
        return sum(l.line_total_ht for l in self.lines)

    @property
    def total_vat(self) -> Decimal:
        return sum(l.vat_amount for l in self.lines)

    @property
    def total_ttc(self) -> Decimal:
        return self.total_ht + self.total_vat

    def vat_breakdown(self) -> dict:
        """Regroupe la TVA par taux."""
        breakdown = {}
        for line in self.lines:
            rate = str(line.vat_rate)
            if rate not in breakdown:
                breakdown[rate] = {"base": Decimal("0"), "vat": Decimal("0")}
            breakdown[rate]["base"] += line.line_total_ht
            breakdown[rate]["vat"] += line.vat_amount
        return breakdown


# ─────────────────────────────────────────────
# Namespaces CII (Cross Industry Invoice)
# ─────────────────────────────────────────────

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

PROFILES = {
    "MINIMUM":   "urn:factur-x.eu:1p0:minimum",
    "BASIC_WL":  "urn:factur-x.eu:1p0:basicwl",
    "BASIC":     "urn:factur-x.eu:1p0:basic",
    "EN16931":   "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:en16931",
    "EXTENDED":  "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended",
}


def _el(tag: str, text: str = None, attrib: dict = None) -> ET.Element:
    """Helper : crée un élément avec namespace."""
    ns, local = tag.split(":")
    e = ET.Element(f"{{{NS[ns]}}}{local}", attrib=attrib or {})
    if text is not None:
        e.text = text
    return e


def _sub(parent: ET.Element, tag: str, text: str = None, attrib: dict = None) -> ET.Element:
    ns, local = tag.split(":")
    e = ET.SubElement(parent, f"{{{NS[ns]}}}{local}", attrib=attrib or {})
    if text is not None:
        e.text = text
    return e


def _date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _amt(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01")))


# ─────────────────────────────────────────────
# Générateur XML CII
# ─────────────────────────────────────────────

def generate_facturx_xml(invoice: Invoice) -> str:
    """Retourne la chaîne XML CII conforme Factur-X."""

    # Déclaration des namespaces
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)

    root = ET.Element(
        f"{{{NS['rsm']}}}CrossIndustryInvoice",
        {
            f"{{{NS['xsi']}}}schemaLocation":
                "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100 "
                "CrossIndustryInvoice_100pD22B.xsd"
        }
    )

    # ── 1. ExchangedDocumentContext ──────────────
    ctx = _sub(root, "rsm:ExchangedDocumentContext")
    gp = _sub(ctx, "ram:GuidelineSpecifiedDocumentContextParameter")
    _sub(gp, "ram:ID", PROFILES.get(invoice.profile, PROFILES["EN16931"]))

    # ── 2. ExchangedDocument ─────────────────────
    doc = _sub(root, "rsm:ExchangedDocument")
    _sub(doc, "ram:ID", invoice.number)
    _sub(doc, "ram:TypeCode", "380")  # 380 = facture commerciale
    issue = _sub(doc, "ram:IssueDateTime")
    dts = _sub(issue, "udt:DateTimeString", _date(invoice.issue_date))
    dts.set("format", "102")
    if invoice.notes:
        note = _sub(doc, "ram:IncludedNote")
        _sub(note, "ram:Content", invoice.notes)

    # ── 3. SupplyChainTradeTransaction ───────────
    txn = _sub(root, "rsm:SupplyChainTradeTransaction")

    # 3a. Lignes de facture
    for idx, line in enumerate(invoice.lines, start=1):
        item = _sub(txn, "ram:IncludedSupplyChainTradeLineItem")
        doc_line = _sub(item, "ram:AssociatedDocumentLineDocument")
        _sub(doc_line, "ram:LineID", str(idx))

        product = _sub(item, "ram:SpecifiedTradeProduct")
        _sub(product, "ram:Name", line.description)

        agreement = _sub(item, "ram:SpecifiedLineTradeAgreement")
        gross = _sub(agreement, "ram:GrossPriceProductTradePrice")
        _sub(gross, "ram:ChargeAmount", _amt(line.unit_price))
        net = _sub(agreement, "ram:NetPriceProductTradePrice")
        _sub(net, "ram:ChargeAmount", _amt(line.unit_price))

        delivery = _sub(item, "ram:SpecifiedLineTradeDelivery")
        qty = _sub(delivery, "ram:BilledQuantity", str(line.quantity))
        qty.set("unitCode", line.unit_code)

        settlement = _sub(item, "ram:SpecifiedLineTradeSettlement")
        tax = _sub(settlement, "ram:ApplicableTradeTax")
        _sub(tax, "ram:TypeCode", "VAT")
        _sub(tax, "ram:CategoryCode", "S")
        _sub(tax, "ram:RateApplicablePercent", str(line.vat_rate))
        total = _sub(settlement, "ram:SpecifiedTradeSettlementLineMonetarySummation")
        _sub(total, "ram:LineTotalAmount", _amt(line.line_total_ht))

    # 3b. Header trade agreement (vendeur / acheteur)
    agreement_h = _sub(txn, "ram:ApplicableHeaderTradeAgreement")

    # Vendeur
    seller_el = _sub(agreement_h, "ram:SellerTradeParty")
    _sub(seller_el, "ram:Name", invoice.seller.name)
    seller_id = _sub(seller_el, "ram:SpecifiedLegalOrganization")
    _sub(seller_id, "ram:ID", invoice.seller.siret, {"schemeID": "0002"})
    seller_tax = _sub(seller_el, "ram:SpecifiedTaxRegistration")
    _sub(seller_tax, "ram:ID", invoice.seller.vat_number, {"schemeID": "VA"})
    _add_address(seller_el, invoice.seller.address)

    # Acheteur
    buyer_el = _sub(agreement_h, "ram:BuyerTradeParty")
    _sub(buyer_el, "ram:Name", invoice.buyer.name)
    buyer_id = _sub(buyer_el, "ram:SpecifiedLegalOrganization")
    _sub(buyer_id, "ram:ID", invoice.buyer.siret, {"schemeID": "0002"})

    # TVA acheteur (BT-48) — obligatoire si présente
    if invoice.buyer.vat_number:                                    
        buyer_tax = _sub(buyer_el, "ram:SpecifiedTaxRegistration")  
        _sub(buyer_tax, "ram:ID", invoice.buyer.vat_number,         
             {"schemeID": "VA"})                                     

    _add_address(buyer_el, invoice.buyer.address)

# Référence contrat (BT-12)
    if invoice.contract_ref:
        contract = _sub(agreement_h, "ram:ContractReferencedDocument")
        _sub(contract, "ram:IssuerAssignedID", invoice.contract_ref)

    # Bon de commande (BT-13)
    if invoice.purchase_order:
        order = _sub(agreement_h, "ram:BuyerOrderReferencedDocument")
        _sub(order, "ram:IssuerAssignedID", invoice.purchase_order)
        
    # 3c. Delivery
    delivery_h = _sub(txn, "ram:ApplicableHeaderTradeDelivery")
    actual = _sub(delivery_h, "ram:ActualDeliverySupplyChainEvent")
    occ = _sub(actual, "ram:OccurrenceDateTime")
    dts2 = _sub(occ, "udt:DateTimeString", _date(invoice.issue_date))
    dts2.set("format", "102")

    # 3d. Settlement
    settlement_h = _sub(txn, "ram:ApplicableHeaderTradeSettlement")
    _sub(settlement_h, "ram:InvoiceCurrencyCode", invoice.currency)

    # Paiement
    if invoice.seller.iban:
        pay_means = _sub(settlement_h, "ram:SpecifiedTradeSettlementPaymentMeans")
        _sub(pay_means, "ram:TypeCode", "58")  # 58 = virement SEPA
        payer_acc = _sub(pay_means, "ram:PayeePartyCreditorFinancialAccount")
        _sub(payer_acc, "ram:IBANID", invoice.seller.iban)
        if invoice.seller.bic:
            fi = _sub(pay_means, "ram:PayeeSpecifiedCreditorFinancialInstitution")
            _sub(fi, "ram:BICID", invoice.seller.bic)

    # TVA par taux
    for rate, amounts in invoice.vat_breakdown().items():
        tax_el = _sub(settlement_h, "ram:ApplicableTradeTax")
        _sub(tax_el, "ram:CalculatedAmount", _amt(amounts["vat"]))
        _sub(tax_el, "ram:TypeCode", "VAT")
        _sub(tax_el, "ram:BasisAmount", _amt(amounts["base"]))
        _sub(tax_el, "ram:CategoryCode", "S")
        _sub(tax_el, "ram:RateApplicablePercent", rate)

    # Échéance
    period = _sub(settlement_h, "ram:SpecifiedTradePaymentTerms")
    due = _sub(period, "ram:DueDateDateTime")
    dts3 = _sub(due, "udt:DateTimeString", _date(invoice.due_date))
    dts3.set("format", "102")

    # Totaux
    totals = _sub(settlement_h, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
    _sub(totals, "ram:LineTotalAmount", _amt(invoice.total_ht))
    _sub(totals, "ram:TaxBasisTotalAmount", _amt(invoice.total_ht))
    tax_total = _sub(totals, "ram:TaxTotalAmount", _amt(invoice.total_vat))
    tax_total.set("currencyID", invoice.currency)
    _sub(totals, "ram:GrandTotalAmount", _amt(invoice.total_ttc))
    _sub(totals, "ram:DuePayableAmount", _amt(invoice.total_ttc))

    # Sérialisation pretty-print
    raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
    parsed = minidom.parseString(raw)
    pretty = parsed.toprettyxml(indent="  ", encoding="UTF-8")
    return pretty.decode("utf-8")


def _add_address(parent: ET.Element, addr: Address):
    postal = _sub(parent, "ram:PostalTradeAddress")
    _sub(postal, "ram:PostcodeCode", addr.postal_code)
    _sub(postal, "ram:LineOne", addr.street)
    _sub(postal, "ram:CityName", addr.city)
    _sub(postal, "ram:CountryID", addr.country_code)


# ─────────────────────────────────────────────
# Facture de démonstration
# ─────────────────────────────────────────────

def make_demo_invoice() -> Invoice:
    """Retourne une facture exemple prête à l'emploi."""
    seller = Party(
        name="Acme Conseil SAS",
        siret="12345678901234",
        vat_number="FR12345678901",
        address=Address("12 rue de la Paix", "Paris", "75001"),
        iban="FR7630006000011234567890189",
        bic="BNPAFRPPXXX",
    )
    buyer = Party(
        name="Dupont & Fils SARL",
        siret="98765432109876",
        vat_number="FR98765432109",
        address=Address("5 avenue des Champs", "Lyon", "69001"),
    )
    lines = [
        InvoiceLine("Audit système de facturation", Decimal("3"), Decimal("800.00"), Decimal("20")),
        InvoiceLine("Implémentation connecteur Chorus Pro", Decimal("5"), Decimal("950.00"), Decimal("20")),
        InvoiceLine("Formation équipe comptable (demi-journée)", Decimal("2"), Decimal("600.00"), Decimal("20")),
    ]
    return Invoice(
        number=f"FAC-2026-{uuid.uuid4().hex[:6].upper()}",
        issue_date=date.today(),
        due_date=date(date.today().year, date.today().month + 1 if date.today().month < 12 else 1,
                      date.today().day),
        seller=seller,
        buyer=buyer,
        lines=lines,
        notes="Merci pour votre confiance. Paiement par virement SEPA sous 30 jours.",
    )


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère une facture Factur-X (XML CII)")
    parser.add_argument("--output", default="facture_demo.xml", help="Fichier de sortie XML")
    parser.add_argument("--profile", default="EN16931",
                        choices=list(PROFILES.keys()), help="Profil Factur-X")
    args = parser.parse_args()

    invoice = make_demo_invoice()
    invoice.profile = args.profile
    xml_content = generate_facturx_xml(invoice)

    output_path = Path(args.output)
    output_path.write_text(xml_content, encoding="utf-8")

    print(f"✅ Facture générée : {output_path}")
    print(f"   Numéro    : {invoice.number}")
    print(f"   Vendeur   : {invoice.seller.name}")
    print(f"   Acheteur  : {invoice.buyer.name}")
    print(f"   Total HT  : {invoice.total_ht} €")
    print(f"   TVA       : {invoice.total_vat} €")
    print(f"   Total TTC : {invoice.total_ttc} €")
    print(f"   Profil    : {invoice.profile}")
