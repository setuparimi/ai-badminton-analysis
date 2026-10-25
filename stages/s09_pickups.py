#!/usr/bin/env python3
"""Stage 9 - PICKUPS.

Looks for a player bending right down (picking up the shuttle) around the end of each
rally, to say which side the shuttle landed on. A bend is a drop of the player's box height
to under --ratio of their own recent standing height, for at least 2 consecutive samples,
while the player is not running.

The result is validated against the rally losers from stage 5 (the shuttle usually lands
on the losing side): if bends do not point at the losing side more often than chance, the
detector is reported as not usable on this video rather than quietly used.

Run:
    python stages/s09_pickups.py --players work/players.npz --serves work/serves.json \
        --points work/points.json --out work/pickups.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common import SLOTS as IDS



def bends(z, ratio, win=2.5):
    t, dt = z["t"], float(z["stride"]) / float(z["fps"])
    out = {}
    for k in IDS:
        B, fl, xy = z[f"{k}_box"], z[f"{k}_flag"], z[f"{k}_xy"]
        h = np.where(fl == 1, B[:, 3] - B[:, 1], np.nan)
        sp = np.full(len(t), np.nan)
        sp[1:] = np.linalg.norm(np.diff(xy, axis=0), axis=1) / dt
        w = int(win / dt)
        ref = np.full(len(t), np.nan)
        for i in range(len(t)):
            seg = h[max(0, i - w):i + w + 1]
            seg = seg[~np.isnan(seg)]
            if len(seg) >= 8:
                ref[i] = np.percentile(seg, 90)
        low = (h / ref < ratio) & (sp < 1.5)
        ev, i = [], 0
        while i < len(t):
            if low[i]:
                j = i
                while j + 1 < len(t) and (low[j + 1] or (j + 2 < len(t) and low[j + 2])):
                    j += 1
                if j - i + 1 >= 2:
                    ev.append((float(t[i]), float(t[j] + dt)))
                i = j + 1
            else:
                i += 1
        out[k] = ev
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", required=True)
    ap.add_argument("--serves", required=True)
    ap.add_argument("--points", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ratio", type=float, default=0.72)
    args = ap.parse_args()

    z = np.load(args.players)
    sv = json.loads(Path(args.serves).read_text())["serves"]
    R = json.loads(Path(args.points).read_text())["rallies"]
    ev = bends(z, args.ratio)
    n_ev = {k: len(v) for k, v in ev.items()}
    print("bend events per player over the whole video:", n_ev)

    # events in the last 1.5 s of each rally and in the pre-serve window that follows the cut
    rows, agree, usable = [], 0, 0
    for k in range(len(R) - 1):
        r = R[k]
        if r["winner"] is None:
            continue
        loser = "B" if r["winner"] == "A" else "A"
        w = sv[k + 1]
        lo, hi = r["end"] - 1.5, w["window_off"] + 0.5
        found = {tm: [] for tm in "AB"}
        for pid, evs in ev.items():
            for a, b in evs:
                if a < hi and b > lo:
                    found[pid[0]].append((pid, round(a, 1), round(b, 1)))
        teams_with = [tm for tm in "AB" if found[tm]]
        side = teams_with[0] if len(teams_with) == 1 else None
        rows.append({"rally": r["rally"], "loser": loser, "bend_team": side, "events": found})
        if side:
            usable += 1
            agree += side == loser
    base = sum(1 for r in rows if r["bend_team"]) / max(1, len(rows))
    p_agree = agree / usable if usable else float("nan")
    # chance level: each team equally likely to be the one that bends -> 50%
    print(f"rallies where exactly one team bends around the cut: {usable} of {len(rows)} ({100 * base:.0f}%)")
    print(f"... and that team is the one that LOST the rally: {agree} of {usable} ({100 * p_agree:.0f}%), chance = 50%")
    from scipy.stats import binomtest
    pv = binomtest(agree, usable, 0.5).pvalue if usable else float("nan")
    print(f"binomial test against chance: p = {pv:.2f}")
    usable_flag = usable >= 12 and p_agree > 0.65 and pv < 0.05
    Path(args.out).write_text(json.dumps({"stage": 9, "ratio": args.ratio, "events_per_player": n_ev, "rows": rows,
                                          "rallies_with_single_bending_team": usable, "agree_with_loser": agree,
                                          "p_value": pv, "usable": bool(usable_flag)}, indent=1))
    print("\nSTAGE 9 " + ("PASSED: bends point at the losing side, pickups are usable." if usable_flag else
                          "NOT USABLE on this video: bends do not identify the losing side reliably."))
    raise SystemExit(0 if usable_flag else 1)


if __name__ == "__main__":
    main()
