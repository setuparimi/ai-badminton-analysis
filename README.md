# Badminton Analysis

![Licence: AGPL-3.0](https://img.shields.io/badge/licence-AGPL--3.0-blue)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)
![Python 3.10 to 3.12](https://img.shields.io/badge/python-3.10--3.12-blue)
![Tested on macOS](https://img.shields.io/badge/tested%20on-macOS-lightgrey)

Give it a video of a **singles or doubles** badminton match, click yourself in a picture, and get a **PDF report**: how the game went,
a coaching plan for you (what is working, what to work on, what to check on video), scouting notes on the opponents
(strengths, possible openings, a game plan to test), the charts, and the moments worth re-watching. It runs on your own computer,
costs nothing, and asks you a few questions first: which video, singles or doubles, which hand you hit with, whether the video shows a live score, and when each game
starts. You do not describe your partner or the opponents: click yourself and they are found for you.
It can also be driven by an AI coding assistant ([Claude Code](https://claude.com/claude-code)) that runs the same steps and checks the results with you.

> **Version 0.2, alpha.** Two routes. With a live score on screen (the reference game) you get the full report with who won each rally. Without one, which is the usual
> case for a match you filmed yourself, you get a report on positions, movement and pace of play for every game in the video. Both were run end to end on real
> matches; singles is tested on synthetic data only. Read [What it cannot do yet](#what-it-cannot-do-yet) before you trust a result.

<p align="center">
<a href="examples/reference-match/match_report.pdf"><img src="examples/reference-match/pdf_preview/page-01.png" width="32%" alt="Cover page of the PDF report: result, short version and contents"></a>
<a href="examples/reference-match/match_report.pdf"><img src="examples/reference-match/pdf_preview/page-03.png" width="32%" alt="Coaching plan page: what to work on, each with a next step, video times and how sure"></a>
<a href="examples/reference-match/match_report.pdf"><img src="examples/reference-match/pdf_preview/page-09.png" width="32%" alt="Scouting page: what the opponents do well and possible openings"></a>
</p>
<p align="center"><em>Three pages of the 13-page example report (<a href="examples/reference-match/match_report.pdf">open the PDF</a>). Charts only, no photographs of people.</em></p>

**Jump to:** [What you get](#what-you-get) · [Example output](#example-output) · [Quick start](#quick-start) · [What it cannot do yet](#what-it-cannot-do-yet) · [How it works](#how-it-works) · [Privacy](#privacy-and-rights)

## What you get

* **`match_report.pdf`**: the report above (the example below is the scoreboard route; without a score on screen the report covers where you and your partner stand,
  how the pair is arranged, how hard each of you works, posture, pace of play and the opponents' habits, and says plainly that it cannot know who won a rally). Cover with the short version; the match; **your coaching plan**; the charts in plain words;
  **scouting the opponents**; moments to check with video times; how sure each number is; a glossary. Charts only, so it is safe to pass on.
* `report.md`: the same facts as text, with the checks that ran.
* 14 images, all shown below (score timeline, serving, rally length, you won-vs-lost, heatmaps, all four players, posture, coaching tips,
  moments to check, how sure, how the computer saw the match, the opponents, where they stood).
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

![Seven coaching points, each with a next step, the video times to watch and how sure the evidence is](examples/reference-match/images/08_coaching_tips.png)

Written by the AI assistant from the numbers: what to work on, what to check on the video, and what is working, each with a next step,
the times to watch and how sure it is. Advice the video cannot test is labelled "general advice"; where the data shows no difference, as with
running here, the tip says there is nothing to fix.

### The opponents

![How the opponents did and how they moved](examples/reference-match/images/12_opponents.png)

The other team from their side: how they did serving and receiving, by rally length and by server, and how each of them plays (distance, speed, time at the
back, who plays the net side). With no shuttle tracking this is about results and positions, not shot types.

### Where the opponents stood

![Heatmaps of where each opponent stood, and how much of each zone they covered](examples/reference-match/images/13_opponent_positions.png)

Where each opponent stood in their own half, and how much of a 3 x 3 split of the half at least one of them covered. It shows where they stood, not where
they lost points. Only the rallies when they were near the camera are used, because far-half positions are rougher.

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

Then start the guided run:

```bash
.venv/bin/python tools/analyze.py
```

It asks, one at a time: where the video is (a file, or a YouTube link to a match you filmed) and what to call the match; **singles or doubles**; **which hand
you hit with**; whether the video shows a **live score** (usually no); and when each game starts and ends (Enter for one game, the whole video). You can give a final score
per game too (used to check the number of plays found). Then it makes a small copy of the video and, while it finds the people in it, opens two pages in your browser:
**click where the painted court lines cross**, then **click yourself** in a few pictures of the game. In doubles your partner and the opponents are found for you (the other person
on your half, the two on the other half), and the page works out how you can be told apart (shirt colour, shade, or light against dark shorts) and checks that across about 12 seconds of video.
After that nothing more is asked: tracking, plays, positions, movement, posture, coaching and scouting notes and the PDF are made. The result is `work_<name>/match_report.pdf`.
Everything can be passed as flags instead (`--help`), and running it again with the same `--work` folder carries on where it stopped.

Prefer an AI assistant? Open [Claude Code](https://claude.com/claude-code) in that folder and type:

```
/analyze-match path/to/your/video.mp4
```

Your match is on YouTube? Give the link instead (`/analyze-match https://youtu.be/...`). After you confirm that you filmed the video or may use it, Claude fetches that one video
with `tools/fetch_video.py` (an optional extra: `.venv/bin/pip install -r requirements-youtube.txt`) and carries on. A link only gets you the file: the video still has to fit
(see the next section).

(`/analyze-match` on its own works too: Claude asks for the file first.)

Claude reads [`CLAUDE.md`](CLAUDE.md), asks the same questions in one message, runs `tools/analyze.py`, looks at the label check sheets with you and can write the coaching words itself.
The two pages that need you (court lines, click yourself) open in your own browser. With a live score on screen the scoreboard route of [`run_all.sh`](run_all.sh) is used and adds one more
step, confirming where the game starts. At the end you get the PDF.
The full, non-technical walkthrough is in [docs/USING_WITH_CLAUDE_CODE.md](docs/USING_WITH_CLAUDE_CODE.md).
Prefer to run it yourself? See [`run_all.sh`](run_all.sh) and [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## What it cannot do yet

Please read this. It is the honest list.

* **One fixed camera.** Moving cameras are not supported, and most broadcast-style matches on YouTube (camera cuts, close-ups, replays) do not work; a club match filmed from a tripod does.
  Several games in one video are fine (you say when each starts); the scoreboard route handles one game at a time.
* **Singles** is supported only in the report without a score, and only tested on synthetic data so far. The scoreboard route is doubles only.
* **Without a live score the report cannot know who won a rally,** who served, what shot was played or where the shuttle landed. It reports positions, formation, movement, posture
  and pace of play, and says so. Plays are found from movement and the sound of the shuttle (37 and 32 found against 40 and 34 on the one match where the result card allowed a check);
  the sound also picks up other courts, so single plays can be merged or split.
* **Telling you from your partner** uses clothes (shirt colour, shade, or light against dark shorts). It is checked over about 12 seconds around your click and by eye on a sheet of 12 moments per game; in
  the one long match checked this way, 2 of 12 moments in game 1 and 0 of 10 in game 2 had your labels swapped (when the two of you overlapped or one of you stood right at the camera). If the two of you dress alike the page says so and stops.
  The two opponents are tracked as a pair when they look alike.
* **A wide-angle lens** (a GoPro, say) works, but the far half of the court is seen small, so far-side depth and distance are rougher; compare players on the same side.
* **Who won each rally comes from a scoreboard** on the scoreboard route: the tested reader needs a yellow server-first score like the reference video.
* **Who served is inferred** from how the players stand before each serve. It is backed by an independent check, but
  parts of the reference game rest on that cue alone (see the "how sure" image).
* **Far-court positions are rougher** than near-court ones, and anything outside the camera's view is missed.
* **No shuttle tracking**, so no shot types, smash counts or landing spots. The opponent scouting is therefore about results, rally length,
  roles and where they stood, never about what shots they play.
* **One game, about 50 rallies**: most comparisons cannot detect small effects. Treat patterns as questions to check on video.
* **Tested on one machine and one video.** Expect to adjust things on yours. Please open an issue with what broke.

## How it works

![From a match video to a report: the stages in order, and which need a person](docs/img/pipeline.png)

Blue steps run on their own and end with a PASS or FAILED check. Orange steps need a person to click or confirm. The black step is where the AI assistant writes the coaching and scouting words from the numbers.

| stage | does | output |
|---|---|---|
| 0 | makes a standard 1280x720, 30 fps copy | `proxy.mp4` |
| 1 | finds every person (YOLO) | `dets.json` |
| 2 | fits the court to the picture from points you click | `calib.json` |
| 3 | you click yourself (partner and opponents found for you); follows the players in court metres | `players_config.json`, `players.npz` |
| 6f, 7f | no score on screen: finds the plays from movement and shuttle sound; positions, formation, movement per player and pair | `play_windows.json`, `free_stats.json` |
| 4a to 6 | reads the scoreboard, works out who served and won, marks rallies | `points.json` |
| 7 | distance, speed, where you stood, how your pair covers the court | `motion.json` |
| 7b | the opponents: results, roles, formation, zones | `opponents.json` |
| 8 | body landmarks for all four players: knee bend, racket hand | `pose_stats.json` |
| 9 | looks for shuttle pickups (did not work on the reference video) | `pickups.json` |
| 10 and 12 | text report and images; the assistant writes `tips.json` and `scouting.json` | `report.md`, `images/` |
| 13 | the PDF report (scoreboard route) | `match_report.pdf` |
| 14a, 14 | no score on screen: coaching and scouting words by rules (an assistant can improve them), then the PDF | `tips.json`, `scouting.json`, `match_report.pdf` |
| 11 | overlay video with a spoken summary (optional) | `analysis_video.mp4` |

Details, file formats and how to extend it: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).
How this project was built, what went wrong and what was learned: [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md).

## Privacy and rights

* The analysis runs **on your computer**. Your video is never uploaded by this project.
* **If you use an AI assistant, frames it looks at are sent to that provider** as part of the chat. The assistant is
  told to ask you first. If that is a problem (for example children in the video), look at the check images yourself.
* Videos show real people. Only analyse video you filmed or have permission to use, and do not publish frames that
  show faces. `tools/anonymize.py` blurs them for examples, but no automatic blur is guaranteed: look at every image.
* The PDF contains charts only. The pages where you click (court lines, who is who) run in your own browser and show frames only there.
* No video, frame, or personal data from the reference match is included beyond blurred images and numbers. Nothing is downloaded unless you ask: the one exception is the optional `tools/fetch_video.py`, which saves a single YouTube video you filmed or may use (see below).

## Licence and credits

[AGPL-3.0](LICENSE). The person detector and pose model are [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
(AGPL-3.0); their weights download on first run and are not included here. Court geometry follows the Badminton World
Federation laws of badminton. On macOS the optional scoreboard reader uses Apple's Vision framework.

## Contributing

Issues and pull requests are welcome, especially: results on other videos, a way to enter the score by hand, a Windows/Linux
scoreboard reader, a way to enter the score of each rally by hand, and singles tested on a real video. See [CONTRIBUTING.md](CONTRIBUTING.md).
