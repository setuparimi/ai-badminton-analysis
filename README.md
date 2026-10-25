# Badminton Analysis

![Licence: AGPL-3.0](https://img.shields.io/badge/licence-AGPL--3.0-blue)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)
![Python 3.10 to 3.12](https://img.shields.io/badge/python-3.10--3.12-blue)
![Tested on macOS](https://img.shields.io/badge/tested%20on-macOS-lightgrey)

Turn a video of a **doubles** badminton game into numbers you can act on: where each player stood, who served,
how long the rallies were, how far you ran in rallies you won versus lost, how you hold your body, and a short
list of moments worth re-watching. It runs on your own computer, costs nothing, and is built to be driven by an
AI coding assistant ([Claude Code](https://claude.com/claude-code)) that asks you a few questions, runs the steps, and
writes the coaching notes from the numbers.

> **Status: alpha.** Built and checked end to end on **one** video (an edited game with an on-screen scoreboard).
> Everything else is untested. Read [What it cannot do yet](#what-it-cannot-do-yet) before you trust a result.

**Jump to:** [Example output](#example-output) · [Quick start](#quick-start) · [What it cannot do yet](#what-it-cannot-do-yet) · [How it works](#how-it-works) · [Privacy](#privacy-and-rights)

![Match at a glance: score timeline and rally lengths](examples/reference-match/images/01_match_summary.png)

## What you get

* `report.md`: the match in numbers, with how sure each number is, and the checks that ran.
* About 11 images (all shown below): score timeline, serving, rally length, you won-vs-lost, heatmaps, all four players,
  posture, coaching tips, "moments to check" with video times, a page on how reliable each part is, and the check pictures.
* Optionally an overlay video (player labels, score bar, top-down mini-map, a spoken summary).

## Example output

Everything in this section came from **one** reference game, the only video the pipeline has been built and checked
on. The video itself is not in this repo. Faces and the crowd in the photographs are blurred, and all numbers are
estimates from video. The files, data and full report are in [`examples/reference-match/`](examples/reference-match/).

Blue always means your team (or a rally you won), orange means the opponents (or a rally you lost).

### Serving and receiving

![Serving and receiving: share of rallies won, by who served, with a timeline of every rally you served](examples/reference-match/images/02_serving.png)

Your team won 61% of rallies when serving and 50% when receiving (p = 0.58, no real gap). Of the rallies you served you won
4 of 10, your partner 9 of 13 (p = 0.22). The timeline marks every rally you served, with video times to check.

### Rally length

![Rally length: share of rallies won by duration, and every rally as a dot](examples/reference-match/images/03_rally_length.png)

Rallies under 6 seconds were won 10 of 13 times, longer ones 19 of 39. That is a hint (p = 0.11), not proof. Each dot is one rally.

### You: rallies won versus lost

![Nine movement measures for you, split by won and lost rallies](examples/reference-match/images/04_you_won_vs_lost.png)

Nine measures of how you moved, split by rallies won and lost. Almost everything is flat. One p-value is small (staying within
1.5 m of your partner, p = 0.03), but with nine comparisons one is expected by chance, so the page marks it as a
question for the video, not a finding.

### Where you and your partner stood

![Heatmaps of where you and your partner stood in won and lost rallies](examples/reference-match/images/05_heatmaps.png)

Time spent in your own half of the court, from the court fit, shown separately for won and lost rallies. Darker means more time.
Parts of the court outside the camera view are under-counted.

### All four players

![Distance, speed and serves for all four players](examples/reference-match/images/06_players.png)

Distance run, distance per rally, mean speed and rallies served for all four players. Each was followed in 90% to 96% of frames.

### Posture (near half only)

![Knee angle and racket-hand height, with sample skeleton frames](examples/reference-match/images/07_posture.png)

Knee angle and how often the racket hand is above the hip, with sample frames so you can see that the body landmarks sit on
the body. It only works while a player is near the camera.

### Coaching tips

![Six coaching tips, each with the video times to watch and how sure the evidence is](examples/reference-match/images/08_coaching_tips.png)

Written by the AI assistant from the numbers and ranked by how much the video supports them. Each tip says which times to watch
and how sure it is. Where the data shows no difference, as with running here, the first tip says there is nothing to fix.

### Moments to check on the video

![A table of video times, rallies and what to look at](examples/reference-match/images/09_moments_to_check.png)

A list of video times with the rally, the score and what to look at, so you can open the clip and see whether the numbers match
what you remember.

### How sure is each number?

![Which rallies were independently confirmed, and the PASS or FAILED result of each stage](examples/reference-match/images/10_how_sure.png)

Blue marks blocks of rallies whose winners were confirmed a second way; grey marks blocks that rest on one cue. The right side
is the check each stage ran. Stage 9 (shuttle pickups) is marked **not used** because it did no better than chance.

### How the computer saw the match

![The court fit, the overlay video frames and the four players followed](examples/reference-match/images/11_how_it_was_seen.png)

The check pictures behind the numbers: court lines fitted on the floor, the overlay video with labels, score bar and mini-map, and
the four players followed. If a label sits on the wrong person, the numbers from that stage are wrong.

## Quick start

You need: a computer (tested on a Mac with Apple silicon; Linux and Windows are untested and run on the CPU),
Python 3.10 to 3.12, [ffmpeg](https://ffmpeg.org), and a video from a **fixed camera** (see the
[filming guide](docs/FILMING_GUIDE.md)).

```bash
git clone https://github.com/setuparimi/ai-badminton-analysis.git
cd ai-badminton-analysis
bash setup.sh
```

Then open [Claude Code](https://claude.com/claude-code) in that folder and type:

```
/analyze-match path/to/your/video.mp4
```

Claude reads [`CLAUDE.md`](CLAUDE.md), asks you about the players and the camera, and runs the steps. Two of them need
you: clicking a few court lines on a photo (a small page opens), and confirming where the game starts. The full,
non-technical walkthrough is in [docs/USING_WITH_CLAUDE_CODE.md](docs/USING_WITH_CLAUDE_CODE.md).
Prefer to run it yourself? See [`run_all.sh`](run_all.sh) and [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## What it cannot do yet

Please read this. It is the honest list.

* **Doubles only**, one fixed camera, one game. Singles, moving cameras and multi-game matches are not supported.
* **Who won each rally comes from a scoreboard.** The tested path reads the score shown on screen. Without a
  scoreboard the program tracks the players but stops before rallies and won/lost splits. A way to enter the score by
  hand is the most useful missing piece.
* **Who served is inferred** from how the players stand before each serve. It is backed by an independent check, but
  parts of the reference game rest on that cue alone (see the "how sure" image).
* **Far-court positions are rougher** than near-court ones, and anything outside the camera's view is missed.
* **No shuttle tracking**, so no shot types, smash counts or landing spots.
* **One game, about 50 rallies**: most comparisons cannot detect small effects. Treat patterns as questions to check on video.
* **Tested on one machine and one video.** Expect to adjust things on yours. Please open an issue with what broke.

## How it works

![From a match video to a report: the stages in order, and which need a person](docs/img/pipeline.png)

Blue steps run on their own and end with a PASS or FAILED check. Orange steps need a person to look, click or confirm.

| stage | does | output |
|---|---|---|
| 0 | makes a standard 1280x720, 30 fps copy | `proxy.mp4` |
| 1 | finds every person (YOLO) | `dets.json` |
| 2 | fits the court to the picture from points you click | `calib.json` |
| 3 | follows the four players in court metres, finds the game start | `players.npz` |
| 4a to 6 | reads the scoreboard, works out who served and won, marks rallies | `points.json` |
| 7 | distance, speed, where you stood, how your pair covers the court | `motion.json` |
| 8 | body landmarks: knee bend, racket hand | `pose_stats.json` |
| 9 | looks for shuttle pickups (did not work on the reference video) | `pickups.json` |
| 10 and 12 | report and images | `report.md`, `images/` |
| 11 | overlay video with a spoken summary (optional) | `analysis_video.mp4` |

Details, file formats and how to extend it: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).
How this project was built, what went wrong and what was learned: [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md).

## Privacy and rights

* The analysis runs **on your computer**. Your video is never uploaded by this project.
* **If you use an AI assistant, frames it looks at are sent to that provider** as part of the chat. The assistant is
  told to ask you first. If that is a problem (for example children in the video), look at the check images yourself.
* Videos show real people. Only analyse video you filmed or have permission to use, and do not publish frames that
  show faces. `tools/anonymize.py` blurs them for examples, but no automatic blur is guaranteed: look at every image.
* No video, frame, or personal data from the reference match is included beyond blurred images and numbers. This repo does not download videos from the internet.

## Licence and credits

[AGPL-3.0](LICENSE). The person detector and pose model are [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
(AGPL-3.0); their weights download on first run and are not included here. Court geometry follows the Badminton World
Federation laws of badminton. On macOS the optional scoreboard reader uses Apple's Vision framework.

## Contributing

Issues and pull requests are welcome, especially: results on other videos, a way to enter the score by hand, a Windows/Linux
scoreboard reader, and singles support. See [CONTRIBUTING.md](CONTRIBUTING.md).
