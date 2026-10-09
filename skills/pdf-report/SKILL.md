---
name: pdf-report
description: Build PDF reports (A4, Azerbaijani-safe fonts, headings, tables, charts) in code_exec.
---
# pdf-report

Build PDF reports inside `code_exec` with the helpers in `/skills/pdf-report/scripts/usta_pdf.py`.

**Never use ReportLab's built-in fonts (Helvetica, Times, Courier).** They cannot show
ə ğ ı ş İ, and the automatic check fails such files. The helpers register DejaVu Sans for you.

```python
import sys
sys.path.insert(0, "/skills/pdf-report/scripts")
from usta_pdf import build_pdf, table, fmt_number, fmt_azn, fmt_date

build_pdf("/out/hesabat.pdf", "Yanacaq sərfiyyatı hesabatı", [
    "## Xülasə",                       # a line starting with "## " is a heading
    "Keçən həftə ümumi sərfiyyat ...",  # any other string is a paragraph
    table([["Maşın", "Litr"], ["10-AB-123", fmt_number(42.5)]]),  # first row is the header
    "/out/qrafik.png",                 # a .png path embeds an image (make charts with the charts skill)
])
```

- `fmt_number(1234.5)` → `1.234,50`, `fmt_azn(73.1)` → `73,10 AZN`, `fmt_date(date)` → `9 okt 2026` (Babel, `az` locale).
- Write currency as `AZN`, never the `₼` sign: the PDF font has no glyph for it and it would vanish.
- Write the report in the user's language. Use short headings and a summary first.
- Save under `/out` with a descriptive file name in the user's language, e.g. `/out/uygunsuzluqlar_hesabati.pdf`.
- After the run, the verifier runs `/skills/pdf-report/check.py` on every PDF in `/out`.
