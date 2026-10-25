#!/usr/bin/env python3
"""Stage 11 - VIDEO (optional).

Renders the game with: a box and label on each player (YOU, PARTNER, OPP), a score/server
bar, the original timecode, and a top-down mini-map of the four players on the court.
Optionally mixes in a spoken coach summary (macOS `say`, local and free) over the first
seconds, with the original sound ducked underneath.

Run:
    python stages/s11_video.py --proxy work/proxy.mp4 --players work/players.npz \
        --points work/points.json --start 46 --out work/analysis_video.mp4 [--voice-text work/coach.txt]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from common import SLOTS as IDS

COL = {"A_partner": (60, 60, 255), "A_you": (0, 230, 255), "B_opp1": (255, 120, 0), "B_opp2": (80, 220, 80)}
LABEL = {"A_partner": "PARTNER", "A_you": "YOU", "B_opp1": "OPP", "B_opp2": "OPP"}
SERVER_NAME = {"A_you": "YOU", "A_partner": "PARTNER", "B_opp1": "OPP", "B_opp2": "OPP"}
W_C, L_C = 6.1, 13.4


def draw_minimap(pos, size=(170, 360)):
    mw, mh = size
    m = np.full((mh, mw, 3), (40, 90, 40), np.uint8)
    pad = 14
    sx, sy = (mw - 2 * pad) / W_C, (mh - 2 * pad) / L_C
    P = lambda X, Y: (int(pad + X * sx), int(mh - pad - Y * sy))
    cv2.rectangle(m, P(0, 0), P(W_C, L_C), (255, 255, 255), 1)
    for X in (0.46, W_C - 0.46):
        cv2.line(m, P(X, 0), P(X, L_C), (200, 200, 200), 1)
    for Y in (6.7 - 1.98, 6.7 + 1.98, 0.76, L_C - 0.76):
        cv2.line(m, P(0, Y), P(W_C, Y), (200, 200, 200), 1)
    cv2.line(m, P(W_C / 2, 0), P(W_C / 2, 6.7 - 1.98), (200, 200, 200), 1)
    cv2.line(m, P(W_C / 2, 6.7 + 1.98), P(W_C / 2, L_C), (200, 200, 200), 1)
    cv2.line(m, P(-0.3, 6.7), P(W_C + 0.3, 6.7), (255, 255, 255), 3)
    for k, xy in pos.items():
        if xy is not None and not np.isnan(xy[0]):
            c = P(float(np.clip(xy[0], -0.5, W_C + 0.5)), float(np.clip(xy[1], -1.0, L_C + 1.0)))
            cv2.circle(m, c, 7, COL[k], -1)
            cv2.circle(m, c, 7, (0, 0, 0), 1)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--players", required=True)
    ap.add_argument("--points", required=True)
    ap.add_argument("--start", type=float, default=46.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice-text", help="text file for the spoken summary")
    ap.add_argument("--voice", default="Samantha")
    args = ap.parse_args()

    z = np.load(args.players)
    frames, fps = z["frames"], float(z["fps"])
    P = json.loads(Path(args.points).read_text())["rallies"]
    n_r = len(P)
    cap = cv2.VideoCapture(args.proxy)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    f0 = int(args.start * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    silent = Path(args.out).with_suffix(".silent.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-",
           "-ss", f"{args.start}", "-i", args.proxy, "-map", "0:v", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "fast",
           "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", str(silent)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def rally_at(t):
        for p in P:
            wnd_on = p["start"] - 3.0                      # the pre-serve window belongs to the rally it precedes
            if wnd_on <= t < p["end"]:
                return p
        return P[-1] if t >= P[-1]["start"] else None

    for f in range(f0, total):
        ok, img = cap.read()
        if not ok:
            break
        t = f / fps
        j = int(np.searchsorted(frames, f, side="right") - 1)
        pos = {}
        for k in IDS:
            xy = z[f"{k}_xy"][j] if j >= 0 else np.array([np.nan, np.nan])
            pos[k] = None if np.isnan(xy[0]) else xy
            b = z[f"{k}_box"][j] if j >= 0 else None
            if b is not None and not np.isnan(b[0]) and z[f"{k}_flag"][j] == 1 and f - frames[j] <= 3:
                cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), COL[k], 3)
                cv2.putText(img, LABEL[k], (int(b[0]), max(20, int(b[1]) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, COL[k], 2, cv2.LINE_AA)
        # bar: score before the rally, who serves, court
        p = rally_at(t)
        bar = img[0:46, 0:W].copy()
        cv2.rectangle(img, (0, 0), (W, 46), (20, 20, 20), -1)
        cv2.addWeighted(bar, 0.25, img[0:46, 0:W], 0.75, 0, img[0:46, 0:W])
        if p:
            a_b = (P[p["rally"] - 2]["A_after"] or 0) if p["rally"] > 1 else 0
            b_b = (P[p["rally"] - 2]["B_after"] or 0) if p["rally"] > 1 else 0
            srv = f"{'YOUR TEAM' if p['server_team'] == 'A' else 'OPPONENTS'} serve ({SERVER_NAME.get(p['server_player'], '')}) from the {p['court']} court".replace("()", "").replace("  ", " ")
            res = "" if not p["winner"] or t < p["end"] - 1.0 else ("  >> point: YOU" if p["winner"] == "A" else "  >> point: OPP")
            cv2.putText(img, f"Rally {p['rally']}/{n_r}   YOUR TEAM {a_b} - {b_b} OPP   {srv}{res}", (10, 31),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, f"{int(t // 60)}:{int(t % 60):02d}", (W - 85, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
        mm = draw_minimap(pos)
        y0 = H - mm.shape[0] - 10
        img[y0:y0 + mm.shape[0], W - mm.shape[1] - 10:W - 10] = mm
        try:
            ff.stdin.write(img.tobytes())
        except BrokenPipeError:
            break
        if (f - f0) % 3000 == 0:
            print(f"  rendered {100 * (f - f0) / (total - f0):.0f}%", flush=True)
    ff.stdin.close()
    ff.wait()
    cap.release()
    if ff.returncode != 0:
        sys.exit("ffmpeg failed")

    if args.voice_text:
        txt = Path(args.voice_text).read_text()
        aiff = Path(args.out).with_suffix(".voice.aiff")
        subprocess.run(["say", "-v", args.voice, "-o", str(aiff), txt], check=True)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(aiff)],
                                   capture_output=True, text=True).stdout)
        flt = (f"[0:a]volume='if(lt(t,{dur + 1.0:.1f}),0.2,1)':eval=frame[a0];[1:a]adelay=800|800[a1];"
               "[a0][a1]amix=inputs=2:duration=first:normalize=0[a]")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(aiff), "-filter_complex", flt,
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", args.out], check=True)
        silent.unlink()
        aiff.unlink()
        print(f"coach voice: {dur:.0f} s over the first seconds, original sound ducked underneath")
    else:
        silent.replace(args.out)
    print(f"video: {args.out} ({Path(args.out).stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
