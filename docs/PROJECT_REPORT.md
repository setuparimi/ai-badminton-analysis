# Project report: Badminton Analysis (alpha)

What was built, how it was checked, what went wrong along the way, and what should happen next. Written to be
read by someone deciding whether to trust, use or extend the project.

## 1. In one paragraph

A local, free pipeline that takes a fixed-camera video of one doubles badminton game and produces player positions in court metres,
rallies with start and end times, a replay of the score, per-rally movement and posture numbers, a report and a set of images, with an AI
assistant writing the coaching text from the numbers. It was built and checked on a single video. On that video every automatic check passed
except one stage (shuttle pickups), which failed its own validation and is not used. The most reliable outputs are the score and rally timings
and the positions of the near-court players. The least reliable are the winner of each rally in some blocks of the game, and anything about far-court
players.

## 2. The reference video, and why it matters

* 11 minutes at 640x360, 30 fps, filmed low from the side of the court. Not a clean, high, behind-the-baseline view.
* It turned out to be an **edited full game**, not raw footage: a title card, a 45-second highlights teaser, trimmed dead time (about 11 seconds per point),
  and a score shown on screen for 2 to 3 seconds before every serve. 53 rallies, one game, ending 29-23 before the last rally.
* The player confirmed afterwards that their team won and that the opponents served first, which matches what the pipeline inferred.
* The video itself is **not** in this repository. `examples/reference-match/` holds only numbers and blurred images.

The edit was discovered, not assumed: the first frame was an empty title card, the "no scene cuts" test passed only because the camera never moved, and the
score-overlay timing only made sense once player motion was plotted around each overlay (players stood almost still while it showed, and the clip jumped at its start).

## 3. Method

1. **Standardise** the video (1280x720, 30 fps, SDR). HDR is refused because tone-mapping needs a filter many ffmpeg builds lack.
2. **Detect people** every third frame with YOLO on the Apple GPU (about 50 frames per second).
3. **Fit the court** to the picture: points clicked on court-line crossings give a homography from pixels to court metres. The fit is judged by drawing the whole court model over
   the photo, including lines that were not used as inputs.
4. **Follow four players.** People inside the court area are scored against each player's shirt colour and joined to the nearest earlier position (assignment problem). Teams swap
   ends at most once; this is found from where a bright shirt colour is seen.
5. **Find the game start** from the rhythm of quiet serve-setup windows, as a suggestion for a person to confirm.
6. **Read the scoreboard** with Apple's text recognition and repair misreads with the scoring rule (each score is a legal one-point step and the digits sum to the rally number).
7. **Work out who served and who won**, from player positions before each serve (see section 5).
8. **Measure** movement, posture, rally length; compare rallies won and lost; draw pictures; write a report. The coaching text is written by the AI assistant under rules in `CLAUDE.md`.

## 4. Results on the reference match (numbers only)

* Your team led 29-23 before the last rally; 8 ties, 7 lead changes, longest run 6 points for each side.
* Serving 17 of 28 (61%), receiving 12 of 24 (50%): no real gap (p = 0.58).
* The player's own serves: 4 of 10 points, against 9 of 13 for the partner (p about 0.22): a hint, not a finding.
* Rallies under 6 s: 10 of 13 won; longer: 19 of 39 (p about 0.11).
* Distance per rally 8.0 m in won and 7.7 m in lost rallies, speed 0.91 and 0.83 m/s; nothing in movement separated won from lost rallies.
* The pair stayed within 1.5 m of each other 26% of the time in won rallies and 16% in lost ones (p = 0.03, weaker after multiple-comparison thinking; the opponents show the same direction). A question for the video, not a finding.
* Posture (near half only): median knee angle 166 degrees; racket hand held up 84% of the time.

## 5. How the results were checked

| claim | independent check | outcome |
|---|---|---|
| court fit | red court lines drawn over the photo, including lines not used as inputs | on the painted lines; fit error 1.9 px of 1280 |
| player identity | labelled frames inspected | labels on the right person in all inspected frames |
| scoreboard digits | 20 scores read by eye against the reader | 20 of 20; one misread repaired by the scoring rule |
| serve window timing | player speed around each overlay | still while shown (0.3 m/s) vs moving before the cut (0.83 m/s) |
| court geometry and parity | does the server's score parity predict which diagonal service quadrants are occupied? | 70% of windows vs 38% for the wrong parity |
| **which team served** | while a team keeps winning on serve, the same player must serve | 11 of 11 pairs (0 of 26 if the inference were backwards) |
| racket hand | looked at swing frames | the first automatic guess was wrong; corrected by eye |
| pickups | do bends point at the losing side? | 8 of 18, chance level: **not used** |

Coverage of the serve check is partial: the same-player test confirms about 30 of 53 rallies independently; the others rest on the position cue alone, which was
very consistent but is only checked indirectly there. The report and the "how sure" image say this.

## 6. What went wrong, and what it taught

* **Assuming the video was a raw match.** It was edited. Lesson: look at the footage and its structure before designing around it.
* **Reading the scoreboard backwards.** At first it looked like a score shown after each rally; it was shown before each serve, server first. Lesson: test the timing against data (player motion) before building on it.
* **A bug that only the replay check caught.** Votes were tied to near and far sides, but the teams swap ends mid-game, so everything after the swap came out wrong. The replay against the scoreboard showed 25 disagreements. Lesson: keep a check that can fail.
* **A confident claim that was wrong.** An early posture result said the player's racket hand was held up only 44% of the time. The hand had been guessed wrongly (left, not right); looking at swing frames fixed it (84%). Lesson: verify by eye anything a guess feeds.
* **A feature that did not work.** Shuttle pickups depend on the seconds after a rally, which the edit had cut away. The stage tests itself, fails, and says so.
* **Report text that overreached.** Early drafts said things like "your effort is not the problem" and "stay compact" with weak support. Lesson: wording must follow the strength of the evidence; the generator now computes claims and the coaching is written under explicit rules.
* **A hidden dependency on one video.** Player identity and report wording were hard-coded to this match's clothes. They are now configuration. A regression run confirmed the refactor reproduced the original tracks and numbers exactly.
* **Privacy.** Absolute file paths (with a username) were being written into output files; they now store file names only. Example images need blurred faces, and an assistant looking at an image sends it to its provider, so the playbook asks permission first.

## 7. Limitations

Doubles only; fixed camera; one game; one end change at most; one tested video. Far-court positions are coarse; shuttle events are not tracked; winners need a
scoreboard or a hand-written score; start detection is a suggestion; player identity depends on shirt colours; macOS-only scoreboard reader; Linux and Windows untested.

## 8. What to build next (ordered by value)

1. Test on raw, high, behind-the-baseline footage from several people and fix what breaks.
2. Score entry by hand, so videos without a scoreboard get rallies and won/lost splits.
3. One joint model for "who won each rally" that outputs probabilities, with ranges carried into the won/lost numbers.
4. Racket-hit detection from the audio, and shuttle tracking for 1080p video: shot counts, rally ends, landing side.
5. Better tracking: feet from ankle landmarks, appearance matching, tiled detection for small far players.
6. A labelled sample (for example 40 frames and 20 rallies marked by the player) to measure real accuracy.
7. Multi-game storage, effect sizes with ranges, and a proper definition of "out of position".
8. Linux and Windows support, a pinned CI test run, and singles.

## 9. Working with an AI assistant

The repository is written so an assistant can drive it: `CLAUDE.md` is the playbook (interview first, one check image per stage, explicit stopping conditions, rules for writing coaching).
This worked on the reference match, where the assistant also found and fixed several of the problems in section 6. It has not been tested on a second video or with any
assistant other than Claude Code. Frames an assistant looks at leave your computer; the project asks permission first.

## 10. Reproducing the reference numbers

`examples/reference-match/data/` holds every result file. The video is not included, so the numbers cannot be regenerated from scratch without your own video of the same match; they are provided so
you can see exactly what each stage produces and in what format.
