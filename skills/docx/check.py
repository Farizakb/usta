"""check.py for docx (SPEC §7.1, §9): python check.py <file.docx>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

SAMPLE_CHARS = 4000


def emit(ok: bool, reasons: list[str], sample: str) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": sample}, ensure_ascii=False))


def check(path: str) -> None:
    from docx import Document

    try:
        doc = Document(path)
        texts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                texts.extend(c.text for c in row.cells if c.text.strip())
    except Exception as e:
        emit(False, [f"cannot open document: {type(e).__name__}: {e}"], "")
        return
    text = "\n".join(texts)
    reasons = []
    if not text.strip():
        reasons.append("document has no text")
    if "�" in text or "\x00" in text:
        reasons.append("text contains U+FFFD or NUL characters (broken encoding)")
    emit(not reasons, reasons, text[:SAMPLE_CHARS])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.docx>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
