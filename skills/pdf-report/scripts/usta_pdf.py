"""PDF report helpers for the Usta sandbox. ReportLab's built-in fonts cannot render
ə ğ ı ş İ (SPEC F6), so everything here uses DejaVu Sans from the image."""

from __future__ import annotations

from datetime import date

from babel.dates import format_date
from babel.numbers import format_currency, format_decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVuSans", f"{FONT_DIR}/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", f"{FONT_DIR}/DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily(
        "DejaVuSans",
        normal="DejaVuSans",
        bold="DejaVuSans-Bold",
        italic="DejaVuSans",
        boldItalic="DejaVuSans-Bold",
    )
    _registered = True


def styles() -> dict[str, ParagraphStyle]:
    register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "UstaTitle", parent=base["Title"], fontName="DejaVuSans-Bold", fontSize=18, leading=22
        ),
        "h2": ParagraphStyle(
            "UstaH2", parent=base["Heading2"], fontName="DejaVuSans-Bold", fontSize=13,
            leading=16, spaceBefore=6,
        ),
        "body": ParagraphStyle(
            "UstaBody", parent=base["BodyText"], fontName="DejaVuSans", fontSize=10, leading=14
        ),
        "cell": ParagraphStyle(
            "UstaCell", parent=base["BodyText"], fontName="DejaVuSans", fontSize=9, leading=11
        ),
    }  # fmt: skip


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def table(rows: list[list], header: bool = True, col_widths: list[float] | None = None) -> Table:
    st = styles()
    data = [[Paragraph(_esc(str(c)), st["cell"]) for c in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(path: str, title: str, blocks: list) -> str:
    """blocks: strings (paragraphs; '## ' starts a heading; a path ending in .png embeds an
    image) or flowables such as table(...)."""
    st = styles()
    story: list = [Paragraph(_esc(title), st["title"]), Spacer(1, 4 * mm)]
    for block in blocks:
        if isinstance(block, str) and block.lower().endswith(".png"):
            story.append(Image(block, width=170 * mm, height=95 * mm, kind="proportional"))
        elif isinstance(block, str) and block.startswith("## "):
            story.append(Paragraph(_esc(block[3:]), st["h2"]))
        elif isinstance(block, str):
            story.append(Paragraph(_esc(block), st["body"]))
        else:
            story.append(block)
        story.append(Spacer(1, 3 * mm))
    doc = SimpleDocTemplate(
        path, pagesize=A4, title=title,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    )  # fmt: skip
    doc.build(story)
    return path


def fmt_number(x: float, decimals: int = 2) -> str:
    return format_decimal(x, format=f"#,##0.{'0' * decimals}" if decimals else "#,##0", locale="az")


def fmt_azn(x: float) -> str:
    # Babel's az symbol is ₼ (U+20BC), which DejaVu Sans lacks: it extracts as NUL. Use the code.
    return format_currency(x, "AZN", locale="az", format="#,##0.00 ¤¤", currency_digits=False)


def fmt_date(d: date) -> str:
    return format_date(d, format="medium", locale="az")
