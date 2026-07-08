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

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    disposition = "inline" if request.GET.get("mode") == "inline" else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response