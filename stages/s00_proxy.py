#!/usr/bin/env python3
"""Stage 0 - PROXY.

Re-encodes the source video into one predictable proxy that every later stage reads:
fits inside 1280x720, constant 30 fps, SDR (HDR is tone-mapped), H.264, one keyframe
per second so frame-accurate seeking is cheap. Writes proxy_info.json so later stages
never guess the frame size or fps.

Run:
    python stages/s00_proxy.py --src my_match.mp4 --out-dir work

Outputs in --out-dir:
    proxy.mp4         the proxy video
    proxy_info.json   source/proxy facts + the check results
    s00_check.jpg     contact sheet of 6 proxy frames to eyeball colour and framing
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # HDR10/PQ and HLG (iPhone)
TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr.strip()}")
    return r


def frac(s):
    n, _, d = (s or "0/1").partition("/")
    return float(n) / float(d or 1) if float(d or 1) else 0.0


def has_filter(ffmpeg, name):
    out = sh([ffmpeg, "-hide_banner", "-filters"]).stdout
    return re.search(rf"^\s*\S+\s+{name}\s", out, re.M) is not None


def probe(ffprobe, path, count_packets=False):
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0"]
    if count_packets:
        cmd.append("-count_packets")
    cmd += ["-show_streams", "-show_format", "-of", "json", str(path)]
    data = json.loads(sh(cmd).stdout)
    if not data.get("streams"):
        sys.exit(f"no video stream in {path}")
    s = data["streams"][0]
    rot = 0
    for sd in s.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if "rotate" in s.get("tags", {}):
        rot = int(s["tags"]["rotate"])
    w, h = int(s["width"]), int(s["height"])
    if abs(rot) % 180 == 90:  # ffmpeg auto-rotates, so this is the displayed size
        w, h = h, w
    audio = sh([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
                "stream=index", "-of", "csv=p=0", str(path)]).stdout.strip()
    return {
        "width": w,
        "height": h,
        "rotation": rot,
        "codec": s.get("codec_name"),
        "pix_fmt": s.get("pix_fmt"),
        "r_fps": frac(s.get("r_frame_rate")),
        "avg_fps": frac(s.get("avg_frame_rate")),
        "duration": float(s.get("duration") or data["format"]["duration"]),
        "nb_read_packets": int(s["nb_read_packets"]) if "nb_read_packets" in s else None,
        "color_transfer": s.get("color_transfer", "unknown"),
        "color_primaries": s.get("color_primaries", "unknown"),
        "has_audio": bool(audio),
    }


def mean_luma(ffmpeg, path, t):
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
         "-vf", "scale=1:1:flags=area,format=gray", "-f", "rawvideo", "pipe:1"],
        capture_output=True)
    return r.stdout[0] if r.returncode == 0 and r.stdout else None


def make_sheet(ffmpeg, proxy, duration, out_jpg):
    step = duration / 6
    sh([ffmpeg, "-v", "error", "-y", "-ss", f"{step / 2:.3f}", "-i", str(proxy),
        "-vf", f"fps={1 / step:.8f},scale=640:-2,tile=3x2",
        "-frames:v", "1", "-update", "1", str(out_jpg)])


def encode(args, src, tmp, tonemap):
    vf = [f"fps={args.fps}"]
    if tonemap:
        vf.append(TONEMAP_CHAIN)
    vf += [f"scale={args.width}:{args.height}:force_original_aspect_ratio=decrease:"
           "force_divisible_by=2:flags=lanczos", "setsar=1", "format=yuv420p"]
    cmd = [args.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y",
           "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-vf", ",".join(vf),
           "-c:v", "libx264", "-preset", "fast", "-crf", str(args.crf),
           "-g", str(args.fps), "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", str(tmp)]
    print("encoding (this is the slow part)...")
    if subprocess.run(cmd).returncode != 0:
        tmp.unlink(missing_ok=True)
        sys.exit("ffmpeg encode failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="source video (any size, any phone codec)")
    ap.add_argument("--out-dir", default="work")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=18, help="x264 quality, lower = bigger/better")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    ap.add_argument("--allow-untonemapped", action="store_true",
                    help="encode HDR source without tone-mapping (colours will look washed out)")
    ap.add_argument("--force", action="store_true", help="re-encode even if proxy.mp4 exists")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        sys.exit(f"source not found: {src}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    proxy, tmp = out_dir / "proxy.mp4", out_dir / "proxy.tmp.mp4"

    s = probe(args.ffprobe, src)
    print(f"source : {s['width']}x{s['height']} {s['r_fps']:.3f} fps {s['duration']:.1f} s "
          f"{s['codec']} {s['pix_fmt']} transfer={s['color_transfer']} audio={s['has_audio']}")
    notes = []
    if s["width"] < args.width and s["height"] < args.height:
        notes.append(f"source is smaller than {args.width}x{args.height}: the proxy is an "
                     "upscale. It adds no detail, but later stages get bigger crops to work with.")
    if s["height"] > s["width"]:
        notes.append("portrait video: the court will be tiny. Film landscape next time.")
    if abs(s["r_fps"] - s["avg_fps"]) > 0.01:
        notes.append("source is variable frame rate; the proxy will be constant "
                     f"{args.fps} fps.")
    if s["r_fps"] and s["r_fps"] < args.fps - 0.5:
        notes.append(f"source is {s['r_fps']:.0f} fps, below {args.fps}: frames get duplicated.")

    hdr = s["color_transfer"] in HDR_TRANSFERS
    tonemap = False
    if hdr:
        if has_filter(args.ffmpeg, "zscale"):
            tonemap = True
        elif args.allow_untonemapped:
            notes.append("HDR source encoded WITHOUT tone-mapping: colours will be washed out, "
                         "so colour-based player ID will be unreliable.")
        else:
            sys.exit(
                f"\nThis is HDR video ({s['color_transfer']}) and your ffmpeg has no 'zscale' "
                "filter, which tone-mapping needs. Pick one:\n"
                "  1. brew install ffmpeg-full   then re-run with\n"
                '       --ffmpeg "$(brew --prefix ffmpeg-full)/bin/ffmpeg" '
                '--ffprobe "$(brew --prefix ffmpeg-full)/bin/ffprobe"\n'
                "  2. next time turn off iPhone Settings > Camera > Record Video > HDR Video\n"
                "  3. add --allow-untonemapped to proceed anyway (washed-out colours)\n")
    for n in notes:
        print("note   :", n)

    if proxy.exists() and not args.force:
        print(f"{proxy} exists, reusing it (add --force to rebuild); running checks only.")
    else:
        encode(args, src, tmp, tonemap)
        tmp.replace(proxy)

    p = probe(args.ffprobe, proxy, count_packets=True)
    src_aspect = s["width"] / s["height"]
    expected_frames = round(s["duration"] * args.fps)
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    check("size fits the target box, aspect kept",
          p["width"] <= args.width and p["height"] <= args.height
          and (args.width - p["width"] <= 2 or args.height - p["height"] <= 2)
          and abs(p["width"] / p["height"] - src_aspect) / src_aspect < 0.01,
          f"{p['width']}x{p['height']} (box {args.width}x{args.height}, source aspect {src_aspect:.3f})")
    check("constant frame rate",
          abs(p["r_fps"] - args.fps) < 0.001 and abs(p["avg_fps"] - args.fps) < 0.001,
          f"r_frame_rate={p['r_fps']:.3f} avg_frame_rate={p['avg_fps']:.3f} (want {args.fps})")
    check("pixel format yuv420p", p["pix_fmt"] == "yuv420p", p["pix_fmt"])
    check("SDR (not PQ/HLG)", p["color_transfer"] not in HDR_TRANSFERS,
          p["color_transfer"] + (" (HDR source was not tone-mapped)" if hdr and not tonemap else ""))
    check("frame count matches source duration",
          p["nb_read_packets"] is not None and abs(p["nb_read_packets"] - expected_frames) <= 2,
          f"{p['nb_read_packets']} frames, expected about {expected_frames}")
    check("duration matches source", abs(p["duration"] - s["duration"]) <= 0.15,
          f"proxy {p['duration']:.2f} s vs source {s['duration']:.2f} s")

    lumas = []
    for f in (0.25, 0.5, 0.75):
        a, b = mean_luma(args.ffmpeg, src, s["duration"] * f), mean_luma(args.ffmpeg, proxy, p["duration"] * f)
        lumas.append((a, b))
    ok_luma = all(a is not None and b is not None for a, b in lumas)
    if hdr:
        check("brightness vs source", True,
              "skipped: HDR source cannot be compared directly; judge s00_check.jpg by eye")
    else:
        check("brightness vs source (mean luma 0-255 at 25/50/75%)",
              ok_luma and all(abs(a - b) <= 12 for a, b in lumas),
              "  ".join(f"{a}->{b}" for a, b in lumas))

    sheet = out_dir / "s00_check.jpg"
    make_sheet(args.ffmpeg, proxy, p["duration"], sheet)

    info = {
        "src": src.name, "proxy": proxy.name,
        "width": p["width"], "height": p["height"], "fps": args.fps,
        "nb_frames": p["nb_read_packets"], "duration": p["duration"],
        "source": s, "hdr_source": hdr, "tonemapped": tonemap, "notes": notes, "checks": checks,
    }
    (out_dir / "proxy_info.json").write_text(json.dumps(info, indent=2))

    print()
    for c in checks:
        print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print(f"\nproxy  : {proxy}  ({proxy.stat().st_size / 1e6:.1f} MB)")
    print(f"sheet  : {sheet}   <- open this and look at it")
    print(f"info   : {out_dir / 'proxy_info.json'}")
    failed = [c for c in checks if not c["ok"]]
    print("\nSTAGE 0 " + ("PASSED (automatic checks); now do the visual check." if not failed
                          else f"FAILED: {len(failed)} check(s) above."))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
