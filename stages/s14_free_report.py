#!/usr/bin/env python3
"""Stage 14 - REPORT FOR A VIDEO WITH NO SCORE ON SCREEN (charts + PDF).

The same kind of PDF as stage 13, for a match where the video shows no scoreboard, so nobody knows who won each rally.
It reports what can be measured from the player tracks and the sound: where you and your partner stand, how the pair
is arranged, how hard you move, how long plays and pauses last, and the same for the opponents. It says plainly what it
cannot know (winners, serves, shots, errors).

Inputs, all in --work:
    games.json                  what to call things and where each game's files are (see below)
    <game dir>/free_stats.json  stage 7f           <game dir>/play_windows.json  stage 6f
    <game dir>/pose_stats.json  stage 8 (optional) calib.json + bg_median.png    stage 2 (for the court picture)
    tips.json, scouting.json    the coaching and scouting words (same format as stage 13), written from the numbers

games.json:
    {"label": "Match 1", "you": "navy tee, white shorts", "partner": "black sleeveless", "racket_hand": "left",
     "games": [{"dir": "g1", "title": "Game 1", "card": "21-19"}, {"dir": "g2", "title": "Game 2", "card": "21-13"}],
     "card_note": "result from the final card on screen",
     "checks": [{"what": "...", "how": "...", "level": "solid | approximate | weak"}]}
"card" is the final score you know for the game (optional); its two numbers added are the rallies played, which the stage compares with
the plays it found.

Run:
    python stages/s14_free_report.py --work work_m1 [--page A4|letter]
Writes <work>/images_free/*.png and <work>/match_report.pdf. Charts only: no photographs of people.
"""
import argparse
import datetime
import json
import re
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)
from scipy.ndimage import gaussian_filter

from common import NET_Y, TEAM_WIDTH, mmss
from s13_pdf_report import (BLUE as PDF_BLUE, GOOD, LINE, MARGIN, MUT, NumberedCanvas, ORANGE as PDF_ORANGE, SURF, KIND_COLOUR, KIND_ORDER,
                            SCOUT_COLOUR, callout, card, esc, figure, grid, heading, load_items, load_scouting, make_styles, register_fonts,
                            safe, tiles)

SURFC, TILEC, INKC, INK2C, MUTC, GRIDC, BASEC = "#fcfcfb", "#f1f0ec", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"
BLUE_SHADES, ORANGE_SHADES = ("#0f3d78", "#7fb0ec", "#d4e4f8"), ("#9a3412", "#f3a37c", "#fbe0d2")     # front-back, mixed, side-by-side
plt.rcParams.update({"font.family": ["Arial", "Helvetica Neue", "DejaVu Sans"], "figure.facecolor": SURFC, "axes.facecolor": SURFC,
                     "savefig.facecolor": SURFC, "axes.edgecolor": BASEC, "axes.labelcolor": INK2C, "xtick.color": MUTC, "ytick.color": MUTC,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 13, "legend.frameon": False})
DPI = 130
CMAP_BLUE = LinearSegmentedColormap.from_list("b", [SURFC, "#cfe0f6", "#6aa3e6", "#1d5fb4", "#0f3d78"])
CMAP_ORANGE = LinearSegmentedColormap.from_list("o", [SURFC, "#fbe0d2", "#f3a37c", "#d9531e", "#8a2d0b"])
LEVELS = {"solid": "Solid", "approximate": "Approximate", "weak": "Weak", "none": "Not measured"}


# ---------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------
def load(W):
    cfg = json.loads((W / "games.json").read_text())
    for k in ("label", "games"):
        if k not in cfg:
            raise SystemExit(f"{W / 'games.json'}: missing '{k}'")
    games = []
    for g in cfg["games"]:
        D = W / g["dir"]
        for need in ("free_stats.json", "play_windows.json"):
            if not (D / need).exists():
                raise SystemExit(f"{D / need} is missing: run stage 6f and 7f for {g['dir']} first")
        e = dict(g)
        e["S"] = json.loads((D / "free_stats.json").read_text())
        e["PW"] = json.loads((D / "play_windows.json").read_text())
        e["POSE"] = json.loads((D / "pose_stats.json").read_text())["stats"] if (D / "pose_stats.json").exists() else {}
        e["you_side"] = e["S"]["slots"]["A_you"]["side"]
        e["card_n"] = sum(int(x) for x in re.findall(r"\d+", g["card"])) if g.get("card") else None
        games.append(e)
    cfg["games"] = games
    cfg["mode"] = cfg.get("mode") or games[0]["S"].get("mode", "doubles")
    src = W / "words_source.json"
    cfg["words_auto"] = src.exists() and json.loads(src.read_text()).get("source") == "automatic"
    cfg["TIPS"] = load_items(W / "tips.json", "the coaching tips") if (W / "tips.json").exists() else None
    cfg["SCOUT"] = load_scouting(W / "scouting.json") if (W / "scouting.json").exists() else None
    return cfg


def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


# ---------------------------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------------------------
def save(fig, path):
    fig.savefig(path, dpi=DPI)
    plt.close(fig)


def court_check(W, out):
    """the median (people-free) photo of the hall with the analysed court drawn on it."""
    calib = json.loads((W / "calib.json").read_text())
    H = np.array(calib["H_court2img"], float)
    img = cv2.cvtColor(cv2.imread(str(W / "bg_median.png")), cv2.COLOR_BGR2RGB)

    def proj(pts):
        p = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ H.T
        return p[:, :2] / p[:, 2:3]

    def line(a, b, n=40):
        return proj([np.array(a) + (np.array(b) - np.array(a)) * t for t in np.linspace(0, 1, n)])

    fig = plt.figure(figsize=(12, 6.9))
    ax = fig.add_axes([0.0, 0.0, 1, 0.86])
    ax.imshow(img)
    ax.axis("off")
    for a, b in [((0, 0), (6.1, 0)), ((0, 0.76), (6.1, 0.76)), ((0, 4.72), (6.1, 4.72)), ((0, 8.68), (6.1, 8.68)), ((0, 12.64), (6.1, 12.64)),
                 ((0, 13.4), (6.1, 13.4)), ((0, 0), (0, 13.4)), ((0.46, 0), (0.46, 13.4)), ((5.64, 0), (5.64, 13.4)), ((6.1, 0), (6.1, 13.4)),
                 ((3.05, 0), (3.05, 4.72)), ((3.05, 8.68), (3.05, 13.4))]:
        p = line(a, b)
        ax.plot(p[:, 0], p[:, 1], color="#e8174b", lw=1.6, alpha=0.95)
    p = line((-0.3, NET_Y), (6.4, NET_Y))
    ax.plot(p[:, 0], p[:, 1], color="#ff00ff", lw=3)
    ax.text(p[-1, 0] + 6, p[-1, 1], "NET", color="#ff00ff", fontsize=14, fontweight="bold", va="center")
    q = proj([(3.05, 0)])[0]
    ax.text(q[0], min(q[1] + 26, img.shape[0] - 8), "near baseline", color="#e8174b", fontsize=12, ha="center", fontweight="bold")
    ax.set_xlim(0, img.shape[1])
    ax.set_ylim(img.shape[0], 0)
    fig.text(0.03, 0.965, "The court this report is about", fontsize=22, fontweight="bold", color=INKC, va="top")
    fig.text(0.03, 0.905, "Red lines: the court model laid on a people-free photo of the hall. Pink: the net.", fontsize=13, color=INK2C, va="top")
    save(fig, out)


def draw_half(ax):
    """the half court a team defends, seen from behind it: net at the top, baseline at the bottom."""
    ax.set_xlim(0, TEAM_WIDTH)
    ax.set_ylim(NET_Y, 0)
    for x in (0, TEAM_WIDTH):
        ax.plot([x, x], [0, NET_Y], color=INK2C, lw=1.2)
    for x in (0.46, TEAM_WIDTH - 0.46):
        ax.plot([x, x], [0, NET_Y], color=BASEC, lw=0.9)
    ax.plot([0, TEAM_WIDTH], [NET_Y, NET_Y], color=INK2C, lw=1.2)
    ax.plot([0, TEAM_WIDTH], [NET_Y - 0.76, NET_Y - 0.76], color=BASEC, lw=0.9)
    ax.plot([0, TEAM_WIDTH], [1.98, 1.98], color=BASEC, lw=0.9)
    ax.plot([TEAM_WIDTH / 2, TEAM_WIDTH / 2], [1.98, NET_Y], color=BASEC, lw=0.9)
    ax.plot([-0.25, TEAM_WIDTH + 0.25], [0, 0], color=INK2C, lw=3)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.text(0.08, -0.12, "net", fontsize=9.5, color=MUTC, va="bottom")
    ax.text(0.08, NET_Y + 0.12, "baseline", fontsize=9.5, color=MUTC, va="top")
    ax.set_aspect("equal")


def heat_img(h):
    a = np.array(h, float).T                                       # [d][u]
    a = gaussian_filter(a, 0.8)
    return a / a.max() if a.max() > 0 else a


def heatmaps(cfg, out):
    games = cfg["games"]
    singles = cfg["mode"] == "singles"
    who = [("A_you", "You")] + ([] if singles else [("A_partner", "Your partner")])
    ncol = len(who) + 1
    fig, axes = plt.subplots(len(games), ncol, figsize=(4.2 * ncol, 4.6 * len(games) + 1.0), squeeze=False)
    fig.subplots_adjust(top=1 - 1.15 / (4.6 * len(games) + 1.0), bottom=0.02, left=0.03, right=0.97, hspace=0.18, wspace=0.08)
    fig.text(0.03, 0.985, "Where you stand" if singles else "Where you and your partner stand", fontsize=22, fontweight="bold", color=INKC, va="top")
    fig.text(0.03, 0.985 - 0.045 * (2 / len(games)) ** 0.5 * 0.9, "Your own half, seen from behind: net at the top, baseline at the bottom, your left on the left. Darker = more time (play only).",
             fontsize=12.5, color=INK2C, va="top")
    for r, g in enumerate(games):
        for c, (slot, name) in enumerate(who):
            ax = axes[r][c]
            h = g["S"]["slots"][slot]["heat"]
            draw_half(ax)
            if h:
                ax.imshow(heat_img(h), extent=[0, TEAM_WIDTH, NET_Y, 0], cmap=CMAP_BLUE, vmin=0, vmax=1, aspect="equal", interpolation="bilinear", zorder=0)
            z = g["S"]["slots"][slot]["zones"]["depth"]
            ax.set_title(f"{g['title']}: {name}\n{ {'near': 'near half', 'far': 'far half', 'both': 'both halves'}[g['you_side']] }  |  front {pct(z['front'])}  middle {pct(z['middle'])}  back {pct(z['back'])}",
                         fontsize=11.5, color=INKC, loc="left")
        ax = axes[r][ncol - 1]
        draw_half(ax)
        opp = [k for k in ("B_opp1", "B_opp2") if k in g["S"]["slots"]]
        hs = [np.array(g["S"]["slots"][k]["heat"], float) for k in opp if g["S"]["slots"][k]["heat"]]
        if hs:
            ax.imshow(heat_img(sum(hs).tolist()), extent=[0, TEAM_WIDTH, NET_Y, 0], cmap=CMAP_ORANGE, vmin=0, vmax=1, aspect="equal", interpolation="bilinear", zorder=0)
        side = g["S"]["slots"][opp[0]]["side"] if opp else "far"
        depth = [g["S"]["slots"][k]["mean_d"] for k in opp if g["S"]["slots"][k]["mean_d"] is not None]
        label = "your opponent" if singles else "both opponents"
        ax.set_title(f"{g['title']}: {label}\n{side} half" + (f"  |  {np.mean(depth):.1f} m from the net on average" if depth else ""), fontsize=11.5, color=INKC, loc="left")
    save(fig, out)


def formation(cfg, out):
    games = cfg["games"]
    fig, ax = plt.subplots(figsize=(12, 1.25 * len(games) * 2 + 1.7))
    fig.subplots_adjust(top=0.80, bottom=0.12, left=0.20, right=0.97)
    fig.text(0.02, 0.975, "How each pair stands", fontsize=22, fontweight="bold", color=INKC, va="top")
    fig.text(0.02, 0.905, "Share of play time: side by side (similar depth), mixed, or front and back (one at least 2.5 m deeper).", fontsize=12.5, color=INK2C, va="top")
    ys, labels, k = [], [], 0
    for g in games:
        for team, shades in (("A", BLUE_SHADES), ("B", ORANGE_SHADES)):
            f = g["S"]["teams"].get(team)
            if not f:
                continue
            vals = [f["front_back"], f["mixed"], f["side_by_side"]]
            left = 0
            for v, col in zip(vals, shades):
                ax.barh(k, v * 100, left=left, color=col, height=0.62, edgecolor=SURFC, lw=2)
                if v >= 0.07:
                    ax.text(left + v * 50, k, f"{100 * v:.0f}%", ha="center", va="center", fontsize=12, color="white" if col == shades[0] else INKC, fontweight="bold")
                left += v * 100
            labels.append(f"{g['title']}: {'your team' if team == 'A' else 'opponents'}")
            ys.append(k)
            k += 1
        k += 0.5
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=12)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([])
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(length=0)
    ax.text(0, -0.65, "front and back", fontsize=11, color=MUTC)
    ax.text(50, -0.65, "mixed", fontsize=11, color=MUTC, ha="center")
    ax.text(100, -0.65, "side by side", fontsize=11, color=MUTC, ha="right")
    save(fig, out)


def movement(cfg, out):
    games = cfg["games"]
    fig, axes = plt.subplots(1, len(games), figsize=(6.2 * len(games), 5.0), sharey=True, squeeze=False)
    fig.subplots_adjust(top=0.76, bottom=0.14, left=0.07, right=0.98, wspace=0.08)
    fig.text(0.02, 0.975, "How hard you worked, minute by minute", fontsize=22, fontweight="bold", color=INKC, va="top")
    fig.text(0.02, 0.905, "Metres moved per minute of play, in 2-minute blocks (blocks with under 30 s of play are left out).", fontsize=12.5, color=INK2C, va="top")
    top, ends = 10, {}
    for ax, g in zip(axes[0], games):
        for slot, col, ls, name in (("A_you", BLUE, "-", "you"), ("A_partner", BLUE, (0, (4, 2)), "partner")):
            if slot not in g["S"]["blocks"]:
                continue
            b = g["S"]["blocks"][slot]
            xs = [(x["from_s"] + 60) / 60 for x in b if x["per_play_min"] is not None]
            ys = [x["per_play_min"] for x in b if x["per_play_min"] is not None]
            ax.plot(xs, ys, color=col, lw=2.6, ls=ls, marker="o", ms=6)
            if xs:
                other = ends.get(g["dir"])
                dy = 0 if other is None or abs(other - ys[-1]) > 4 else (3.5 if ys[-1] >= other else -3.5)
                ax.text(xs[-1] + 0.12, ys[-1] + dy, name, color=col, fontsize=11.5, va="center")
                ends[g["dir"]] = ys[-1]
            top = max(top, max(ys) if ys else 0)
        ax.set_title(f"{g['title']}" + (" (you on the far half: distances read a little high)" if g["you_side"] == "far" else ""), fontsize=12, color=INKC, loc="left")
        ax.set_xlabel("minutes into the game")
        ax.yaxis.grid(True, color=GRIDC)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
        ax.spines["left"].set_visible(False)
    for ax in axes[0]:
        ax.set_ylim(0, top * 1.15)
        ax.set_xlim(0, ax.get_xlim()[1] + 0.6)
    axes[0][0].set_ylabel("metres per minute of play")
    save(fig, out)


def pace(cfg, out):
    games = cfg["games"]
    fig, axes = plt.subplots(1, len(games), figsize=(6.2 * len(games), 4.8), sharey=True, squeeze=False)
    fig.subplots_adjust(top=0.76, bottom=0.15, left=0.07, right=0.98, wspace=0.08)
    fig.text(0.02, 0.975, "How long the plays lasted", fontsize=22, fontweight="bold", color=INKC, va="top")
    fig.text(0.02, 0.905, "Each bar counts plays of that length. A play is a stretch of movement and shuttle sound; two close rallies can merge.", fontsize=12.5, color=INK2C, va="top")
    bins = np.arange(0, 32, 2.5)
    for ax, g in zip(axes[0], games):
        d = np.clip(g["S"]["plays"]["durations"], 0, 31)
        ax.hist(d, bins=bins, color=BLUE, edgecolor=SURFC, lw=2)
        ax.axvline(g["S"]["plays"]["median_s"], color=INKC, lw=1.6, ls=(0, (4, 3)))
        ax.text(g["S"]["plays"]["median_s"] + 0.4, ax.get_ylim()[1] * 0.93, f"median {g['S']['plays']['median_s']:.1f} s", fontsize=11.5, color=INKC, va="top")
        n = g["S"]["plays"]["n"]
        ax.set_title(f"{g['title']}: {n} plays found" + (f" (the final card implies {g['card_n']})" if g.get("card_n") else ""), fontsize=12, color=INKC, loc="left")
        ax.set_xlabel("seconds (the last bar is 30 s and longer)")
        ax.yaxis.grid(True, color=GRIDC)
        ax.set_axisbelow(True)
        ax.tick_params(length=0)
        ax.spines["left"].set_visible(False)
    axes[0][0].set_ylabel("plays")
    save(fig, out)


def make_images(W, cfg):
    d = W / "images_free"
    d.mkdir(exist_ok=True)
    imgs = {"heat": d / "01_heatmaps.png", "form": d / "02_formation.png", "move": d / "03_movement.png", "pace": d / "04_pace.png"}
    heatmaps(cfg, imgs["heat"])
    if cfg["mode"] == "doubles":
        formation(cfg, imgs["form"])
    movement(cfg, imgs["move"])
    pace(cfg, imgs["pace"])
    if (W / "calib.json").exists() and (W / "bg_median.png").exists():
        imgs["court"] = d / "00_court.png"
        court_check(W, imgs["court"])
    return imgs


# ---------------------------------------------------------------------------------------------
# PDF sections
# ---------------------------------------------------------------------------------------------
def near_games(cfg):
    return [g for g in cfg["games"] if g["you_side"] == "near"]


def cover(cfg, S, W_, today):
    games = cfg["games"]
    story = [Paragraph("BADMINTON ANALYSIS  |  SAMPLE REPORT, INVENTED DATA" if cfg.get("sample") else "BADMINTON ANALYSIS  |  MATCH REPORT", S["kicker"]), Spacer(1, 4 * mm),
             Paragraph("Sample report" if cfg.get("sample") else "Match report", S["title"]),
             Paragraph(esc(f"{cfg['label']}. {'Singles' if cfg['mode'] == 'singles' else 'Doubles'}, {len(games)} game{'s' if len(games) != 1 else ''}." + ("" if cfg.get("sample") else f" Made {today}.")), S["subtitle"])]
    singles = cfg["mode"] == "singles"
    facts = [["Player analysed", f"{cfg.get('you', 'you')} (\"you\" in this report)" + (f", {cfg['racket_hand']}-handed" if cfg.get("racket_hand") else "")]]
    if not singles:
        facts.append(["Partner", cfg.get("partner", "your partner")])
    facts += [["Opponents" if not singles else "Opponent", cfg.get("opponents", "the other pair" if not singles else "your opponent")],
              ["Result", cfg.get("card_note") or "not shown in the video"]]
    story += [grid(facts, [34 * mm, W_ - 34 * mm], S, header=False), Spacer(1, 6 * mm)]
    plays = sum(g["S"]["plays"]["n"] for g in games)
    dur = sum(g["S"]["end"] - g["S"]["start"] for g in games) / 60
    you = [g["S"]["slots"]["A_you"]["distance_per_play_min"] for g in near_games(cfg)] or [g["S"]["slots"]["A_you"]["distance_per_play_min"] for g in games]
    story.append(tiles([(str(len(games)), "games analysed"), (f"{dur:.0f} min", "of match video"), (str(plays), "plays found"),
                        (f"{np.mean(you):.0f} m", "you move per minute of play" + ("" if near_games(cfg) else " (far side)"))], S, W_))
    story.append(Spacer(1, 4 * mm))
    if cfg.get("sample_note"):
        story.append(callout("This is a sample", [cfg["sample_note"]], S, W_, PDF_ORANGE))
    story.append(callout("What this report can and cannot tell you", [
        "The video has no scoreboard, so it does not know who won each rally, who served, what shot was played or where the shuttle landed. "
        "Everything here comes from where the four players were and from the sound of the shuttle: positions, formations, movement, and how long plays and pauses lasted.",
        "That makes it good for 'where do we stand and how do we move' and not for 'which shot loses us points'. Each pattern is a question to check on the video, not a verdict."],
        S, W_, PDF_ORANGE))
    story.append(Paragraph("The short version", S["h2"]))
    rows = []
    tips, scout = cfg["TIPS"], cfg["SCOUT"]
    if tips:
        by = {k: [t for t in tips if t["kind"] == k] for k in KIND_ORDER}
        for t in by["improve"][:2]:
            rows.append(("Work on", t["title"], PDF_BLUE))
        for t in by["check"][:1]:
            rows.append(("Check on video", t["title"], MUT))
        for t in by["strength"][:1]:
            rows.append(("Working well", t["title"], GOOD))
    if scout and scout["weaknesses"]:
        rows.append(("Opponents", scout["weaknesses"][0]["title"], PDF_ORANGE))
    if rows:
        t = Table([[Paragraph(f"<font color='#{c.hexval()[2:]}'><b>{esc(a)}</b></font>", S["cell"]), Paragraph(esc(b), S["cell"])] for a, b, c in rows],
                  colWidths=[32 * mm, W_ - 32 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)
    else:
        story.append(callout("Coaching notes are missing", ["tips.json and scouting.json have not been written yet, so this report has the numbers but no words."], S, W_, PDF_ORANGE))
    return story


def court_section(cfg, S, W_, imgs):
    if "court" not in imgs:
        return []
    out = heading("The court that was analysed", S, "Everything below is measured on the court drawn here. If this is not the court you played on, stop and say so: nothing after this page would be right.")
    out.append(figure(imgs["court"], W_, S, caption="The court model (red) laid on a photo made by taking the middle value of many frames, so no people are in it."))
    return out


def glance_section(cfg, S, W_):
    out = heading("The games at a glance", S)
    rows = [["", *[g["title"] for g in cfg["games"]]]]
    def row(label, fn):
        rows.append([label, *[fn(g) for g in cfg["games"]]])
    row("Result", lambda g: g.get("card") or "not shown")
    row("You were on the", lambda g: ("both halves (ends changed at " + mmss(g["S"]["end_change_s"]) + ")") if g["you_side"] == "both" else f"{g['you_side']} half of the video")
    row("Plays found", lambda g: str(g["S"]["plays"]["n"]) + (f" (card implies {g['card_n']})" if g.get("card_n") else ""))
    row("Typical play", lambda g: f"{g['S']['plays']['median_s']:.1f} s (longest {g['S']['plays']['max_s']:.0f} s)")
    row("Plays under 5 s / over 10 s", lambda g: f"{pct(g['S']['plays']['short_share'])} / {pct(g['S']['plays']['long_share'])}")
    row("Typical pause between plays", lambda g: f"{g['S']['plays']['rest_median_s']:.1f} s")
    row("Time in play", lambda g: pct(g["S"]["plays"]["play_share"]))
    row("You: metres per play-minute", lambda g: f"{g['S']['slots']['A_you']['distance_per_play_min']:.0f}" + (" (far: reads high)" if g["you_side"] == "far" else ""))
    row("You: fast bursts per play-minute", lambda g: f"{g['S']['slots']['A_you']['bursts_per_play_min']:.1f}")
    if cfg["mode"] == "doubles":
        row("Partner: metres per play-minute", lambda g: f"{g['S']['slots']['A_partner']['distance_per_play_min']:.0f}" + (" (far: reads high)" if g["you_side"] == "far" else ""))
        row("Partner: fast bursts per play-minute", lambda g: f"{g['S']['slots']['A_partner']['bursts_per_play_min']:.1f}")
    n = len(cfg["games"])
    first = 52 * mm
    out.append(grid(rows, [first] + [(W_ - first) / n] * n, S))
    out.append(Spacer(1, 2 * mm))
    out.append(Paragraph("A 'fast burst' is a move above 2.5 m/s that lasts at least 0.3 s. Distances use tracks smoothed over one second, so small shuffles are not counted.", S["small"]))
    return out


def coaching_section(cfg, S, W_):
    tips = cfg["TIPS"]
    out = heading("Your coaching plan", S, "Each item says what to try and how sure the number behind it is. "
                  + ("These notes were written automatically by rules from the numbers in this report; an AI assistant can write a more personal version (see CLAUDE.md)." if cfg.get("words_auto")
                     else "Written from the numbers in this report."))
    if not tips:
        return out + [callout("Not written yet", ["tips.json is missing."], S, W_, PDF_ORANGE)]
    n = 0
    for kind, title in (("improve", "Work on"), ("check", "Check on the video"), ("strength", "Working well")):
        items = [t for t in tips if t["kind"] == kind]
        if not items:
            continue
        out.append(CondPageBreak(55 * mm))                     # a sub-heading never ends a page
        out.append(Paragraph(title, S["h2"]))
        for t in items:
            n += 1
            out.append(card(t, n, KIND_COLOUR[kind], S, W_))
    return out


def position_section(cfg, S, W_, imgs):
    out = heading("Where you play", S, "Heat maps of the time each player spent in each part of their own half, during play only.")
    who = (("A_you", "You"),) if cfg["mode"] == "singles" else (("A_you", "You"), ("A_partner", "Partner"))
    out.append(figure(imgs["heat"], W_, S, max_h=215 * mm))
    rows = [["", "Front court (net to 2.2 m)", "Middle", "Back court (4.5 m to baseline)", "Left / middle / right"]]
    for g in cfg["games"]:
        for slot, nm in who:
            s = g["S"]["slots"][slot]
            z = s["zones"]
            rows.append([f"{g['title']}: {nm}", pct(z["depth"]["front"]), pct(z["depth"]["middle"]), pct(z["depth"]["back"]),
                         f"{pct(z['width']['left'])} / {pct(z['width']['middle'])} / {pct(z['width']['right'])}"])
    out.append(KeepTogether([grid(rows, [44 * mm] + [(W_ - 44 * mm) / 4] * 4, S), Spacer(1, 2 * mm),
                             Paragraph("'Left' and 'right' are your own: left means your left when you face the net.", S["small"])]))
    return out


def work_section(cfg, S, W_, imgs):
    out = heading("How hard you worked", S, "Metres moved per minute of play through each game.")
    out.append(figure(imgs["move"], W_, S, max_h=120 * mm))
    return out


def pair_section(cfg, S, W_, imgs):
    if cfg["mode"] == "singles":
        return work_section(cfg, S, W_, imgs)
    out = heading("You and your partner", S, "How the pair is arranged, who covers what, and how the work is shared.")
    out.append(figure(imgs["form"], W_, S, max_h=120 * mm))
    rows = [["", "Typical gap: depth / width", "Within 1.5 m across", "Partner at the back when front-and-back", "Back-court swaps"]]
    for g in cfg["games"]:
        f = g["S"]["teams"].get("A")
        if not f:
            continue
        back = 1 - f["first_at_back_when_front_back"] if f.get("first_at_back_when_front_back") is not None else None
        rows.append([g["title"], f"{f['gap_depth_median']:.1f} m / {f['gap_width_median']:.1f} m", pct(f["close_together"]), pct(back), str(f["rear_swaps"])])
    out.append(KeepTogether([grid(rows, [30 * mm, 38 * mm, 32 * mm, 44 * mm, (W_ - 144 * mm)], S), Spacer(1, 3 * mm)]))
    out.append(figure(imgs["move"], W_, S, max_h=120 * mm))
    return out


def pose_section(cfg, S, W_):
    rows = [["", "Knee bent under 150 deg", "Racket hand up between shots", "Feet apart / shoulder width", "Samples"]]
    for g in cfg["games"]:
        for slot, nm in (("A_you", "You"), ("A_partner", "Partner")):
            p = g["POSE"].get(slot)
            if p and p.get("samples", 0) >= 200 and g["S"]["slots"].get(slot, {}).get("side") == "near":
                rows.append([f"{g['title']}: {nm}", pct(p["bent_lt150"]), pct(p["racket_up_share"]), f"{p['stance_median']:.1f}", str(p["samples"])])
    if len(rows) == 1:
        return []
    out = heading("Posture snapshot", S, "From body-point tracking on the frames where each of you was close to the camera.")
    out.append(grid(rows, [44 * mm] + [(W_ - 44 * mm) / 4] * 4, S))
    hand = cfg.get("racket_hand")
    out.append(Spacer(1, 2 * mm))
    out.append(Paragraph(esc("'Racket hand up' means the wrist is above the hip, counted on the hand that goes overhead most often"
                             + (f"; you told us that is your {hand} hand" if hand else "") + ". The tracker's own left/right labels are mirrored for people seen from behind, so no handedness is read from them. "
                             "A knee angle of 180 degrees is a straight leg."), S["small"]))
    return out


def opponents_section(cfg, S, W_, imgs):
    singles = cfg["mode"] == "singles"
    out = heading("Your opponent" if singles else "The opponents", S, "Where they stood" + ("" if singles else " and how they arranged themselves") + ". Without a score this shows habits, not what won them points.")
    if singles:
        rows = [["", "Front court", "Middle", "Back court", "Moves per play-minute"]]
        for g in cfg["games"]:
            o = g["S"]["slots"]["B_opp1"]
            z = o["zones"]["depth"]
            rows.append([f"{g['title']} ({o['side']})", pct(z["front"]), pct(z["middle"]), pct(z["back"]), f"{o['distance_per_play_min']:.0f}"])
        out.append(KeepTogether([grid(rows, [34 * mm] + [(W_ - 34 * mm) / 4] * 4, S), Spacer(1, 3 * mm)]))
    else:
        rows = [["", "Pair side by side / front and back", "Typical gap: depth / width", "Pair sits from the net", "Moves per play-minute (each)"]]
        for g in cfg["games"]:
            f = g["S"]["teams"].get("B")
            if not f:
                continue
            a, b = (g["S"]["slots"][k]["distance_per_play_min"] for k in ("B_opp1", "B_opp2"))
            rows.append([f"{g['title']} ({f['side']})", f"{pct(f['side_by_side'])} / {pct(f['front_back'])}", f"{f['gap_depth_median']:.1f} m / {f['gap_width_median']:.1f} m",
                         f"{f['pair_depth_mean']:.1f} m", f"{a:.0f} and {b:.0f}"])
        out.append(KeepTogether([grid(rows, [34 * mm, 40 * mm, 38 * mm, 32 * mm, (W_ - 144 * mm)], S), Spacer(1, 3 * mm)]))
    scout = cfg["SCOUT"]
    if not scout:
        return out + [callout("Scouting notes are missing", ["scouting.json has not been written yet."], S, W_, PDF_ORANGE)]
    n = 0
    for key, title in (("strengths", "What they do well"), ("weaknesses", "Where they may be open"), ("plan", "A plan against them")):
        if scout[key]:
            out.append(CondPageBreak(55 * mm))
            out.append(Paragraph(title, S["h2"]))
            for t in scout[key]:
                n += 1
                out.append(card(t, n, SCOUT_COLOUR[key], S, W_))
    return out


def pace_section(cfg, S, W_, imgs):
    out = heading("Pace of play", S, "How long plays and pauses lasted. These need the sound as well as the movement.")
    out.append(figure(imgs["pace"], W_, S, max_h=120 * mm))
    return out


def moments_section(cfg, S, W_):
    out = heading("Plays to watch back", S, "The longest plays of each game, with the time in the video file. Long plays show how the two of you build or defend a point, so they are the best ones to rewatch for the questions in this report.")
    rows = [["Game", "Longest plays: starts at (lasts)"]]
    for g in cfg["games"]:
        w = sorted(g["PW"]["windows"], key=lambda x: -x["dur"])[:8]
        if w:
            rows.append([g["title"], ",  ".join(f"{mmss(x['start'])} ({x['dur']:.0f} s)" for x in sorted(w, key=lambda x: x["start"]))])
    out.append(grid(rows, [24 * mm, W_ - 24 * mm], S))
    out.append(Spacer(1, 2 * mm))
    out.append(Paragraph("Times are minutes:seconds in the video file; a play can start a second or two earlier than shown. A very long play at the very start of a game can be a warm-up rally.", S["small"]))
    return out


def sure_section(cfg, S, W_):
    out = heading("How sure", S, "What was checked, what is approximate, and what this report does not measure.")
    rows = [["What", "How it was checked", "How sure"]]
    for c in cfg.get("checks", []):
        rows.append([c["what"], c["how"], LEVELS.get(c.get("level", "approximate"), c.get("level", ""))])
    for g in cfg["games"]:
        n, card_n = g["S"]["plays"]["n"], g.get("card_n")
        rows.append([f"Plays found, {g['title']}", f"{n} found" + (f"; the result card {g['card']} implies {card_n} (difference {n - card_n:+d}). The count can be right while single plays are merged or split." if card_n else "; no result card to compare with."),
                     "Approximate"])
    rows += [["Winners, serves, shots, errors", "Not in the video: there is no scoreboard and no shuttle tracking.", "Not measured"],
             ["Distance, far-half players", "Seen small, so tracking jitter adds distance: compare players on the same side, not near with far.", "Approximate"]]
    out.append(grid(rows, [46 * mm, W_ - 46 * mm - 24 * mm, 24 * mm], S))
    return out


# ---------------------------------------------------------------------------------------------
class Doc(BaseDocTemplate):
    pass


def build(W, out, page, today):
    cfg = load(W)
    register_fonts()
    S = make_styles()
    imgs = make_images(W, cfg)
    size = A4 if page == "A4" else letter
    W_ = size[0] - 2 * MARGIN
    label = cfg["label"]
    doc = Doc(str(out), pagesize=size, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=22 * mm, bottomMargin=17 * mm,
              title=f"Match report: {label}", author="Badminton Analysis (alpha)", subject="Doubles badminton match report", creator="Badminton Analysis stage 14")

    def decorate(c, doc_, first):
        w, h = size
        c.saveState()
        c.setFillColor(SURF)
        c.rect(0, 0, w, h, stroke=0, fill=1)
        if first:
            c.setFillColor(PDF_BLUE)
            c.rect(0, h - 7 * mm, w * 0.72, 7 * mm, stroke=0, fill=1)
            c.setFillColor(PDF_ORANGE)
            c.rect(w * 0.72, h - 7 * mm, w * 0.28, 7 * mm, stroke=0, fill=1)
        else:
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.line(MARGIN, h - 15 * mm, w - MARGIN, h - 15 * mm)
            c.setFont("Body", 7.8)
            c.setFillColor(MUT)
            c.drawString(MARGIN, h - 12.5 * mm, "BADMINTON ANALYSIS  |  SAMPLE REPORT, INVENTED DATA" if cfg.get("sample") else "BADMINTON ANALYSIS  |  MATCH REPORT (NO SCORE ON SCREEN)")
            c.drawRightString(w - MARGIN, h - 12.5 * mm, safe(label))
        c.restoreState()

    frame = Frame(MARGIN, 17 * mm, W_, size[1] - 39 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
    front = Frame(MARGIN, 17 * mm, W_, size[1] - 31 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="cover")
    doc.addPageTemplates([PageTemplate("cover", [front], onPage=lambda c, dd: decorate(c, dd, True)),
                          PageTemplate("body", [frame], onPage=lambda c, dd: decorate(c, dd, False))])
    story = cover(cfg, S, W_, today) + [NextPageTemplate("body"), PageBreak()]
    story += court_section(cfg, S, W_, imgs) + [Spacer(1, 6 * mm)] + glance_section(cfg, S, W_) + [PageBreak()]
    story += coaching_section(cfg, S, W_) + [PageBreak()]
    story += position_section(cfg, S, W_, imgs) + [PageBreak()]
    story += pair_section(cfg, S, W_, imgs) + [PageBreak()]
    for part in (pose_section(cfg, S, W_), opponents_section(cfg, S, W_, imgs), pace_section(cfg, S, W_, imgs), moments_section(cfg, S, W_), sure_section(cfg, S, W_)):
        if part:
            story += [CondPageBreak(95 * mm)] + part + [Spacer(1, 6 * mm)]
    doc.build(story, canvasmaker=NumberedCanvas)
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", help="PDF to write (default: <work>/match_report.pdf)")
    ap.add_argument("--page", choices=["A4", "letter"], default="A4")
    ap.add_argument("--date", help="date shown on the cover (default: today)")
    args = ap.parse_args()
    W = Path(args.work)
    out = Path(args.out) if args.out else W / "match_report.pdf"
    today = args.date or datetime.date.today().strftime("%d %B %Y").lstrip("0")
    cfg = build(W, out, args.page, today)
    for name, ok in (("tips.json", cfg["TIPS"]), ("scouting.json", cfg["SCOUT"])):
        if not ok:
            print(f"WARNING: {name} is missing, so that part of the report is a placeholder.")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB); charts only, no photographs")


if __name__ == "__main__":
    main()
