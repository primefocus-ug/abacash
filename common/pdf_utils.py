from io import BytesIO
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def _format_money(value):
    return f"UGX {value:,.0f}"


def _append_signatory(story, signatory, normal_style):
    if not signatory or not signatory.signature:
        return
    with signatory.signature.open("rb") as uploaded_signature:
        image_data = BytesIO(uploaded_signature.read())
    story.extend([
        Spacer(1, 10),
        Paragraph(f"<b>Authorised signatory:</b> {signatory.full_name}", normal_style),
        Image(image_data, width=45*mm, height=18*mm, kind="proportional"),
    ])


def _make_receipt_story(receipt, guarantees, collateral_items, signatory=None):
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
    _append_signatory(story, signatory, normal)

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
    signatory = context.get("selected_signatory")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []

    if receipt is not None:
        story = _make_receipt_story(receipt, guarantees, collateral_items, signatory)
    else:
        story = [Paragraph("PDF generation is not configured for this document.", getSampleStyleSheet()["Normal"])]

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def generate_loan_schedule_pdf(loan, signatory=None):
    """Generate PDF for a loan schedule."""
    from datetime import datetime
    from xml.sax.saxutils import escape
    from accounts.models import BankAccount

    styles = getSampleStyleSheet()
    normal = ParagraphStyle("Normal", parent=styles["Normal"], fontSize=9, spaceAfter=2)
    header_style = ParagraphStyle("Header", parent=styles["Heading1"], fontSize=14, alignment=TA_CENTER, spaceAfter=8)
    small = ParagraphStyle("Small", parent=normal, fontSize=8, textColor=colors.grey)
    table_text = ParagraphStyle("ScheduleCell", parent=normal, fontSize=7, leading=8)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12*mm,
        leftMargin=12*mm,
        topMargin=14*mm,
        bottomMargin=16*mm,
    )
    story = []
    generated_at = datetime.now()
    nominal_apr = loan.interest_rate_monthly * 12
    total_cost_of_credit = loan.total_interest + loan.processing_fee

    # Header
    story.append(Paragraph("Loan Schedule", header_style))
    story.append(Paragraph(f"<b>Loan:</b> {loan.loan_number} | <b>Client:</b> {loan.client.full_name} | <b>Amount:</b> UGX {loan.principal_amount:,.0f}", normal))
    story.append(Paragraph(f"<b>Product:</b> {loan.product.name} | <b>Status:</b> {loan.get_status_display()}", normal))
    disbursement_date = loan.disbursement_date.strftime("%d %b %Y") if loan.disbursement_date else "—"
    maturity_date = loan.maturity_date.strftime("%d %b %Y") if loan.maturity_date else "—"
    story.append(Paragraph(
        f"<b>Disbursement:</b> {disbursement_date} | <b>Maturity:</b> {maturity_date} | "
        f"<b>Interest:</b> {loan.get_interest_method_display()} at {loan.interest_rate_monthly}%/month "
        f"(<b>Nominal APR:</b> {nominal_apr:.2f}%)",
        normal,
    ))
    story.append(Paragraph(
        f"<b>Total interest:</b> {_format_money(loan.total_interest)} | "
        f"<b>Processing fee:</b> {_format_money(loan.processing_fee)} | "
        f"<b>Total cost of credit:</b> {_format_money(total_cost_of_credit)} | "
        f"<b>Scheduled repayment:</b> {_format_money(loan.total_repayable)}",
        normal,
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Payment instructions</b>", normal))
    story.append(Paragraph(
        f"Pay by mobile money or bank transfer using an active account below. "
        f"Enter loan number <b>{escape(loan.loan_number)}</b> as the payment reference.",
        small,
    ))
    accounts = BankAccount.objects.filter(
        is_active=True,
        account_type__in=(
            BankAccount.AccountType.CURRENT,
            BankAccount.AccountType.SAVINGS,
            BankAccount.AccountType.MOBILE,
        ),
    ).order_by("account_type", "bank_name")
    if accounts.exists():
        for account in accounts:
            account_details = " · ".join(filter(None, [
                account.get_account_type_display(),
                account.bank_name,
                account.branch_name,
                account.account_name,
                account.account_number,
            ]))
            story.append(Paragraph(escape(account_details), small))
    else:
        story.append(Paragraph(
            "Contact your branch for current mobile money or bank account details.",
            small,
        ))
    story.append(Spacer(1, 8))

    collateral_items = loan.collateral_items.all()
    if collateral_items.exists():
        story.append(Paragraph("<b>Collateral pledged</b>", normal))
        for item in collateral_items:
            details = [escape(item.description), f"UGX {item.estimated_value:,.0f}"]
            if item.document_number:
                details.append(f"Document: {escape(item.document_number)}")
            if item.storage_location:
                details.append(f"Held at: {escape(item.storage_location)}")
            if item.notes:
                details.append(escape(item.notes))
            if item.release_date:
                released_to = f" to {escape(item.released_to)}" if item.released_to else ""
                details.append(f"Released {item.release_date}{released_to}")
            story.append(Paragraph(" — ".join(details), small))
        story.append(Spacer(1, 8))

    # Schedule table
    schedule_items = getattr(loan, "schedule", None)
    if schedule_items is None:
        schedule_items = []
    elif hasattr(schedule_items, 'all'):
        schedule_items = list(schedule_items.select_related("paid_by_payment").all())
    else:
        schedule_items = list(schedule_items)

    schedule_items = sorted(schedule_items, key=lambda item: getattr(item, "due_date", ""))
    table_data = [[
        Paragraph("<b>#</b>", table_text),
        Paragraph("<b>Due date</b>", table_text),
        Paragraph("<b>Opening</b>", table_text),
        Paragraph("<b>Principal</b>", table_text),
        Paragraph("<b>Interest</b>", table_text),
        Paragraph("<b>Penalty</b>", table_text),
        Paragraph("<b>Total due</b>", table_text),
        Paragraph("<b>Paid</b>", table_text),
        Paragraph("<b>Date paid</b>", table_text),
        Paragraph("<b>Payment ref.</b>", table_text),
        Paragraph("<b>Closing bal.</b>", table_text),
        Paragraph("<b>Status</b>", table_text),
    ]]

    for idx, item in enumerate(schedule_items, 1):
        due_date = getattr(item, "due_date", None)
        if hasattr(due_date, "strftime"):
            due_date_text = due_date.strftime("%d %b %Y")
        else:
            due_date_text = str(due_date or "")
        paid_date = getattr(item, "paid_date", None)
        paid_date_text = paid_date.strftime("%d %b %Y") if paid_date else "—"
        payment = getattr(item, "paid_by_payment", None)
        payment_reference = escape(payment.reference_number) if payment and payment.reference_number else "—"

        table_data.append([
            Paragraph(str(idx), table_text),
            Paragraph(due_date_text, table_text),
            Paragraph(f"{item.opening_balance:,.0f}", table_text),
            Paragraph(f"{item.principal_due:,.0f}", table_text),
            Paragraph(f"{item.interest_due:,.0f}", table_text),
            Paragraph(f"{item.penalty_due:,.0f}", table_text),
            Paragraph(f"{item.total_payment:,.0f}", table_text),
            Paragraph(f"{item.amount_paid:,.0f}", table_text),
            Paragraph(paid_date_text, table_text),
            Paragraph(payment_reference, table_text),
            Paragraph(f"{item.closing_balance:,.0f}", table_text),
            Paragraph(escape(item.get_status_display()), table_text),
        ])

    if schedule_items:
        table_data.append([
            Paragraph("<b>Totals</b>", table_text), "",
            "—", f"{loan.principal_amount:,.0f}", f"{loan.total_interest:,.0f}", "—",
            f"{loan.total_repayable:,.0f}", f"{loan.total_paid:,.0f}", "", "", "0", "",
        ])

    table = Table(
        table_data,
        colWidths=[8*mm, 20*mm, 20*mm, 19*mm, 19*mm, 16*mm, 20*mm, 18*mm, 20*mm, 28*mm, 20*mm, 18*mm],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("ALIGN", (9, 1), (9, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E5E7EB")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(table)
    _append_signatory(story, signatory, normal)

    def draw_page_footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(document.leftMargin, 8*mm, f"Generated on {generated_at:%d %b %Y %H:%M}")
        canvas.drawRightString(landscape(A4)[0] - document.rightMargin, 8*mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page_footer, onLaterPages=draw_page_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes