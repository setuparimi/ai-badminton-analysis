#!/usr/bin/env python3
"""Stage 2 - CALIBRATE.

Fits a homography H between proxy pixels and court metres from hand-picked court points
(the camera is static, so this is done once per camera position), then draws the whole
court model back onto a clean background image so you can see whether it lies on the
painted lines.

Court frame (metres): X across the court 0..6.1 and Y along it 0..13.4.
    Y = 0 is the near baseline (the one closest to the camera), the net is at Y = 6.7.
    X = 0 is the LEFT doubles sideline for a player standing on the near baseline facing the net.

Run:
    python stages/s02_calibrate.py --proxy work/proxy.mp4 --points work/court_points.json --out work/calib.json
    python stages/s02_calibrate.py --proxy work/proxy.mp4 --grid     # writes work/bg_grid.png to read pixel coords by eye

court_points.json: [{"name": "...", "px": [x, y], "court": [X, Y]}, ...]  (at least 4, spread out)

Outputs next to --out: calib.json, bg_median.png, s02_check.jpg
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

W_D, L, NET_Y = 6.1, 13.4, 6.7  # doubles width, length, net position
SINGLES_INSET, SSL, LSL_INSET = 0.46, 1.98, 0.76

LINES = [  # court-metre segments of every painted line
    ((0, 0), (W_D, 0)), ((0, L), (W_D, L)),                      # baselines
    ((0, 0), (0, L)), ((W_D, 0), (W_D, L)),                      # doubles sidelines
    ((SINGLES_INSET, 0), (SINGLES_INSET, L)),
    ((W_D - SINGLES_INSET, 0), (W_D - SINGLES_INSET, L)),        # singles sidelines
    ((0, NET_Y - SSL), (W_D, NET_Y - SSL)), ((0, NET_Y + SSL), (W_D, NET_Y + SSL)),  # short service lines
    ((0, LSL_INSET), (W_D, LSL_INSET)), ((0, L - LSL_INSET), (W_D, L - LSL_INSET)),  # doubles long service
    ((W_D / 2, 0), (W_D / 2, NET_Y - SSL)), ((W_D / 2, NET_Y + SSL), (W_D / 2, L)),  # centre lines
]
NET = ((0, NET_Y), (W_D, NET_Y))


def median_background(proxy, n=150):
    cap = cv2.VideoCapture(str(proxy))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for i in np.linspace(0, total - 1, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if ok:
            frames.append(f)
    cap.release()
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def project(Hc2i, pts):
    p = cv2.perspectiveTransform(np.array(pts, np.float64).reshape(-1, 1, 2), Hc2i)
    return p.reshape(-1, 2)


def draw_grid(bg, out):
    g = bg.copy()
    for x in range(0, g.shape[1], 100):
        cv2.line(g, (x, 0), (x, g.shape[0] - 1), (0, 255, 255), 1)
        cv2.putText(g, str(x), (x + 3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    for y in range(0, g.shape[0], 100):
        cv2.line(g, (0, y), (g.shape[1] - 1, y), (0, 255, 255), 1)
        cv2.putText(g, str(y), (3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    cv2.imwrite(str(out), g)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--points", help="court_points.json")
    ap.add_argument("--out", help="calib.json to write")
    ap.add_argument("--grid", action="store_true", help="only write bg_median.png and bg_grid.png")
    args = ap.parse_args()

    proxy = Path(args.proxy)
    out_dir = Path(args.out).parent if args.out else proxy.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    bg_path = out_dir / "bg_median.png"
    bg = cv2.imread(str(bg_path)) if bg_path.exists() else None
    if bg is None:
        print("building median background (players disappear in a median)...")
        bg = median_background(proxy)
        cv2.imwrite(str(bg_path), bg)
    if args.grid:
        draw_grid(bg, out_dir / "bg_grid.png")
        print("wrote", out_dir / "bg_grid.png")
        return
    if not (args.points and args.out):
        sys.exit("need --points and --out (or --grid)")

    pts = json.loads(Path(args.points).read_text())
    if len(pts) < 4:
        sys.exit("need at least 4 court points")
    px = np.array([p["px"] for p in pts], np.float64)
    co = np.array([p["court"] for p in pts], np.float64)
    Hc2i, _ = cv2.findHomography(co, px, 0)           # court metres -> pixels
    Hi2c = np.linalg.inv(Hc2i)
    err = np.linalg.norm(project(Hc2i, co) - px, axis=1)

    loo = []                                          # leave-one-out: how well do the others predict this point?
    for i in range(len(pts)):
        keep = [j for j in range(len(pts)) if j != i]
        H, _ = cv2.findHomography(co[keep], px[keep], 0)
        loo.append(float(np.linalg.norm(project(H, co[i:i + 1])[0] - px[i])))

    chk = bg.copy()
    for a, b in LINES:
        p = project(Hc2i, [a, b]).astype(int)
        cv2.line(chk, tuple(p[0]), tuple(p[1]), (0, 0, 255), 1, cv2.LINE_AA)
    p = project(Hc2i, list(NET)).astype(int)
    cv2.line(chk, tuple(p[0]), tuple(p[1]), (255, 0, 255), 2, cv2.LINE_AA)
    for (x, y), e, q in zip(px, err, pts):
        cv2.circle(chk, (int(x), int(y)), 5, (0, 255, 0), 2)
    cv2.imwrite(str(out_dir / "s02_check.jpg"), chk, [cv2.IMWRITE_JPEG_QUALITY, 92])

    # scale sanity: how many pixels is 1 m at a few places?
    def ppm(X, Y, dX=1.0, dY=0.0):
        a, b = project(Hc2i, [(X, Y), (X + dX, Y + dY)])
        return float(np.linalg.norm(a - b))
    scale = {"1m across, near court (Y=2)": ppm(3, 2), "1m across, at the net": ppm(3, 6.7),
             "1m along, near court (Y=2)": ppm(3, 2, 0, 1), "1m along, far court (Y=11)": ppm(3, 11, 0, 1)}

    calib = {"stage": 2, "court": {"width": W_D, "length": L, "net_y": NET_Y, "ssl": SSL,
                                   "lsl_inset": LSL_INSET, "singles_inset": SINGLES_INSET},
             "points": pts, "H_court2img": Hc2i.tolist(), "H_img2court": Hi2c.tolist(),
             "rms_px": float(np.sqrt((err ** 2).mean())), "max_px": float(err.max()),
             "loo_px": loo, "pixels_per_metre": scale}
    Path(args.out).write_text(json.dumps(calib, indent=2))

    print(f"points used        : {len(pts)}")
    print(f"fit error          : rms {calib['rms_px']:.2f} px, worst {err.max():.2f} px  (frame is 1280x720)")
    print(f"leave-one-out error: median {np.median(loo):.1f} px, worst {max(loo):.1f} px "
          f"({pts[int(np.argmax(loo))]['name']})")
    if max(loo) > 15:
        print("  note: a large worst case usually means that point is the only one in its region,\n"
              "  so dropping it forces an extrapolation. Judge by the red lines in s02_check.jpg.")
    for k, v in scale.items():
        print(f"  pixels per metre, {k}: {v:.0f}")
    print(f"calib  : {args.out}\ncheck  : {out_dir / 's02_check.jpg'}  <- red lines must sit on the painted lines")
    ok = calib["rms_px"] < 4 and float(np.median(loo)) < 12
    print("\nSTAGE 2 " + ("PASSED (automatic checks); now do the visual check." if ok
                          else "FAILED: error too large, re-read the court points."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
