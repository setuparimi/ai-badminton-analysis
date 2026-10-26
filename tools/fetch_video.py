#!/usr/bin/env python3
"""Fetch ONE YouTube video so it can be analysed here.

Use it only for a video you filmed or have permission to use. YouTube's Terms of Service restrict downloading other
people's videos and the owner may hold the copyright. The program asks you to confirm that, saves a single video into
a fresh folder on this computer, and never uploads it anywhere.

It is a thin, optional wrapper around yt-dlp, which is NOT part of this project and is installed separately:
    .venv/bin/pip install -r requirements-youtube.txt
YouTube changes often; if a download stops working, update it first:  .venv/bin/pip install -U yt-dlp

What it will and will not do
    * one video per run: playlists, channels, search pages, live streams and other websites are refused
    * no logins and no browser cookies: private, members-only and age-gated videos fail with a message
    * it looks the video up first (--info) and refuses very long or very large ones (see the limits below)
    * the file keeps the video's id as its name (not the title), in a new empty folder, and is checked with ffprobe afterwards
    * the title and channel are other people's text: they are cleaned before printing and never become file names

Run:
    python tools/fetch_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --info                       # look, download nothing
    python tools/fetch_video.py "https://youtu.be/VIDEO_ID" --out-dir work/download --confirm-rights    # download
Output: <out-dir>/<id>.mp4 (or .mkv) and <out-dir>/source.json (where it came from, size, checksum, that you confirmed the right to use it).
Exit code: 0 done, 1 something went wrong, 2 a safety rule said no.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov")
MAX_URL = 300
RIGHTS_TEXT = ("Only download a video you filmed or have permission to use. YouTube's Terms of Service restrict downloading other people's "
               "videos, and the video's owner may hold the copyright. This saves ONE video on this computer for analysis; this project never uploads it.")


class Refused(Exception):
    """a safety rule said no (exit code 2)"""


class Failed(Exception):
    """something went wrong (exit code 1)"""


class Limits:
    def __init__(self, max_minutes=120, max_mb=2500, max_height=720):
        self.max_minutes, self.max_mb, self.max_height = max_minutes, max_mb, max_height


# ---------------------------------------------------------------------------------------------
# the link
# ---------------------------------------------------------------------------------------------
def normalise_url(url, extra_hosts=()):
    """Return (canonical link, extractor regex). Accepts one YouTube video link; anything else is refused.

    extra_hosts: host names accepted as a plain link to a video file (used by the tests with a local server)."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL or re.search(r"[\s\x00-\x1f\x7f]", url.strip()):
        raise Refused("that is not a usable link (give one https address, no spaces)")
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if "@" in parts.netloc:
        raise Refused("links with a user name or password in them are refused")
    if host in extra_hosts:
        if parts.scheme not in ("http", "https"):
            raise Refused("only http or https links are accepted")
        return url.strip(), "^generic$"
    if parts.scheme != "https":
        raise Refused("only https links are accepted")
    if host not in YT_HOSTS or parts.port not in (None, 443):
        raise Refused("only YouTube video links are supported (youtube.com or youtu.be)")
    segs = [s for s in parts.path.split("/") if s]
    vid = None
    if host == "youtu.be":
        vid = segs[0] if segs else None
    elif segs[:1] == ["watch"]:
        vid = (parse_qs(parts.query).get("v") or [None])[0]
    elif len(segs) >= 2 and segs[0] in ("shorts", "live", "embed", "v"):
        vid = segs[1]
    if not vid or not ID_RE.match(vid):
        raise Refused("this is not a link to one YouTube video (playlists, channels and search pages are not supported)")
    return f"https://www.youtube.com/watch?v={vid}", "^youtube$"


# ---------------------------------------------------------------------------------------------
# what the video is
# ---------------------------------------------------------------------------------------------
def clean_text(value, limit=120):
    """Other people's text (a title, a channel): drop control and invisible characters, squeeze spaces, cut to length."""
    s = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value or ""))                 # terminal colour codes
    s = re.sub(r"[\t\r\n\v\f]", " ", s)                                          # line breaks become spaces, not nothing
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")              # other control and invisible characters
    return re.sub(r"\s+", " ", s).strip()[:limit]


def approx_size_mb(info):
    pick = lambda d: d.get("filesize") or d.get("filesize_approx") or 0
    total = pick(info) or sum(pick(f) for f in info.get("requested_formats") or [])
    return total / 1e6 if total else None


def summarise(info):
    return {"id": clean_text(info.get("id"), 40), "title": clean_text(info.get("title")), "channel": clean_text(info.get("channel") or info.get("uploader"), 80),
            "duration_s": info.get("duration"), "upload_date": clean_text(info.get("upload_date"), 8), "width": info.get("width"), "height": info.get("height"),
            "fps": info.get("fps"), "approx_size_mb": approx_size_mb(info)}


def check_info(info, limits, generic=False):
    """Raise Refused unless this is one ordinary, finished video within the limits."""
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
        raise Refused("that link is a playlist or a collection; give the link of one video")
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise Refused("live streams are not supported; use the link once the recording is available")
    if info.get("availability") in ("private", "needs_auth", "subscriber_only", "premium_only"):
        raise Refused("this video needs a login; logins and browser cookies are not supported")
    dur = info.get("duration")
    if dur is None and not generic:
        raise Refused("the length of this video is unknown, so it cannot be checked against the limit")
    if dur is not None and dur > limits.max_minutes * 60:
        raise Refused(f"this video is {dur / 60:.0f} minutes long; the limit is {limits.max_minutes} (change it with --max-minutes)")
    size = approx_size_mb(info)
    if size is not None and size > limits.max_mb:
        raise Refused(f"this download would be about {size:.0f} MB; the limit is {limits.max_mb} MB (change it with --max-mb)")


def describe(s):
    mins = f"{s['duration_s'] / 60:.1f} min" if s["duration_s"] else "length unknown"
    size = f"about {s['approx_size_mb']:.0f} MB" if s["approx_size_mb"] else "size unknown"
    res = f"{s['width']}x{s['height']}" if s["width"] and s["height"] else "resolution unknown"
    return [f"title   : {s['title']}", f"channel : {s['channel']}", f"length  : {mins}", f"quality : {res}" + (f", {s['fps']:g} fps" if s["fps"] else ""), f"download: {size}"]


# ---------------------------------------------------------------------------------------------
# yt-dlp
# ---------------------------------------------------------------------------------------------
def load_yt_dlp():
    try:
        import yt_dlp
    except ImportError:
        raise Failed("yt-dlp is not installed. It is optional and separate from this project. Install it with:\n"
                     "    .venv/bin/pip install -r requirements-youtube.txt")
    return yt_dlp.YoutubeDL, yt_dlp.version.__version__


def format_string(height):
    return f"bv*[height<={height}]+ba/b[height<={height}]/wv*+wa/w"


def base_opts(extractor, limits):
    """Options shared by the look-up and the download. No cookies, no login, one video, one extractor, nothing run after the download."""
    return {"noplaylist": True, "allowed_extractors": [extractor], "cachedir": False, "socket_timeout": 30, "retries": 3, "no_warnings": True,
            "format": format_string(limits.max_height), "merge_output_format": "mp4/mkv"}


def _wrap(action, e):
    msg = clean_text(e, 300) or type(e).__name__
    return Failed(f"yt-dlp could not {action}: {msg}\nYouTube changes often: try updating it with  .venv/bin/pip install -U yt-dlp")


def lookup(canonical, extractor, limits, ydl_cls):
    try:
        with ydl_cls(dict(base_opts(extractor, limits), skip_download=True, quiet=True)) as ydl:
            return ydl.extract_info(canonical, download=False)
    except (Refused, Failed):
        raise
    except Exception as e:
        raise _wrap("read this video's details", e)


def ffprobe(path):
    """(duration seconds, width, height, fps) of the first video stream; raises Failed when there is none."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate",
                              "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, timeout=60, check=True).stdout
        doc = json.loads(out)
        st = doc["streams"][0]
        num, den = (st.get("avg_frame_rate") or "0/1").split("/")
        return float(doc["format"]["duration"]), int(st["width"]), int(st["height"]), (float(num) / float(den) if float(den) else 0.0)
    except FileNotFoundError:
        raise Failed("ffprobe is missing (it comes with ffmpeg: macOS  brew install ffmpeg)")
    except (subprocess.SubprocessError, KeyError, IndexError, ValueError):
        raise Failed("the downloaded file has no readable video: " + Path(path).name)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_dir(out_dir):
    out = Path(out_dir)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused(f"{out} already exists and is not empty. Downloads go into a new, empty folder: pick another --out-dir or remove it")
    out.mkdir(parents=True, exist_ok=True)
    return out


def fetch(url, out_dir, confirm=False, limits=None, info_only=False, ydl_cls=None, tool_version=None, extra_hosts=(), how_confirmed="flag", log=print):
    """Look up (and, when confirmed, download) one video. Returns the summary dict, plus 'file' and 'source' when downloaded."""
    limits = limits or Limits()
    canonical, extractor = normalise_url(url, tuple(extra_hosts))
    generic = extractor == "^generic$"
    if ydl_cls is None:
        ydl_cls, tool_version = load_yt_dlp()
    info = lookup(canonical, extractor, limits, ydl_cls)
    if not isinstance(info, dict):
        raise Failed("yt-dlp returned nothing for this link")
    check_info(info, limits, generic)
    summary = summarise(info)
    summary["url"] = canonical
    if info_only:
        return summary
    if not confirm:
        raise Refused("rights not confirmed. " + RIGHTS_TEXT)
    out = prepare_dir(out_dir)
    opts = dict(base_opts(extractor, limits), outtmpl=str(out / "%(id)s.%(ext)s"), restrictfilenames=True, overwrites=False, quiet=False,
                max_filesize=int(limits.max_mb * 1e6), noprogress=False)
    try:
        with ydl_cls(opts) as ydl:
            ydl.extract_info(canonical, download=True)
    except (Refused, Failed):
        raise
    except Exception as e:
        raise _wrap("download this video", e)
    # the finished video is named <id>.<ext>; yt-dlp's byproducts (<id>.f137.mp4, .part, .ytdl) have an extra dot or another suffix
    files = sorted((p for p in out.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXT and "." not in p.stem), key=lambda p: -p.stat().st_size)
    if not files:
        raise Failed("nothing was downloaded (the video may be too large for the limit, or yt-dlp skipped it)")
    video = files[0]
    for p in out.iterdir():                                             # the folder was empty before: anything else is a leftover
        if p != video and p.is_file():
            p.unlink(missing_ok=True)
    dur, w, h, fps = ffprobe(video)
    if dur > limits.max_minutes * 60:
        video.unlink()
        raise Refused(f"the file is {dur / 60:.0f} minutes long; the limit is {limits.max_minutes}. It was deleted")
    if summary["duration_s"] and abs(dur - summary["duration_s"]) > 0.1 * summary["duration_s"] + 2:
        raise Failed(f"the file is {dur:.0f} s but the video is {summary['duration_s']:.0f} s: the download looks incomplete. Remove {out} and try again")
    source = {"source": "youtube" if not generic else "file link", "url": canonical, "id": summary["id"] or video.stem, "title": summary["title"], "channel": summary["channel"],
              "upload_date": summary["upload_date"], "file": video.name, "size_bytes": video.stat().st_size, "sha256": sha256(video), "duration_s": round(dur, 2),
              "width": w, "height": h, "fps": round(fps, 3), "downloaded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "rights_confirmed": True, "rights_confirmed_how": how_confirmed, "tool": f"yt-dlp {tool_version}"}
    (out / "source.json").write_text(json.dumps(source, indent=2) + "\n")
    summary.update({"file": str(video), "source": source})
    return summary


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------
def ask_rights(inp=None, out=print):
    out(RIGHTS_TEXT)
    return (inp or input)("Type YES if this is your video or you have permission to use it: ").strip() == "YES"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="the link of one YouTube video")
    ap.add_argument("--info", action="store_true", help="show the title, length and size and download nothing")
    ap.add_argument("--out-dir", default="work/download", help="a new or empty folder for the video (default: %(default)s)")
    ap.add_argument("--confirm-rights", action="store_true", help="say that you filmed this video or may use it (otherwise you are asked)")
    ap.add_argument("--max-minutes", type=float, default=120, help="refuse longer videos (default: %(default)s)")
    ap.add_argument("--max-mb", type=float, default=2500, help="refuse larger downloads (default: %(default)s)")
    ap.add_argument("--max-height", type=int, default=720, help="download at most this many pixels of height (default: %(default)s; the analysis uses 720)")
    ap.add_argument("--allow-host", action="append", default=[], help=argparse.SUPPRESS)      # for tests: a host that serves a plain video file
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    limits = Limits(args.max_minutes, args.max_mb, args.max_height)
    try:
        confirm, how = args.confirm_rights, "flag"
        if not args.info and not confirm:
            if not sys.stdin.isatty():
                raise Refused("rights not confirmed. " + RIGHTS_TEXT + " Run again with --confirm-rights if that is true.")
            summary = fetch(args.url, args.out_dir, limits=limits, info_only=True, extra_hosts=args.allow_host)
            print("\n".join(describe(summary)))
            if not ask_rights():
                raise Refused("not confirmed, nothing was downloaded")
            confirm, how = True, "typed YES"
        result = fetch(args.url, args.out_dir, confirm=confirm, limits=limits, info_only=args.info, extra_hosts=args.allow_host, how_confirmed=how)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
    except Failed as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    print("\n".join(describe(result)))
    if args.info:
        print("(nothing was downloaded)")
        return
    print(f"\nsaved   : {result['file']}\nsource  : {Path(args.out_dir) / 'source.json'}")
    print(f"Next    : bash run_all.sh {result['file']}   (or /analyze-match {result['file']})")


if __name__ == "__main__":
    main()
