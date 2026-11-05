"""
reports/pdf_utils.py
====================
Shared ReportLab helpers used by every report's *_download view.

Drop this file in as reports/pdf_utils.py (same folder as views.py).

Usage from a view:

    from .pdf_utils import build_report_pdf, p

    return build_report_pdf(
        request=request,
        filename=f"Collections-{today}.pdf",
        title="Collections by Cashier",
        subtitle=f"Period: {date_from} to {date_to} | Generated: {datetime.now():%d %b %Y %H:%M}",
        sections=[
            {
                "heading": None,
                "head_row": ["Cashier", "Payments", "Total Collected"],
                "col_widths": [80*mm, 40*mm, 60*mm],
                "body_rows": [...],
                "totals_row": [...],   # optional
            },
        ],
    )
"""

from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape as make_landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

_styles = getSampleStyleSheet()

HEADER_STYLE = ParagraphStyle(
    "PDFHeader", parent=_styles["Heading1"],
    fontSize=14, alignment=TA_CENTER, spaceAfter=6,
)
SUB_STYLE = ParagraphStyle(
    "PDFSub", parent=_styles["Normal"],
    fontSize=9, alignment=TA_CENTER, spaceAfter=10,
    textColor=colors.HexColor("#475569"),
)
SECTION_STYLE = ParagraphStyle(
    "PDFSection", parent=_styles["Heading2"],
    fontSize=11, alignment=TA_LEFT, spaceBefore=10, spaceAfter=6,
    textColor=colors.HexColor("#1e293b"),
)
CELL_STYLE = ParagraphStyle("PDFCell", parent=_styles["Normal"], fontSize=8, spaceAfter=2)
CELL_BOLD = ParagraphStyle("PDFCellBold", parent=CELL_STYLE, fontName="Helvetica-Bold")


def p(text, style=CELL_STYLE):
    """Wrap a value in a Paragraph so long text wraps inside table cells."""
    if text is None:
        text = ""
    return Paragraph(str(text), style)


def _excel_value(value):
    if isinstance(value, Paragraph):
        return value.getPlainText()
    return value


def build_report_excel(request, filename, title, subtitle, sections):
    """Build a styled, filterable workbook using the same rows as the PDF."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    workbook.properties.title = title
    workbook.properties.subject = subtitle
    header_fill = PatternFill("solid", fgColor="163B50")
    section_fill = PatternFill("solid", fgColor="DCE8EF")
    total_fill = PatternFill("solid", fgColor="E8F1F5")
    white_font = Font(color="FFFFFF", bold=True)
    bold_font = Font(bold=True)
    thin_border = Border(bottom=Side(style="thin", color="D5E0E7"))

    for section_index, section in enumerate(sections):
        sheet = workbook.active if section_index == 0 else workbook.create_sheet()
        heading = section.get("heading") or title
        sheet.title = (heading or f"Report {section_index + 1}")[:31]
        sheet.append([title])
        sheet.append([subtitle])
        sheet.append([])
        if section.get("heading"):
            sheet.append([section["heading"]])
        sheet.append([_excel_value(value) for value in section["head_row"]])
        header_row = sheet.max_row
        for row in section.get("body_rows", []):
            sheet.append([_excel_value(value) for value in row])
        if section.get("totals_row"):
            sheet.append([_excel_value(value) for value in section["totals_row"]])
        last_row = sheet.max_row

        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(section["head_row"]))
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(section["head_row"]))
        sheet["A1"].font = Font(size=15, bold=True, color="163B50")
        sheet["A2"].font = Font(italic=True, color="516A7F")
        sheet["A1"].alignment = Alignment(horizontal="left")
        sheet["A2"].alignment = Alignment(horizontal="left")
        if section.get("heading"):
            sheet.merge_cells(start_row=4, start_column=1, end_row=4, end_column=len(section["head_row"]))
            sheet["A4"].font = Font(bold=True, color="163B50")
            sheet["A4"].fill = section_fill
        for cell in sheet[header_row]:
            cell.font = white_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if section.get("totals_row"):
            for cell in sheet[last_row]:
                cell.font = bold_font
                cell.fill = total_fill
        for row in sheet.iter_rows(min_row=header_row + 1, max_row=last_row):
            for cell in row:
                cell.border = thin_border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.freeze_panes = f"A{header_row + 1}"
        if last_row >= header_row:
            sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(len(section['head_row']))}{last_row}"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.page_setup.orientation = "landscape" if len(section["head_row"]) > 6 else "portrait"
        sheet.oddFooter.center.text = "Generated by ABA Uganda Loan Management System"
        for column in range(1, len(section["head_row"]) + 1):
            values = [sheet.cell(row, column).value for row in range(header_row, last_row + 1)]
            width = max((len(str(value or "")) for value in values), default=10)
            sheet.column_dimensions[get_column_letter(column)].width = min(max(width + 2, 12), 42)

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def build_report_pdf(request, filename, title, subtitle, sections, landscape=False):
    """
    Build and return an HttpResponse containing a generated PDF.

    sections: list of dicts, each with:
        heading     (str or None)      - optional sub-heading printed above the table
        head_row    (list[str])        - column header labels
        body_rows   (list[list])       - list of rows; each cell should already be a
                                          Paragraph (use `p(...)`) or plain string
        col_widths  (list[float])      - column widths in points (use `mm` units), must
                                          sum to <= usable page width
        totals_row  (list, optional)   - a final bold/highlighted row

    mode: pass ?mode=inline in the query string to open the PDF in-browser
          (used by the "Print" button); default is a forced download/attachment
          (used by the "Download PDF" button).
    """
    if request.GET.get("format") in {"excel", "xlsx"}:
        return build_report_excel(
            request,
            filename=filename.rsplit(".", 1)[0] + ".xlsx",
            title=title,
            subtitle=subtitle,
            sections=sections,
        )

    buffer = BytesIO()
    pagesize = make_landscape(A4) if landscape else A4
    doc = SimpleDocTemplate(
        buffer, pagesize=pagesize,
        rightMargin=12 * mm, leftMargin=12 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    story = [Paragraph(title, HEADER_STYLE), Paragraph(subtitle, SUB_STYLE)]

    for section in sections:
        if section.get("heading"):
            story.append(Paragraph(section["heading"], SECTION_STYLE))

        head_row = [p(f"<b>{h}</b>", CELL_BOLD) for h in section["head_row"]]
        table_data = [head_row] + list(section["body_rows"])

        totals_row = section.get("totals_row")
        if totals_row:
            table_data.append(totals_row)

        if not section["body_rows"] and not totals_row:
            story.append(Paragraph("No records found for the selected filters.", CELL_STYLE))
            story.append(Spacer(1, 10))
            continue

        table = Table(table_data, colWidths=section["col_widths"], repeatRows=1)
        style_cmds = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]
        if totals_row:
            last = len(table_data) - 1
            style_cmds += [
                ("BACKGROUND", (0, last), (-1, last), colors.HexColor("#F1F5F9")),
                ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
            ]
        table.setStyle(TableStyle(style_cmds))
        story.append(table)
        story.append(Spacer(1, 14))

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        canvas.line(document.leftMargin, 10 * mm, pagesize[0] - document.rightMargin, 10 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(document.leftMargin, 6 * mm, "ABA Uganda Loan Management System")
        canvas.drawRightString(
            pagesize[0] - document.rightMargin,
            6 * mm,
            f"Page {document.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    disposition = "inline" if request.GET.get("mode") == "inline" else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response