#!/usr/bin/env python3
"""Stage 6 - RALLIES.

Puts a start and an end on every rally and attaches the score replay to it.
  start = the moment the pre-serve window (banner / overlay) goes off
  end   = the edit cut at the next overlay (the clip stops when the rally stops);
          the final rally ends when the players stop moving.
Writes points.json and a contact sheet of the last frame before each cut for a sample of
rallies, so the end can be checked by eye.

Run:
    python stages/s06_rallies.py --proxy work/proxy.mp4 --serves work/serves.json \
        --score work/score.json --players work/players.npz --out work/points.json
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common import SLOTS as IDS



def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--serves", required=True)
    ap.add_argument("--score", required=True)
    ap.add_argument("--players", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    S = json.loads(Path(args.serves).read_text())
    sc = json.loads(Path(args.score).read_text())["rows"]
    sv, chains = S["serves"], S["chains"]
    z = np.load(args.players)
    t, fps = z["t"], float(z["fps"])
    dt = float(z["stride"]) / fps

    sp = []
    for k in IDS:
        xy = z[f"{k}_xy"]
        v = np.full(len(t), np.nan)
        v[1:] = np.linalg.norm(np.diff(xy, axis=0), axis=1) / dt
        sp.append(v)
    speed = np.nanmean(np.stack(sp), axis=0)

    cap = cv2.VideoCapture(args.proxy)
    video_end = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    cap.release()

    def conf_of(r):
        for c in chains:
            if c["rallies"][0] <= r <= c["rallies"][1]:
                return c["confidence"]
        return 0.0

    pts = []
    for k, s in enumerate(sv):
        start = s["window_off"]
        if k + 1 < len(sv):
            end = sv[k + 1]["window_on"]
        else:                                     # last rally: until the players stop moving, then 1 s
            m = (t > start) & (speed > 1.2)
            end = float(t[m].max()) + 1.0 if m.any() else video_end
        row = sc[k]
        pts.append({"rally": k + 1, "start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2),
                    "server_team": s["server_team"], "server_player": s["server_player"], "court": s["court"],
                    "score_before": [s["server_score"], s["receiver_score"]], "server_team_confidence": conf_of(k + 1),
                    "winner": row["winner"], "A_after": row["A_after"], "B_after": row["B_after"],
                    "user_team_won": None if row["winner"] is None else row["winner"] == "A"})
    Path(args.out).write_text(json.dumps({"stage": 6, "rallies": pts}, indent=1))

    d = np.array([p["duration"] for p in pts])
    print(f"rallies: {len(pts)}   duration  min {d.min():.1f} s  median {np.median(d):.1f} s  mean {d.mean():.1f} s  max {d.max():.1f} s")
    print(f"total rally time {d.sum() / 60:.1f} min of the {video_end / 60:.1f} min video")
    print("longest 5: " + ", ".join(f"R{p['rally']} {p['duration']:.0f}s" for p in sorted(pts, key=lambda p: -p['duration'])[:5]))
    print("shortest 5: " + ", ".join(f"R{p['rally']} {p['duration']:.0f}s" for p in sorted(pts, key=lambda p: p['duration'])[:5]))

    # check: players are moving right up to the cut, and nearly still in the window before the serve
    before_cut, in_window = [], []
    for p in pts[:-1]:
        m = (t >= p["end"] - 1.5) & (t < p["end"] - 0.2)
        before_cut.append(np.nanmean(speed[m]) if m.any() else np.nan)
    for s in sv:
        m = (t >= s["window_on"] + 0.5) & (t <= s["window_off"] - 0.2)
        in_window.append(np.nanmean(speed[m]) if m.any() else np.nan)
    print(f"mean player speed: last 1.5 s before each cut {np.nanmean(before_cut):.2f} m/s | inside the pre-serve window {np.nanmean(in_window):.2f} m/s")

    cap = cv2.VideoCapture(args.proxy)
    tiles = []
    for p in pts[:-1][::5][:12]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((p["end"] - 0.15) * fps))
        ok, img = cap.read()
        img = cv2.resize(img[200:720, 250:1280], (520, 262))
        cv2.putText(img, f"R{p['rally']} end t={p['end']:.1f}s winner {p['winner']}", (6, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        tiles.append(img)
    cap.release()
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(Path(args.out).with_name("s06_rally_ends.jpg")),
                np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]), [cv2.IMWRITE_JPEG_QUALITY, 90])
    # the last rally's end is only an estimate (the clip may stop right after it), so it is not judged here
    ok = 3 < d[:-1].min() and d[:-1].max() < 60 and np.nanmean(before_cut) > 2 * np.nanmean(in_window)
    print(f"points : {args.out}\nsheet  : {Path(args.out).with_name('s06_rally_ends.jpg')}")
    print("\nSTAGE 6 " + ("PASSED (automatic checks)." if ok else "FAILED: see numbers above."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
