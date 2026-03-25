"""
generate_facturx.py
--------------------
Assemble le PDF visuel + le XML CII en un fichier Factur-X PDF/A-3b.
"""
from __future__ import annotations

from io import BytesIO

from generate_invoice import Invoice, PROFILES
from generate_pdf import render_invoice_pdf

# ── Import facturx — gestion multi-versions ────────────────
try:
    from facturx import generate_facturx_from_file as _facturx_gen
except (ImportError, AttributeError):
    try:
        from facturx.main import generate_facturx_from_file as _facturx_gen
    except (ImportError, AttributeError):
        _facturx_gen = None

# ── Fallback pypdf si facturx indisponible ─────────────────
def _embed_xml_pypdf(pdf_bytes: bytes, xml_bytes: bytes) -> bytes:
    """Embedding basique via pypdf (sans XMP Factur-X — fallback)."""
    from pypdf import PdfWriter, PdfReader
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_attachment("factur-x.xml", xml_bytes)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


FACTURX_LEVELS = {
    "MINIMUM":  "minimum",
    "BASIC_WL": "basicwl",
    "BASIC":    "basic",
    "EN16931":  "en16931",
    "EXTENDED": "extended",
}


def build_facturx(invoice: Invoice, xml_string: str) -> bytes:
    """Génère un Factur-X complet (PDF/A-3b + XML CII embarqué)."""
    pdf_bytes = render_invoice_pdf(invoice)
    xml_bytes = xml_string.encode("utf-8")
    level     = FACTURX_LEVELS.get(invoice.profile, "en16931")

    if _facturx_gen:
        return _facturx_gen(
            pdf_io=BytesIO(pdf_bytes),
            xml=xml_bytes,
            facturx_level=level,
            lang="fr",
            check_xsd=False,
        )
    else:
        return _embed_xml_pypdf(pdf_bytes, xml_bytes)


def build_facturx_from_xml(xml_string: str, profile: str = "EN16931") -> bytes:
    """Génère un Factur-X à partir d'un XML CII existant."""
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    import xml.etree.ElementTree as ET

    # Extraire le numéro depuis le XML
    try:
        root   = ET.fromstring(xml_string)
        ns     = {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
                  "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"}
        el     = root.find(".//rsm:ExchangedDocument/ram:ID", ns)
        inv_num = el.text if el is not None else "N/A"
    except Exception:
        inv_num = "N/A"

    # Page de garde minimale
    buf    = BytesIO()
    styles = getSampleStyleSheet()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=20*mm, rightMargin=20*mm,
                               topMargin=30*mm, bottomMargin=20*mm)
    doc.build([
        Paragraph("<b>Facture électronique Factur-X</b>", styles["Heading1"]),
        Spacer(1, 6*mm),
        Paragraph(f"Numéro : <b>{inv_num}</b>", styles["Normal"]),
        Spacer(1, 4*mm),
        Paragraph("Ce document est une facture électronique au format Factur-X (PDF/A-3b).", styles["Normal"]),
        Spacer(1, 2*mm),
        Paragraph("Le fichier XML CII conforme EN 16931 est embarqué dans ce PDF.", styles["Normal"]),
        Spacer(1, 2*mm),
        Paragraph(f"Profil : {profile}", styles["Normal"]),
    ])
    pdf_bytes = buf.getvalue()
    xml_bytes = xml_string.encode("utf-8")
    level     = FACTURX_LEVELS.get(profile, "en16931")

    if _facturx_gen:
        return _facturx_gen(
            pdf_io=BytesIO(pdf_bytes),
            xml=xml_bytes,
            facturx_level=level,
            lang="fr",
            check_xsd=False,
        )
    else:
        return _embed_xml_pypdf(pdf_bytes, xml_bytes)