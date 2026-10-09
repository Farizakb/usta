"""check.py for xlsx (SPEC §7.1, §9): python check.py <file.xlsx>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

ERRORS = {"#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}
SAMPLE_CHARS = 4000


def emit(ok: bool, reasons: list[str], sample: str) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": sample}, ensure_ascii=False))


def check(path: str) -> None:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, read_only=True)
    except Exception as e:
        emit(False, [f"cannot open workbook: {type(e).__name__}: {e}"], "")
        return
    reasons: list[str] = []
    texts: list[str] = []
    values = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if v is None or v == "":
                    continue
                values += 1
                if isinstance(v, str):
                    if v.strip().upper() in ERRORS:
                        reasons.append(f"sheet {ws.title!r} has an error value {v.strip()}")
                    elif not v.startswith("="):
                        texts.append(v)
    wb.close()
    if values == 0:
        reasons.append("workbook has no data")
    text = " | ".join(texts)
    if "�" in text or "\x00" in text:
        reasons.append("text contains U+FFFD or NUL characters (broken encoding)")
    emit(not reasons, sorted(set(reasons)), text[:SAMPLE_CHARS])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.xlsx>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
