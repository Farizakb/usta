"""check.py for charts (SPEC §7.1, §9): python check.py <file.png>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

MIN_W, MIN_H = 300, 200


def emit(ok: bool, reasons: list[str]) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": ""}, ensure_ascii=False))


def check(path: str) -> None:
    from PIL import Image

    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        emit(False, [f"cannot open image: {type(e).__name__}: {e}"])
        return
    reasons = []
    if img.format != "PNG":
        reasons.append(f"expected PNG, got {img.format}")
    w, h = img.size
    if w < MIN_W or h < MIN_H:
        reasons.append(f"image too small: {w}x{h} (min {MIN_W}x{MIN_H})")
    lo, hi = img.convert("L").getextrema()
    if lo == hi:
        reasons.append("image is blank (a single colour)")
    emit(not reasons, reasons)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.png>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
