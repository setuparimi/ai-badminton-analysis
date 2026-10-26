#!/usr/bin/env python3
"""Stage 7b - OPPONENTS (scouting numbers).

What the video can say about the other team, from their own point of view:
    results     how they did serving and receiving, by rally length, per server, their longest run
    players     per opponent: distance, speed, where they stood (net / mid / back), who plays the net
                side of the pair, racket hand and knee bend (near-camera frames only)
    pair        how the pair stood (front-back, side by side, stacked, crowded, open gap), in rallies
                they won versus lost
    zones       how much of their half was covered: the court split in 3 x 3, the share of time at
                least one of them stood within 1.5 m of each zone's centre

What it cannot say: shot types, where the shuttle went, or who made the error. There is no shuttle
tracking, so everything here is about results, tempo and positions. A "weak zone" is a place they
rarely stood, not a place where they lost points.

Positions are rougher on the far half of the court (about 18 pixels per metre) and depth there is
squeezed towards the net, so depth, role and zone numbers use only the rallies where the opponents were
on the NEAR half (if there are at least --min-near of them; otherwise every rally, and the file says so).

Run:
    python stages/s07b_opponents.py --work work
Reads  points.json, motion.json, players.npz and, if present, pose_stats.json and players_config.json.
Writes opponents.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import stats

from common import NET_Y, TEAM_WIDTH, load_config, own_half_coords

OPP = ("B_opp1", "B_opp2")
BUCKETS = [("under 6 s", 0, 6), ("6 to 10 s", 6, 10), ("over 10 s", 10, 99)]
LATERAL = ("left", "centre", "right")
DEPTH = ("front", "mid", "back")
ZONE_CENTRES = {(i, j): ((2 * i + 1) * TEAM_WIDTH / 6, c) for i in range(3) for j, c in enumerate((1.25, 3.5, 5.6))}
COVER_M = 1.5
PAIR_KEYS = ("open_gap_mean", "crowded", "stacked", "front_back", "side_by_side")


def fisher_p(a_won, a_n, b_won, b_n):
    if not a_n or not b_n:
        return None
    return float(stats.fisher_exact([[a_won, a_n - a_won], [b_won, b_n - b_won]])[1])


def streak(decided, team):
    best, cur, start, best_start = 0, 0, None, None
    for p in decided:
        if p["winner"] == team:
            cur += 1
            start = p if cur == 1 else start
            if cur > best:
                best, best_start = cur, start
        else:
            cur = 0
    return {"length": best, "rally": best_start["rally"] if best_start else None, "start": best_start["start"] if best_start else None}


def results(points):
    """The opponents' results. `points` are the rally dicts from points.json (last one has no winner)."""
    D = [p for p in points if p["winner"]]
    won = lambda rows: [sum(r["winner"] == "B" for r in rows), len(rows)]
    serving = won([p for p in D if p["server_team"] == "B"])
    receiving = won([p for p in D if p["server_team"] == "A"])
    out = {"decided": len(D), "serving": serving, "receiving": receiving,
           "serve_vs_receive_p": fisher_p(*serving, *receiving),
           "by_server": {k: won([p for p in D if p["server_player"] == k]) for k in OPP},
           "server_unknown": sum(1 for p in D if p["server_player"] is None),
           "by_length": [{"bucket": name, "n": len(rows), "won": sum(r["winner"] == "B" for r in rows)}
                         for name, lo, hi in BUCKETS for rows in [[p for p in D if lo <= p["duration"] < hi]]],
           "longest_run": streak(D, "B")}
    short, long_ = out["by_length"][0], out["by_length"][1:]
    ln, lw = sum(b["n"] for b in long_), sum(b["won"] for b in long_)
    out["short_vs_long"] = {"short": [short["won"], short["n"]], "longer": [lw, ln], "p": fisher_p(short["won"], short["n"], lw, ln)}
    quarters = np.array_split(np.arange(len(D)), 4) if len(D) >= 8 else []
    out["quarters"] = [{"rallies": f"{D[i[0]]['rally']}-{D[i[-1]]['rally']}", "won": sum(D[j]["winner"] == "B" for j in i), "n": len(i)} for i in quarters]
    return out


def pick_rows(rows, min_near):
    """Rallies used for depth-based numbers: those where the opponents were on the near half, if there are enough."""
    near = [r for r in rows if not r["A_is_near"]]
    return (near, "near") if len(near) >= min_near else (rows, "all")


def players_block(rows, used, pose):
    out = {}
    nearest_net = {k: 0 for k in OPP}
    both = 0
    for r in used:
        a, b = (r["players"][k] for k in OPP)
        if "mean_depth" in a and "mean_depth" in b:
            both += 1
            nearest_net[OPP[0] if a["mean_depth"] < b["mean_depth"] else OPP[1]] += 1
    for k in OPP:
        have = [r["players"][k] for r in rows if "distance_m" in r["players"][k]]
        use = [r["players"][k] for r in used if "distance_m" in r["players"][k]]
        mean = lambda v, key: float(np.mean([x[key] for x in v])) if v else None
        rec = {"rallies": len(have), "rallies_used_for_depth": len(use),
               "distance_per_rally": mean(have, "distance_m"), "total_distance": float(sum(x["distance_m"] for x in have)),
               "mean_speed": mean(have, "mean_speed"), "peak_speed": mean(have, "peak_speed"),
               "front": mean(use, "front"), "mid": mean(use, "mid"), "back": mean(use, "back"), "mean_depth": mean(use, "mean_depth"),
               "mean_lateral_from_centre": mean(use, "mean_lateral_from_centre"),
               "net_side_share": nearest_net[k] / both if both else None}
        s = (pose or {}).get(k)
        if s:
            over = s["overhead_left"] + s["overhead_right"]
            near = (s.get("by_side") or {}).get("near") or {}
            rec["pose"] = {"racket_arm": s["racket_arm"], "overhead_left": s["overhead_left"], "overhead_right": s["overhead_right"],
                           "racket_arm_clear": bool(over >= 6 and max(s["overhead_left"], s["overhead_right"]) / over >= 0.7),
                           "samples": s["samples"], "knee_median": near.get("knee_median", s["knee_median"]),
                           "bent_lt150": near.get("bent_lt150", s["bent_lt150"]), "racket_up_share": near.get("racket_up_share", s["racket_up_share"])}
        out[k] = rec
    return out, {"rallies_with_both": both}


def pair_block(rows, used):
    """The opponents' pair shape, overall and in rallies they won versus lost. Uses `used` for the overall mean."""
    def col(rs, key, winner=None):
        return np.array([r["pair_B"][key] for r in rs if r["pair_B"] and (winner is None or r["winner"] == winner)], float)
    out = {"overall": {k: float(col(used, k).mean()) for k in PAIR_KEYS if len(col(used, k))}, "won_vs_lost": {}, "rallies_used": len(used)}
    for k in PAIR_KEYS:
        w, l = col(rows, k, "B"), col(rows, k, "A")
        p = float(stats.mannwhitneyu(w, l).pvalue) if len(w) > 3 and len(l) > 3 else None
        out["won_vs_lost"][k] = {"won": float(w.mean()) if len(w) else None, "lost": float(l.mean()) if len(l) else None, "p": p,
                                 "n_won": len(w), "n_lost": len(l)}
    out["n_comparisons"] = len(PAIR_KEYS)
    return out


def zone_block(z, used):
    """Occupancy of a 3 x 3 split of the opponents' half, and how much of each zone they cover together."""
    t = z["t"]
    occ = {k: np.zeros((3, 3)) for k in OPP}
    cover = np.zeros((3, 3))
    n_pair, n_player = 0, {k: 0 for k in OPP}
    for r in used:
        m = (t >= r["start"] + 0.3) & (t < r["end"] - 0.3)
        P = {k: own_half_coords(z[f"{k}_xy"][m], not r["A_is_near"]) for k in OPP}
        for k in OPP:
            u, d = P[k]
            ok = ~np.isnan(u)
            for ui, di in zip(u[ok], d[ok]):
                occ[k][min(2, int(ui / (TEAM_WIDTH / 3))), 0 if di <= 2.5 else 1 if di <= 4.5 else 2] += 1
            n_player[k] += int(ok.sum())
        both = ~np.isnan(P[OPP[0]][0]) & ~np.isnan(P[OPP[1]][0])
        n_pair += int(both.sum())
        for (i, j), (cu, cd) in ZONE_CENTRES.items():
            near_any = np.zeros(both.sum(), bool)
            for k in OPP:
                u, d = P[k]
                near_any |= np.hypot(u[both] - cu, d[both] - cd) <= COVER_M
            cover[i, j] += near_any.sum()
    names = {(i, j): f"{DEPTH[j]} {LATERAL[i]}" for i in range(3) for j in range(3)}
    share = {names[ij]: float(cover[ij] / n_pair) if n_pair else None for ij in names}
    ranked = sorted((v, n) for n, v in share.items() if v is not None)
    return {"samples_pair": n_pair, "within_m": COVER_M,
            "occupancy": {k: {names[(i, j)]: float(occ[k][i, j] / max(n_player[k], 1)) for i in range(3) for j in range(3)} for k in OPP},
            "coverage": share, "least_covered": [{"zone": n, "share": v} for v, n in ranked[:2]],
            "most_covered": [{"zone": n, "share": v} for v, n in ranked[::-1][:2]]}


def scout(points, motion, pose=None, z=None, min_near=10):
    rows = motion["rallies"]
    used, which = pick_rows(rows, min_near)
    players, extra = players_block(rows, used, pose)
    out = {"stage": "7b", "rallies_compared": len(rows), "depth_numbers_from": which, "rallies_used_for_depth": len(used),
           "results": results(points), "players": players, "role": extra, "pair": pair_block(rows, used)}
    if z is not None:
        out["zones"] = zone_block(z, used)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--min-near", type=int, default=10, help="fewest near-half rallies to use only those for depth numbers (default %(default)s)")
    args = ap.parse_args()
    W = Path(args.work)
    P = json.loads((W / "points.json").read_text())["rallies"]
    M = json.loads((W / "motion.json").read_text())
    pose = json.loads((W / "pose_stats.json").read_text())["stats"] if (W / "pose_stats.json").exists() else None
    z = dict(np.load(W / "players.npz")) if (W / "players.npz").exists() else None
    out = scout(P, M, pose, z, args.min_near)
    cfg_path = W / "players_config.json"
    if cfg_path.exists():
        cfg = load_config(cfg_path)
        for k in OPP:
            out["players"][k]["describe"] = cfg[k]["describe"]
    (W / "opponents.json").write_text(json.dumps(out, indent=1, default=float))

    r = out["results"]
    pc = lambda a: f"{a[0]} of {a[1]} ({100 * a[0] / a[1]:.0f}%)" if a[1] else "n/a"
    print(f"opponents: {r['decided']} decided rallies; depth numbers from {out['rallies_used_for_depth']} rallies ({out['depth_numbers_from']} half)")
    print(f"  they won {pc(r['serving'])} when serving, {pc(r['receiving'])} when receiving (p = {r['serve_vs_receive_p']:.2f})")
    for b in r["by_length"]:
        print(f"  rallies {b['bucket']:10s}: they won {pc([b['won'], b['n']])}")
    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    for k in OPP:
        q = out["players"][k]
        print(f"  {k}: {q['distance_per_rally']:.1f} m/rally, {q['mean_speed']:.2f} m/s, front/mid/back {pct(q['front'])}/{pct(q['mid'])}/{pct(q['back'])}, "
              f"net side in {pct(q['net_side_share'])} of rallies, served {pc(r['by_server'][k])}")
    for key, v in out["pair"]["won_vs_lost"].items():
        if v["p"] is not None:
            print(f"  pair {key:14s} won {v['won']:.2f} lost {v['lost']:.2f} p = {v['p']:.2f}")
    if "zones" in out:
        print("  least covered:", ", ".join(f"{x['zone']} {x['share']:.0%}" for x in out["zones"]["least_covered"]))
    ok = all(out["players"][k]["rallies"] >= 10 for k in OPP)
    print(f"\nopponents: {W / 'opponents.json'}")
    print("STAGE 7b " + ("PASSED (automatic checks)." if ok else "FAILED: fewer than 10 rallies with both opponents tracked."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
