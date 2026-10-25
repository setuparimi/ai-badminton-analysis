#!/usr/bin/env python3
"""Stage 3b - PLAYERS.

Turns the candidate boxes from stage 3a into four named player tracks in court metres.
Doubles, so two teams of two:
    team A = A_you + A_partner   <- the user's team
    team B = B_opp1 + B_opp2     <- the opponents
Shirt colours come from players_config.json (see examples/reference-match/players_config.json).
Which half of the court a team is on follows from where a bright "signature" shirt colour is
seen; the teams may swap ends once (found automatically). Inside a team, players are told apart
by shirt colour and by staying close to where they were a moment ago. Gaps up to 0.6 s are
filled and single-frame jumps removed.

Run:
    python stages/s03_players.py --proxy work/proxy.mp4 --cand work/cand.npz \
        --start 48.8 --out work/players.npz [--config work/players_config.json]
    --end-change none --first-near A|B     if no bright colour is available, say so by hand
    --end-change SECONDS --first-near A|B  if you already know when the teams swapped ends

Outputs next to --out: players.npz (tracks), players.json (summary), s03_check.jpg
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from common import NO_CHANGE, SLOTS as IDS, load_config, near_team_at, other, signature, slot_probs

NET_Y = 6.7
COLOURS = {"A_partner": (0, 0, 255), "A_you": (0, 255, 255), "B_opp1": (255, 0, 0), "B_opp2": (0, 200, 0)}
FEATS = ("tL", "t_red", "t_blue", "t_green", "t_yellow", "t_orange")


def load_candidates(path, start, min_conf):
    z = np.load(path)
    D, cols = z["data"], list(z["cols"])
    c = {k: D[:, i] for i, k in enumerate(cols)}
    fps, stride = float(z["fps"]), int(z["stride"])
    t = c["f"] / fps
    X, Y = c["X"], c["Y"]
    far = Y >= NET_Y
    ok = (c["conf"] >= min_conf) & (c["h_per_ppm"] > 1.25) & (c["h_per_ppm"] < 2.5) & (t >= start) \
        & (Y > -2.5) & (Y < 13.8) & np.where(far, (X > -0.3) & (X < 6.4), (X > -1.0) & (X < 7.0))
    return {k: v[ok] for k, v in c.items()}, fps, stride


def dedupe(idxs, c):
    keep = []
    for i in sorted(idxs, key=lambda i: -c["conf"][i]):
        dup = False
        for j in keep:
            if np.hypot(c["X"][i] - c["X"][j], c["Y"][i] - c["Y"][j]) < 0.35:
                ix1, iy1 = max(c["x1"][i], c["x1"][j]), max(c["y1"][i], c["y1"][j])
                ix2, iy2 = min(c["x2"][i], c["x2"][j]), min(c["y2"][i], c["y2"][j])
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                a = (c["x2"][i] - c["x1"][i]) * (c["y2"][i] - c["y1"][i])
                if inter / a > 0.3:
                    dup = True
                    break
        if not dup:
            keep.append(i)
    return keep


def find_end_change(c, fps, start, sig_team, sig_colour):
    """When do the teams swap ends? Looks at where the signature shirt colour (worn by sig_team) is
    seen, far half or near half, over time. Returns (tc, first_near_team, strength); tc is NO_CHANGE
    if the teams never swap."""
    t = c["f"] / fps
    sig = c["t_" + sig_colour] > 0.12
    grid = np.arange(start + 3, t.max() - 3, 1.0)
    s = []
    for g in grid:
        m = (t >= g - 3) & (t < g + 3)
        nr = sig[m & (c["Y"] < NET_Y)].mean() if (m & (c["Y"] < NET_Y)).any() else 0
        fr = sig[m & (c["Y"] >= NET_Y)].mean() if (m & (c["Y"] >= NET_Y)).any() else 0
        s.append(fr - nr)               # > 0: the signature team is on the far half
    s = np.array(s)
    best, tc, sign = 0.0, None, 1
    for i in range(5, len(grid) - 5):   # single change point
        d = s[:i].mean() - s[i:].mean()
        if abs(d) > best:
            best, tc, sign = abs(d), float(grid[i]), (1 if d > 0 else -1)
    if best >= 0.35:
        return tc, (other(sig_team) if sign > 0 else sig_team), best
    return NO_CHANGE, (other(sig_team) if s.mean() > 0 else sig_team), best


def team_prob(cand_i, c, cfg):
    return slot_probs(cfg, {k: c[k][cand_i] for k in FEATS})


def track(c, fps, stride, tc, first_near, start, cfg):
    by_f = {}
    for i in range(len(c["f"])):
        by_f.setdefault(int(c["f"][i]), []).append(i)
    frames = np.arange(int(start * fps) // stride * stride, int(c["f"].max()) + 1, stride)
    n = len(frames)
    pos = {k: np.full((n, 2), np.nan, np.float32) for k in IDS}
    box = {k: np.full((n, 5), np.nan, np.float32) for k in IDS}
    last = {k: None for k in IDS}  # (frame_index_in_array, X, Y)
    for r, f in enumerate(frames):
        t = f / fps
        cands = dedupe(by_f.get(int(f), []), c)
        if not cands:
            continue
        near_team = near_team_at(t, tc, first_near)
        cost = np.full((len(cands), 4), 1e6)
        for a, i in enumerate(cands):
            Y = c["Y"][i]
            p = team_prob(i, c, cfg)
            for b, k in enumerate(IDS):
                team_is_near = (k[0] == near_team)
                if (Y < 6.2 and not team_is_near) or (Y > 7.2 and team_is_near):
                    continue
                move = 0.0
                if last[k] is not None and r - last[k][0] <= 10:
                    d = np.hypot(c["X"][i] - last[k][1], c["Y"][i] - last[k][2])
                    move = 1.2 * min(d / 1.5, 3.0)
                cost[a, b] = -np.log(p[k] + 0.03) + move
        ri, ci = linear_sum_assignment(cost)
        for a, b in zip(ri, ci):
            if cost[a, b] > 4.5:
                continue
            k, i = IDS[b], cands[a]
            pos[k][r] = (c["X"][i], c["Y"][i])
            box[k][r] = (c["x1"][i], c["y1"][i], c["x2"][i], c["y2"][i], c["conf"][i])
            last[k] = (r, c["X"][i], c["Y"][i])
    return frames, pos, box


def clean(pos, max_gap=6, win=7, tol=1.2):
    """Hampel despike, linear gap fill (<= max_gap samples), then a 5-sample median."""
    out, flag = {}, {}
    for k, p in pos.items():
        p = p.copy()
        n = len(p)
        for ax in (0, 1):
            x = p[:, ax]
            for i in range(n):
                if np.isnan(x[i]):
                    continue
                lo, hi = max(0, i - win // 2), min(n, i + win // 2 + 1)
                nb = x[lo:hi][~np.isnan(x[lo:hi])]
                if len(nb) >= 3 and abs(x[i] - np.median(nb)) > tol:
                    p[i, :] = np.nan
        raw_valid = ~np.isnan(p[:, 0])
        f = np.zeros(n, np.int8)                 # 0 missing, 1 detected, 2 interpolated
        f[raw_valid] = 1
        idx = np.where(raw_valid)[0]
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= max_gap + 1:
                for ax in (0, 1):
                    p[a + 1:b, ax] = np.linspace(p[a, ax], p[b, ax], b - a + 1)[1:-1]
                f[a + 1:b] = 2
        sm = p.copy()
        for ax in (0, 1):
            for i in range(n):
                lo, hi = max(0, i - 2), min(n, i + 3)
                v = p[lo:hi, ax][~np.isnan(p[lo:hi, ax])]
                if len(v) >= 3 and not np.isnan(p[i, ax]):
                    sm[i, ax] = np.median(v)
        out[k], flag[k] = sm, f
    return out, flag


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--cand", required=True)
    ap.add_argument("--start", type=float, required=True, help="second the real game starts (skip any teaser)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-conf", type=float, default=0.25)
    ap.add_argument("--config", help="players_config.json (default: next to --out)")
    ap.add_argument("--end-change", default="auto", help="auto, none, or the second the teams swapped ends")
    ap.add_argument("--first-near", choices=["A", "B"], help="team on the near half at the start (needed with --end-change none or a number)")
    args = ap.parse_args()

    cfg = load_config(args.config or Path(args.out).with_name("players_config.json"))
    c, fps, stride = load_candidates(args.cand, args.start, args.min_conf)
    sig = signature(cfg)
    strength = float("nan")
    if args.end_change == "auto":
        if sig is None:
            raise SystemExit("No shirt in players_config.json has a bright colour (red, blue, green, yellow, orange), so the "
                             "end change cannot be found automatically. Pass --end-change none (or SECONDS) and --first-near A|B.")
        tc, first_near, strength = find_end_change(c, fps, args.start, *sig)
        what = "never (teams stay on their halves)" if tc == NO_CHANGE else f"t = {tc:.0f} s"
        print(f"end change: {what}; team {first_near} starts on the near half (signature {sig[1]} of team {sig[0]}, separation {strength:.2f})")
    else:
        if not args.first_near:
            raise SystemExit("--first-near A|B is needed together with --end-change none or SECONDS")
        tc = NO_CHANGE if args.end_change == "none" else float(args.end_change)
        first_near = args.first_near
        print(f"end change given by hand: {args.end_change}; team {first_near} starts on the near half")
    frames, pos_raw, box = track(c, fps, stride, tc, first_near, args.start, cfg)
    pos, flag = clean(pos_raw)
    t = frames / fps

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save = {"frames": frames, "t": t, "fps": fps, "stride": stride, "tc": tc, "first_near": np.array(first_near)}
    for k in IDS:
        save[f"{k}_xy"], save[f"{k}_flag"], save[f"{k}_box"] = pos[k], flag[k], box[k]
    np.savez_compressed(out, **save)

    cov = {k: float((flag[k] > 0).mean()) for k in IDS}
    det = {k: float((flag[k] == 1).mean()) for k in IDS}
    speeds = {}
    for k in IDS:
        v = np.linalg.norm(np.diff(pos[k], axis=0), axis=1) / (stride / fps)
        v = v[~np.isnan(v)]
        speeds[k] = (float(np.median(v)), float(np.percentile(v, 99)), float((v > 9).mean()))
    summ = {"tc": tc, "first_near": first_near, "start": args.start, "coverage": cov, "detected_only": det,
            "speed_median_p99_over9": speeds}
    out.with_suffix(".json").write_text(json.dumps(summ, indent=1))

    # annotated check frames: 6 moments spread over the game
    cap = cv2.VideoCapture(args.proxy)
    picks = np.linspace(len(frames) * 0.05, len(frames) * 0.95, 6).astype(int)
    tiles = []
    for r in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frames[r]))
        ok, img = cap.read()
        for k in IDS:
            if flag[k][r] and not np.isnan(box[k][r][0]):
                x1, y1, x2, y2, _ = box[k][r]
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), COLOURS[k], 3)
                cv2.putText(img, k, (int(x1), max(18, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLOURS[k], 2, cv2.LINE_AA)
        cv2.putText(img, f"t={t[r]:.1f}s", (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
    cap.release()
    cv2.imwrite(str(out.with_name("s03_check.jpg")),
                np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:])]), [cv2.IMWRITE_JPEG_QUALITY, 92])

    print("\nper player: frames with a position (detected + filled) | detected only | median speed m/s | 99th pct | share > 9 m/s")
    for k in IDS:
        print(f"  {k:8s} {100 * cov[k]:5.1f}% | {100 * det[k]:5.1f}% | {speeds[k][0]:.2f} | {speeds[k][1]:.2f} | {100 * speeds[k][2]:.2f}%")
    print(f"\ntracks : {out}\nsummary: {out.with_suffix('.json')}\nsheet  : {out.with_name('s03_check.jpg')}  <- every label must sit on the right person")
    ok = all(cov[k] > 0.6 for k in IDS) and all(speeds[k][2] < 0.01 for k in IDS) and (tc == NO_CHANGE or strength >= 0.35 or args.end_change != "auto")
    print("\nSTAGE 3 " + ("PASSED (automatic checks); now do the visual check." if ok else "FAILED: see numbers above."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
