"""Seeded synthetic fixtures (SPEC §7.3). M1: the T-c pair, a device list and the warehouse
stock with planted mismatches. Ground truth goes OUTSIDE the user's workspace, or the agent
could read the answer.
    uv run python -m fixtures.generate <files_dir> <truth.json>"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from openpyxl import Workbook

SEED = 20261009
MODELS = ["FMB003", "FMB140", "FMB920", "FMC130", "FMC650"]
WAREHOUSES = ["Bakı mərkəzi anbarı", "Gəncə anbarı", "Sumqayıt anbarı"]
N_MISMATCHES = 5


def build(seed: int = SEED) -> tuple[list[list], list[list], list[dict]]:
    rng = random.Random(seed)
    counts: dict[tuple[str, str], int] = {}
    devices: list[list] = []
    imeis: set[str] = set()
    for wh in WAREHOUSES:
        for model in MODELS:
            n = rng.randint(1, 4)
            counts[(wh, model)] = n
            for _ in range(n):
                imei = "35" + "".join(str(rng.randint(0, 9)) for _ in range(13))
                while imei in imeis:
                    imei = "35" + "".join(str(rng.randint(0, 9)) for _ in range(13))
                imeis.add(imei)
                devices.append([imei, model, wh, "anbarda"])
    rng.shuffle(devices)
    stock = dict(counts)
    truth = []
    for wh, model in sorted(rng.sample(sorted(counts), N_MISMATCHES)):
        delta = rng.choice([-2, -1, 1, 2])
        if counts[(wh, model)] + delta < 0:
            delta = -delta
        stock[(wh, model)] = counts[(wh, model)] + delta
        truth.append(
            {
                "anbar": wh,
                "model": model,
                "siyahida": counts[(wh, model)],
                "qaliq": stock[(wh, model)],
                "ferq": delta,
            }
        )
    device_rows = [["IMEI", "Model", "Anbar", "Status"], *devices]
    stock_rows = [["Anbar", "Model", "Qalıq"], *([w, m, stock[(w, m)]] for w, m in sorted(stock))]
    return device_rows, stock_rows, truth


def _save(path: Path, title: str, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    wb.save(path)


def write(files_dir: Path, truth_path: Path, seed: int = SEED) -> None:
    devices, stock, truth = build(seed)
    files_dir.mkdir(parents=True, exist_ok=True)
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    _save(files_dir / "cihazlar.xlsx", "Cihazlar", devices)
    _save(files_dir / "anbar_qaliqlari.xlsx", "Qalıqlar", stock)
    truth_path.write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m fixtures.generate <files_dir> <truth.json>")
    write(Path(sys.argv[1]), Path(sys.argv[2]))
