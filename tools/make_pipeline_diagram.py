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

ROW1 = [("Your video", "singles or doubles,\nfixed camera", None),
        ("0  Standard\ncopy", "1280x720, 30 fps", "auto"),
        ("1  Find\npeople", "YOLO, every 3rd frame", "auto"),
        ("2  Fit the\ncourt", "you click the lines", "human"),
        ("3  Follow the\nplayers", "you click yourself", "human")]
ROW2 = [("4-6  Serves,\nscore, rallies", "from the scoreboard", "auto"),
        ("7, 8  Movement\nand opponents", "won vs lost; scouting", "auto"),
        ("10, 12  Charts\nand words", "assistant writes coaching", "ai"),
        ("13  PDF\nreport", "match_report.pdf", "auto"),
        ("11  Overlay\nvideo", "optional", "auto")]
ROW3 = [("6f  Find the\nplays", "sound + movement", "auto"),
        ("7f, 8  Positions\nand movement", "per player and pair", "auto"),
        ("14a  Coaching\nand scouting", "rules, or an assistant", "ai"),
        ("14  PDF\nreport", "match_report.pdf", "auto")]


def box(ax, x, y, w, h, title, sub, kind):
    edge = {"human": ORANGE, "auto": BLUE, "ai": INK}.get(kind, BASE)
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.12", fc=TILE, ec=edge, lw=2.6 if kind else 1.6))
    ax.text(x + w / 2, y + h * 0.64, title, ha="center", va="center", fontsize=12, fontweight="bold", color=INK, linespacing=1.2)
    ax.text(x + w / 2, y + h * 0.18, sub, ha="center", va="center", fontsize=9, color=INK2, linespacing=1.2)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/img/pipeline.png")
    args = ap.parse_args()
    fig, ax = plt.subplots(figsize=(13, 8.2))
    ax.set_xlim(0, 13); ax.set_ylim(0, 8.2); ax.axis("off")
    fig.patch.set_facecolor(SURF)
    ax.text(0.1, 7.95, "From a match video to a report", fontsize=20, fontweight="bold", color=INK, va="center")
    ax.text(0.1, 7.55, "tools/analyze.py asks the questions first: which video, singles or doubles, which hand, live score or not, when each game starts", fontsize=11, color=INK2, va="center")
    w, h, gap = 2.2, 1.3, 0.45
    y1, y2, y3 = 5.7, 3.35, 1.1
    for row, y in ((ROW1, y1), (ROW2, y2), (ROW3, y3)):
        for i, (t, sub, k) in enumerate(row):
            x = 0.1 + i * (w + gap)
            box(ax, x, y, w, h, t, sub, k)
            if i:
                ax.add_patch(FancyArrowPatch((x - gap + 0.03, y + h / 2), (x - 0.03, y + h / 2), arrowstyle="-|>", mutation_scale=16, color=INK2, lw=1.8))
    ax.text(0.1, y2 + h + 0.2, "With a live score on screen (doubles): who won each rally", fontsize=11, color=INK, fontweight="bold", va="center")
    ax.text(0.1, y3 + h + 0.2, "Without one (the usual case): positions, movement, posture, pace of play", fontsize=11, color=INK, fontweight="bold", va="center")
    xr, bus = 0.1 + 4 * (w + gap) + w / 2, 0.03
    ymid = y1 - 0.4
    ax.plot([xr, xr, bus, bus], [y1 - 0.03, ymid, ymid, y3 + h / 2], color=INK2, lw=1.8, linestyle=(0, (4, 3)), solid_capstyle="butt")
    for y in (y2, y3):
        ax.add_patch(FancyArrowPatch((bus, y + h / 2), (0.07, y + h / 2), arrowstyle="-|>", mutation_scale=16, color=INK2, lw=1.8))
    for x, color, label in ((0.1, BLUE, "automatic (PASS or FAILED)"), (3.85, ORANGE, "a person clicks or confirms"), (7.7, INK, "words: rules, or the AI assistant"), (11.35, BASE, "input")):
        ax.add_patch(FancyBboxPatch((x, 0.18), 0.42, 0.28, boxstyle="round,pad=0,rounding_size=0.05", fc=TILE, ec=color, lw=2.6))
        ax.text(x + 0.55, 0.32, label, fontsize=10.5, color=INK2, va="center")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, facecolor=SURF, bbox_inches="tight", pad_inches=0.15)
    print("wrote", out)


if __name__ == "__main__":
    main()
