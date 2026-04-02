"""
generate_pdf.py
----------------
Génère un PDF visuel de la facture (couche humaine du Factur-X).
Utilise ReportLab. Ce PDF sera ensuite enrichi par generate_facturx.py
pour embarquer le XML CII et devenir un PDF/A-3 Factur-X complet.

Usage :
    from generate_pdf import render_invoice_pdf
    pdf_bytes = render_invoice_pdf(invoice)
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER

from generate_invoice import Invoice

# ── Palette ───────────────────────────────────────────────
BLUE_DARK  = colors.HexColor("#0f3460")
BLUE_MID   = colors.HexColor("#16213e")
GREY_LIGHT = colors.HexColor("#f8f9fa")
GREY_MID   = colors.HexColor("#dee2e6")
RED_DGFIP  = colors.HexColor("#c0392b")
WHITE      = colors.white
BLACK      = colors.HexColor("#212529")

W, H = A4  # 210 × 297 mm


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Retourne les bytes du PDF visuel de la facture."""
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
        title=f"Facture {invoice.number}",
        author=invoice.seller.name,
        subject="Facture électronique Factur-X",
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Style helpers ──────────────────────────────────────
    def s(name, **kw):
        base = styles[name]
        return ParagraphStyle(name + "_custom", parent=base, **kw)

    title_style    = s("Heading1", textColor=WHITE, fontSize=18, leading=22, alignment=TA_LEFT)
    h2_style       = s("Heading2", textColor=BLUE_DARK, fontSize=10, leading=14, spaceAfter=2)
    normal_style   = s("Normal",   textColor=BLACK,    fontSize=9,  leading=13)
    small_style    = s("Normal",   textColor=BLACK,    fontSize=8,  leading=12)
    right_style    = s("Normal",   textColor=BLACK,    fontSize=9,  alignment=TA_RIGHT)
    bold_style     = s("Normal",   textColor=BLACK,    fontSize=9,  leading=13, fontName="Helvetica-Bold")
    total_style    = s("Normal",   textColor=WHITE,    fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    footer_style   = s("Normal",   textColor=colors.HexColor("#6c757d"), fontSize=7, alignment=TA_CENTER)

    # ── HEADER BANNER ──────────────────────────────────────
    type_labels = {"380": "FACTURE", "381": "AVOIR", "384": "FACTURE RECTIFICATIVE", "386": "ACOMPTE"}
    doc_type    = type_labels.get(str(getattr(invoice, "type_code", "380")), "FACTURE")

    header_data = [[
        Paragraph(f'<b>{invoice.seller.name}</b><br/>'
                  f'<font size="9">{invoice.seller.address.street}<br/>'
                  f'{invoice.seller.address.postal_code} {invoice.seller.address.city}</font>',
                  s("Normal", textColor=WHITE, fontSize=11, leading=16)),
        Paragraph(f'<b>{doc_type}</b><br/>'
                  f'<font size="9">{invoice.number}</font>',
                  s("Normal", textColor=WHITE, fontSize=16, leading=22, alignment=TA_RIGHT)),
    ]]
    header_table = Table(header_data, colWidths=[110 * mm, 65 * mm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), BLUE_DARK),
        ("TOPPADDING",  (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",(0,0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    # ── INFOS FACTURE (dates, vendeur, acheteur) ───────────
    date_str = invoice.issue_date.strftime("%d/%m/%Y")
    due_str  = invoice.due_date.strftime("%d/%m/%Y")

    info_data = [
        [
            # Émetteur
            Paragraph("<b>ÉMETTEUR</b>", h2_style),
            Paragraph("<b>DESTINATAIRE</b>", h2_style),
            Paragraph("<b>DÉTAILS FACTURE</b>", h2_style),
        ],
        [
            Paragraph(
                f"<b>{invoice.seller.name}</b><br/>"
                f"{invoice.seller.address.street}<br/>"
                f"{invoice.seller.address.postal_code} {invoice.seller.address.city}<br/>"
                f"SIREN : {invoice.seller.siret or '—'}<br/>"
                f"TVA : {invoice.seller.vat_number or '—'}",
                small_style
            ),
            Paragraph(
                f"<b>{invoice.buyer.name}</b><br/>"
                f"{invoice.buyer.address.street}<br/>"
                f"{invoice.buyer.address.postal_code} {invoice.buyer.address.city}<br/>"
                f"SIREN : {invoice.buyer.siret or '—'}",
                small_style
            ),
            Paragraph(
                f"<b>Date d'émission :</b> {date_str}<br/>"
                f"<b>Date d'échéance :</b> {due_str}<br/>"
                f"<b>Devise :</b> {invoice.currency}<br/>"
                f"<b>Profil :</b> {invoice.profile}",
                small_style
            ),
        ],
    ]
    info_table = Table(info_data, colWidths=[58 * mm, 58 * mm, 59 * mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), GREY_LIGHT),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.5, GREY_MID),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 6 * mm))

    # ── LIGNES DE FACTURE ─────────────────────────────────
    story.append(Paragraph("DÉTAIL DES PRESTATIONS", h2_style))

    line_header = ["#", "Description", "Qté", "PU HT (€)", "TVA %", "Total HT (€)"]
    line_rows = [line_header]
    for i, line in enumerate(invoice.lines, start=1):
        line_rows.append([
            str(i),
            line.description,
            str(line.quantity),
            f"{float(line.unit_price):,.2f}",
            f"{float(line.vat_rate):.0f}%",
            f"{float(line.line_total_ht):,.2f}",
        ])

    col_w = [8 * mm, 73 * mm, 14 * mm, 22 * mm, 14 * mm, 24 * mm]
    line_table = Table(line_rows, colWidths=col_w, repeatRows=1)
    line_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE_MID),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
        # Données
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("ALIGN",         (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 1), (0, -1),  "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.3, GREY_MID),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, BLUE_DARK),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 4 * mm))

    # ── TOTAUX ────────────────────────────────────────────
    totals_data = [
        ["", "Total HT :",     f"{float(invoice.total_ht):,.2f} €"],
        ["", "TVA :",          f"{float(invoice.total_vat):,.2f} €"],
        ["", "TOTAL TTC :",    f"{float(invoice.total_ttc):,.2f} €"],
    ]
    totals_table = Table(totals_data, colWidths=[100 * mm, 40 * mm, 35 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTNAME",      (1, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (1, 0), (-1, -1), 9),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        # Ligne TTC
        ("BACKGROUND",    (1, 2), (-1, 2), BLUE_DARK),
        ("TEXTCOLOR",     (1, 2), (-1, 2), WHITE),
        ("FONTNAME",      (1, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE",      (1, 2), (-1, 2), 10),
        ("LINEABOVE",     (1, 1), (-1, 1), 0.5, GREY_MID),
        ("LINEABOVE",     (1, 2), (-1, 2), 1,   BLUE_DARK),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 6 * mm))

    # ── PAIEMENT + NOTES ──────────────────────────────────
    if invoice.seller.iban:
        story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("<b>COORDONNÉES DE PAIEMENT</b>", h2_style))
        story.append(Paragraph(
            f"Virement SEPA — IBAN : <b>{invoice.seller.iban}</b>"
            + (f" · BIC : <b>{invoice.seller.bic}</b>" if invoice.seller.bic else ""),
            small_style
        ))
        story.append(Spacer(1, 3 * mm))

    if invoice.notes:
        story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("<b>MENTIONS LÉGALES</b>", h2_style))
        story.append(Paragraph(invoice.notes, small_style))
        story.append(Spacer(1, 3 * mm))

    # ── FOOTER FACTUR-X ───────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=BLUE_DARK))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f"Document Factur-X conforme EN 16931 · Profil {invoice.profile} · "
        f"XML CII embarqué conformément à la réforme DGFiP 2026",
        footer_style
    ))

    doc.build(story)
    return buffer.getvalue()