"""Chart helpers for the Usta sandbox: matplotlib with DejaVu Sans (covers ə ğ ı ş İ)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.family"] = "DejaVu Sans"


def _save(fig, ax, path: str, title: str, xlabel: str, ylabel: str) -> str:
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def bar_chart(
    path: str,
    labels: list[str],
    values: list[float],
    title: str,
    xlabel: str = "",
    ylabel: str = "",
) -> str:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([str(label) for label in labels], values, color="#3B6EA5")
    return _save(fig, ax, path, title, xlabel, ylabel)


def line_chart(
    path: str,
    x: list,
    series: dict[str, list[float]],
    title: str,
    xlabel: str = "",
    ylabel: str = "",
) -> str:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for name, values in series.items():
        ax.plot([str(v) for v in x], values, marker="o", label=name)
    if len(series) > 1:
        ax.legend()
    return _save(fig, ax, path, title, xlabel, ylabel)
