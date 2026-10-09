import pytest

from tests.conftest import Box

pytestmark = pytest.mark.sandbox

XLSX = """
import sys
sys.path.insert(0, "/skills/xlsx/scripts")
from usta_xlsx import write_xlsx
write_xlsx("/out/uygunsuzluqlar.xlsx", {
    "Uyğunsuzluqlar": [["Anbar", "Model", "Siyahıda", "Qalıq", "Fərq"],
                       ["Gəncə anbarı", "FMB920", 3, 1, -2]],
    "Mənbə: [köhnə]/x": [["Qeyd"], ["İŞIQ"]],
})
"""

DOCX = """
import sys
sys.path.insert(0, "/skills/docx/scripts")
from usta_docx import add_table, new_document
doc = new_document()
doc.add_heading("Müqavilə xülasəsi", level=1)
doc.add_paragraph("Ödəniş şərtləri: hər ayın 5-nə qədər. Cərimə: gecikmənin hər günü üçün 0,1%.")
add_table(doc, [["Bənd", "Məzmun"], ["4.2", "Gecikmə cəriməsi"]])
doc.save("/out/xulase.docx")
"""


async def test_xlsx_with_azerbaijani_headers_passes(box: Box) -> None:
    res = await box.run(XLSX)
    assert res.exit_code == 0, res.stderr
    result = await box.check("xlsx", "uygunsuzluqlar.xlsx")
    assert result["ok"], result["reasons"]
    assert "Gəncə anbarı" in result["text_sample"] and "İŞIQ" in result["text_sample"]


async def test_xlsx_with_error_values_or_no_data_fails(box: Box) -> None:
    code = (
        "from openpyxl import Workbook\n"
        "wb = Workbook(); wb.active.append(['Cəm', '#REF!']); wb.save('/out/xeta.xlsx')\n"
        "Workbook().save('/out/bos.xlsx')\n"
    )
    assert (await box.run(code)).exit_code == 0
    err = await box.check("xlsx", "xeta.xlsx")
    empty = await box.check("xlsx", "bos.xlsx")
    assert not err["ok"] and any("#REF!" in r for r in err["reasons"])
    assert not empty["ok"] and any("no data" in r for r in empty["reasons"])


async def test_docx_with_heading_paragraph_and_table_passes(box: Box) -> None:
    res = await box.run(DOCX)
    assert res.exit_code == 0, res.stderr
    result = await box.check("docx", "xulase.docx")
    assert result["ok"], result["reasons"]
    assert (
        "Ödəniş şərtləri" in result["text_sample"] and "Gecikmə cəriməsi" in result["text_sample"]
    )


async def test_empty_docx_fails(box: Box) -> None:
    assert (
        await box.run("from docx import Document; Document().save('/out/bos.docx')")
    ).exit_code == 0
    result = await box.check("docx", "bos.docx")
    assert not result["ok"] and any("no text" in r for r in result["reasons"])


async def test_header_only_workbook_fails(box: Box) -> None:
    code = (
        "from openpyxl import Workbook\n"
        "wb = Workbook(); wb.active.append(['Anbar', 'Qalıq']); wb.save('/out/basliq.xlsx')\n"
    )
    assert (await box.run(code)).exit_code == 0
    result = await box.check("xlsx", "basliq.xlsx")
    assert not result["ok"] and any("no data rows" in r for r in result["reasons"])


async def test_corrupt_sheet_xml_keeps_json_contract(box: Box) -> None:
    code = (
        "import zipfile\n"
        "from openpyxl import Workbook\n"
        "wb = Workbook(); wb.active.append(['Anbar', 'Qalıq']); wb.active.append(['Gəncə', 1])\n"
        "wb.save('/tmp/good.xlsx')\n"
        "with zipfile.ZipFile('/tmp/good.xlsx') as src, "
        "zipfile.ZipFile('/out/sinig.xlsx', 'w') as dst:\n"
        "    for item in src.infolist():\n"
        "        data = src.read(item.filename)\n"
        "        if item.filename == 'xl/worksheets/sheet1.xml':\n"
        "            data = data[: len(data) // 2]\n"
        "        dst.writestr(item, data)\n"
    )
    assert (await box.run(code)).exit_code == 0
    result = await box.check("xlsx", "sinig.xlsx")
    assert not result["ok"] and result["reasons"][0].startswith("cannot read workbook")
