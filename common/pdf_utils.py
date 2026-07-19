from io import BytesIO
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def _format_money(value):
    return f"UGX {value:,.0f}"


def _make_receipt_story(receipt, guarantees, collateral_items):
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.spaceAfter = 6
    header_style = ParagraphStyle(
        "Header",
        parent=styles["Heading1"],
        fontSize=16,
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    small = ParagraphStyle("Small", parent=normal, fontSize=9, textColor=colors.grey)

    story = [Paragraph("ABA Uganda", header_style)]
    story.append(Paragraph("Loan Management System · Kampala, Uganda", small))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>PAYMENT RECEIPT</b>", styles["Heading2"]))
    story.append(Paragraph(f"<b>Receipt:</b> {receipt.receipt_number}", normal))
    story.append(Paragraph(f"<b>Date:</b> {receipt.payment.payment_date}", normal))
    story.append(Paragraph(f"<b>Client:</b> {receipt.payment.client.full_name}", normal))
    story.append(Paragraph(f"<b>Loan Reference:</b> {receipt.payment.loan.loan_number}", normal))
    story.append(Spacer(1, 12))

    table_data = [
        [Paragraph("<b>Field</b>", normal), Paragraph("<b>Value</b>", normal)],
        ["Client #", receipt.payment.client.client_number],
        ["Phone", receipt.payment.client.phone_primary],
        ["Product", receipt.payment.loan.product.name],
        ["Payment Method", receipt.payment.get_payment_method_display()],
    ]

    if receipt.payment.reference_number:
        table_data.append(["Reference #", receipt.payment.reference_number])

    table_data.extend([
        ["Principal Paid", _format_money(receipt.principal_paid)],
        ["Interest Paid", _format_money(receipt.interest_paid)],
        ["Penalty Paid", _format_money(receipt.penalty_paid)],
        ["Amount Received", _format_money(receipt.amount_received)],
        ["Balance Before", _format_money(receipt.balance_before)],
        ["Balance After", _format_money(receipt.balance_after)],
    ])

    table = Table(table_data, colWidths=[90*mm, 80*mm])
    table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (0,-1), "LEFT"),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))
    story.append(table)

    summary_table_data = [
        [Paragraph("<b>Loan Summary</b>", normal), Paragraph("<b>Value</b>", normal)],
        ["Principal + Interest", _format_money(receipt.payment.loan.total_repayable)],
        ["Processing Fee", _format_money(receipt.payment.loan.effective_processing_fee)],
        ["Outstanding Balance", _format_money(receipt.payment.loan.outstanding_balance)],
    ]
    summary_table = Table(summary_table_data, colWidths=[90*mm, 80*mm])
    summary_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (0,0), (0,-1), "LEFT"),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))
    story.append(Spacer(1, 10))
    story.append(summary_table)

    if guarantees:
        story.append(Spacer(1, 12))
        story.append(Paragraph("<b>Guarantors</b>", styles["Heading3"]))
        for g in guarantees:
            story.append(Paragraph(f"{g.guarantor.full_name} — {_format_money(g.guaranteed_amount)}", normal))

    if collateral_items:
        story.append(Spacer(1, 12))
        story.append(Paragraph("<b>Collateral</b>", styles["Heading3"]))
        for c in collateral_items:
            story.append(Paragraph(f"{c.description} — {_format_money(c.estimated_value)}", normal))

    story.append(Spacer(1, 18))
    story.append(Paragraph(f"Served by: {receipt.payment.recorded_by.full_name}", small))
    story.append(Paragraph(f"Issued: {receipt.issued_at:%d %b %Y %H:%M}", small))
    story.append(Paragraph("ABA Uganda — This is an official receipt. Keep it safe.", small))

    return story


def render_pdf_response(request, template_name, context, filename="document.pdf"):
    receipt = context.get("receipt")
    guarantees = context.get("guarantees", [])
    collateral_items = context.get("collateral_items", [])

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []

    if receipt is not None:
        story = _make_receipt_story(receipt, guarantees, collateral_items)
    else:
        story = [Paragraph("PDF generation is not configured for this document.", getSampleStyleSheet()["Normal"])]

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def generate_loan_schedule_pdf(loan):
    """Generate PDF for a loan schedule."""
    from datetime import datetime

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("Normal", parent=styles["Normal"], fontSize=9, spaceAfter=2)
    header_style = ParagraphStyle("Header", parent=styles["Heading1"], fontSize=14, alignment=TA_CENTER, spaceAfter=8)
    small = ParagraphStyle("Small", parent=normal, fontSize=8, textColor=colors.grey)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []

    # Header
    story.append(Paragraph("Loan Schedule", header_style))
    story.append(Paragraph(f"<b>Loan:</b> {loan.loan_number} | <b>Client:</b> {loan.client.full_name} | <b>Amount:</b> UGX {loan.principal_amount:,.0f}", normal))
    story.append(Paragraph(f"<b>Product:</b> {loan.product.name} | <b>Status:</b> {loan.get_status_display()}", normal))
    story.append(Spacer(1, 8))

    # Schedule table
    schedule_items = getattr(loan, "schedule", None)
    if schedule_items is None:
        schedule_items = []
    elif hasattr(schedule_items, 'all'):
        schedule_items = list(schedule_items.all())
    else:
        schedule_items = list(schedule_items)

    schedule_items = sorted(schedule_items, key=lambda item: getattr(item, "due_date", ""))
    table_data = [[
        Paragraph("<b>#</b>", normal),
        Paragraph("<b>Due Date</b>", normal),
        Paragraph("<b>Opening Bal.</b>", normal),
        Paragraph("<b>Principal</b>", normal),
        Paragraph("<b>Interest</b>", normal),
        Paragraph("<b>Penalty</b>", normal),
        Paragraph("<b>Total Due</b>", normal),
        Paragraph("<b>Paid</b>", normal),
        Paragraph("<b>Status</b>", normal),
    ]]

    for idx, item in enumerate(schedule_items, 1):
        due_date = getattr(item, "due_date", None)
        if hasattr(due_date, "strftime"):
            due_date_text = due_date.strftime("%d %b %Y")
        else:
            due_date_text = str(due_date or "")

        table_data.append([
            Paragraph(str(idx), normal),
            Paragraph(due_date_text, normal),
            Paragraph(f"UGX {item.opening_balance:,.0f}", normal),
            Paragraph(f"UGX {item.principal_due:,.0f}", normal),
            Paragraph(f"UGX {item.interest_due:,.0f}", normal),
            Paragraph(f"UGX {item.penalty_due:,.0f}", normal),
            Paragraph(f"UGX {item.total_payment:,.0f}", normal),
            Paragraph(f"UGX {item.amount_paid:,.0f}", normal),
            Paragraph(item.get_status_display(), normal),
        ])

    table = Table(table_data, colWidths=[8*mm, 16*mm, 18*mm, 16*mm, 16*mm, 14*mm, 16*mm, 16*mm, 14*mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(table)

    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Generated on {datetime.now():%d %b %Y %H:%M}", small))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes