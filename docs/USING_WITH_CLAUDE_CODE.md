# Using Badminton Analysis with Claude Code (no programming needed)

This guide is for a player who wants results, not code. Allow about 30 minutes the first time, most of it waiting
for the computer.

## 1. What you need

| thing | how to get it |
|---|---|
| A video of your doubles match from a **fixed** camera | see [FILMING_GUIDE.md](FILMING_GUIDE.md). A phone on a tripod works |
| A Mac (Apple silicon is best) | Linux and Windows are untested |
| ffmpeg | Mac: `brew install ffmpeg` (install Homebrew first from brew.sh if you do not have it) |
| Python 3.10, 3.11 or 3.12 | check with `python3 --version` |
| Claude Code | install it from <https://claude.com/claude-code>. It needs a Claude account |

## 2. Get the project

Open the Terminal app and run these three lines, one at a time:

```bash
git clone https://github.com/setuparimi/ai-badminton-analysis.git
cd ai-badminton-analysis
bash setup.sh
```

`setup.sh` takes a few minutes and downloads about 1 GB (PyTorch). It ends with a short list of versions. On a Mac
with Apple silicon it says `Apple GPU (MPS) available: True`.

## 3. Start Claude in the project folder

In the same Terminal window type `claude` and press Return. Then type:

```
/analyze-match /full/path/to/your/video.mp4
```

(Tip: drag the video file into the Terminal window to paste its path.)

If your Claude Code does not show `/analyze-match`, paste this instead:

> Analyse my badminton doubles video at `/full/path/to/your/video.mp4`. Follow CLAUDE.md in this folder exactly:
> interview me first, run each step, check every image, and tell me plainly what is solid and what is weak.

## 4. What Claude will ask you

* Where the video is, and whether you filmed it (or may use it).
* Whether it is doubles, and where the camera was.
* The **shirt colour of each of the four players** (you, partner, two opponents) and which hand you hold the racket in.
* Whether the video has an on-screen scoreboard, and whether it is edited or raw.
* If you remember who served first and the final score (it uses this to check itself).
* **Permission to look at frames.** When Claude opens a picture to check its work, that picture is sent to the AI
  service as part of your chat. The video itself is not uploaded. If you say no, Claude asks you to look at the
  pictures yourself and describe them.

## 5. The two things you do by hand

1. **Click the court.** A page opens with a photo of your court. Click a landmark on the small diagram, then click the
   same spot on the photo. Do at least 6, spread out: some near the camera, some far, some left and some right. The page draws the
   court on the photo as you go and tells you if it does not fit. Press Save.
2. **Confirm the game start.** Claude shows you a strip of pictures around the time it thinks the game begins (titles, teasers
   and warm-ups can fool it). You say yes, or give the right time.

## 6. What you get

Everything is saved in a folder called `work/` inside the project:

* `work/report.md`: open it in any text editor or on GitHub. It starts with what was measured, what was inferred and how sure.
* `work/images/`: about 11 pictures. Start with `01_match_summary.png`, then `08_coaching_tips.png` and `09_moments_to_check.png`.
* `work/analysis_video.mp4` (if you ask): your video with player labels, a score bar and a top-down mini-map.

## 7. How to read the results

* **"No real gap" or a big p-number** (above 0.2) means the data does not show a difference. It does not prove there is none.
* One game has about 50 rallies. That cannot reveal small effects. Look for patterns that repeat across several games.
* **Moments to check** lists video times. Open your video at those times and see if the numbers match what you remember.
* The **how sure** image shows which parts were independently confirmed and which rest on one guess.

## 8. If something goes wrong

| what you see | do this |
|---|---|
| `setup.sh` says ffmpeg is missing | `brew install ffmpeg`, then run `bash setup.sh` again |
| Labels on the wrong player in a picture | tell Claude; the shirt colours may need changing (white versus grey is the hardest pair) |
| "no repeating serve-setup rhythm found" | tell Claude the second the game starts |
| The court lines do not match the painted lines | redo the clicks; spread the points out more |
| No scoreboard, so it stops after tracking | expected for now: players are tracked but rallies and winners need the score. See "Scores" in [HOW_IT_WORKS.md](HOW_IT_WORKS.md) |

## 9. Privacy in one paragraph

Your video stays on your computer. Frames Claude looks at (only with your permission) go to the AI provider as part of the
chat. Do not publish frames showing faces. If you want to share example pictures, use `tools/anonymize.py` and look at
each image before posting.

## Other AI tools

This repo is written and tested with Claude Code. [`CLAUDE.md`](../CLAUDE.md) is plain text, so any assistant that can run
commands in a folder and open images could follow it, but that has not been tried. If you try one, please say how it went in an issue.
