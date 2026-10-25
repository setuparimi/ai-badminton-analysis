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

What the numbers support, in order of confidence. Times are video time.

1. **Nothing in your running separates won from lost rallies.** Distance, speed and court position are about the same in both (all p above 0.2). With 28 against 23 rallies a small effect could be hidden, but there is no sign that you run less, or sit deeper, in the rallies you lose.
2. **Look at your own serve.** You won 4 of 10 points on your serve against 9 of 13 on your partner's (p about 0.22, so a hint only). Watch 1:35, 4:23, 6:24, 7:36, 9:00 and 9:56 and ask whether the serve is too high or too predictable, and what the third shot looks like.
3. **Finish quickly, and prepare for long rallies.** Your team won 10 of 13 rallies under 6 s, but 19 of 39 longer ones (p about 0.11). Check the three longest rallies you lost: R33 at 7:03, R1 at 0:51 and R15 at 3:38, and see who is pushed back first.
4. **Ready posture.** Your legs are nearly straight in 82% of near-half frames (median 166 degrees), slightly more bent than your partner's. Your left racket hand is held up 84% of the time. A lower, bent-knee stance is general advice for a faster first step; this video does not test it, and posture does not differ between won and lost rallies.
5. **A question for the video: compactness.** Your pair is closer together in rallies you win (26% of the time within 1.5 m against 16%), but this is one of nine comparisons, the average gap in your half is the same in won and lost rallies, and it is not significant on either half of the court alone. Watch R2 at 1:12, R19 at 4:23 and R43 at 9:00.
6. **Momentum.** Points won by quarter were 7/13, 6/13, 8/13 and 8/13: no collapse and a small lift late. The opponents' six-point run from R12 at 3:05 is the stretch to watch to see what changed.

