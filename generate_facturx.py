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
    
def extract_xml_from_facturx(pdf_bytes: bytes) -> tuple[str, str]:
    """Extrait le XML CII embarqué dans un PDF Factur-X."""

    # ── Tentative via librairie facturx ───────────────────
    if _facturx_gen:
        try:
            import facturx as _fx
            _extract = getattr(_fx, "get_facturx_xml_from_pdf",
                       getattr(getattr(_fx, "main", None), "get_facturx_xml_from_pdf", None))
            if _extract:
                xml_bytes, profile = _extract(BytesIO(pdf_bytes))
                return xml_bytes.decode("utf-8"), profile or "EN16931"
        except Exception:
            pass

    # ── Fallback pypdf — chercher toute pièce jointe XML ──
    from pypdf import PdfReader
    reader  = PdfReader(BytesIO(pdf_bytes))
    catalog = reader.trailer["/Root"].get_object()

    # Méthode 1 : /Names > /EmbeddedFiles (standard PDF/A-3)
    try:
        ef_names = catalog["/Names"]["/EmbeddedFiles"]["/Names"]
        for i in range(0, len(ef_names), 2):
            name = str(ef_names[i])
            if name.lower().endswith(".xml") or "factur" in name.lower():
                fspec    = ef_names[i + 1].get_object()
                xml_data = fspec["/EF"]["/F"].get_object().get_data()
                return xml_data.decode("utf-8"), "EN16931"
    except Exception:
        pass

    # Méthode 2 : /AF (Associated Files — Factur-X spec)
    try:
        af = catalog["/AF"]
        for ref in af:
            fspec = ref.get_object()
            if "/EF" in fspec:
                xml_data = fspec["/EF"]["/F"].get_object().get_data()
                return xml_data.decode("utf-8"), "EN16931"
    except Exception:
        pass

    # Méthode 3 : chercher dans les annotations de chaque page
    try:
        for page in reader.pages:
            annots = page.get("/Annots", [])
            for annot in annots:
                a = annot.get_object()
                if a.get("/Subtype") == "/FileAttachment":
                    fspec    = a["/FS"].get_object()
                    xml_data = fspec["/EF"]["/F"].get_object().get_data()
                    return xml_data.decode("utf-8"), "EN16931"
    except Exception:
        pass

    raise ValueError(
        "Aucun XML Factur-X trouvé dans ce PDF. "
        "Vérifiez que le fichier est un PDF Factur-X (pas un simple PDF)."
    )