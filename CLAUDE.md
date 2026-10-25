# CLAUDE.md: playbook for an AI assistant working in this repository

You are helping a badminton player analyse a video of their own **doubles** match. The person is
usually not a programmer. Speak plainly, run the commands yourself, show what you found, and be
honest about what is uncertain. This is an **alpha** project, built and checked on one video, so
treat every result as a measurement with error bars, not a verdict.

Start by reading `README.md` (what it does) and `docs/HOW_IT_WORKS.md` (each stage, the file formats).

## Ground rules

1. **Privacy.** Videos show real people, often children and spectators. The analysis runs on this computer and
   the video is never uploaded. But **when you open an image to check it, that image is sent to the AI provider
   as part of this conversation.** Ask the person once, before opening any frame: "To check my work I need to look at
   frames from your video. They are sent to the AI service as part of this chat. Is that OK?" If not, ask them to open
   `work/*_check.jpg` themselves and tell you what they see, and work from the text outputs. Never commit anything under
   `work/` or any video, and run `git status` before any commit. Before publishing images, generate them with
   `tools/anonymize.py` (blurred faces) and have the person look at each one.
2. **No downloading other people's videos.** Do not add or run a video downloader. Ask for a file the
   person filmed or has the right to use. If they give you a link, say you will not fetch it and ask for the file.
3. **Honesty.** Say what a number is based on (how many rallies, which stage) and how sure it is. Never state a
   cause ("you lost because...") from a comparison. Give p-values with sample sizes, and remember that with
   many comparisons some p below 0.05 are expected by chance. If a stage fails or an image looks wrong,
   say so and stop or fix it. Do not carry on with bad data.
4. **Scope.** Doubles only. One fixed camera (a tripod, no panning or zooming). One game. If the video is
   singles, handheld, or moves, say that the pipeline does not support it yet.
5. **Ask before long jobs** (detection is about 2 to 3 minutes per 10 minutes of video on an Apple GPU, much
   longer on CPU). Tell the person what is running.

## Step 0: set up (once)

`bash setup.sh`. It needs ffmpeg and Python 3.10 to 3.12. It prints `Apple GPU (MPS) available: True` on
a Mac with Apple silicon. The weights file (about 40 MB, from Ultralytics) downloads on first use into `models/`.

## Step 1: interview the person (ask these in one message)

1. The path to the video file (their own recording or one they have permission to use).
2. Is it doubles, filmed from a fixed camera? Where is the camera (behind the baseline, at the side, high, low)?
3. The four players' **shirt colours**: you, your partner, opponent 1, opponent 2. Allowed colours: red, white,
   black, grey, blue, green, yellow, orange. The two players of one team must wear different colours. At least one
   shirt should be a bright colour (red, blue, green, yellow, orange) so the program can tell which team is on which half.
   Also: which hand does the person hold the racket in?
4. Is there an on-screen scoreboard? Is the video edited (title cards, a teaser, trimmed rallies) or raw?
5. Do they know who served first and the final score? (Keep the answer: it is used to check the result at the end.)
6. May you look at frames from the video (see rule 1)?

Write `work/players_config.json` from the answers (copy `examples/reference-match/players_config.json`).

## Step 2: run the stages, and look after each one

Use `.venv/bin/python`. Replace `work` with the person's work folder if different. After each stage, **open the check
image yourself** before moving on.

| step | command | what to check |
|---|---|---|
| proxy | `python stages/s00_proxy.py --src VIDEO --out-dir work` | all checks PASS. HDR video is refused: follow the message. Look at `work/s00_check.jpg`: natural colours |
| detect | `python stages/s01_detect.py --proxy work/proxy.mp4 --out work/dets.json` | all PASS. `work/s01_check.jpg`: people boxed |
| court points | `python tools/pick_court_points.py --video work/proxy.mp4 --out work/court_points.json` | a page opens (or open the printed address). The person clicks at least 6 visible court-line crossings; the page draws the court so they can see it fit. If you cannot give them a browser, open the address in your own browser tool and walk them through it |
| calibrate | `python stages/s02_calibrate.py --proxy work/proxy.mp4 --points work/court_points.json --out work/calib.json` | PASS, fit error under 4 px. **Look at `work/s02_check.jpg`: the red lines must lie on the painted lines.** If not, redo the points |
| candidates | `python stages/s03_features.py --proxy work/proxy.mp4 --dets work/dets.json --calib work/calib.json --out work/cand.npz` | writes a count |
| game start | `python stages/s03_find_start.py --proxy work/proxy.mp4 --cand work/cand.npz --calib work/calib.json --out work/game_start.json` | **Show the person `work/start_check.jpg` and ask whether the game starts at the suggested time.** The first tile is before it. Set `"confirmed": true` (and fix `start`, `first_window_on`, `first_window_off` if needed) |
| players | `python stages/s03_players.py --proxy work/proxy.mp4 --cand work/cand.npz --start START --out work/players.npz` | PASS. **Look at `work/s03_check.jpg`: every label must sit on the right person.** If two players are swapped, the shirt colours in `players_config.json` need changing (white versus grey is the hardest pair). No bright shirt colour? pass `--end-change none --first-near A` (or `B`) |

If there is no scoreboard, **stop here** and tell the person: players are tracked, but rallies and who won them cannot be
worked out yet (see `docs/HOW_IT_WORKS.md`, "Scores"). Do not invent scores.

With a scoreboard:

| step | command | what to check |
|---|---|---|
| scoreboard | `python stages/s04a_overlay.py --proxy work/proxy.mp4 --out work/overlay.json` (macOS, yellow digits at the top right like the reference video) | every run decoded; compare 5 of them by eye. Other scoreboards: write `overlay.json` by hand in the same format |
| serves | `python stages/s04_serves.py --players work/players.npz --overlay work/overlay.json --game-start work/game_start.json --out work/serves.json` | court parity (correct vs wrong) clearly apart |
| score | `python stages/s05_score.py --serves work/serves.json --out work/score.json` | 0 disagreements with the scoreboard. **Read the same-player test:** it should be high, and the line "if the direction were wrong" low. If it is the other way round, rerun stage 4 with `--flip-cue` |
| rallies | `python stages/s06_rallies.py --proxy work/proxy.mp4 --serves work/serves.json --score work/score.json --players work/players.npz --out work/points.json` | durations plausible (3 to 40 s) |
| movement | `python stages/s07_movement.py --players work/players.npz --points work/points.json --out work/motion.json` | PASS |
| posture | `python stages/s08_pose.py --proxy work/proxy.mp4 --players work/players.npz --points work/points.json --out work/pose_stats.json` | look at `work/s08_check.jpg`; **check the racket hand on a few swing frames** by eye, the automatic guess can be wrong |
| pickups | `python stages/s09_pickups.py --players work/players.npz --serves work/serves.json --points work/points.json --out work/pickups.json` | it may say NOT USABLE; that is a result, report it |
| numbers | `python stages/s10_report.py --work work` | writes `report_data.json` |

At this point **ask the two check questions**: who served first, and who won? Compare with `work/serves.json`
(rally 1 `server_team`) and the last scoreboard. If the person says the replay is backwards, rerun stage 4 with `--flip-cue`. If
they are not sure, say the winners are unverified.

## Step 3: write the coaching (this is your job, not a script's)

Read `work/report_data.json` and `work/motion.json`. Write two files:

* `work/tips.json`: a list of 3 to 6 objects `{"title", "body", "watch", "sure"}`. `body` states the numbers;
  `watch` lists video times (mm:ss) to check; `sure` says how sure and why (sample size, p-value).
* `work/coaching.md`: the same points in a few short paragraphs for the report.

Rules: every claim cites a number from the files. Order tips by how well the data supports them. Say "no sign of
a difference" rather than "no difference". Give a timestamp to verify each tip. A general coaching idea that
the data does not test (for example "bend your knees more") is allowed only if labelled as general advice.
Do not mention the person's name or anyone else's.

## Step 4: build the outputs

```
.venv/bin/python stages/s10_build_report.py --work work --label "MATCH NAME"
.venv/bin/python stages/s12_images.py --work work --label "MATCH NAME"
.venv/bin/python stages/s11_video.py --proxy work/proxy.mp4 --players work/players.npz --points work/points.json --start START --out work/analysis_video.mp4   # optional
```

Show the person `work/report.md` and the images in `work/images/`. Look at every image for overlapping text before
you show it. These raw images contain people's faces; they are for the person only.

## If something fails

| symptom | cause and fix |
|---|---|
| `players_config.json ... same shirt colour` | two teammates need different colours |
| stage 3 labels swapped | adjust shirt colours; white versus grey is the weakest pair |
| stage 2 error over 4 px | redo the click points; spread them over the court, include near and far lines |
| stage 5 same-player test low in both directions | the winners are unreliable: report that, do not build a won/lost story |
| start finder finds nothing | no repeating serve-setup rhythm; ask the person for the start second |
| MPS errors | `PYTORCH_ENABLE_MPS_FALLBACK=1` is already set; try `--device cpu` in stage 1 |

## Do not

* Download videos, or call any online service with the person's video or frames.
* Skip a check image or a confirmation step to save time.
* Claim causes, or hide a failed stage.
* Commit or push on the person's behalf without being asked.
