#!/usr/bin/env python3
"""Draws docs/img/pipeline.png: the stages in order, and which steps need a person.

Run:
    python tools/make_pipeline_diagram.py [--out docs/img/pipeline.png]
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

SURF, TILE, INK, INK2, BASE = "#fcfcfb", "#f1f0ec", "#0b0b0b", "#52514e", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"

ROW1 = [("Your video", "one game,\nfixed camera", None),
        ("0  Standard\ncopy", "1280x720, 30 fps", "auto"),
        ("1  Find\npeople", "YOLO, every 3rd frame", "auto"),
        ("2  Fit the\ncourt", "you click the lines", "human"),
        ("3  Follow\n4 players", "you confirm the start", "human")]
ROW2 = [("4-6  Serves,\nscore, rallies", "from the scoreboard", "auto"),
        ("7  Movement", "won vs lost rallies", "auto"),
        ("8  Posture", "knees, racket hand", "auto"),
        ("10, 12  Report\nand images", "assistant writes coaching", "human"),
        ("11  Overlay\nvideo", "optional", "auto")]


def box(ax, x, y, w, h, title, sub, kind):
    edge = ORANGE if kind == "human" else (BLUE if kind == "auto" else BASE)
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12", fc=TILE, ec=edge, lw=2.6 if kind else 1.6))
    ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", fontsize=12, fontweight="bold", color=INK, linespacing=1.2)
    ax.text(x + w / 2, y + h * 0.18, sub, ha="center", va="center", fontsize=9, color=INK2, linespacing=1.2)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/img/pipeline.png")
    args = ap.parse_args()
    fig, ax = plt.subplots(figsize=(13, 5.4))
    ax.set_xlim(0, 13); ax.set_ylim(0, 5.4); ax.axis("off")
    fig.patch.set_facecolor(SURF)
    ax.text(0.1, 5.15, "From a match video to a report", fontsize=20, fontweight="bold", color=INK, va="center")
    w, h, gap = 2.2, 1.3, 0.45
    for row, y in ((ROW1, 3.0), (ROW2, 0.9)):
        for i, (t, s, k) in enumerate(row):
            x = 0.1 + i * (w + gap)
            box(ax, x, y, w, h, t, s, k)
            if i:
                ax.add_patch(FancyArrowPatch((x - gap + 0.03, y + h / 2), (x - 0.03, y + h / 2), arrowstyle="-|>", mutation_scale=16, color=INK2, lw=1.8))
    xr, xl, ymid = 0.1 + 4 * (w + gap) + w / 2, 0.1 + w / 2, 2.62
    ax.plot([xr, xr, xl], [3.0 - 0.03, ymid, ymid], color=INK2, lw=1.8, linestyle=(0, (4, 3)), solid_capstyle="butt")
    ax.add_patch(FancyArrowPatch((xl, ymid), (xl, 0.9 + h + 0.03), arrowstyle="-|>", mutation_scale=16, color=INK2, lw=1.8, linestyle=(0, (4, 3))))
    ax.text(6.4, ymid - 0.2, "from here on a scoreboard, or a hand-written score, is needed", fontsize=10, color=INK2, ha="center", va="center")
    for x, color, label in ((0.1, BLUE, "automatic, ends with PASS or FAILED"), (4.7, ORANGE, "a person looks, clicks or confirms"), (9.0, BASE, "input")):
        ax.add_patch(FancyBboxPatch((x, 0.18), 0.42, 0.28, boxstyle="round,pad=0,rounding_size=0.05", fc=TILE, ec=color, lw=2.6))
        ax.text(x + 0.55, 0.32, label, fontsize=11, color=INK2, va="center")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, facecolor=SURF, bbox_inches="tight", pad_inches=0.15)
    print("wrote", out)


if __name__ == "__main__":
    main()
