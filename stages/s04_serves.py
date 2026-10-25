#!/usr/bin/env python3
"""Stage 4 - SERVES.

For every rally, finds the pre-serve window (the first quiet window found by s03_find_start.py for rally 1,
the score overlay for every later rally), measures where the four players stand in it, and works out
WHICH TEAM SERVES and from which court.

The scoreboard gives the server's score first but not which team that is. What the video
adds (see the checks printed below):
  * the server's score parity says which service court is used (even = right), and the
    receiver stands in the diagonal court. Seen in 70% of windows, versus 38% for the wrong parity.
  * between two non-tied scores the numbers tell whether the SAME team serves again, so the
    rallies form independent chains broken only at tied scores.
  * inside a chain, the team whose two players stand further apart sideways is the RECEIVING
    team (receivers keep their lanes, the server swaps courts with the partner); the compact
    team serves. A majority vote in each chain gives the serving team for every rally in it.
    (Other players may stand the other way round: --flip-cue reverses the rule. Stage 5's same-player
    test says which setting is right.)

Run:
    python stages/s04_serves.py --players work/players.npz --overlay work/overlay.json \
        --game-start work/game_start.json --out work/serves.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common import SLOTS as IDS, TEAMS, near_team_at

NET = 6.7


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", required=True)
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--game-start", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--flip-cue", action="store_true",
                    help="use if stage 5 shows the same-player test passing only for the OPPOSITE direction")
    args = ap.parse_args()
    flip = -1.0 if args.flip_cue else 1.0

    z = np.load(args.players)
    t, tc, first_near = z["t"], float(z["tc"]), str(z["first_near"])
    ov = json.loads(Path(args.overlay).read_text())["runs"]
    gs = json.loads(Path(args.game_start).read_text())
    first_on, first_off = gs.get("first_window_on", gs.get("love_all_on")), gs.get("first_window_off", gs.get("love_all_off"))
    wins = [dict(on=first_on, off=first_off, s=0, r=0, src="first serve window")]
    wins += [dict(on=r["t_on"], off=r["t_off"], s=r["first"], r=r["second"], src=f"overlay {r['j']}") for r in ov]
    n = len(wins)

    def near_team(tm):
        return near_team_at(tm, tc, first_near)

    # 1. where does everybody stand in each window
    for w in wins:
        m = (t >= w["on"] + 0.5) & (t <= w["off"] - 0.2)
        w["pos"] = {}
        for k in IDS:
            xy = z[f"{k}_xy"][m]
            xy = xy[~np.isnan(xy[:, 0])]
            w["pos"][k] = np.median(xy, axis=0).tolist() if len(xy) >= 3 else None
        w["near"] = near_team((w["on"] + w["off"]) / 2)
        w["far"] = "A" if w["near"] == "B" else "B"
        pn = [w["pos"][k] for k in TEAMS[w["near"]] if w["pos"][k]]
        pf = [w["pos"][k] for k in TEAMS[w["far"]] if w["pos"][k]]
        sx = lambda p: abs(p[0][0] - p[1][0]) if len(p) == 2 else np.nan
        sy = lambda p: abs(p[0][1] - p[1][1]) if len(p) == 2 else np.nan
        w["spreadX"] = float(sx(pn) - sx(pf))      # near minus far, metres
        w["spreadY"] = float(sy(pn) - sy(pf))
        even = (w["s"] % 2 == 0)
        # diagonal service quadrants for the server's parity: near X>3.05 pairs with far X<3.05 when even
        qn = [q for q in pn if (q[0] > 3.05) == even]
        qf = [q for q in pf if (q[0] < 3.05) == even]
        w["diag_ok"] = bool(qn and qf)
        qn2 = [q for q in pn if (q[0] > 3.05) != even]
        qf2 = [q for q in pf if (q[0] < 3.05) != even]
        w["diag_ok_wrong_parity"] = bool(qn2 and qf2)

    # 2. relations between consecutive rallies from the scoreboard
    rel = [0] * n
    for k in range(n - 1):
        s, r, s2, r2 = wins[k]["s"], wins[k]["r"], wins[k + 1]["s"], wins[k + 1]["r"]
        if s == r:
            rel[k] = 0                               # tie: numbers cannot say
        elif (s2, r2) == (s + 1, r):
            rel[k] = +1                              # server won again
        elif (s2, r2) == (r + 1, s):
            rel[k] = -1                              # receiver won, serve changes
        else:
            raise SystemExit(f"illegal score step before rally {k + 2}: {(s, r)} -> {(s2, r2)}")
    chains, cur = [], [0]
    for k in range(n - 1):
        if rel[k] == 0:
            chains.append(cur); cur = [k + 1]
        else:
            cur.append(k + 1)
    chains.append(cur)

    # 3. per-chain vote. x_k = +1 means team A serves rally k, -1 means team B. The scoreboard says whether the
    #    SAME team serves again (rel), so inside a chain x_k = x_first * (product of rel). The cue at each
    #    window votes for "near team serves" / "far team serves", which is turned into a vote for A or B
    #    using who is on the near half at that moment (the teams swap ends once).
    x = [None] * n
    chain_info = []
    for ch in chains:
        lab = [1]
        for k in ch[:-1]:
            lab.append(lab[-1] * rel[k])
        V = 0.0
        used = 0
        for k, lb in zip(ch, lab):
            cue_near = 0.0
            sx_, sy_ = wins[k]["spreadX"], wins[k]["spreadY"]
            if not np.isnan(sx_) and abs(sx_) > 0.3:
                cue_near += -np.sign(sx_)            # near wider -> near receives
            if not np.isnan(sy_) and abs(sy_) > 0.5:
                cue_near += 0.5 * np.sign(sy_)       # serving team stands more front/back
            if cue_near:
                used += 1
            cue_near *= flip
            cue_A = cue_near if wins[k]["near"] == "A" else -cue_near
            V += cue_A * lb
        bit = int(np.sign(V)) if V != 0 else 0
        conf = abs(V) / max(1.0, 1.5 * len(ch))
        for k, lb in zip(ch, lab):
            x[k] = bit * lb if bit else None
        chain_info.append({"rallies": [ch[0] + 1, ch[-1] + 1], "n": len(ch), "vote": float(V), "used": used,
                           "confidence": round(conf, 2), "decided": bool(bit)})
    server_near = [None if x[k] is None else (1 if (("A" if x[k] > 0 else "B") == wins[k]["near"]) else -1) for k in range(n)]

    serves = []
    for k, w in enumerate(wins):
        sn = server_near[k]
        team = None if sn is None else (w["near"] if sn > 0 else w["far"])
        server_player = None
        if team:
            even = (w["s"] % 2 == 0)
            is_near_side = team == w["near"]
            cands = []
            for idn in TEAMS[team]:
                p = w["pos"][idn]
                if p and ((p[0] > 3.05) == even if is_near_side else (p[0] < 3.05) == even):
                    cands.append((abs(p[1] - NET), idn))
            if cands:
                server_player = min(cands)[1]
        serves.append({"rally": k + 1, "window_on": w["on"], "window_off": w["off"], "source": w["src"],
                       "server_score": w["s"], "receiver_score": w["r"],
                       "court": "right" if w["s"] % 2 == 0 else "left",
                       "near_team": w["near"], "server_team": team, "server_side": None if sn is None else ("near" if sn > 0 else "far"),
                       "server_player": server_player,
                       "spreadX_near_minus_far": None if np.isnan(w["spreadX"]) else round(w["spreadX"], 2),
                       "spreadY_near_minus_far": None if np.isnan(w["spreadY"]) else round(w["spreadY"], 2),
                       "diag_quadrants_occupied": w["diag_ok"], "positions": w["pos"]})
    Path(args.out).write_text(json.dumps({"stage": 4, "tc": tc, "first_near": first_near, "chains": chain_info, "serves": serves}, indent=1))

    ok_c = np.mean([w["diag_ok"] for w in wins]); ok_w = np.mean([w["diag_ok_wrong_parity"] for w in wins])
    decided = sum(s["server_team"] is not None for s in serves)
    print(f"serve windows            : {n}  (rally 1 = the first quiet window, then {n - 1} score overlays)")
    print(f"diagonal court check     : correct parity {100 * ok_c:.0f}% vs wrong parity {100 * ok_w:.0f}% of windows")
    print(f"chains between ties      : sizes {[c['n'] for c in chain_info]}")
    print(f"server team decided for  : {decided} of {n} rallies")
    for c in chain_info:
        print(f"   rallies {c['rallies'][0]:2d}-{c['rallies'][1]:2d}  vote {c['vote']:+5.1f}  confidence {c['confidence']:.2f}  {'' if c['decided'] else 'UNDECIDED'}")
    first = serves[0]
    print(f"rally 1 server           : team {first['server_team']} ({'near' if first['server_side']=='near' else 'far'} side)  [inference]")
    print(f"serves.json              : {args.out}")
    ok = ok_c > ok_w + 0.15 and decided >= n - 3
    print("\nSTAGE 4 " + ("PASSED (automatic checks)." if ok else "FAILED: see numbers above."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
