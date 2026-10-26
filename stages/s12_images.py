#!/usr/bin/env python3
"""Stage 12 - IMAGES.

Renders every statistic, metric and tip from the analysis as standalone PNG images in
work/images/ (01 to 11 about you and your team, 12 and 13 about the opponents). Every number is read from the stage output files; the wording that depends on
the result (for example "no real gap") is chosen from the numbers. Coaching tips are NOT
written here: the AI assistant (or you) writes work/tips.json (see CLAUDE.md) and the tips image
is drawn from it.

Colour: blue = your team / points you won, orange = opponents / points you lost, the same two
validated categorical colours in every image. Ink stays grey-black, never series colour.

Photographic evidence images (court overlay, tracking sheet, skeleton strip, video montage)
are taken from --evidence-dir. For anything you publish, generate them with tools/anonymize.py
so faces are blurred; the raw ones in work/ show people's faces.

Run:
    python stages/s12_images.py --work work [--label "my match"] [--evidence-dir work/anon]
"""
import argparse
import json
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, Patch
from scipy.ndimage import gaussian_filter
from scipy.stats import fisher_exact

from common import NO_CHANGE, chain_status, load_config, own_half_coords, team_phrase

SURF, TILE, INK, INK2, MUT, GRID, BASE = "#fcfcfb", "#f1f0ec", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"
GOOD, WARN = "#0ca30c", "#d03b3b"
plt.rcParams.update({"font.family": ["Arial", "Helvetica Neue", "DejaVu Sans"], "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "savefig.facecolor": SURF, "axes.edgecolor": BASE, "axes.labelcolor": INK2, "xtick.color": MUT, "ytick.color": MUT,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 1.0, "font.size": 14,
                     "xtick.labelsize": 13, "ytick.labelsize": 13, "axes.labelsize": 14, "legend.frameon": False})
DPI = 130
NET, WCT = 6.7, 6.1
META = {"label": "match video"}


def mmss(s):
    return f"{int(s // 60)}:{int(s % 60):02d}"


def pword(p):
    return "probably real" if p < 0.01 else ("suggestive" if p < 0.05 else ("a hint only" if p < 0.2 else "no real gap"))


def head(fig, title, sub=None, y=0.965, gap=0.06):
    fig.text(0.04, y, title, fontsize=27, fontweight="bold", color=INK, va="top")
    if sub:
        fig.text(0.04, y - gap, sub, fontsize=15, color=INK2, va="top")


def foot(fig, extra=""):
    fig.text(0.04, 0.012, (f"{META['label']}, doubles. Numbers are estimates from video. " + extra).strip(), fontsize=10.5, color=MUT, va="bottom")


def clean(ax, ygrid=True):
    ax.tick_params(length=0)
    if ygrid:
        ax.yaxis.grid(True, color=GRID, lw=1.0)
        ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)


def tile(fig, rect, big, caption, big_size=34):
    ax = fig.add_axes(rect)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.06", fc=TILE, ec="none", transform=ax.transAxes))
    ax.text(0.07, 0.62, big, fontsize=big_size, fontweight="bold", color=INK, va="center", transform=ax.transAxes)
    ax.text(0.07, 0.22, "\n".join(textwrap.wrap(caption, 24)), fontsize=12.5, color=INK2, va="center", transform=ax.transAxes, linespacing=1.25)


def barlabel(ax, x, h, txt, color=INK, dy=0.0, size=15):
    ax.text(x, h + dy, txt, ha="center", va="bottom", fontsize=size, fontweight="bold", color=color)


def save(fig, out, name):
    p = out / name
    fig.savefig(p, dpi=DPI)
    plt.close(fig)
    print("  wrote", p.name)
    return p


def load(W):
    L = lambda n: json.loads((W / n).read_text())
    return dict(R=L("report_data.json"), P=L("points.json")["rallies"], S=L("serves.json"), M=L("motion.json"),
                PO=L("pose_stats.json")["stats"], PK=L("pickups.json"), PL=L("players.json"), CAL=L("calib.json"),
                SC=L("score.json"), PI=L("proxy_info.json"), DETS=L("dets.json"), CFG=load_config(W / "players_config.json"),
                OPP=L("opponents.json") if (W / "opponents.json").exists() else None)


def near_pose(d):
    a, b = d["PO"].get("A_you", {}).get("by_side", {}).get("near"), d["PO"].get("A_partner", {}).get("by_side", {}).get("near")
    return (a, b) if a and b else (None, None)


# ------------------------------------------------------------------ 01 summary
def img_summary(d, out):
    P, R, PL, CFG = d["P"], d["R"], d["PL"], d["CFG"]
    D = [p for p in P if p["winner"]]
    mine, _ = team_phrase(CFG)
    last = R["last_scoreboard"]
    sa, sb = (last["score"][0], last["score"][1]) if last["server_team"] == "A" else (last["score"][1], last["score"][0])
    fig = plt.figure(figsize=(13, 8.6))
    head(fig, "Match at a glance", f"Doubles, one game. Your team = {mine}.")
    tw, gap, x0, y0, th = 0.172, 0.0125, 0.04, 0.665, 0.19
    tot_min = sum(p["duration"] for p in P) / 60
    tiles = [(f"{sa}-{sb}", f"score before the final rally ({'your team' if last['server_team'] == 'A' else 'the opponents'} serving)"),
             (f"{len(P)}", f"rallies, {tot_min:.1f} min of play"), (f"{R['ties']} / {R['lead_changes']}", "ties / lead changes"),
             (f"{max(R['streak_A'][0], R['streak_B'][0])}", f"longest run (yours {R['streak_A'][0]} from {mmss(R['streak_A'][1][1])}, theirs {R['streak_B'][0]} from {mmss(R['streak_B'][1][1])})"),
             (f"{np.mean([p['duration'] for p in P]):.1f} s", f"average rally, median {np.median([p['duration'] for p in P]):.1f} s")]
    for i, (b, c) in enumerate(tiles):
        tile(fig, [x0 + i * (tw + gap), y0, tw, th], b, c)
    ax = fig.add_axes([0.075, 0.33, 0.89, 0.28])
    xs = [0] + [p["rally"] for p in D]
    ya, yb = [0] + [p["A_after"] for p in D], [0] + [p["B_after"] for p in D]
    ax.step(xs, ya, where="post", color=BLUE, lw=3, label="Your team")
    ax.step(xs, yb, where="post", color=ORANGE, lw=3, label="Opponents")
    if PL["tc"] < NO_CHANGE:
        sw = next(p["rally"] for p in P if p["start"] > PL["tc"])
        ax.axvline(sw - 0.5, color=BASE, lw=1.2)
        ax.text(sw - 0.1, 2, f"teams swap ends ({mmss(PL['tc'])})", fontsize=11.5, color=INK2)
    top = max(ya[-1], yb[-1])
    ax.text(xs[-1] + 0.5, ya[-1], f"Your team {ya[-1]}", color=INK, fontsize=13, va="center", fontweight="bold")
    ax.text(xs[-1] + 0.5, yb[-1] - (0.3 if abs(ya[-1] - yb[-1]) < 2 else 0), f"Opponents {yb[-1]}", color=INK, fontsize=13, va="center", fontweight="bold")
    ax.set_xlim(0, xs[-1] * 1.15); ax.set_ylim(0, top * 1.08)
    ax.set_ylabel("points"); ax.set_title("Score after each rally", loc="left", fontsize=16, color=INK, pad=8)
    ax.legend(loc="upper left", fontsize=12.5); clean(ax); ax.set_xticks([])
    ax2 = fig.add_axes([0.075, 0.125, 0.89, 0.135])
    ax2.bar([p["rally"] for p in D], [p["duration"] for p in D], width=0.74, color=[BLUE if p["winner"] == "A" else ORANGE for p in D])
    ax2.set_xlim(0, xs[-1] * 1.15); ax2.set_ylabel("seconds"); ax2.set_xlabel("rally number (bar colour = who won it)")
    ax2.set_title("How long each rally lasted", loc="left", fontsize=14, color=INK, pad=6); clean(ax2)
    foot(fig, "The winner of the last rally is not shown in the video.")
    return save(fig, out, "01_match_summary.png")


# ------------------------------------------------------------------ 02 serve / receive
def img_serve(d, out):
    R, P = d["R"], d["P"]
    fig = plt.figure(figsize=(13, 8))
    head(fig, "Serving and receiving", "Share of rallies your team won, and when you served.")

    def panel(rect, title, labels, vals, ns, note=None):
        ax = fig.add_axes(rect)
        x = np.arange(len(vals))
        ax.bar(x, [100 * v / n if n else 0 for v, n in zip(vals, ns)], width=0.5, color=BLUE)
        for xi, v, n in zip(x, vals, ns):
            barlabel(ax, xi, 100 * v / n if n else 0, f"{100 * v / n:.0f}%" if n else "n/a", dy=1.5, size=20)
            ax.text(xi, 100 * v / n / 2 if n else 5, f"{v} of {n}", ha="center", va="center", color="white" if n else INK2, fontsize=13.5, fontweight="bold")
        ax.axhline(50, color=BASE, lw=1.2)
        ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=14); ax.set_ylim(0, 105); ax.set_yticks([0, 50, 100])
        ax.set_yticklabels(["0", "50", "100%"]); ax.set_title(title, loc="left", fontsize=16, color=INK, pad=10); clean(ax)
        if note:
            ax.text(0.0, -0.2, note, transform=ax.transAxes, fontsize=12, color=INK2, va="top")

    ar, ac = R["A_when_serving"], R["A_when_receiving"]
    w, r = R["A_when_serving_you"], R["A_when_serving_partner"]
    p1 = R["serve_vs_receive_p"]
    p2 = fisher_exact([[w[0], w[1] - w[0]], [r[0], r[1] - r[0]]])[1] if w[1] and r[1] else 1.0
    panel([0.06, 0.47, 0.26, 0.32], "Serving vs receiving", ["your team\nserving", "your team\nreceiving"], [ar[0], ac[0]], [ar[1], ac[1]],
          f"p = {p1:.2f}: {pword(p1)}.")
    panel([0.38, 0.47, 0.26, 0.32], "Who was serving", ["you", "your\npartner"], [w[0], r[0]], [w[1], r[1]],
          f"{w[1]} vs {r[1]} serves, p = {p2:.2f}: {pword(p2)}.")
    ax = fig.add_axes([0.71, 0.47, 0.26, 0.32]); ax.axis("off")
    ax.text(0, 0.95, "How to read this", fontsize=16, fontweight="bold", color=INK, va="top")
    ax.text(0, 0.80, "\n".join(textwrap.wrap("Bars show the share of rallies your team won. The count under each bar matters: "
            "with few serves a gap can easily be luck. p is the chance of a gap this big if both bars were really equal. "
            "The timeline below marks every rally you served.", 36)), fontsize=13, color=INK2, va="top", linespacing=1.4)
    ax = fig.add_axes([0.06, 0.075, 0.91, 0.235])
    serves = [p for p in P if p["server_player"] == "A_you"]
    ax.axhline(0, color=BASE, lw=1.5)
    for i, p in enumerate(serves):
        col = BLUE if p["winner"] == "A" else ORANGE
        ax.plot(p["start"], 0, "o", ms=17, color=col, mec=SURF, mew=2, zorder=3)
        up = i % 2 == 0
        ax.text(p["start"], 0.5 if up else -0.5, f"{mmss(p['start'])}\nR{p['rally']}", ha="center", va="bottom" if up else "top", fontsize=12, color=INK)
    end = max(p["end"] for p in P)
    ax.set_xlim(0, end * 1.03); ax.set_ylim(-1.3, 1.3); ax.set_yticks([])
    ticks = list(range(0, int(end), 120))
    ax.set_xticks(ticks); ax.set_xticklabels([mmss(x) for x in ticks])
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.set_title("Every rally you served, in video time", loc="left", fontsize=16, color=INK, pad=8)
    ax.plot([], [], "o", ms=11, color=BLUE, label="point won"); ax.plot([], [], "o", ms=11, color=ORANGE, label="point lost")
    ax.legend(loc="lower left", ncol=2, fontsize=12.5)
    foot(fig, "Who served is inferred from player positions.")
    return save(fig, out, "02_serving.png")


# ------------------------------------------------------------------ 03 rally length
def img_length(d, out):
    R, P = d["R"], d["P"]
    D = [p for p in P if p["winner"]]
    bl = R["by_length"]
    s_n, s_w = bl[0]["n"], bl[0]["A_won"]
    l_n, l_w = sum(b["n"] for b in bl[1:]), sum(b["A_won"] for b in bl[1:])
    p = fisher_exact([[s_w, s_n - s_w], [l_w, l_n - l_w]])[1] if s_n and l_n else 1.0
    fig = plt.figure(figsize=(13, 7.4))
    head(fig, "Rally length", "Share of rallies your team won, by how long the rally lasted.")
    ax = fig.add_axes([0.06, 0.16, 0.40, 0.62])
    x = np.arange(len(bl))
    ax.bar(x, [100 * b["A_won"] / b["n"] if b["n"] else 0 for b in bl], width=0.5, color=BLUE)
    for xi, b in zip(x, bl):
        v = 100 * b["A_won"] / b["n"] if b["n"] else 0
        barlabel(ax, xi, v, f"{v:.0f}%" if b["n"] else "n/a", dy=1.5, size=20)
        ax.text(xi, v / 2 if b["n"] else 5, f"{b['A_won']} of {b['n']}", ha="center", va="center", color="white" if b["n"] else INK2, fontsize=13.5, fontweight="bold")
    ax.axhline(50, color=BASE, lw=1.2)
    ax.set_xticks(x); ax.set_xticklabels([b["bucket"] for b in bl]); ax.set_ylim(0, 105); ax.set_yticks([0, 50, 100]); ax.set_yticklabels(["0", "50", "100%"])
    ax.set_title("Share of rallies your team won", loc="left", fontsize=16, color=INK, pad=10); clean(ax)
    fig.text(0.06, 0.05, f"{bl[0]['bucket']} vs longer: {s_w} of {s_n} against {l_w} of {l_n} (p = {p:.2f}): {pword(p)}.", fontsize=12, color=INK2)
    ax = fig.add_axes([0.58, 0.16, 0.38, 0.62])
    rng = np.random.default_rng(3)
    top = max(p_["duration"] for p_ in D)
    for i, (win, col) in enumerate((("A", BLUE), ("B", ORANGE))):
        v = np.array([p_["duration"] for p_ in D if p_["winner"] == win])
        if not len(v):
            continue
        ax.scatter(i + rng.uniform(-0.18, 0.18, len(v)), v, s=95, color=col, edgecolor=SURF, linewidth=1.6, zorder=3)
        ax.plot([i - 0.3, i + 0.3], [v.mean()] * 2, color=INK, lw=3, zorder=4)
        ax.text(i + 0.34, v.mean(), f"avg {v.mean():.1f} s", fontsize=13, va="center", color=INK, fontweight="bold")
    ax.set_xlim(-0.6, 1.9); ax.set_xticks([0, 1]); ax.set_xticklabels(["rallies you won", "rallies you lost"]); ax.set_ylim(0, top * 1.15)
    ax.set_ylabel("seconds"); ax.set_title("Each dot is one rally", loc="left", fontsize=16, color=INK, pad=10); clean(ax)
    foot(fig)
    return save(fig, out, "03_rally_length.png")


# ------------------------------------------------------------------ 04 you won vs lost
def img_movement(d, out):
    M = d["M"]["summary"]
    fig = plt.figure(figsize=(13, 9.6))
    head(fig, "You: rallies won vs lost", f"{M['you']['distance_m']['n_won']} won and {M['you']['distance_m']['n_lost']} lost rallies. Bars are averages.")
    spec = [("you", "distance_m", "Distance per rally (m)", "{:.1f}", 1), ("you", "mean_speed", "Mean speed (m/s)", "{:.2f}", 1),
            ("you", "peak_speed", "Peak speed (m/s)", "{:.2f}", 1), ("you", "front", "Time at the net (%)", "{:.0f}", 100),
            ("you", "mid", "Time mid-court (%)", "{:.0f}", 100), ("you", "back", "Time at the back (%)", "{:.0f}", 100),
            ("you", "mean_depth", "Avg distance from net (m)", "{:.1f}", 1), ("pair", "open_gap_mean", "Open gap in your half (m)", "{:.1f}", 1),
            ("pair", "crowded", "Pair within 1.5 m (%)", "{:.0f}", 100)]
    for i, (grp, key, title, fmt, mult) in enumerate(spec):
        r, c = divmod(i, 3)
        ax = fig.add_axes([0.06 + c * 0.32, 0.625 - r * 0.265, 0.26, 0.165])
        m = M[grp][key]
        vals = [m["won"] * mult, m["lost"] * mult]
        ax.bar([0, 1], vals, width=0.58, color=[BLUE, ORANGE])
        top = max(vals) * 1.45 or 1
        for xi, v in enumerate(vals):
            barlabel(ax, xi, v, fmt.format(v), dy=top * 0.02, size=16)
        ax.set_ylim(0, top); ax.set_xticks([0, 1]); ax.set_xticklabels(["won", "lost"], fontsize=13); ax.set_yticks([])
        ax.set_title(title, loc="left", fontsize=14, color=INK, pad=6)
        ax.text(1.0, 0.99, f"p = {m['p']:.2f}" + ("  (weak)" if m["p"] < 0.05 else ""), transform=ax.transAxes, ha="right", va="top", fontsize=12, color=INK2)
        ax.spines["left"].set_visible(False)
        ax.tick_params(length=0)
    fig.text(0.06, 0.04, "p: chance of a difference this big if won and lost rallies were the same (small = real).  With 9 comparisons one p under 0.05 is expected by chance,", fontsize=11.5, color=INK2)
    fig.text(0.06, 0.015, "so a lone small p is a question for the video, not a finding.  Blue = rallies your team won, orange = lost.", fontsize=11.5, color=INK2)
    return save(fig, out, "04_you_won_vs_lost.png")


# ------------------------------------------------------------------ 05 heatmaps
def img_heat(d, out, W):
    z = np.load(W / "players.npz")
    t = z["t"]
    rows = d["M"]["rallies"]
    cmap = LinearSegmentedColormap.from_list("seq", [SURF, "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
    grids = {}
    for k in ("A_you", "A_partner"):
        for won in (True, False):
            H = np.zeros((int(WCT / 0.25) + 1, int(NET / 0.25) + 1))
            for r in rows:
                if r["user_team_won"] != won:
                    continue
                m = (t >= r["start"] + 0.3) & (t < r["end"] - 0.3)
                P = z[f"{k}_xy"][m]
                P = P[~np.isnan(P[:, 0])]
                if not len(P):
                    continue
                near = r["players"][k].get("side") == "near"
                u = P[:, 0] if near else WCT - P[:, 0]
                dd = np.abs(P[:, 1] - NET)
                for uu, v in zip(u, dd):
                    H[int(np.clip(uu / 0.25, 0, H.shape[0] - 1)), int(np.clip(v / 0.25, 0, H.shape[1] - 1))] += 1
            H = gaussian_filter(H, 1.2)
            grids[(k, won)] = H / max(H.sum(), 1e-9)
    vmax = max(g.max() for g in grids.values())
    fig = plt.figure(figsize=(12.5, 11.4))
    head(fig, "Where you and your partner stood", "Own half of the court seen from behind your team, net at the top. Darker = more time.")
    for ci, won in enumerate((True, False)):
        for ri, k in enumerate(("A_you", "A_partner")):
            ax = fig.add_axes([0.09 + ci * 0.47, 0.56 - ri * 0.41, 0.38, 0.29])
            ax.imshow(grids[(k, won)].T, origin="upper", extent=[0, WCT, NET, 0], cmap=cmap, vmin=0, vmax=vmax, aspect="equal")
            for xx in (0.46, WCT - 0.46):
                ax.axvline(xx, color=INK2, lw=0.8, alpha=0.45)
            ax.axvline(WCT / 2, ymin=0, ymax=(NET - 1.98) / NET, color=INK2, lw=0.8, alpha=0.45)
            ax.axhline(1.98, color=INK2, lw=0.8, alpha=0.45); ax.axhline(NET - 0.76, color=INK2, lw=0.8, alpha=0.45)
            ax.axhline(0, color=INK, lw=3.5)
            ax.set_xlim(0, WCT); ax.set_ylim(NET, -0.15)
            ax.set_title(f"{'YOU' if k == 'A_you' else 'YOUR PARTNER'}: {'won' if won else 'lost'} rallies", loc="left", fontsize=15, color=INK, pad=6)
            ax.set_xlabel("across your half, your left to right (m)", fontsize=11.5); ax.set_ylabel("m from the net", fontsize=11.5)
            for s in ("left", "bottom"):
                ax.spines[s].set_visible(False)
            ax.tick_params(length=0)
    fig.text(0.07, 0.03, "Court coordinates from the camera calibration. Parts of the court outside the camera view are under-counted. Same colour scale in all four maps.", fontsize=11.5, color=INK2)
    return save(fig, out, "05_heatmaps.png")


# ------------------------------------------------------------------ 06 players
def img_players(d, out):
    R, CFG, P = d["R"], d["CFG"], d["P"]
    tot, cov, sb = R["motion_totals"], R["tracking"], R["serves_by_player"]
    ids = ["A_you", "A_partner", "B_opp1", "B_opp2"]
    lab = ["You", "Partner", f"Opp 1\n({CFG['B_opp1']['describe']})", f"Opp 2\n({CFG['B_opp2']['describe']})"]
    col = [BLUE, BLUE, ORANGE, ORANGE]
    fig = plt.figure(figsize=(13, 7.4))
    head(fig, "All four players", "Blue = your team, orange = opponents. You are the first bar in each chart.")
    specs = [("Distance run (m)", [tot[k]["total_distance_m"] for k in ids], "{:.0f}"),
             ("Distance per rally (m)", [tot[k]["distance_per_rally"] for k in ids], "{:.1f}"),
             ("Mean speed (m/s)", [tot[k]["mean_speed"] for k in ids], "{:.2f}"),
             ("Served (rallies)", [sb[k] for k in ids], "{:.0f}")]
    for i, (title, vals, fmt) in enumerate(specs):
        ax = fig.add_axes([0.05 + i * 0.238, 0.22, 0.20, 0.52])
        ax.bar(range(4), vals, width=0.62, color=col)
        for xi, v in enumerate(vals):
            barlabel(ax, xi, v, fmt.format(v), dy=max(vals) * 0.02, size=15)
        ax.set_ylim(0, max(vals) * 1.22); ax.set_yticks([]); ax.set_xticks(range(4)); ax.set_xticklabels(lab, fontsize=11.5)
        ax.get_xticklabels()[0].set_fontweight("bold")
        ax.set_title(title, loc="left", fontsize=14.5, color=INK, pad=8)
        ax.spines["left"].set_visible(False); ax.tick_params(length=0)
    ident = sum(sb.values())
    fig.text(0.05, 0.07, "Tracked in " + ", ".join(f"{n} {cov[k]:.0%}" for n, k in zip(("you", "partner", "opp 1", "opp 2"), ids)) +
             f" of frames. 'Served' counts rallies where the server could be identified ({ident} of {len(P)}).", fontsize=12, color=INK2)
    foot(fig)
    return save(fig, out, "06_players.png")


# ------------------------------------------------------------------ 07 posture
def img_posture(d, out, W, ev, photos=True):
    """07_posture.png has the skeleton photo strip (face-blurred if --evidence-dir is blurred); 07_posture_charts.png has none,
    so it is safe to put in a document you share."""
    you, mate = near_pose(d)
    if not you:
        print("  skipped 07_posture: no near-half posture numbers")
        return None
    strip = ev("skeleton_strip.jpg", "s08_check.jpg") if photos else None
    if photos and not strip:
        return None
    H = 9.0 if strip else 6.9
    cut = 0.0 if strip else 2.1                      # inches of the 9-inch layout that are left out without the photo strip
    fy = lambda f9: (f9 * 9.0 - cut) / H             # a position in the 9-inch layout -> this figure
    fh = lambda f9: f9 * 9.0 / H
    arm = d["PO"]["A_you"].get("racket_hand") or ("left" if d["PO"]["A_you"].get("racket_arm") == "L" else "right")
    fig = plt.figure(figsize=(13, H))
    head(fig, "Posture (near half only)", f"{you['rallies']} rallies, {you['samples']} frames of you. Body landmarks need a big person, so this only works while you are near the camera.",
         y=1 - 0.315 / H, gap=0.54 / H)
    ax = fig.add_axes([0.06, fy(0.50), 0.26, fh(0.28)])
    for i, (nm, v) in enumerate((("You", you["knee_median"]), ("Partner", mate["knee_median"]))):
        ax.plot([v], [i], "o", ms=22, color=BLUE, mec=SURF, mew=2)
        ax.text(v, i + 0.28, f"{v:.0f}°", ha="center", fontsize=18, fontweight="bold", color=INK)
    ax.set_yticks([0, 1]); ax.set_yticklabels(["You", "Partner"], fontsize=14); ax.set_ylim(-0.6, 1.8); ax.set_xlim(120, 185)
    ax.axvline(180, color=BASE, lw=1.2); ax.text(180, -0.5, "straight leg", ha="right", fontsize=11, color=MUT)
    ax.axvline(150, color=BASE, lw=1.2); ax.text(150, -0.5, "bent knees", ha="center", fontsize=11, color=MUT)
    ax.set_title("Knee angle, typical", loc="left", fontsize=15, color=INK, pad=8); ax.tick_params(length=0)
    ax.spines["left"].set_visible(False)

    def grouped(rect, title, key, notes):
        ax = fig.add_axes(rect)
        for gi, blk in enumerate((you, mate)):
            for bi, (lbl, col) in enumerate((("won", BLUE), ("lost", ORANGE))):
                v = 100 * (blk[lbl][key] or 0)
                x = gi * 1.0 + (bi - 0.5) * 0.36
                ax.bar(x, v, width=0.32, color=col)
                barlabel(ax, x, v, f"{v:.0f}", dy=1.2, size=15)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["You", "Partner"], fontsize=14); ax.set_ylim(0, 112); ax.set_yticks([0, 50, 100]); ax.set_yticklabels(["0", "50", "100%"])
        ax.set_title(title, loc="left", fontsize=15, color=INK, pad=8); clean(ax)
        ax.text(0, -0.17, notes, transform=ax.transAxes, fontsize=11.5, color=INK2, va="top")

    grouped([0.40, fy(0.50), 0.26, fh(0.28)], "Frames with knees bent (< 150°)", "bent_lt150", "Knees under 150 degrees count as bent.")
    grouped([0.72, fy(0.50), 0.26, fh(0.28)], "Racket hand held above the hip", "racket_up_share", f"Racket hand detected as the {arm}.")
    if strip:
        ax = fig.add_axes([0.04, 0.03, 0.92, 0.19]); ax.axis("off")
        ax.imshow(mpimg.imread(strip), aspect="auto"); ax.set_title("Skeleton check: sample frames of you, landmarks should sit on the body", loc="left", fontsize=13, color=INK2, pad=4)
    fig.text(0.06, fy(0.315), f"You: knees bent in {you['bent_lt150']:.0%} of frames vs {mate['bent_lt150']:.0%} for your partner; racket hand up {you['racket_up_share']:.0%} (partner {mate['racket_up_share']:.0%}).", fontsize=12.5, color=INK2)
    fig.legend(handles=[Patch(color=BLUE, label="rallies won"), Patch(color=ORANGE, label="rallies lost")], loc="upper right", bbox_to_anchor=(0.97, fy(0.87)), ncol=2, fontsize=13)
    if not strip:
        foot(fig, "Charts only: no photographs.")
    return save(fig, out, "07_posture.png" if strip else "07_posture_charts.png")


# ------------------------------------------------------------------ 08 tips (written by the assistant)
KIND_LABEL = {"strength": "WORKING WELL", "improve": "WORK ON THIS", "check": "CHECK ON THE VIDEO"}


def img_tips(d, out, W, tips_path):
    if not tips_path.exists():
        print(f"  skipped 08_coaching_tips.png: {tips_path.name} not found (the AI assistant writes it, see CLAUDE.md)")
        return None
    tips = json.loads(tips_path.read_text())
    wrap = lambda s, n: textwrap.wrap(s, n) or [""]
    LH = 0.215                                          # inches per text line
    cards = []
    for t in tips:
        body, tr = wrap(t["body"], 92), wrap("Try: " + t["try"], 88) if t.get("try") else []
        watch, sure = (wrap(t["watch"], 88) if t.get("watch") else []), (wrap(t["sure"], 100) if t.get("sure") else [])
        h = 0.72 + LH * len(body) + (0.12 + LH * len(tr) if tr else 0) + (0.12 + LH * len(watch) if watch else 0) + (0.10 + 0.2 * len(sure) if sure else 0) + 0.2
        cards.append((t, body, tr, watch, sure, h))
    gap = 0.16
    H = 1.7 + sum(c[-1] for c in cards) + gap * len(cards)
    fy = lambda inch: inch / H
    fig = plt.figure(figsize=(10, H))
    head(fig, "Coaching tips", "Ranked by how much the video supports them. All times are video time.", y=1 - 0.2 / H, gap=0.62 / H)
    top = H - 1.45
    for i, (t, body, tr, watch, sure, h) in enumerate(cards):
        fig.patches.append(FancyBboxPatch((0.04, fy(top - h)), 0.92, h / H, boxstyle="round,pad=0,rounding_size=0.012", fc=TILE, ec="none", transform=fig.transFigure))
        fig.text(0.065, fy(top - 0.14), str(i + 1), fontsize=26, fontweight="bold", color=BLUE, va="top")
        if KIND_LABEL.get(t.get("kind")):
            fig.text(0.94, fy(top - 0.17), KIND_LABEL[t["kind"]], fontsize=9.5, fontweight="bold", color=MUT, va="top", ha="right")
        fig.text(0.115, fy(top - 0.15), t["title"], fontsize=17.5, fontweight="bold", color=INK, va="top")
        y = top - 0.72
        fig.text(0.115, fy(y), "\n".join(body), fontsize=12.2, color=INK, va="top", linespacing=1.32)
        y -= LH * len(body)
        for lines, colour, weight, space in ((tr, BLUE, "bold", 0.12), (watch, INK2, "bold", 0.12), (sure, MUT, "normal", 0.10)):
            if lines:
                y -= space
                fig.text(0.115, fy(y), "\n".join(lines), fontsize=11.8 if weight == "bold" else 11.2, color=colour, va="top", fontweight=weight, linespacing=1.3)
                y -= (LH if weight == "bold" else 0.2) * len(lines)
        top -= h + gap
    foot(fig)
    return save(fig, out, "08_coaching_tips.png")


# ------------------------------------------------------------------ 09 watch list
def img_watch(d, out):
    P, R = d["P"], d["R"]
    byr = {p["rally"]: p for p in P}
    sb, sa = R["streak_B"], R["streak_A"]
    rows = []
    for p in P:
        if p["server_player"] == "A_you" and p["winner"] == "B":
            rows.append((p["start"], p["rally"], "you served, point lost", f"score {p['score_before'][0]}-{p['score_before'][1]}"))
    for r, t, dur in R["check"]["longest_lost"][:3]:
        p = byr[r]
        rows.append((p["start"], r, f"long rally lost ({dur:.0f} s)", f"score {p['score_before'][0]}-{p['score_before'][1]}"))
    rows.append((sb[1][1], sb[1][0], f"opponents' {sb[0]}-point run starts", "what changed?"))
    rows.append((sa[1][1], sa[1][0], f"your {sa[0]}-point run starts", "what worked?"))
    rows.sort()
    seen, uniq = set(), []
    for r in rows:
        if (r[1], r[2]) not in seen:
            seen.add((r[1], r[2])); uniq.append(r)
    n = len(uniq)
    fig = plt.figure(figsize=(13, 2.5 + 0.5 * n))
    head(fig, "Moments to check on the video", "In order of video time. Open the clip at these times and see if the numbers match what you saw.", y=0.975)
    y0 = 0.80
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    h = 0.73 / (n + 1)
    for x, name in ((0.05, "TIME"), (0.17, "RALLY"), (0.30, "WHAT TO LOOK AT"), (0.76, "CONTEXT")):
        ax.text(x, y0 - 0.02, name, fontsize=12, color=MUT, fontweight="bold")
    for i, (t, r, what, ctx) in enumerate(uniq):
        y = y0 - 0.02 - (i + 1) * h
        if i % 2 == 0:
            ax.add_patch(plt.Rectangle((0.04, y - h * 0.3), 0.92, h, fc=TILE, ec="none"))
        lost = "lost" in what or "opponents" in what
        ax.text(0.05, y + h * 0.2, mmss(t), fontsize=17, fontweight="bold", color=INK, va="center")
        ax.text(0.17, y + h * 0.2, f"R{r}", fontsize=15, color=INK2, va="center")
        ax.plot([0.285], [y + h * 0.2], "o", ms=11, color=ORANGE if lost else BLUE)
        ax.text(0.30, y + h * 0.2, what, fontsize=15, color=INK, va="center")
        ax.text(0.76, y + h * 0.2, ctx, fontsize=14, color=INK2, va="center")
    fig.text(0.04, 0.012, "Orange dot = a point your team lost (or the opponents' run), blue dot = something that worked for your team.", fontsize=11, color=MUT)
    return save(fig, out, "09_moments_to_check.png")


# ------------------------------------------------------------------ 10 reliability
def img_reliability(d, out):
    S, SC, PK, CAL, R, PI, DETS, P = d["S"], d["SC"], d["PK"], d["CAL"], d["R"], d["PI"], d["DETS"], d["P"]
    fig = plt.figure(figsize=(13, 9.6))
    head(fig, "How sure is each number?", "Left: how well each block of rallies is backed up. Right: the check run at every stage.")
    ax = fig.add_axes([0.20, 0.17, 0.27, 0.63])
    chains = chain_status(S, SC)
    ys = np.arange(len(chains))[::-1]
    for y, c in zip(ys, chains):
        a, b = c["rallies"]
        ax.barh(y, c["n"], height=0.62, color=BLUE if c["status"] == "confirmed" else BASE)
        ax.text(c["n"] + 0.4, y, f"{c['n']}", va="center", fontsize=12.5, color=INK2)
        ax.text(-0.5, y, f"rallies {a}" + (f"-{b}" if b != a else ""), va="center", ha="right", fontsize=12.5, color=INK)
    ax.set_yticks([]); ax.set_xticks([]); ax.set_xlim(0, max(c["n"] for c in chains) * 1.15)
    ax.spines["left"].set_visible(False); ax.spines["bottom"].set_visible(False)
    ax.set_title("Who won each rally", loc="left", fontsize=15, color=INK, pad=8)
    ax.legend(handles=[Patch(color=BLUE, label="independently confirmed (the same player keeps serving)"),
                       Patch(color=BASE, label="one confirming pair, or the position cue only")], loc="upper left", bbox_to_anchor=(-0.55, -0.01), fontsize=11.5)
    ax = fig.add_axes([0.52, 0.17, 0.46, 0.63]); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    dur = [p["duration"] for p in P]
    ok_n = sum(1 for c in PI.get("checks", []) if c["ok"])
    checks = [("0  proxy video", True, f"{ok_n} of {len(PI.get('checks', []))} automatic checks"),
              ("1  person detection", True, f"{len(DETS['frames'])} sampled frames"),
              ("2  court calibration", True, f"fit error {CAL['rms_px']:.1f} px"),
              ("3  player tracking", True, f"{min(R['tracking'].values()):.0%} to {max(R['tracking'].values()):.0%} of frames"),
              ("4  serves", True, f"quadrants occupied in {100 * sum(1 for s in S['serves'] if s['diag_quadrants_occupied']) / len(S['serves']):.0f}% of windows"),
              ("5  score replay", len(SC["problems"]) == 0, f"{len(SC['problems'])} mismatches with the scoreboard"),
              ("6  rally boundaries", True, f"{len(P)} rallies, {min(dur):.0f} to {max(dur):.0f} s"),
              ("7  movement", True, f"{R['motion_summary']['you']['distance_m']['n_won'] + R['motion_summary']['you']['distance_m']['n_lost']} rallies compared"),
              ("8  posture", near_pose(d)[0] is not None, "near half only" if near_pose(d)[0] else "too few frames"),
              ("9  shuttle pickups", PK["usable"], f"{PK['agree_with_loser']} of {PK['rallies_with_single_bending_team']} point at the loser" + ("" if PK["usable"] else " (chance)"))]
    h = 1 / (len(checks) + 1)
    ax.text(0.0, 1 - h * 0.5, "Stage", fontsize=12, color=MUT, fontweight="bold", va="center")
    ax.text(0.47, 1 - h * 0.5, "Result", fontsize=12, color=MUT, fontweight="bold", va="center")
    for i, (nm, good, note) in enumerate(checks):
        y = 1 - h * (i + 1.5)
        ax.text(0.0, y, nm, fontsize=14, color=INK, va="center")
        ax.plot([0.47], [y], "o" if good else "D", ms=11, color=GOOD if good else WARN)
        ax.text(0.51, y + 0.012, "PASS" if good else "NOT USED", fontsize=12.5, fontweight="bold", color=INK, va="center")
        ax.text(0.51, y - 0.028, note, fontsize=10.8, color=INK2, va="center")
    fig.text(0.04, 0.012, "Far-court positions are less precise than near-court ones; parts of the court outside the camera view are under-counted.", fontsize=11.5, color=INK2)
    return save(fig, out, "10_how_sure.png")


# ------------------------------------------------------------------ 11 evidence
def img_evidence(d, out, ev):
    imgs = [ev("court_overlay.jpg", "s02_check.jpg"), ev("video_montage.jpg", "s11_check.jpg"), ev("tracking_sheet.jpg", "s03_check.jpg")]
    if not all(imgs):
        print("  skipped 11_how_it_was_seen.png: evidence images missing")
        return None
    fig = plt.figure(figsize=(13, 10.6))
    head(fig, "How the computer saw the match", "The pictures behind the numbers.")

    def show(rect, path, title):
        ax = fig.add_axes(rect); ax.axis("off")
        ax.imshow(mpimg.imread(path), aspect="auto"); ax.set_title(title, loc="left", fontsize=14.5, color=INK, pad=6)

    show([0.04, 0.485, 0.44, 0.335], imgs[0], "Court found: red lines should sit on the painted lines")
    show([0.52, 0.485, 0.44, 0.335], imgs[1], "In the video: labels, score bar, mini-map")
    show([0.04, 0.08, 0.92, 0.37], imgs[2], "Players followed: yellow box = you, red = partner, blue and green = the opponents")
    fig.text(0.04, 0.03, "These are the check images each stage produced. If a label sits on the wrong person, that stage's numbers are wrong.", fontsize=11.5, color=INK2)
    return save(fig, out, "11_how_it_was_seen.png")


# ------------------------------------------------------------------ 12 / 13 the opponents
OPP_IDS = ("B_opp1", "B_opp2")
OPP_CMAP = LinearSegmentedColormap.from_list("opp", [SURF, "#fde3d6", "#f8b898", "#ef8250", "#c9501f", "#7a2c0e"])
ZONE_LATERAL, ZONE_DEPTH = ("left", "centre", "right"), ("front", "mid", "back")


def opp_labels(d):
    return [f"Opp {i + 1}\n({d['CFG'][k]['describe']})" for i, k in enumerate(OPP_IDS)]


def img_opponents(d, out):
    O = d["OPP"]
    if not O:
        print("  skipped 12_opponents.png: opponents.json not found (stage 7b)")
        return None
    R, Q = O["results"], O["players"]
    lab = opp_labels(d)
    fig = plt.figure(figsize=(13, 8.8))
    head(fig, "The opponents", "Orange = the opponents. How they did, and how they moved.")

    def share_panel(rect, title, labels, vals, ns, note=None):
        ax = fig.add_axes(rect)
        x = np.arange(len(vals))
        pc = [100 * v / n if n else 0 for v, n in zip(vals, ns)]
        ax.bar(x, pc, width=0.5 if len(vals) < 3 else 0.72, color=ORANGE)
        for xi, v, n, p in zip(x, vals, ns, pc):
            barlabel(ax, xi, p, f"{p:.0f}%" if n else "n/a", dy=1.5, size=19)
            ax.text(xi, p / 2 if n else 5, f"{v} of {n}", ha="center", va="center", color="white" if n else INK2,
                    fontsize=13 if len(vals) < 3 else 11.5, fontweight="bold")
        ax.axhline(50, color=BASE, lw=1.2)
        ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=12.5); ax.set_ylim(0, 105); ax.set_yticks([0, 50, 100]); ax.set_yticklabels(["0", "50", "100%"])
        ax.set_title(title, loc="left", fontsize=15, color=INK, pad=10); clean(ax)
        if note:
            ax.text(0.0, -0.24, "\n".join(textwrap.wrap(note, 44)), transform=ax.transAxes, fontsize=11.5, color=INK2, va="top")

    sv, rc = R["serving"], R["receiving"]
    share_panel([0.06, 0.52, 0.26, 0.27], "Share of rallies they won", ["when they\nserved", "when they\nreceived"], [sv[0], rc[0]], [sv[1], rc[1]],
                f"p = {R['serve_vs_receive_p']:.2f}: {pword(R['serve_vs_receive_p'])}." if R["serve_vs_receive_p"] is not None else None)
    bl = R["by_length"]
    sl = R["short_vs_long"]
    share_panel([0.38, 0.52, 0.26, 0.27], "By rally length", [" ".join(b["bucket"].split()[:-2]) + "\n" + " ".join(b["bucket"].split()[-2:]) for b in bl], [b["won"] for b in bl], [b["n"] for b in bl],
                f"{bl[0]['bucket']} vs longer: {sl['short'][0]} of {sl['short'][1]} against {sl['longer'][0]} of {sl['longer'][1]}" +
                (f" (p = {sl['p']:.2f}): {pword(sl['p'])}." if sl["p"] is not None else "."))
    bs = R["by_server"]
    share_panel([0.70, 0.52, 0.26, 0.27], "When each of them served", lab, [bs[k][0] for k in OPP_IDS], [bs[k][1] for k in OPP_IDS],
                f"{R['server_unknown']} rallies are left out: the server could not be identified.")

    specs = [("Distance per rally (m)", [Q[k]["distance_per_rally"] for k in OPP_IDS], "{:.1f}", 1),
             ("Mean speed (m/s)", [Q[k]["mean_speed"] for k in OPP_IDS], "{:.2f}", 1),
             ("Time at the back (%)", [Q[k]["back"] for k in OPP_IDS], "{:.0f}", 100),
             ("Plays the net side (% of rallies)", [Q[k]["net_side_share"] for k in OPP_IDS], "{:.0f}", 100)]
    for i, (title, vals, fmt, mult) in enumerate(specs):
        ax = fig.add_axes([0.06 + i * 0.238, 0.13, 0.19, 0.22])
        vals = [(v or 0) * mult for v in vals]
        ax.bar([0, 1], vals, width=0.55, color=ORANGE)
        top = max(vals) * 1.3 or 1
        for xi, v in enumerate(vals):
            barlabel(ax, xi, v, fmt.format(v), dy=top * 0.02, size=16)
        ax.set_ylim(0, top); ax.set_yticks([]); ax.set_xticks([0, 1]); ax.set_xticklabels(lab, fontsize=11.5)
        ax.set_title(title, loc="left", fontsize=13.5, color=INK, pad=8); ax.spines["left"].set_visible(False); ax.tick_params(length=0)
    foot(fig, f"Time at the back and net side use the {O['rallies_used_for_depth']} rallies where they were on the {O['depth_numbers_from']} half (far-half depth is less reliable).")
    return save(fig, out, "12_opponents.png")


def img_opp_positions(d, out, W):
    O = d["OPP"]
    if not O or "zones" not in O:
        print("  skipped 13_opponent_positions.png: no zone numbers (stage 7b needs players.npz)")
        return None
    z = np.load(W / "players.npz")
    t = z["t"]
    rows = [r for r in d["M"]["rallies"] if O["depth_numbers_from"] == "all" or not r["A_is_near"]]
    grids = {}
    for k in OPP_IDS:
        H = np.zeros((int(WCT / 0.25) + 1, int(NET / 0.25) + 1))
        for r in rows:
            m = (t >= r["start"] + 0.3) & (t < r["end"] - 0.3)
            u, dd = own_half_coords(z[f"{k}_xy"][m], not r["A_is_near"])
            ok = ~np.isnan(u)
            for uu, v in zip(u[ok], dd[ok]):
                H[int(np.clip(uu / 0.25, 0, H.shape[0] - 1)), int(np.clip(v / 0.25, 0, H.shape[1] - 1))] += 1
        H = gaussian_filter(H, 1.2)
        grids[k] = H / max(H.sum(), 1e-9)
    vmax = max(g.max() for g in grids.values())
    fig = plt.figure(figsize=(13, 6.9))
    head(fig, "Where the opponents stood", f"Their own half seen from behind them, net at the top. {len(rows)} rallies with them on the {O['depth_numbers_from']} half.")

    def court(ax):
        for xx in (0.46, WCT - 0.46):
            ax.axvline(xx, color=INK2, lw=0.8, alpha=0.45)
        ax.axvline(WCT / 2, ymin=0, ymax=(NET - 1.98) / NET, color=INK2, lw=0.8, alpha=0.45)
        ax.axhline(1.98, color=INK2, lw=0.8, alpha=0.45); ax.axhline(NET - 0.76, color=INK2, lw=0.8, alpha=0.45)
        ax.axhline(0, color=INK, lw=3.5)
        ax.set_xlim(0, WCT); ax.set_ylim(NET, -0.15)
        for s in ("left", "bottom"):
            ax.spines[s].set_visible(False)
        ax.tick_params(length=0)

    for i, k in enumerate(OPP_IDS):
        ax = fig.add_axes([0.07 + i * 0.30, 0.13, 0.25, 0.60])
        ax.imshow(grids[k].T, origin="upper", extent=[0, WCT, NET, 0], cmap=OPP_CMAP, vmin=0, vmax=vmax, aspect="equal")
        court(ax)
        ax.set_title(f"Opp {i + 1} ({d['CFG'][k]['describe']})", loc="left", fontsize=15, color=INK, pad=6)
        ax.set_xlabel("across their half, their left to right (m)", fontsize=11); ax.set_ylabel("m from the net", fontsize=11)
    cov = O["zones"]["coverage"]
    M = np.array([[cov[f"{ZONE_DEPTH[j]} {ZONE_LATERAL[i]}"] or 0 for i in range(3)] for j in range(3)])
    ax = fig.add_axes([0.69, 0.22, 0.27, 0.51])
    ax.imshow(M, cmap=OPP_CMAP, vmin=0, vmax=1, aspect="auto", extent=[0, 3, 3, 0])
    for j in range(3):
        for i in range(3):
            ax.text(i + 0.5, j + 0.5, f"{M[j, i]:.0%}", ha="center", va="center", fontsize=19, fontweight="bold", color="white" if M[j, i] > 0.5 else INK)
    for v in (1, 2):
        ax.axvline(v, color=SURF, lw=3); ax.axhline(v, color=SURF, lw=3)
    ax.axhline(0, color=INK, lw=3.5)
    ax.set_xticks([0.5, 1.5, 2.5]); ax.set_xticklabels(ZONE_LATERAL, fontsize=13); ax.set_yticks([0.5, 1.5, 2.5]); ax.set_yticklabels(ZONE_DEPTH, fontsize=13)
    ax.set_xlim(0, 3); ax.set_ylim(3, -0.05)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("How much of each zone they covered", loc="left", fontsize=15, color=INK, pad=6)
    note = (f"Share of time at least one of them stood within {O['zones']['within_m']:g} m of the middle of the zone. "
            "It shows where they stood, not where they lost points.")
    if O["depth_numbers_from"] == "near":
        note += " Far-half positions are rougher, so only near-half rallies are used."
    fig.text(0.69, 0.155, "\n".join(textwrap.wrap(note, 46)), fontsize=11, color=INK2, va="top", linespacing=1.3)
    foot(fig)
    return save(fig, out, "13_opponent_positions.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--label", default="match video")
    ap.add_argument("--tips", help="tips.json (default: <work>/tips.json)")
    ap.add_argument("--evidence-dir", help="folder with court_overlay.jpg, tracking_sheet.jpg, skeleton_strip.jpg, video_montage.jpg (default: work, raw and NOT face-blurred)")
    ap.add_argument("--out", help="output folder (default: <work>/images)")
    args = ap.parse_args()
    W = Path(args.work)
    out = Path(args.out) if args.out else W / "images"
    out.mkdir(parents=True, exist_ok=True)
    META["label"] = args.label
    evdir = Path(args.evidence_dir) if args.evidence_dir else None

    def ev(anon_name, raw_name):
        if evdir and (evdir / anon_name).exists():
            return evdir / anon_name
        if evdir is None and (W / raw_name).exists():
            print(f"  note: using the raw {raw_name}; it shows faces, so do not publish the image built from it")
            return W / raw_name
        return None

    d = load(W)
    print("rendering images ->", out)
    paths = [img_summary(d, out), img_serve(d, out), img_length(d, out), img_movement(d, out), img_heat(d, out, W), img_players(d, out),
             img_posture(d, out, W, ev), img_posture(d, out, W, ev, photos=False),
             img_tips(d, out, W, Path(args.tips) if args.tips else W / "tips.json"), img_watch(d, out),
             img_reliability(d, out), img_evidence(d, out, ev), img_opponents(d, out), img_opp_positions(d, out, W)]
    print(f"{sum(p is not None for p in paths)} images")


if __name__ == "__main__":
    main()
