#!/usr/bin/env python3
"""Stage 7f - POSITIONS AND MOVEMENT WITHOUT A SCORE.

For a video with no scoreboard (see stage 6f): what each player did while the shuttle was in play, from the stage 3 tracks alone.
All positions are turned into "your own half" coordinates first: u = metres across (the team's left to right), d = metres
from the net. Then, over the play windows of one game:
  - per player: distance, speed, bursts, share of time in the front / middle / back court and in the left / middle / right, heat map;
  - per team: how the pair stands (side by side = like depth, front and back = one clearly deeper), the gap between partners,
    who takes the back when they stand front and back, how often that swaps, how far back the pair sits;
  - how hard each player worked over the game (distance per minute of play in 2-minute blocks);
  - how long the plays and the pauses were.
Nothing here knows who won a point, what shot was played or where the shuttle went.

The pair on the far side of the court is seen small, so their depth (d) is less exact than their width (u) and their distance
covered runs a little high from jitter; `accuracy` in the output says which side each team was on.

Run:
    python stages/s07f_free_stats.py --players work/g1/players.npz --windows work/g1/play_windows.json --out work/g1/free_stats.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common import NET_Y, SLOTS, TEAM_WIDTH, active_slots, load_config, match_mode, near_team_at, own_half_coords

FRONT_D, REAR_D = 2.2, 4.5                    # metres from the net: front court below, back court from
LEFT_U, RIGHT_U = TEAM_WIDTH / 3, 2 * TEAM_WIDTH / 3
SINGLES_EDGE = 0.46                           # the singles sidelines are this far inside the doubles ones
SIDE_BY_SIDE_GAP, FRONT_BACK_GAP = 1.5, 2.5   # depth gap between partners
FAST_MPS, BURST_MPS, BURST_MIN_S = 2.0, 2.5, 0.3
BLOCK_S = 120.0
HEAT_BINS = (14, 14)


def smooth_nan(x, w):
    """moving average of width w samples that skips missing (nan) values; stays nan where nothing was seen within the window."""
    x = np.asarray(x, float)
    ok = ~np.isnan(x)
    k = np.ones(w)
    num = np.convolve(np.where(ok, x, 0.0), k, "same")
    den = np.convolve(ok.astype(float), k, "same")
    with np.errstate(all="ignore"):
        out = num / den
    out[den < max(1, w // 3)] = np.nan
    out[~ok & (den < w // 2)] = np.nan
    return out


def play_mask(t, windows):
    m = np.zeros(len(t), bool)
    for w in windows:
        m |= (t >= w["start"]) & (t <= w["end"])
    return m


def share(mask, base):
    n = int(base.sum())
    return float(mask[base].sum() / n) if n else None


def zone_shares(u, d, singles=False):
    """front / middle / back and left / middle / right shares of the samples that have a position (thirds of the singles court in singles)."""
    ok = ~np.isnan(d)
    lo, hi = (SINGLES_EDGE, TEAM_WIDTH - SINGLES_EDGE) if singles else (0.0, TEAM_WIDTH)
    left, right = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
    return {"depth": {"front": share(d < FRONT_D, ok), "middle": share((d >= FRONT_D) & (d < REAR_D), ok), "back": share(d >= REAR_D, ok)},
            "width": {"left": share(u < left, ok), "middle": share((u >= left) & (u < right), ok), "right": share(u >= right, ok)}}


def heat(u, d):
    ok = ~np.isnan(u) & ~np.isnan(d)
    if ok.sum() < 20:
        return None
    h, _, _ = np.histogram2d(np.clip(u[ok], 0, TEAM_WIDTH - 1e-6), np.clip(d[ok], 0, NET_Y - 1e-6), bins=HEAT_BINS,
                             range=[[0, TEAM_WIDTH], [0, NET_Y]])
    return (h / h.sum()).round(4).tolist()          # [u_bin][d_bin]


def runs_len(on):
    """lengths (samples) of the runs of True."""
    out, n = [], 0
    for v in on:
        if v:
            n += 1
        elif n:
            out.append(n)
            n = 0
    if n:
        out.append(n)
    return out


def player_stats(xy_team, play, dt, smooth_w, singles=False):
    """xy_team: (n, 2) court metres of one player, already in own-half coordinates as (u, d) columns."""
    u, d = xy_team[:, 0], xy_team[:, 1]
    us, ds = smooth_nan(u, smooth_w), smooth_nan(d, smooth_w)
    step = np.full(len(u), np.nan)
    step[1:] = np.hypot(np.diff(us), np.diff(ds))
    v = step / dt
    inplay = play & ~np.isnan(us)
    moving = play & ~np.isnan(v) & (v < 9.0)
    play_min = max(1e-9, play.sum() * dt / 60.0)
    bursts = [r for r in runs_len(moving & (v > BURST_MPS)) if r * dt >= BURST_MIN_S]
    z = zone_shares(us[play], ds[play], singles)
    return {"seen_in_play": round(float(inplay.sum() / max(1, play.sum())), 3),
            "distance_m": round(float(np.nansum(step[moving])), 1), "distance_per_play_min": round(float(np.nansum(step[moving]) / play_min), 1),
            "speed_median_mps": round(float(np.nanmedian(v[moving])), 2) if moving.any() else None,
            "speed_p90_mps": round(float(np.nanpercentile(v[moving], 90)), 2) if moving.any() else None,
            "fast_share": round(float((v[moving] > FAST_MPS).mean()), 3) if moving.any() else None,
            "bursts_per_play_min": round(len(bursts) / play_min, 2),
            "mean_u": round(float(np.nanmean(us[play])), 2) if inplay.any() else None, "mean_d": round(float(np.nanmean(ds[play])), 2) if inplay.any() else None,
            "zones": z, "heat": heat(us[play], ds[play])}


def formation(ua, da, ub, db, play):
    """how a pair stands, over the moments in play when both are seen. Returns shares, gaps and who is at the back."""
    ok = play & ~np.isnan(da) & ~np.isnan(db) & ~np.isnan(ua) & ~np.isnan(ub)
    if ok.sum() < 20:
        return None
    gap_d, gap_u = np.abs(da - db)[ok], np.abs(ua - ub)[ok]
    sbs, fb = gap_d < SIDE_BY_SIDE_GAP, gap_d >= FRONT_BACK_GAP
    a_rear = (da > db)[ok]
    a_left = (ua < ub)[ok]
    idx = np.where(ok)[0]
    rear_seq = np.where(a_rear, 0, 1)[fb]                       # 0: first player is at the back
    swaps = int((np.diff(rear_seq) != 0).sum()) if len(rear_seq) > 1 else 0
    # a swap only counts when the new arrangement is held for at least 5 samples
    held = _held_swaps(np.where(fb, np.where(a_rear, 0, 1), -1), 5)
    return {"n": int(ok.sum()), "side_by_side": round(float(sbs.mean()), 3), "front_back": round(float(fb.mean()), 3),
            "mixed": round(float((~sbs & ~fb).mean()), 3), "gap_depth_median": round(float(np.median(gap_d)), 2),
            "gap_width_median": round(float(np.median(gap_u)), 2), "close_together": round(float((gap_u < 1.5).mean()), 3),
            "first_at_back_when_front_back": round(float(a_rear[fb].mean()), 3) if fb.any() else None,
            "first_on_left_when_side_by_side": round(float(a_left[sbs].mean()), 3) if sbs.any() else None,
            "rear_swaps": held, "rear_swaps_raw": swaps, "pair_depth_mean": round(float(np.mean((da[ok] + db[ok]) / 2)), 2)}


def _held_swaps(seq, hold):
    """number of changes between the two front-and-back arrangements (0 / 1), ignoring moments that are neither (-1) and blips shorter
    than `hold` samples."""
    runs, cur, n = [], None, 0
    for v in list(seq) + [None]:
        if v == cur:
            n += 1
            continue
        if cur is not None and cur >= 0:
            runs.append((cur, n))
        cur, n = v, 1
    kept = [r for r in runs if r[1] >= hold]
    return int(sum(1 for a, b in zip(kept[:-1], kept[1:]) if a[0] != b[0]))


def load_blocks(distance_by_block, play_by_block):
    return [{"from_s": round(i * BLOCK_S), "play_min": round(p / 60, 2), "per_play_min": round(dsum / (p / 60), 1) if p >= 30 else None}
            for i, (dsum, p) in enumerate(zip(distance_by_block, play_by_block))]


def summarise_windows(windows, game_start, game_end):
    d = np.array([w["dur"] for w in windows]) if windows else np.array([0.0])
    rest = np.array([b["start"] - a["end"] for a, b in zip(windows[:-1], windows[1:])]) if len(windows) > 1 else np.array([0.0])
    return {"n": len(windows), "median_s": round(float(np.median(d)), 1), "p90_s": round(float(np.percentile(d, 90)), 1), "max_s": round(float(d.max()), 1),
            "short_share": round(float((d < 5).mean()), 3), "long_share": round(float((d >= 10).mean()), 3),
            "rest_median_s": round(float(np.median(rest)), 1), "play_share": round(float(d.sum() / max(1e-9, game_end - game_start)), 3),
            "durations": [round(float(x), 1) for x in d]}


def analyse(z, windows, cfg=None):
    """cfg is the players_config.json content (common.load_config); without it the game is read as doubles."""
    t = np.asarray(z["t"], float)
    dt = float(z["stride"]) / float(z["fps"])
    play = play_mask(t, windows)
    near_team = str(z["first_near"])
    swap_s = float(z["tc"]) if "tc" in z and float(z["tc"]) < 1e8 else None        # the teams changed ends in the middle of this game
    singles = bool(cfg) and match_mode(cfg) == "singles"
    act = active_slots(cfg) if cfg else list(SLOTS)
    smooth_w = max(3, int(round(1.0 / dt)))
    own = {}
    tc = float(z["tc"]) if "tc" in z else 1e9
    for k in act:
        team_is_near = np.array([near_team_at(x, tc, near_team) == k[0] for x in t])        # per sample: the teams may change ends once
        u, d = own_half_coords(np.asarray(z[f"{k}_xy"], float), team_is_near)
        own[k] = (u, d)
    slots, blocks = {}, {}
    nblk = int(np.ceil((t[-1] - t[0]) / BLOCK_S))
    for k in act:
        u, d = own[k]
        slots[k] = player_stats(np.stack([u, d], 1), play, dt, smooth_w, singles)
        slots[k]["side"] = "both" if swap_s else ("near" if k[0] == near_team else "far")
        us, ds = smooth_nan(u, smooth_w), smooth_nan(d, smooth_w)
        step = np.full(len(t), np.nan)
        step[1:] = np.hypot(np.diff(us), np.diff(ds))
        dist, pl = [], []
        for i in range(nblk):
            m = (t >= t[0] + i * BLOCK_S) & (t < t[0] + (i + 1) * BLOCK_S)
            mv = m & play & ~np.isnan(step) & (step / dt < 9.0)
            dist.append(float(np.nansum(step[mv])))
            pl.append(float((m & play).sum() * dt))
        blocks[k] = load_blocks(dist, pl)
    teams = {}
    if not singles:
        for team, (a, b) in {"A": ("A_you", "A_partner"), "B": ("B_opp1", "B_opp2")}.items():
            f = formation(own[a][0], own[a][1], own[b][0], own[b][1], play)
            if f:
                f["slots"] = [a, b]
                f["side"] = "both" if swap_s else ("near" if team == near_team else "far")
            teams[team] = f
    return {"mode": "singles" if singles else "doubles", "end_change_s": round(swap_s, 1) if swap_s else None, "start": round(float(t[0]), 1), "end": round(float(t[-1]), 1), "near_team": near_team, "slots": slots,
            "teams": teams, "blocks": blocks, "plays": summarise_windows(windows, float(t[0]), float(t[-1])),
            "accuracy": {"near": "good: width and depth to about 0.3 m", "far": "width good, depth rougher (the far half is seen small); distance covered runs high"}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", required=True)
    ap.add_argument("--windows", required=True, help="play_windows.json from stage 6f")
    ap.add_argument("--config", help="players_config.json (singles or doubles); default: doubles")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    z = np.load(args.players, allow_pickle=True)
    W = json.loads(Path(args.windows).read_text())["windows"]
    out = analyse(z, W, load_config(args.config) if args.config else None)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{out['mode']}: {out['plays']['n']} plays, median {out['plays']['median_s']} s, rest median {out['plays']['rest_median_s']} s; near team {out['near_team']}")
    for k, s in out["slots"].items():
        print(f"  {k:10s} {s['side']:4s} seen {100 * s['seen_in_play']:3.0f}%  {s['distance_per_play_min']:5.1f} m/play-min  median {s['speed_median_mps']} m/s  "
              f"back {100 * s['zones']['depth']['back']:.0f}% front {100 * s['zones']['depth']['front']:.0f}%")
    for tm, f in out["teams"].items():
        if f:
            print(f"  team {tm} ({f['side']}): side-by-side {100 * f['side_by_side']:.0f}%, front-back {100 * f['front_back']:.0f}%, rear swaps {f['rear_swaps']}, "
                  f"gap {f['gap_depth_median']} m deep / {f['gap_width_median']} m wide")


if __name__ == "__main__":
    main()
