"""
generate_facturx.py
--------------------
Assemble le PDF visuel + le XML CII en un fichier Factur-X PDF/A-3b.
Le XML est embarqué dans le PDF avec les métadonnées XMP obligatoires.

Usage :
    from generate_facturx import build_facturx
    pdf_bytes = build_facturx(invoice, xml_string)

    # Ou depuis un XML existant :
    pdf_bytes = build_facturx_from_xml(xml_string, profile="EN16931")
"""
from __future__ import annotations

from io import BytesIO

import facturx

from generate_invoice import Invoice, PROFILES
from generate_pdf import render_invoice_pdf

# Map profil Factur-X → niveau attendu par la lib
FACTURX_LEVELS = {
    "MINIMUM":  "minimum",
    "BASIC_WL": "basicwl",
    "BASIC":    "basic",
    "EN16931":  "en16931",
    "EXTENDED": "extended",
}


def build_facturx(invoice: Invoice, xml_string: str) -> bytes:
    """
    Génère un Factur-X complet (PDF/A-3b + XML CII embarqué)
    à partir d'un objet Invoice et du XML CII déjà généré.
    """
    # 1. Générer le PDF visuel
    pdf_bytes = render_invoice_pdf(invoice)

    # 2. Embarquer le XML dans le PDF → Factur-X
    level = FACTURX_LEVELS.get(invoice.profile, "en16931")

    facturx_pdf = facturx.generate_facturx_from_file(
        pdf_io=BytesIO(pdf_bytes),
        xml=xml_string.encode("utf-8"),
        facturx_level=level,
        lang="fr",
        check_xsd=False,           # validation XSD déjà faite en amont
    )
    return facturx_pdf


def build_facturx_from_xml(xml_string: str, profile: str = "EN16931") -> bytes:
    """
    Génère un Factur-X à partir d'un XML CII existant.
    Crée un PDF minimaliste (page de garde) pour envelopper le XML.
    Utile pour convertir un XML conforme en Factur-X sans formulaire.
    """
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    import xml.etree.ElementTree as ET

    # Extraire le numéro de facture depuis le XML pour le titre
    try:
        root = ET.fromstring(xml_string)
        ns = {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
              "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"}
        inv_id = root.find(".//rsm:ExchangedDocument/ram:ID", ns)
        inv_num = inv_id.text if inv_id is not None else "N/A"
    except Exception:
        inv_num = "N/A"

    # PDF minimaliste — page de garde
    buf    = BytesIO()
    styles = getSampleStyleSheet()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=20*mm, rightMargin=20*mm,
                               topMargin=30*mm, bottomMargin=20*mm)
    story = [
        Paragraph(f"<b>Facture électronique Factur-X</b>", styles["Heading1"]),
        Spacer(1, 6*mm),
        Paragraph(f"Numéro : <b>{inv_num}</b>", styles["Normal"]),
        Spacer(1, 4*mm),
        Paragraph("Ce document est une facture électronique au format Factur-X (PDF/A-3b).", styles["Normal"]),
        Spacer(1, 2*mm),
        Paragraph("Le fichier XML CII conforme EN 16931 est embarqué dans ce PDF.", styles["Normal"]),
        Spacer(1, 2*mm),
        Paragraph(f"Profil : {profile}", styles["Normal"]),
    ]
    doc.build(story)
    pdf_bytes = buf.getvalue()

    level = FACTURX_LEVELS.get(profile, "en16931")
    return facturx.generate_facturx_from_file(
        pdf_io=BytesIO(pdf_bytes),
        xml=xml_string.encode("utf-8"),
        facturx_level=level,
        lang="fr",
        check_xsd=False,
    )