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

At version 0.1: doubles only; fixed camera; one game; one end change at most; one tested video (version 0.2 relaxes the first, third and last of these; see its section at the end). Far-court positions are coarse; shuttle events are not tracked; winners need a
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

## Update: the PDF report

After the first release the project was extended so that one run ends in a document a player can read and share.

* **Who is who by clicking.** `tools/pick_players.py` replaces typing shirt colours: a local page shows pictures from the start of the game, the person clicks the
  player to analyse, their partner and the two opponents, and the tool reads and checks the shirt colours. Tested on the reference video with real page events:
  the saved config equalled the hand-written one and tracking was identical. Lesson: colour reading is imperfect under changing light (a dark top was read as blue
  or white in some pictures), so the page ranks pictures with four distinct colours first and always lets the person correct a colour.
* **Opponent scouting.** `s07b_opponents.py` turns the same tracks into the other team's results, roles, pair shape and a 3 x 3 coverage map. A check on the data found that
  far-half depth is squeezed towards the net (almost nobody is ever "at the back" there), so role and zone numbers use only the rallies when the opponents were near the camera.
  There is still no shuttle tracking, so nothing is said about shots.
* **PDF.** `s13_pdf_report.py` lays out the numbers and the assistant's words (`tips.json`, `scouting.json`, validated) with embedded fonts, charts only by default. A first render
  with standard fonts looked wrong in one viewer (bold shown as regular) and would have broken accents in a name; embedding fonts fixed both.
* **Scanner.** `tools/check_repo.sh` flagged "email addresses" inside the PDF's compressed image data; it now scans a PDF's extracted text and metadata and lists PDFs for a human to read.

## Update: fetching a YouTube video

The first release asked for a file and said so plainly ("no downloader"). That was reversed on request, with limits: an optional `tools/fetch_video.py` saves **one** YouTube video, only
after the person confirms they filmed it or may use it, and nothing is vendored (yt-dlp is installed separately). The risks it is built around: other people's copyright and YouTube's terms
(a confirmation, a look-up before any download, no bulk or playlist use), a hostile link (one host family, one extractor, no userinfo or odd ports), hostile text in a title (cleaned, never used
as a file name), a hostile or broken file (new empty folder, ffprobe check, length match) and credentials (no logins, no browser cookies). Tested without YouTube by pointing the real yt-dlp at a
local web server serving the reference video: the saved file was byte-identical (same SHA-256), and `run_all.sh` given a YouTube-style link reused it and ran stages 0 and 1 on it exactly as on the original (6,827 detection records both times). Not tested against YouTube itself, which changes often.
Honest limit: most YouTube matches will not fit the pipeline (broadcast camera work, singles, no scoreboard), so a link usually gets a person to "stopped after stage 3", not to a PDF.
The most useful next step for that case is still a way to enter the score by hand.

## Update: three more videos (what a second and third video taught)

Run on a tournament video from a videographer (two sets, score overlay top left, glossy floor, spectators at the court edge) and on two matches from a wide-angle camera in a
multi-court hall, the pipeline needed changes the reference video never asked for. Fixed and tested: stage 1 treated title cards as missed detections (now listed as cutaways);
the score overlay reader only looked top right and assumed one game (now it finds the corner, and splits games at each 0-0 or at a title card, with zero corrections needed on the
tournament video's 86 runs); and two teammates in two shades of one colour could not be told apart (now a light/dark tone in the config).
Not solved, and said so: on the tournament video player tracking failed its own visual check (the partner is sometimes beyond the sideline near the camera, where a court model
anchored only on the net half is least accurate, and spectators sit at the court edge), so no report was written from it. The two wide-angle matches have no per-rally score at all
(only a game label and a final-result card), so winners, serve and won-versus-lost analysis are impossible from the video; a positions-and-movement report without winners would need
a score-free report mode that does not exist yet. Lesson: judge fit from the whole video, not five frames (the overlay that "did not exist" flashed for 1.5 s per rally), and never carry on past a failed label check.

## Version 0.2: a guided run and a report without a score

What changed and why. The first version needed a yellow on-screen score to say anything about rallies, which excludes most matches people film themselves. Version 0.2 adds a route that needs no score
and a single guided entry point, and was built on two real club matches (19 and 30 minutes, 2 and 3 games, a wide-angle camera behind the baseline in a hall with several courts). Only the first match was taken all the way to a report; for the second the court could not be fitted from painted lines alone (the lens bends them and neighbouring courts have look-alike lines), which is why the court page asks the person to click.

* **One command with the questions asked up front** (`tools/analyze.py`): video, singles or doubles, left or right hand, live score or not, when each game starts, each game's final score. Then two clicks. Everything else runs.
* **One click instead of four.** Click yourself; the partner and opponents follow from which half of the court they stand on. The cue that tells you from your partner is chosen by trying every candidate on about 12 seconds of tracked video.
* **Telling people apart in a dim hall.** Shirt colours failed: under hall lighting every torso read near black. The cue that worked was the brightness of the shorts (hip to mid-thigh): light shorts 60 to 140, dark 0 to 20 on a 0-255 scale.
* **A wide-angle lens broke the person-size filter.** Real near players measured 2.3 to 3.2 times the local scale and were thrown away (coverage 60%). The window now follows the video's own median (coverage 96 to 98%).
* **Shorts are not read from boxes that cannot be read.** A fresh-clone test run came out with YOU and PARTNER inverted on all twelve check moments: the click had landed on a partner standing at the camera with an arm out (bright floor in the middle of the box read 161 for black shorts),
  and a player cut off at the bottom of the picture read 7 for white ones. Wide boxes and boxes touching the edge now say nothing about shorts, the cue's direction is taken from the readable moments nearest the click, and the guided run verifies after tracking that the YOU track is where the person clicked.
* **Continuity beats a momentary clothes reading.** A visual check found the "partner" label on the user for about a second while their shorts read dark for a moment. A slot that was at this spot 0.3 s ago keeps its person.
* **A check sheet nobody can skip.** `tools/check_tracking.py` makes twelve moments per game, six of them at the closest crossings. On the checked game the first pass looked clean on 12 moments and the larger sheet found a wrong label; with the final tracker 2 of 12 game-1 moments were still swapped (your partner at the camera at the start; the two of you overlapping) and all 10 game-2 moments were right.
  The reports now say how many moments were looked at and how many were wrong.
* **Plays from sound and movement** because there is no score to anchor rallies. Validated against result cards (the one thing the video gives): 37 and 32 found against 40 and 34.
* **Pose handedness.** The pose model said the (left-handed) player was right-handed. Its left and right labels are mirrored for people seen from behind, so the hand the player declares is used and the model's guess is not printed.
* **Honest limits, version 0.2:** one fixed camera; singles only on synthetic data; far-side depth and distance are rougher; the sound includes neighbouring courts; the report cannot say who won anything.
