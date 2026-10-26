# Badminton match analysis: reference match

Your team (you in the white tee and your partner in the red shirt) against the opponents in the dark top and the grey top. Doubles, one game.

## What was measured, and how sure it is

* **Score:** your team was 29-23 before the final rally (your team serving). The winner of that last rally is not shown, so the game finished 30-23 to your team if it won the last rally, 29-24 to the opponents if it lost it. 8 ties, 7 lead changes, longest run 6 points.
* **Measured directly:** where the four players stood (court metres), rally start and end times, distance, speed and posture. The scoreboard was read from 52 on-screen overlays.
* **Inferred:** *which team won each rally*. The scoreboard shows the server's score but not the team, so the serving team is worked out from how the players stand before each serve. It is independently confirmed for 30 of 53 rallies (blocks 2-9, 10-15, 38-53); blocks 1, 16-23, 24-25, 26-27, 34-35, 36-37 rest on the position cue alone.
* **Rougher:** far-court positions (see section 6).

![score](images/01_match_summary.png)

## 1. The match

| | |
|---|---|
| Rallies | 53 (median 8.5 s, longest 18.7 s) |
| Your team's points by quarter | 7/13, 6/13, 8/13, 8/13 |
| Longest run, your team | 6 points from rally 6 at 2:01 |
| Longest run, opponents | 6 points from rally 12 at 3:05 |
| Teams changed ends | at 6:18 |

Analysis starts at 0:48; anything before that (title card, teaser, warm-up) is ignored.

## 2. Serving and receiving

| | won / played | |
|---|---|---|
| Your team when serving | 17 / 28 | 61% |
| Your team when receiving | 12 / 24 | 50% |
| Points when **you** served | 4 / 10 | 40% |
| Points when your partner served | 9 / 13 | 69% |

Serving versus receiving: p = 0.58. Rallies you served and lost: R4 1:35, R19 4:23, R29 6:24, R35 7:36, R43 9:00, R48 9:56; won: R27 6:00, R28 6:10, R42 8:45, R47 9:48.

## 3. Rally length

| rally length | rallies | your team won |
|---|---|---|
| under 6 s | 13 | 10 (77%) |
| 6 to 10 s | 22 | 11 (50%) |
| over 10 s | 17 | 8 (47%) |

## 4. You, won versus lost rallies (movement)

Court metres from the calibrated camera; 28 won and 23 lost rallies. p is a Mann-Whitney test; with 9 comparisons about one p below 0.05 is expected by chance.

| | won | lost | p |
|---|---|---|---|
| distance per rally (m) | 8.0 | 7.7 | 0.93 |
| mean speed (m/s) | 0.91 | 0.83 | 0.24 |
| peak speed, 95th percentile (m/s) | 2.85 | 2.64 | 0.30 |
| share of time at the net (<= 2.5 m) | 0.27 | 0.26 | 0.85 |
| share of time mid-court | 0.61 | 0.58 | 0.97 |
| share of time at the back (> 4.5 m) | 0.12 | 0.16 | 0.66 |
| **your pair** | | | |
| open gap in your half (m) | 3.22 | 3.07 | 0.17 |
| time within 1.5 m of your partner | 0.26 | 0.16 | 0.029 |

Over the game: you ran 400 m in 51 rallies (7.8 m per rally, 0.88 m/s); your partner 392 m; the opponents 325 m and 377 m.

Re-running the same comparison on only the rallies whose serving team is best backed up (39 rallies): time within 1.5 m of your partner 0.26 vs 0.12 (p = 0.005); distance 8.1 vs 7.4 m (p = 0.88).

![heatmaps](images/05_heatmaps.png)

## 5. Posture

Near half only (24 rallies, 1926 frames of you). Body landmarks need a large person, so they exist only while a player is near the camera. Racket hand detected as **left** (check it by eye on a few swings: it rests on a small number of overhead frames).

| | you | your partner |
|---|---|---|
| knee angle, median (180 = straight leg) | 166 deg | 168 deg |
| frames with knees bent under 150 deg | 18% | 12% |
| racket hand held above the hip | 84% | 79% |
| won rallies / lost rallies: knees bent | 17% / 18% | 14% / 10% |
| won rallies / lost rallies: racket hand up | 88% / 80% | 80% / 77% |

Pickups (stage 9): not usable on this video: in 18 of 52 rallies exactly one team bends near the end of the rally, and that team is the loser 8 times (44%; chance is 50%).

## 6. Limits of these numbers

* **Far-court accuracy.** Pixels per metre from the calibration: 1m across, near court (Y=2) 175; 1m across, at the net 110; 1m along, near court (Y=2) 95; 1m along, far court (Y=11) 18. Few pixels per metre means less precise positions, which is why the far half of the court is rougher than the near half.
* **Tracking coverage per player (share of frames with a position):** A_partner 95%, A_you 96%, B_opp1 90%, B_opp2 91%.
* **Who won each rally** is inferred. The independent test: while a team keeps winning on serve, the same player must serve. It held in 11 of 11 pairs, against 0 of 26 if the inference were backwards.
* **The last rally** is excluded from per-rally statistics: after the final point the players keep moving.
* **Clothing colour** identifies people only inside the court area, from shirt colours in players_config.json.

## 7. Checks that ran

| stage | check | result |
|---|---|---|
| 2 calibrate | court model against hand-picked points | fit error 1.9 px |
| 3 players | share of frames with a position | 90% to 96% |
| 4 serves | both diagonal service quadrants occupied | 37 of 53 windows |
| 5 score | replay against the scoreboard | 0 disagreements |
| 5 score | same player keeps serving | 11 of 11 |
| 9 pickups | bends point at the losing side | 8 of 18 |

## Coaching

### What to work on

**1. Look at your own serve**

Your team won 4 of the 10 rallies you served, against 9 of the 13 your partner served. Overall your team won 17 of 28 rallies on serve (61%), so the team's serving record is not weak overall.

Try next time: Watch your six lost serves and ask: is it too high, too predictable, or is the third shot the problem? Change one thing next game (height, placement or the plan for the third shot) and count again. General advice, not tested by this video: mixing a short serve with a flick serve makes the receiver's first move harder to guess.

Watch your lost serves: 1:35 (R4), 4:23 (R19), 6:24 (R29), 7:36 (R35), 9:00 (R43), 9:56 (R48).

How sure: low. Ten serves is a hint, not proof (p about 0.22), and who served is inferred from where the players stand.

**2. Have a plan for the long rallies**

Your team won 10 of 13 rallies under 6 s (77%) but only 19 of 39 longer ones (49%), and 8 of 17 over 10 s (47%). The video cannot show which shots were played.

Try next time: Agree what you do when the first attack does not end the point: where you reset the rally (a clear to the back, a lift to the middle), and who covers the net. General advice; then check whether the long-rally record moves in your next game.

Watch the long rallies you lost: 0:51 (R1, 18 s), 3:38 (R15, 14 s), 7:03 (R33, 19 s), 9:20 (R45, 12 s).

How sure: low to medium. 13 short rallies against 39 longer ones, p about 0.11.

**3. Ready stance: get lower**

Your legs were nearly straight (knees not bent below 150 degrees) in 82% of the frames where you were near the camera; your typical knee angle was 166 degrees against 168 for your partner. Posture was the same in won and lost rallies (bent in 17% and 18% of frames).

Try next time: General advice, not tested by this video: a bent-knee ready position usually gives a quicker first step. Next game, the share of bent-knee frames is the number to move.

Watch your stance in any rally after 6:19, when you are on the near side of the court.

How sure: medium for the measurement (1,926 frames of you in 25 rallies, near half only). Whether a lower stance wins you more points is not tested here.

### Questions to check on the video

**4. A question for the video: stay compact?**

You and your partner were within 1.5 m of each other 26% of the time in rallies you won and 16% in rallies you lost (p = 0.03). It is one of nine comparisons, so about one result like this is expected by chance, and on each half of the court alone it is not significant (p = 0.12 and 0.17).

Try next time: Watch the clips and see whether being far apart left a gap the opponents used. If it did, agree who takes the middle.

Watch the lost rallies where you two were furthest apart: 4:23 (R19), 1:12 (R2), 9:00 (R43), 9:20 (R45).

How sure: lowest. One small p among nine; tracking is weakest when players overlap.

### What is working

**5. Your team wins the quick points**

Your team won 10 of 13 rallies that ended within 6 seconds (77%).

Try next time: Keep attacking the first loose ball. General advice: when a point is going your way early, do not slow it down.

Watch some of them: 2:22 (R8), 2:50 (R10), 2:57 (R11), 5:04 (R22), 6:37 (R30), 7:57 (R37).

How sure: low to medium. 13 short rallies; p about 0.11.

**6. Running is not what separates won from lost rallies**

You covered 400 m, the most of the four players (your partner 392 m, the opponents 325 m and 377 m). Per rally you ran 8.0 m in won and 7.7 m in lost rallies, at 0.91 and 0.83 m/s, and spent 12% and 16% of the time at the back (all p above 0.2).

Nothing to fix here: this is not a fitness problem.

How sure: medium. Small effects could hide in 28 won and 23 lost rallies; far-court distances are rougher.

**7. A steady game from start to finish**

Your team won 7, 6, 8 and 8 of 13 rallies in the four quarters of the game. The score was tied 8 times with 7 lead changes, and your team led 29-23 before the last rally. Your best run was 6 points from 2:01.

Watch your run from 2:01 (R6) to see what worked.

How sure: high. This is read straight from the scoreboard.

### What the opponents do well

**1. Once a rally settles, they are an even match**

In rallies longer than 6 seconds the opponents won 20 of 39 (51%), including 9 of 17 over 10 seconds (53%).

Long rallies they won: 7:03 (R33, 19 s), 0:51 (R1, 18 s), 3:38 (R15, 14 s), 9:56 (R48, 12 s).

How sure: low to medium. 39 rallies; the video cannot show which shots decided them.

**2. Opponent 2 plays the net and does most of the serving**

Opponent 2 (grey top) won 5 of the 10 rallies they served and was the player nearer the net in 70% of the 28 rallies when the opponents were near the camera. Opponent 2 ran 7.3 m per rally against 6.9 m for Opponent 1.

Opponent 2's serves: 0:51, 1:24, 3:27, 3:55, 4:14, 5:34, 6:50, 7:24, 8:34, 9:35.

How sure: low. 10 serves and 28 rallies; who served is inferred.

**3. They can string points together**

Their best run was 6 points, from rally 12 at 3:05, the same length as your best run.

Watch rallies 12 to 17, 3:05 to 4:05, to see what changed.

How sure: high that it happened (scoreboard); why it happened is not visible.

### Possible openings

**4. Quick points go against them**

The opponents won only 3 of the 13 rallies that ended within 6 seconds (23%), against 20 of 39 longer ones (51%). This is the same finding as your quick-point record, seen from their side.

Short rallies your team won: 2:22 (R8), 2:50 (R10), 2:57 (R11), 5:04 (R22), 6:37 (R30), 7:57 (R37).

How sure: low to medium. 13 short rallies, p about 0.11.

**5. A little weaker when receiving, but not clearly**

They won 11 of 28 rallies (39%) when receiving and 12 of 24 (50%) when serving (p = 0.58).

How sure: low. No real gap: do not build a plan on this.

**6. Opponent 1's serve rarely paid off**

Opponent 1 (dark top) won 1 of the 5 rallies they served; Opponent 2 won 5 of 10. In 14 rallies the server could not be identified.

Opponent 1's serves: 1:49 (R5, theirs), 2:01 (R6), 4:29 (R20), 9:12 (R44), 10:22 (R50).

How sure: very low. Five serves.

**7. A question for the video: side-by-side defence**

Their pair stood side by side 6% of the time in rallies they won and 15% in rallies they lost (p = 0.04). It is one of five comparisons, so a result like this can easily be chance.

Rallies they lost while most side by side: 2:12 (R7), 6:10 (R28), 8:18 (R39), 10:54 (R52).

How sure: lowest. One small p among five, and positions of overlapping players are the roughest.

**8. Their side lanes were thinly covered**

In the 28 rallies when they were near the camera, at least one of them stood within 1.5 m of the middle of the middle lane for 81% of the time in mid-court and 74% at the back. The left and right lanes were covered only about 20% of the time, and the front corners 3% and 7%. This shows where they stood, not where they lost points.

How sure: low to medium. Positions are good near the camera but this is one game and says nothing about shot placement.

### Game plan to try

**9. Try to finish early**

They struggle most in rallies under 6 seconds. Attack the first loose ball instead of resetting, and count how many of your next game's rallies end early and who wins them.

Built on a low-confidence hint (p about 0.11): a test to run, not a rule.

**10. Test the side lanes and back corners**

They mostly held the middle lane. Try placing some shots wide and deep and watch whether they are stretched. The video cannot say where your shots landed, so note it yourself.

A test to run: the video shows where they stood, not where points were lost.

**11. Be patient in long rallies**

In rallies over 6 seconds they win about half, so they are as good as you there. Have your reset plan ready (see your coaching plan) and avoid gambling when the rally is level.

General advice backed by the long-rally record above.

**12. Check which hand each of them uses**

The program guessed Opponent 1 right-handed (8 of 11 overhead frames) and Opponent 2 left-handed (16 of 24, not clear). Left- and right-handers have different backhand corners; confirm on the video before you plan around it.

How sure: low. A few dozen frames.

