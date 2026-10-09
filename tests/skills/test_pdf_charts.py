import pytest

from tests.conftest import Box

pytestmark = pytest.mark.sandbox

PDF = """
import sys
sys.path.insert(0, "/skills/pdf-report/scripts")
sys.path.insert(0, "/skills/charts/scripts")
from usta_charts import bar_chart
from usta_pdf import build_pdf, fmt_azn, fmt_number, table

bar_chart("/out/qrafik.png", ["Bakı", "Gəncə", "Şəki"], [12, 7, 3], "Cihazlar (İyun)")
build_pdf("/out/hesabat.pdf", "Yanacaq sərfiyyatı hesabatı", [
    "## Xülasə",
    "Keçən həftə ümumi sərfiyyat artdı; ən çox Gəncə filialında. İŞIQ, ığ, şə, öü, ç.",
    table([["Maşın", "Litr", "Məbləğ"], ["10-AB-123", fmt_number(42.5), fmt_azn(73.1)]]),
    "/out/qrafik.png",
])
print("ok")
"""


async def test_pdf_with_azerbaijani_text_table_and_chart_passes(box: Box) -> None:
    res = await box.run(PDF)
    assert res.exit_code == 0, res.stderr
    result = await box.check("pdf-report", "hesabat.pdf")
    assert result["ok"], result["reasons"]
    sample = result["text_sample"]
    for word in ("Yanacaq sərfiyyatı", "Gəncə", "İŞIQ", "Məbləğ"):
        assert word in sample
    assert "AZN" in sample or "₼" in sample
    chart = await box.check("charts", "qrafik.png")
    assert chart["ok"], chart["reasons"]


async def test_pdf_with_builtin_font_fails_check(box: Box) -> None:
    code = (
        "from reportlab.pdfgen import canvas\n"
        "c = canvas.Canvas('/out/pis.pdf'); c.setFont('Helvetica', 12)\n"
        "c.drawString(72, 720, 'Gence seheri'); c.save()\n"
    )
    assert (await box.run(code)).exit_code == 0
    result = await box.check("pdf-report", "pis.pdf")
    assert not result["ok"]
    assert any("built-in PDF fonts" in r for r in result["reasons"])


async def test_not_a_pdf_fails_check(box: Box) -> None:
    (box.dirs.out / "fake.pdf").write_text("not a pdf", encoding="utf-8")
    result = await box.check("pdf-report", "fake.pdf")
    assert not result["ok"] and "cannot open" in result["reasons"][0]


async def test_blank_or_tiny_png_fails_check(box: Box) -> None:
    code = (
        "from PIL import Image\n"
        "Image.new('RGB', (400, 300), 'white').save('/out/bos.png')\n"
        "Image.new('RGB', (50, 50), 'red').save('/out/kicik.png')\n"
    )
    assert (await box.run(code)).exit_code == 0
    blank = await box.check("charts", "bos.png")
    tiny = await box.check("charts", "kicik.png")
    assert not blank["ok"] and any("blank" in r for r in blank["reasons"])
    assert not tiny["ok"] and any("too small" in r for r in tiny["reasons"])


async def test_check_usage_error_exits_2(box: Box) -> None:
    res = await box.sandbox.exec(box.run_id, box.dirs, ("python", "/skills/pdf-report/check.py"))
    assert res.exit_code == 2 and "usage" in res.stderr
