"""check.py for pdf-report (SPEC §7.1, §9): python check.py <file.pdf>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

BASE14 = ("Courier", "Helvetica", "Times", "Symbol", "ZapfDingbats")
SAMPLE_CHARS = 4000


def emit(ok: bool, reasons: list[str], sample: str) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": sample}, ensure_ascii=False))


def check(path: str) -> None:
    import pdfplumber

    try:
        pdf = pdfplumber.open(path)
    except Exception as e:
        emit(False, [f"cannot open PDF: {type(e).__name__}: {e}"], "")
        return
    reasons: list[str] = []
    texts: list[str] = []
    fonts: set[str] = set()
    with pdf:
        if not pdf.pages:
            reasons.append("PDF has no pages")
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            fonts.update(c.get("fontname", "") for c in page.chars)
    text = "\n".join(texts)
    if not text.strip():
        reasons.append("PDF has no extractable text")
    builtin = sorted(f for f in fonts if f.split("+")[-1].startswith(BASE14))
    if builtin:
        reasons.append(
            "uses built-in PDF fonts that cannot show Azerbaijani letters: "
            + ", ".join(builtin)
            + "; build it with /skills/pdf-report/scripts/usta_pdf.py (DejaVu Sans)"
        )
    if "(cid:" in text or "�" in text or "\x00" in text:
        reasons.append("text has characters without a glyph mapping ((cid:…), U+FFFD or NUL)")
    emit(not reasons, reasons, text[:SAMPLE_CHARS])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.pdf>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
