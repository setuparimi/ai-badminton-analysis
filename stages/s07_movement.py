#!/usr/bin/env python3
"""Stage 7 - MOVEMENT.

Per rally and per player: distance run, speed, how much time is spent near the net / mid /
at the back, and for doubles how the pair covers its half (formation, shared lane, open gap).
Then compares the user (A_you) between rallies the team won and lost.

All distances are court metres from the stage 2 homography. The far half of the court has
only ~18 pixels per metre, so far-side numbers are rougher than near-side ones (reported).

Definitions (own half, d = distance from the net):
    front  d <= 2.5 m     mid 2.5 < d <= 4.5 m     back d > 4.5 m
    open gap     widest stretch of the half's width (6.1 m) with nobody in it, from the two partners' X
    stacked      both partners on the same side of the centre line and within 1.5 m sideways
    crowded      partners closer than 1.5 m (any direction)

Run:
    python stages/s07_movement.py --players work/players.npz --points work/points.json --out work/motion.json
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats
from scipy.ndimage import gaussian_filter

from common import SLOTS as IDS, near_team_at

NET, W = 6.7, 6.1
PARTNER = {"A_partner": "A_you", "A_you": "A_partner", "B_opp1": "B_opp2", "B_opp2": "B_opp1"}


def own_frame(team_is_near, X, Y):
    """canonical coordinates: u across (own left->right), v distance from the net"""
    return (X if team_is_near else W - X), np.abs(Y - NET)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", required=True)
    ap.add_argument("--points", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    z = np.load(args.players)
    t, tc, dt = z["t"], float(z["tc"]), float(z["stride"]) / float(z["fps"])
    first_near = str(z["first_near"])
    xy = {k: z[f"{k}_xy"] for k in IDS}
    R = json.loads(Path(args.points).read_text())["rallies"][:-1]       # drop the last rally (post-game motion)

    rows = []
    for p in R:
        a, b = p["start"] + 0.3, p["end"] - 0.3
        m = (t >= a) & (t < b)
        if m.sum() < 25:
            continue
        near_A = near_team_at((a + b) / 2, tc, first_near) == "A"
        rec = {"rally": p["rally"], "start": p["start"], "end": p["end"], "winner": p["winner"],
               "user_team_won": p["user_team_won"], "server_team": p["server_team"],
               "A_is_near": bool(near_A), "players": {}}
        for k in IDS:
            P = xy[k][m]
            ok = ~np.isnan(P[:, 0])
            cov = float(ok.mean())
            r = {"coverage": round(cov, 2)}
            if cov >= 0.6:
                step = np.linalg.norm(np.diff(P, axis=0), axis=1)
                valid = ~np.isnan(step)
                v = step[valid] / dt
                v = v[v < 9]
                dist = float(np.nansum(step[valid][step[valid] / dt < 9]))
                frac = max(valid.mean(), 0.3)
                is_near = (k[0] == "A") == near_A
                u, d = own_frame(is_near, P[ok, 0], P[ok, 1])
                r.update({"distance_m": round(dist / frac, 1), "mean_speed": round(float(v.mean()), 2),
                          "peak_speed": round(float(np.percentile(v, 95)), 2),
                          "front": round(float((d <= 2.5).mean()), 3), "mid": round(float(((d > 2.5) & (d <= 4.5)).mean()), 3),
                          "back": round(float((d > 4.5).mean()), 3), "mean_depth": round(float(d.mean()), 2),
                          "mean_lateral_from_centre": round(float(np.abs(u - W / 2).mean()), 2),
                          "side": "near" if is_near else "far"})
            rec["players"][k] = r
        # pair metrics per team
        for team, (i, j) in (("A", ("A_partner", "A_you")), ("B", ("B_opp1", "B_opp2"))):
            P, Q = xy[i][m], xy[j][m]
            ok = ~np.isnan(P[:, 0]) & ~np.isnan(Q[:, 0])
            if ok.sum() < 15:
                rec[f"pair_{team}"] = None
                continue
            P, Q = P[ok], Q[ok]
            xs = np.sort(np.stack([P[:, 0], Q[:, 0]], 1), axis=1)
            gap = np.max(np.stack([xs[:, 0], xs[:, 1] - xs[:, 0], W - xs[:, 1]], 1), axis=1)
            dx, dy = np.abs(P[:, 0] - Q[:, 0]), np.abs(P[:, 1] - Q[:, 1])
            same_side = (P[:, 0] - W / 2) * (Q[:, 0] - W / 2) > 0
            rec[f"pair_{team}"] = {"open_gap_mean": round(float(gap.mean()), 2), "open_gap_over3m": round(float((gap > 3.0).mean()), 3),
                                   "stacked": round(float((same_side & (dx < 1.5)).mean()), 3),
                                   "crowded": round(float((np.hypot(dx, dy) < 1.5).mean()), 3),
                                   "front_back": round(float(((dy >= 2.0) & (dx < 2.0)).mean()), 3),
                                   "side_by_side": round(float(((dx >= 2.0) & (dy < 2.0)).mean()), 3)}
        rows.append(rec)

    # --- you (A_you) won vs lost
    def collect(player, key, won, side=None):
        vals = []
        for r in rows:
            if r["user_team_won"] is None or r["user_team_won"] != won:
                continue
            q = r["players"][player]
            if key in q and (side is None or q["side"] == side):
                vals.append(q[key])
        return np.array(vals, float)

    def collect_pair(key, won):
        return np.array([r["pair_A"][key] for r in rows if r["user_team_won"] is not None and r["user_team_won"] == won and r["pair_A"]], float)

    metrics = [("distance_m", "distance per rally (m)"), ("mean_speed", "mean speed (m/s)"), ("peak_speed", "peak speed, 95th pct (m/s)"),
               ("front", "share of time at the net (<=2.5 m)"), ("mid", "share mid-court"), ("back", "share at the back (>4.5 m)"),
               ("mean_depth", "mean distance from net (m)")]
    pair_metrics = [("open_gap_mean", "open gap in your half (m)"), ("open_gap_over3m", "share of time gap > 3 m"),
                    ("stacked", "share of time stacked on one side"), ("crowded", "share of time within 1.5 m of partner"),
                    ("front_back", "share of time in front-back"), ("side_by_side", "share of time side-by-side")]
    summary = {"you": {}, "partner": {}, "pair": {}}
    print(f"{'YOU (A_you)':38s} {'won':>9s} {'lost':>9s}   p (Mann-Whitney)   n won/lost")
    for key, label in metrics:
        w, l = collect("A_you", key, True), collect("A_you", key, False)
        pv = stats.mannwhitneyu(w, l).pvalue if len(w) > 3 and len(l) > 3 else np.nan
        summary["you"][key] = {"won": float(w.mean()), "lost": float(l.mean()), "p": float(pv), "n_won": len(w), "n_lost": len(l)}
        print(f"  {label:36s} {w.mean():9.2f} {l.mean():9.2f}   {pv:8.3f}          {len(w)}/{len(l)}")
    print(f"{'YOUR PAIR (red + white)':38s}")
    for key, label in pair_metrics:
        w, l = collect_pair(key, True), collect_pair(key, False)
        pv = stats.mannwhitneyu(w, l).pvalue if len(w) > 3 and len(l) > 3 else np.nan
        summary["pair"][key] = {"won": float(w.mean()), "lost": float(l.mean()), "p": float(pv), "n_won": len(w), "n_lost": len(l)}
        print(f"  {label:36s} {w.mean():9.2f} {l.mean():9.2f}   {pv:8.3f}          {len(w)}/{len(l)}")
    for key, label in metrics[:3]:
        w, l = collect("A_partner", key, True), collect("A_partner", key, False)
        summary["partner"][key] = {"won": float(w.mean()), "lost": float(l.mean()), "n_won": len(w), "n_lost": len(l)}

    # accuracy caveat: near vs far for the user
    cov_near = [r["players"]["A_you"]["coverage"] for r in rows if r["A_is_near"]]
    cov_far = [r["players"]["A_you"]["coverage"] for r in rows if not r["A_is_near"]]
    print(f"\nyour tracking coverage per rally: near half {np.mean(cov_near):.2f}, far half {np.mean(cov_far):.2f}")

    # per-player totals
    tot = {}
    for k in IDS:
        d = [r["players"][k].get("distance_m") for r in rows if "distance_m" in r["players"][k]]
        s = [r["players"][k].get("mean_speed") for r in rows if "mean_speed" in r["players"][k]]
        tot[k] = {"rallies_used": len(d), "distance_per_rally": float(np.mean(d)), "total_distance_m": float(np.sum(d)), "mean_speed": float(np.mean(s))}
        print(f"  {k:8s} rallies {len(d):2d}  distance/rally {np.mean(d):5.1f} m  total {np.sum(d):6.0f} m  mean speed {np.mean(s):.2f} m/s")

    # heatmaps in own-half coordinates, you and your partner, won vs lost
    fig, axes = plt.subplots(2, 2, figsize=(9, 9))
    for ci, won in enumerate((True, False)):
        for ri, k in enumerate(("A_you", "A_partner")):
            H = np.zeros((int(W / 0.25) + 1, int(NET / 0.25) + 1))
            for r in rows:
                if r["user_team_won"] != won:
                    continue
                m = (t >= r["start"] + 0.3) & (t < r["end"] - 0.3)
                P = xy[k][m]
                P = P[~np.isnan(P[:, 0])]
                if not len(P):
                    continue
                u, d = own_frame(r["players"][k]["side"] == "near" if "side" in r["players"][k] else True, P[:, 0], P[:, 1])
                for uu, dd in zip(u, d):
                    iu, iv = int(np.clip(uu / 0.25, 0, H.shape[0] - 1)), int(np.clip(dd / 0.25, 0, H.shape[1] - 1))
                    H[iu, iv] += 1
            H = gaussian_filter(H, 1.2)
            ax = axes[ri][ci]
            ax.imshow((H / H.sum()).T, origin="upper", extent=[0, W, NET, 0], cmap="inferno", aspect="equal")
            ax.axhline(0, color="white", lw=3)                        # net at the top
            ax.axhline(1.98, color="white", lw=0.6); ax.axvline(W / 2, color="white", lw=0.6)
            ax.set_title(f"{'YOU' if k == 'A_you' else 'YOUR PARTNER'} - {'WON' if won else 'LOST'} rallies", fontsize=10)
            ax.set_xlabel("across your half, your left -> right (m)"); ax.set_ylabel("distance from the net (m)")
    fig.suptitle("Where you stood (net at top)", fontsize=12)
    fig.tight_layout()
    heat = Path(args.out).with_name("s07_heatmaps.png")
    fig.savefig(heat, dpi=110)

    Path(args.out).write_text(json.dumps({"stage": 7, "rallies": rows, "summary": summary, "totals": tot}, indent=1))
    ok = len(rows) >= 10 and 0.3 < tot["A_you"]["mean_speed"] < 3.0
    if len(rows) < 30:
        print(f"NOTE: only {len(rows)} rallies compared; small differences cannot be detected with so few.")
    print(f"\nmotion : {args.out}\nheatmap: {heat}")
    print("STAGE 7 " + ("PASSED (automatic checks)." if ok else "FAILED: see numbers above."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
