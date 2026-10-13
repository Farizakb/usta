---
name: docx
description: Write Word documents (headings, paragraphs, tables) and read .docx files in code_exec.
---
# docx

**Reading:** `from docx import Document; d = Document("/workspace/x.docx")`, then read
`d.paragraphs` and `d.tables`.

**Writing:** use `/skills/docx/scripts/usta_docx.py`. It sets Arial 11, which covers ə ğ ı ş İ in Word and LibreOffice.

```python
import sys
sys.path.insert(0, "/skills/docx/scripts")
from usta_docx import add_table, new_document

doc = new_document()
doc.add_heading("Müqavilə xülasəsi", level=1)
doc.add_paragraph("Ödəniş şərtləri: ...")
add_table(doc, [["Bənd", "Məzmun"], ["4.2", "Gecikmə cəriməsi"]])
doc.save("/out/muqavile_xulasesi.docx")
```

- Write in the user's language, unless the user asks for a document for someone else (e.g. a reply to a customer who wrote in Russian).
- Write currency as `AZN`, not the `₼` sign.
- The verifier runs `/skills/docx/check.py` on every `.docx` in `/out`. Documents without text fail.
