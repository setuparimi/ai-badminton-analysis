#!/usr/bin/env python3
"""Stage 6f - PLAY WINDOWS (for videos with no score on screen).

Stage 6 puts a start and an end on every rally from the scoreboard. When the video has no scoreboard there is no
such anchor, so this stage finds the stretches of play from two signals that need no score:
  - how much the four players are moving (stage 3 tracks), and
  - how often a shuttle hit is heard (the sound track: short, bright clicks, 1.8 to 9 kHz).
Each signal is turned into a score (standard deviations from its own average), the two are averaged, and a stretch is
"play" when the average is above a threshold chosen automatically (Otsu's method: the split that best separates two
groups), with a lower threshold to stay in it (hysteresis). Stretches shorter than 2.5 s are dropped and stretches
less than 2 s apart are joined.

It cannot see who won a rally, cannot tell a long rally from two short ones with a pause, and a neighbouring court's
shuttle sounds count too. Check the number against the result card when the video has one (21-19 means 40 rallies).
Without a sound track it falls back to movement alone, which is less reliable.

Run:
    python stages/s06f_play_windows.py --players work/g1/players.npz --audio-from video.mp4 --out work/g1/play_windows.json
Writes the windows (start, end, seconds) and the numbers it used.
"""
import argparse
import json
import subprocess
import tempfile
import warnings
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d

from common import SLOTS

HIT_BAND = (1800.0, 9000.0)
HIT_RATIO = 3.0          # a hit is a peak this many times louder than the 3 s median
HIT_GAP_S = 0.08         # two hits are at least this far apart
HIT_HALF_S = 1.5         # hit density is counted this far either side of a moment
ACT_S = 1.5              # movement is averaged over this long
MIN_DUR_S = 2.5
MERGE_GAP_S = 2.0
HYSTERESIS = 0.25        # leave play at this many standard deviations below the entry threshold


def has_audio(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    return r.returncode == 0 and "audio" in r.stdout


def read_audio(video, sr=22050):
    """mono samples (float32, -1..1) and the sample rate, or None when the file has no sound."""
    from scipy.io import wavfile
    if not has_audio(video):
        return None
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(wav)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"ffmpeg could not read the sound of {video}: {r.stderr.strip()[:200]}")
        rate, x = wavfile.read(wav)
    return x.astype(np.float32) / 32768.0, int(rate)


def hit_times(x, sr, band=HIT_BAND, ratio=HIT_RATIO):
    """seconds at which a shuttle hit is heard: peaks of the band-passed energy that stand out from the local (3 s) median."""
    from scipy import signal
    sos = signal.butter(4, band, btype="band", fs=sr, output="sos")
    y = signal.sosfiltfilt(sos, x)
    hop = int(sr * 0.01)
    n = len(y) // hop
    if n < 400:
        return np.array([])
    e = np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    r = e / (median_filter(e, size=301) + 1e-9)
    pk, _ = signal.find_peaks(r, height=ratio, distance=max(1, int(HIT_GAP_S / 0.01)))
    return pk * 0.01


def otsu(v, bins=64):
    """the value that best splits v into a low group and a high group (Otsu's method)."""
    h, edges = np.histogram(v, bins=bins)
    p = h / h.sum()
    c = (edges[:-1] + edges[1:]) / 2
    best, thr = -1.0, float(c[0])
    for i in range(1, bins):
        w0, w1 = p[:i].sum(), p[i:].sum()
        if w0 == 0 or w1 == 0:
            continue
        m0, m1 = (p[:i] * c[:i]).sum() / w0, (p[i:] * c[i:]).sum() / w1
        s = w0 * w1 * (m0 - m1) ** 2
        if s > best:
            best, thr = s, float(c[i])
    return thr


def movement(z):
    """mean speed (m/s) of the four players at every sample of a players.npz, lightly smoothed; also the sample step."""
    t = np.asarray(z["t"], float)
    dt = float(z["stride"]) / float(z["fps"])
    sp = []
    for k in SLOTS:
        xy = np.asarray(z[f"{k}_xy"], float)
        v = np.full(len(t), np.nan)
        v[1:] = np.linalg.norm(np.diff(xy, axis=0), axis=1) / dt
        sp.append(np.clip(v, 0, 8))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # a moment with nobody tracked is simply 0
        m = np.nanmean(np.stack(sp), axis=0)
    return t, uniform_filter1d(np.nan_to_num(m), max(1, int(ACT_S / dt))), dt


def runs(on, t):
    out, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            out.append([float(t[i]), float(t[j - 1])])
            i = j
        else:
            i += 1
    return out


def detect(t, act, hits, dt, weight=0.5, min_dur=MIN_DUR_S, merge_gap=MERGE_GAP_S):
    """play windows [[start, end], ...] and the numbers used. hits is None for 'no sound': then movement alone decides."""
    z2 = (act - act.mean()) / (act.std() + 1e-9)
    if hits is None or len(hits) < 20:
        score, used_audio = z2, False
    else:
        hd = np.array([((hits >= x - HIT_HALF_S) & (hits < x + HIT_HALF_S)).sum() for x in t]) / (2 * HIT_HALF_S)
        f1 = np.log1p(hd)
        z1 = (f1 - f1.mean()) / (f1.std() + 1e-9)
        score, used_audio = (1 - weight) * z1 + weight * z2, True
    thr = otsu(score)
    lo = thr - HYSTERESIS * score.std()
    on, state = np.zeros(len(score), bool), False
    for i, v in enumerate(score):
        if not state and v > thr:
            state = True
        elif state and v < lo:
            state = False
        on[i] = state
    merged = []
    for s in runs(on, t):
        if merged and s[0] - merged[-1][1] < merge_gap:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    wins = [w for w in merged if w[1] - w[0] >= min_dur]
    return wins, {"threshold": round(thr, 3), "audio_used": used_audio, "weight_movement": weight if used_audio else 1.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--players", required=True, help="players.npz of one game (stage 3)")
    ap.add_argument("--audio-from", help="the video file with the sound (the original, not the proxy); without it movement alone is used")
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect", type=int, help="number of rallies you know the game had (for example 21 + 19 = 40); only shown beside the result")
    args = ap.parse_args()
    z = np.load(args.players, allow_pickle=True)
    t, act, dt = movement(z)
    hits, sound = None, "none"
    if args.audio_from:
        a = read_audio(args.audio_from)
        if a is None:
            print("note: the video has no sound track, so movement alone is used (less reliable)")
        else:
            h = hit_times(*a)
            hits = h[(h >= t[0] - 2) & (h <= t[-1] + 2)]
            sound = f"{len(hits)} hits heard"
    wins, info = detect(t, act, hits, dt)
    durs = np.array([w[1] - w[0] for w in wins]) if wins else np.array([0.0])
    out = {"windows": [{"start": round(a, 2), "end": round(b, 2), "dur": round(b - a, 2)} for a, b in wins], "n": len(wins),
           "play_share": round(float(durs.sum() / max(1e-9, t[-1] - t[0])), 3), "median_dur_s": round(float(np.median(durs)), 2),
           "game_start": round(float(t[0]), 1), "game_end": round(float(t[-1]), 1), "sound": sound, **info}
    if args.expect:
        out["expected"] = args.expect
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{len(wins)} play windows, median {out['median_dur_s']} s, {100 * out['play_share']:.0f}% of the game in play ({sound}; "
          f"{'sound + movement' if info['audio_used'] else 'movement only'})" + (f"; the result card implies {args.expect}" if args.expect else ""))


if __name__ == "__main__":
    main()
