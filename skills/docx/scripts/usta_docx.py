"""Word writing helpers for the Usta sandbox (python-docx)."""

from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

FONT = "Arial"  # present in Word and mapped to Liberation Sans in LibreOffice; covers Azerbaijani


def new_document():
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(11)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), FONT)
    return doc


def add_table(doc, rows: list[list], header: bool = True):
    cols = max(len(r) for r in rows)
    t = doc.add_table(rows=0, cols=cols)
    t.style = "Table Grid"
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j, value in enumerate(row):
            cells[j].text = str(value)
            if header and i == 0:
                for run in cells[j].paragraphs[0].runs:
                    run.bold = True
    return t
