import io
from datetime import datetime
from typing import List, Dict, Optional
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_RIGHT, TA_CENTER


def generate_invoice_pdf(
    invoice_number: str,
    therapist_name: str,
    therapist_email: str,
    therapist_license: Optional[str],
    client_name: str,
    client_email: str,
    line_items: List[Dict],   # [{"description", "date", "session_type", "amount"}]
    amount: float,
    status: str,
    due_date: str,
    paid_at: Optional[str] = None,
    invoice_id: Optional[str] = None,
    payment_instructions: Optional[str] = None,
    currency: str = "USD",
) -> bytes:
    sym = "ILS " if currency == "ILS" else "$"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=0.75 * inch, leftMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # Header
    title_style = ParagraphStyle("title", fontSize=24, fontName="Helvetica-Bold",
                                 textColor=colors.HexColor("#4F46E5"))
    story.append(Paragraph("INVOICE", title_style))
    story.append(Spacer(1, 0.1 * inch))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#4F46E5")))
    story.append(Spacer(1, 0.2 * inch))

    # Invoice meta + therapist info
    meta_data = [
        [Paragraph(f"<b>{therapist_name}</b>", styles["Normal"]),
         Paragraph(f"<b>Invoice #:</b> {invoice_number}", styles["Normal"])],
        [Paragraph(therapist_email, styles["Normal"]),
         Paragraph(f"<b>Date:</b> {datetime.utcnow().strftime('%B %d, %Y')}", styles["Normal"])],
        [Paragraph(f"License: {therapist_license or 'N/A'}", styles["Normal"]),
         Paragraph(f"<b>Due Date:</b> {due_date}", styles["Normal"])],
        [Paragraph("", styles["Normal"]),
         Paragraph(
             f"<b>Status:</b> <font color='{'green' if status == 'paid' else 'red'}'>{status.upper()}</font>",
             styles["Normal"]
         )],
    ]
    meta_table = Table(meta_data, colWidths=[3.5 * inch, 3.5 * inch])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.3 * inch))

    # Bill To
    story.append(Paragraph("<b>BILL TO</b>", styles["Normal"]))
    story.append(Spacer(1, 0.05 * inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(client_name, styles["Normal"]))
    story.append(Paragraph(client_email, styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    # Services table
    header_style = ParagraphStyle("header", fontName="Helvetica-Bold", fontSize=10)
    services_data = [[
        Paragraph("DESCRIPTION", header_style),
        Paragraph("DATE", header_style),
        Paragraph("TYPE", header_style),
        Paragraph("AMOUNT", header_style),
    ]]
    for item in line_items:
        services_data.append([
            Paragraph(item["description"], styles["Normal"]),
            Paragraph(item["date"], styles["Normal"]),
            Paragraph(item["session_type"], styles["Normal"]),
            Paragraph(f"{sym}{item['amount']:.2f}", styles["Normal"]),
        ])

    services_table = Table(services_data, colWidths=[3 * inch, 1.5 * inch, 1.5 * inch, 1 * inch])
    services_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(services_table)
    story.append(Spacer(1, 0.2 * inch))

    # Total
    total_data = [
        ["", "", Paragraph("<b>TOTAL</b>", styles["Normal"]),
         Paragraph(f"<b>{sym}{amount:.2f}</b>", styles["Normal"])],
    ]
    if status == "paid" and paid_at:
        total_data.append(["", "",
                           Paragraph("<font color='green'>PAID</font>", styles["Normal"]),
                           Paragraph(paid_at, styles["Normal"])])

    total_table = Table(total_data, colWidths=[3 * inch, 1.5 * inch, 1.5 * inch, 1 * inch])
    total_table.setStyle(TableStyle([
        ("ALIGN", (2, 0), (3, -1), "RIGHT"),
        ("LINEABOVE", (2, 0), (3, 0), 1, colors.HexColor("#4F46E5")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(total_table)

    # Payment instructions
    if payment_instructions:
        story.append(Spacer(1, 0.3 * inch))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph("<b>Payment Instructions</b>", styles["Normal"]))
        story.append(Spacer(1, 0.05 * inch))
        instr_style = ParagraphStyle("instr", fontSize=10, textColor=colors.HexColor("#374151"),
                                     leading=14)
        story.append(Paragraph(payment_instructions.replace("\n", "<br/>"), instr_style))

    if invoice_id:
        story.append(Spacer(1, 0.4 * inch))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        note_style = ParagraphStyle("note", fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
        story.append(Paragraph(f"Reference ID: {invoice_id}", note_style))

    doc.build(story)
    return buffer.getvalue()
