#!/usr/bin/env python3
"""Stage 1 - DETECT.

Finds every person in every Nth frame of the proxy (default every 3rd frame = 10 fps)
with a YOLO model and saves the boxes to dets.json. There is no tracking and no court
logic here: spectators and the umpire are detected too. Stages 2-3 decide who is a
player.

Run:
    python stages/s01_detect.py --proxy work/proxy.mp4 --out work/dets.json

Outputs:
    dets.json        {"frames": [{"f": frame_index, "t": seconds, "b": [[x1,y1,x2,y2,conf], ...]}]}
                     coordinates are pixels of the proxy video
    s01_check.jpg    6 frames with the detected boxes drawn on, next to dets.json
"""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # let unsupported MPS ops run on CPU

import cv2
import numpy as np


def pick_device(arg):
    if arg != "auto":
        return arg
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def load_model(name, weights_dir):
    from ultralytics import YOLO
    path = Path(name)
    if not path.exists():
        path = Path(weights_dir) / path.name
    if not path.exists():
        Path(weights_dir).mkdir(parents=True, exist_ok=True)
        from ultralytics.utils.downloads import attempt_download_asset
        print(f"downloading {path.name} (one time, free, from the ultralytics GitHub release)...")
        attempt_download_asset(str(path))
    return YOLO(str(path))


def draw_sheet(proxy, boxes_by_frame, picks, fps, out_jpg):
    cap = cv2.VideoCapture(str(proxy))
    tiles = []
    for fi in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, img = cap.read()
        if not ok:
            continue
        boxes = boxes_by_frame[fi]
        for x1, y1, x2, y2, c in boxes:
            col = (0, 200, 0) if c >= 0.5 else (0, 140, 255)  # green = confident, orange = weak
            cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), col, 3)
            cv2.putText(img, f"{c:.2f}", (int(x1), max(14, int(y1) - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
        cv2.putText(img, f"t={fi / fps:.1f}s  persons={len(boxes)}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
    cap.release()
    while len(tiles) < 6:
        tiles.append(np.zeros((360, 640, 3), np.uint8))
    sheet = np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:6])])
    cv2.imwrite(str(out_jpg), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True, help="proxy.mp4 from stage 0")
    ap.add_argument("--out", required=True, help="dets.json to write")
    ap.add_argument("--model", default="yolo11m.pt")
    ap.add_argument("--weights-dir", default="models")
    ap.add_argument("--stride", type=int, default=3, help="detect on every Nth frame")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--conf", type=float, default=0.20)
    ap.add_argument("--iou", type=float, default=0.70, help="NMS overlap; high keeps overlapping partners")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default="auto", help="auto, mps or cpu")
    ap.add_argument("--max-seconds", type=float, default=0, help="only process the first N seconds (testing)")
    args = ap.parse_args()

    proxy, out = Path(args.proxy), Path(args.out)
    if not proxy.is_file():
        sys.exit(f"proxy not found: {proxy}  (run stage 0 first)")
    out.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(proxy))
    fps = cap.get(cv2.CAP_PROP_FPS)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    info_path = proxy.with_name("proxy_info.json")
    info_frames = json.loads(info_path.read_text()).get("nb_frames") if info_path.exists() else None
    limit = int(args.max_seconds * fps) if args.max_seconds else None
    approx_total = limit or int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    device = pick_device(args.device)
    model = load_model(args.model, args.weights_dir)
    print(f"proxy {W}x{H} @ {fps:.2f} fps | model {args.model} | imgsz {args.imgsz} | "
          f"device {device} | conf {args.conf} | every {args.stride}rd frame")

    frames, batch, batch_idx = [], [], []

    def flush():
        res = model.predict(batch, imgsz=args.imgsz, conf=args.conf, iou=args.iou,
                            classes=[0], device=device, verbose=False)
        for fi, r in zip(batch_idx, res):
            xyxy, cf = r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()
            b = [[round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1),
                  round(float(c), 3)] for (x1, y1, x2, y2), c in zip(xyxy, cf)]
            b.sort(key=lambda v: -(v[3] - v[1]))  # biggest (nearest) first
            frames.append({"f": fi, "t": round(fi / fps, 3), "b": b})
        batch.clear()
        batch_idx.clear()

    t0, idx, next_report = time.time(), 0, 0.1
    while True:
        if limit is not None and idx >= limit:
            break
        if not cap.grab():
            break
        if idx % args.stride == 0:
            ok, img = cap.retrieve()
            if not ok:
                break
            batch.append(img)
            batch_idx.append(idx)
            if len(batch) == args.batch:
                flush()
        idx += 1
        if approx_total and idx / approx_total >= next_report:
            el = time.time() - t0
            print(f"  {int(100 * idx / approx_total):3d}%  {len(frames) / el:5.1f} det-frames/s  "
                  f"elapsed {el:4.0f}s  eta {el * (approx_total / idx - 1):4.0f}s")
            next_report += 0.1
    if batch:
        flush()
    cap.release()
    elapsed = time.time() - t0

    meta = {"stage": 1, "proxy": proxy.name, "width": W, "height": H, "fps": fps,
            "stride": args.stride, "model": args.model, "imgsz": args.imgsz, "conf": args.conf,
            "iou": args.iou, "n_proxy_frames": idx}
    out.write_text(json.dumps({**meta, "frames": frames}, separators=(",", ":")))

    counts = np.array([len(f["b"]) for f in frames])
    idxs = [f["f"] for f in frames]
    allb = [b for f in frames for b in f["b"]]
    checks = []

    def check(name, ok, detail):
        checks.append((name, bool(ok), detail))

    want = math.ceil(idx / args.stride)
    check("one detection record per sampled frame, none skipped",
          idxs == list(range(0, idx, args.stride)), f"{len(frames)} records, expected {want}")
    if info_frames and not limit:
        check("decoded frame count equals stage 0's", idx == info_frames,
              f"decoded {idx}, proxy_info.json says {info_frames}")
    check("boxes lie inside the frame",
          all(-2 <= b[0] and -2 <= b[1] and b[2] <= W + 2 and b[3] <= H + 2 and b[0] < b[2] and b[1] < b[3]
              for b in allb), f"{len(allb)} boxes checked")
    zero = float((counts == 0).mean())
    check("almost no frames with zero people", zero < 0.01, f"{100 * zero:.2f}% of frames empty")
    check("persons per frame plausible (court + crowd)", 4 <= np.median(counts) <= 80,
          f"min {counts.min()}  median {int(np.median(counts))}  max {counts.max()}")

    boxes_by_frame = {f["f"]: f["b"] for f in frames}
    picks = [idxs[min(len(idxs) - 1, int((i + 0.5) * len(idxs) / 6))] for i in range(6)]
    sheet = out.with_name("s01_check.jpg")
    draw_sheet(proxy, boxes_by_frame, picks, fps, sheet)

    print()
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    print(f"\nspeed  : {len(frames) / elapsed:.1f} frames/s, {elapsed:.0f} s total")
    print(f"dets   : {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"sheet  : {sheet}   <- open this and count the players in every tile")
    bad = [c for c in checks if not c[1]]
    print("\nSTAGE 1 " + ("PASSED (automatic checks); now do the visual check." if not bad
                          else f"FAILED: {len(bad)} check(s) above."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
