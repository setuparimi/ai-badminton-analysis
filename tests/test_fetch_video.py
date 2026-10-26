"""Checks of the video fetcher: which links it accepts, what it refuses, and the download path, with a fake yt-dlp (no network)
and, when yt-dlp and ffmpeg are installed, with the real yt-dlp against a tiny local web server (still no YouTube).
Run: python -m unittest discover -s tests"""
import contextlib
import hashlib
import http.server
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import fetch_video as fv  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
CLIP_SECONDS = 2
TMP = None
CLIP = None


def setUpModule():
    global TMP, CLIP
    TMP = tempfile.TemporaryDirectory()
    if HAVE_FFMPEG:
        CLIP = Path(TMP.name) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration={CLIP_SECONDS}:size=320x240:rate=15", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", str(CLIP)], check=True)


def tearDownModule():
    TMP.cleanup()


VID = "dQw4w9WgXcQ"
GOOD_INFO = {"id": VID, "title": "Saturday doubles", "channel": "A club", "duration": CLIP_SECONDS, "upload_date": "20260101", "width": 320, "height": 240, "fps": 15,
             "requested_formats": [{"filesize": 3_000_000}], "availability": "public"}


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: answers look-ups and 'downloads' by copying the test clip (plus the leftovers a real merge can leave)."""
    info = dict(GOOD_INFO)
    seen = []
    raise_with = None

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        if FakeYDL.raise_with:
            raise FakeYDL.raise_with
        if download:
            d = Path(self.opts["outtmpl"]).parent
            shutil.copy(CLIP, d / f"{self.info['id']}.mp4")
            (d / f"{self.info['id']}.f137.mp4").write_bytes(b"video-only leftover")
            (d / f"{self.info['id']}.f140.m4a.part").write_bytes(b"x")
        return dict(self.info)


def fake(**info):
    FakeYDL.info = dict(GOOD_INFO, **info)
    FakeYDL.seen = []
    FakeYDL.raise_with = None
    return FakeYDL


class Links(unittest.TestCase):
    def test_accepted_forms_become_one_canonical_link(self):
        want = f"https://www.youtube.com/watch?v={VID}"
        for url in (f"https://www.youtube.com/watch?v={VID}", f"https://youtube.com/watch?v={VID}&list=PLxyz&t=90s&index=3", f"https://youtu.be/{VID}?si=abc",
                    f"https://m.youtube.com/watch?v={VID}", f"https://www.youtube.com/shorts/{VID}", f"https://www.youtube.com/live/{VID}",
                    f"https://www.youtube.com/embed/{VID}", f"  https://youtu.be/{VID}  ", f"https://YOUTU.BE/{VID}"):
            with self.subTest(url):
                self.assertEqual(fv.normalise_url(url), (want, "^youtube$"))

    def test_refused_links(self):
        bad = {"playlist": "https://www.youtube.com/playlist?list=PL1234567890", "channel": "https://www.youtube.com/@someone", "search": "https://www.youtube.com/results?search_query=x",
               "home": "https://www.youtube.com/", "plain http": f"http://www.youtube.com/watch?v={VID}", "other site": f"https://vimeo.com/{VID}",
               "look-alike host": f"https://youtube.com.evil.example/watch?v={VID}", "look-alike path": f"https://evil.example/youtube.com/watch?v={VID}",
               "user info": "https://user:pw" + chr(64) + f"www.youtube.com/watch?v={VID}", "odd port": f"https://www.youtube.com:8443/watch?v={VID}", "short id": "https://youtu.be/abc",
               "bad id": "https://youtu.be/" + "!" * 11, "no id": "https://www.youtube.com/watch", "space": f"https://youtu.be/{VID} extra", "newline": f"https://youtu.be/{VID}\nx",
               "empty": "", "too long": "https://youtu.be/" + "a" * 400, "local file": "file:///etc/passwd", "local server": f"http://127.0.0.1:8000/{VID}.mp4", "not text": 5}
        for label, url in bad.items():
            with self.subTest(label), self.assertRaises(fv.Refused):
                fv.normalise_url(url)

    def test_an_extra_host_is_for_plain_video_files_only(self):
        self.assertEqual(fv.normalise_url("http://127.0.0.1:8123/clip.mp4", ("127.0.0.1",)), ("http://127.0.0.1:8123/clip.mp4", "^generic$"))
        with self.assertRaises(fv.Refused):
            fv.normalise_url("ftp://127.0.0.1/clip.mp4", ("127.0.0.1",))
        with self.assertRaises(fv.Refused):
            fv.normalise_url("http://user" + chr(64) + "127.0.0.1/clip.mp4", ("127.0.0.1",))


class Text(unittest.TestCase):
    def test_other_peoples_text_is_cleaned(self):
        self.assertEqual(fv.clean_text("Match\x1b[31m red\x1b[0m\nline two\u200b\u202e end"), "Match red line two end")
        self.assertEqual(fv.clean_text("a\tb\r\nc"), "a b c")
        self.assertEqual(len(fv.clean_text("x" * 500, 120)), 120)
        self.assertEqual(fv.clean_text(None), "")


class Rules(unittest.TestCase):
    def refuses(self, why, **info):
        with self.assertRaises(fv.Refused, msg=why):
            fv.check_info(dict(GOOD_INFO, **info), fv.Limits())

    def test_refusals(self):
        self.refuses("playlist", _type="playlist")
        self.refuses("entries", entries=[{}])
        self.refuses("live", is_live=True)
        self.refuses("upcoming", live_status="is_upcoming")
        self.refuses("private", availability="private")
        self.refuses("members only", availability="subscriber_only")
        self.refuses("unknown length", duration=None)
        self.refuses("too long", duration=121 * 60)
        self.refuses("too big", requested_formats=[{"filesize": 3_000_000_000}])

    def test_an_ordinary_video_passes_and_limits_can_be_raised(self):
        fv.check_info(dict(GOOD_INFO), fv.Limits())
        fv.check_info(dict(GOOD_INFO, duration=150 * 60), fv.Limits(max_minutes=200))
        fv.check_info(dict(GOOD_INFO, duration=None), fv.Limits(), generic=True)        # a plain file link has no metadata: checked after the download

    def test_options_never_carry_a_login_or_cookies_and_pin_one_extractor(self):
        o = fv.base_opts("^youtube$", fv.Limits())
        self.assertTrue(o["noplaylist"])
        self.assertEqual(o["allowed_extractors"], ["^youtube$"])
        for k in o:
            self.assertNotIn("cookie", k.lower())
            self.assertNotIn("username", k.lower())
            self.assertNotIn("password", k.lower())
            self.assertNotIn("exec", k.lower())
        self.assertIn("height<=720", o["format"])
        self.assertIn("height<=480", fv.format_string(480))


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class Download(unittest.TestCase):
    def run_fetch(self, out, **kw):
        kw.setdefault("ydl_cls", FakeYDL)
        kw.setdefault("tool_version", "9.9.9")
        kw.setdefault("log", lambda *a: None)
        with contextlib.redirect_stdout(io.StringIO()):
            return fv.fetch(f"https://youtu.be/{VID}", out, **kw)

    def test_info_only_downloads_and_creates_nothing(self):
        fake()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dl"
            s = self.run_fetch(out, info_only=True)
            self.assertFalse(out.exists())
            self.assertEqual((s["id"], s["title"], s["duration_s"]), (VID, "Saturday doubles", CLIP_SECONDS))
            self.assertAlmostEqual(s["approx_size_mb"], 3.0)
            self.assertTrue(all(o.get("skip_download") for o in FakeYDL.seen))

    def test_without_confirmation_nothing_is_downloaded(self):
        fake()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dl"
            with self.assertRaises(fv.Refused) as cm:
                self.run_fetch(out)
            self.assertIn("Terms of Service", str(cm.exception))
            self.assertFalse(out.exists())

    def test_a_confirmed_download(self):
        fake(title="Evil \x1b[31m title\n")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dl"
            r = self.run_fetch(out, confirm=True)
            self.assertEqual(sorted(p.name for p in out.iterdir()), [f"{VID}.mp4", "source.json"])       # leftovers removed, file named by id not title
            src = json.loads((out / "source.json").read_text())
            self.assertEqual(Path(r["file"]).name, f"{VID}.mp4")
            self.assertEqual(src["sha256"], hashlib.sha256((out / f"{VID}.mp4").read_bytes()).hexdigest())
            self.assertEqual((src["id"], src["width"], src["height"], src["rights_confirmed"], src["tool"]), (VID, 320, 240, True, "yt-dlp 9.9.9"))
            self.assertEqual(src["url"], f"https://www.youtube.com/watch?v={VID}")
            self.assertNotIn("\x1b", src["title"])
            self.assertNotIn("\n", src["title"])
            self.assertAlmostEqual(src["duration_s"], CLIP_SECONDS, delta=0.3)
            dl_opts = FakeYDL.seen[-1]
            self.assertTrue(dl_opts["restrictfilenames"] and dl_opts["noplaylist"] and not dl_opts["overwrites"])
            self.assertIn("%(id)s", dl_opts["outtmpl"])
            self.assertNotIn("title", dl_opts["outtmpl"])

    def test_a_folder_that_is_not_empty_is_left_alone(self):
        fake()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dl"
            out.mkdir()
            (out / "mine.txt").write_text("keep me")
            with self.assertRaises(fv.Refused):
                self.run_fetch(out, confirm=True)
            self.assertEqual([p.name for p in out.iterdir()], ["mine.txt"])
            self.assertEqual((out / "mine.txt").read_text(), "keep me")

    def test_an_incomplete_download_is_reported(self):
        fake(duration=60)                                   # the look-up says a minute, the file has two seconds
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(fv.Failed) as cm:
            self.run_fetch(Path(tmp) / "dl", confirm=True)
        self.assertIn("incomplete", str(cm.exception))

    def test_a_file_longer_than_the_limit_is_deleted(self):
        fake()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dl"
            with self.assertRaises(fv.Refused):
                self.run_fetch(out, confirm=True, limits=fv.Limits(max_minutes=0.01))
            self.assertFalse(list(out.glob("*.mp4")))

    def test_an_error_from_yt_dlp_becomes_a_plain_message(self):
        fake()
        FakeYDL.raise_with = RuntimeError("ERROR: Sign in to confirm\x1b[0m you're not a bot\nTraceback...")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(fv.Failed) as cm:
            self.run_fetch(Path(tmp) / "dl", confirm=True)
        msg = str(cm.exception)
        self.assertIn("pip install -U yt-dlp", msg)
        self.assertNotIn("\x1b", msg)

    def test_a_playlist_answer_is_refused_before_any_download(self):
        fake(_type="playlist", entries=[{}])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dl"
            with self.assertRaises(fv.Refused):
                self.run_fetch(out, confirm=True)
            self.assertFalse(out.exists())
            self.assertTrue(all(o.get("skip_download") for o in FakeYDL.seen))


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe")
class CommandLine(unittest.TestCase):
    def run_main(self, *argv, tty=False):
        fake()
        out, err = io.StringIO(), io.StringIO()
        stdin = mock.Mock()
        stdin.isatty.return_value = tty
        with mock.patch.object(fv, "load_yt_dlp", return_value=(FakeYDL, "9.9.9")), mock.patch.object(sys, "stdin", stdin), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                fv.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_no_terminal_and_no_flag_means_no_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = self.run_main(f"https://youtu.be/{VID}", "--out-dir", str(Path(tmp) / "dl"))
            self.assertEqual(code, 2)
            self.assertIn("--confirm-rights", err)
            self.assertFalse((Path(tmp) / "dl").exists())

    def test_info_prints_the_details(self):
        code, out, err = self.run_main(f"https://youtu.be/{VID}", "--info")
        self.assertEqual(code, 0)
        self.assertIn("Saturday doubles", out)
        self.assertIn("nothing was downloaded", out)

    def test_typing_yes_in_a_terminal_confirms_and_anything_else_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("builtins.input", return_value="yes"):
                code, _, err = self.run_main(f"https://youtu.be/{VID}", "--out-dir", str(Path(tmp) / "a"), tty=True)
            self.assertEqual(code, 2)
            self.assertFalse((Path(tmp) / "a").exists())
            with mock.patch("builtins.input", return_value="YES"):
                code, out, _ = self.run_main(f"https://youtu.be/{VID}", "--out-dir", str(Path(tmp) / "b"), tty=True)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((Path(tmp) / "b" / "source.json").read_text())["rights_confirmed_how"], "typed YES")

    def test_a_bad_link_exits_2_with_a_reason(self):
        code, _, err = self.run_main("https://www.youtube.com/playlist?list=PL1234567890", "--info")
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err)


def real_yt_dlp():
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(HAVE_FFMPEG and real_yt_dlp(), "needs ffmpeg and yt-dlp (pip install -r requirements-youtube.txt)")
class RealYtDlpAgainstALocalServer(unittest.TestCase):
    """The real yt-dlp doing a real download, from a tiny web server on this computer instead of YouTube."""

    def test_download_through_yt_dlp(self):
        serve_dir = Path(TMP.name)

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(serve_dir), **k)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/clip.mp4"
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "dl"
                with contextlib.redirect_stdout(io.StringIO()):
                    r = fv.fetch(url, out, confirm=True, extra_hosts=("127.0.0.1",))
                src = json.loads((out / "source.json").read_text())
                self.assertEqual(src["source"], "file link")
                self.assertTrue(src["tool"].startswith("yt-dlp "))
                self.assertEqual((src["width"], src["height"]), (320, 240))
                self.assertEqual(src["sha256"], hashlib.sha256(Path(r["file"]).read_bytes()).hexdigest())
                # the same address is refused when the host is not allowed
                with self.assertRaises(fv.Refused):
                    fv.fetch(url, Path(tmp) / "dl2", confirm=True)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
