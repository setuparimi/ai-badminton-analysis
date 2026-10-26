# Using Badminton Analysis with Claude Code (no programming needed)

This guide is for a player who wants results, not code. Allow about 30 minutes the first time, most of it waiting
for the computer.

## 1. What you need

| thing | how to get it |
|---|---|
| A video of your singles or doubles match from a **fixed** camera | see [FILMING_GUIDE.md](FILMING_GUIDE.md). A phone on a tripod works |
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

## 3a. Or skip the assistant: one command

```bash
.venv/bin/python tools/analyze.py
```

It asks the same questions Claude would (below), opens the same two pages, and makes the PDF. It asks: where the video is and what to call the match; singles or doubles; which hand you hit with; whether the video
shows a live score; when each game starts and ends; and each game's final score if you know it. Then you click the court and click yourself, and it does the rest. The coaching and scouting words are written
by rules from the numbers (an assistant can write better ones). Run `.venv/bin/python tools/analyze.py --help` for every flag; run it again with the same `--work` folder to carry on after a stop.

## 3. Start Claude in the project folder

In the same Terminal window type `claude` and press Return. Then type:

```
/analyze-match /full/path/to/your/video.mp4
```

(Tip: drag the video file into the Terminal window to paste its path. Typing just `/analyze-match` works too: Claude asks for the file first.)

If your Claude Code does not show `/analyze-match`, paste this instead:

> Analyse my badminton video at `/full/path/to/your/video.mp4`. Follow CLAUDE.md in this folder exactly:
> ask me the interview questions first, run each step, and give me the PDF report with a coaching plan for the player I choose and scouting notes
> on the opponents. Tell me plainly what is solid and what is weak.

## 3b. Your match is on YouTube

You can give Claude a YouTube link instead of a file: `/analyze-match https://youtu.be/...`. Things to know first:

* **Only your own video, or one you have permission to use.** YouTube's Terms of Service restrict downloading other people's videos, and the owner may hold the copyright. Claude asks you,
  and does not download if the answer is no.
* **It is an optional extra.** Claude installs it for you the first time (`.venv/bin/pip install -r requirements-youtube.txt`). It uses the separate open-source tool yt-dlp, which is not part
  of this project. If a download stops working, YouTube has probably changed: `.venv/bin/pip install -U yt-dlp`.
* **You see before it saves.** Claude shows the title, channel, length and size and waits for your yes. One video only: no playlists, no live streams, nothing over 120 minutes or 2.5 GB, nothing that
  needs a login, and your browser's cookies are never used. The file goes into `work/download/` on your computer and is never uploaded by this project.
* **A link only gets you the file.** The analysis still needs a match from one fixed camera. A tripod video of your own club match is fine; a broadcast with camera cuts and replays is not.
  With no score on screen you get the position-and-movement report; with the reference format of on-screen score (doubles) you also get who won each rally. Claude tells you which case you have.

## 4. What Claude will ask you

* **Where your video is** (drag the file into the window). If you typed it after `/analyze-match`, Claude does not ask again.
* What to call the match on the report cover, and optionally your name.
* **Singles or doubles**, and **which hand you hit with**, left or right.
* Whether the video shows a **live score** that changes every rally (usually no), and **when each game starts and ends**.
* The final score of each game, yours first, if you remember it (it uses this to check the number of plays it finds).
* **Permission to look at frames.** When Claude opens a picture to check its work, that picture is sent to the AI
  service as part of your chat. The video itself is not uploaded. If you say no, Claude asks you to look at the
  pictures yourself and describe them. The pages where you click (court lines, players) run in your own browser and are not sent anywhere.

## 5. The two things you do by hand (three with a live score)

1. **Click the court.** A page opens with a photo of your court. Click a landmark on the small diagram, then click the
   same spot on the photo. Do at least 6, spread out: some near the camera, some far, some left and some right. The page draws the
   court on the photo as you go and tells you if it does not fit. Press Save.
2. **Click yourself.** Another page opens with a picture from the game and a numbered box around everyone on court. Click **yourself** (this is "you" in the report).
   In doubles your partner (the other person on your half) and the two opponents are filled in; if the picture does not show two and two, click them yourself or press "Another picture".
   The page says how you are told apart (shirt colour, shade, or light against dark shorts, checked over about 12 seconds of video). Pick your hand and press Save.
3. **Only with a live score on screen: confirm the game start.** Claude shows you a strip of pictures around the time it thinks the game begins (titles, teasers
   and warm-ups can fool it). You say yes, or give the right time.

Afterwards, **look at two pictures**: the court drawn on the photo (page 2 of the PDF) must sit on the lines you played on, and `g1/qa_check.jpg` (one per game) must show YOU, PARTNER and the opponents on the right people.

## 6. What you get

Everything is saved in a folder called `work/` inside the project. The one to open is **`work/match_report.pdf`**:

* a cover with the result and the short version (what to work on, what is working, what to check, where the opponents are beatable);
* **your coaching plan**: what is working, what to work on (each with a next step, video times to check and how sure it is), and questions to check on the video;
* the charts: serving, rally length, won versus lost, where you stood, all four players, posture;
* **scouting the opponents**: how they did, how each of them plays (net or back, serving record, racket hand), strengths, possible openings and a game plan to test;
* moments to check on the video, how sure each number is, and a short glossary.

Without a live score on screen the PDF covers: the court that was analysed, the games at a glance, your coaching plan, where you and your partner stand (heat maps), how the pair is arranged,
how hard you worked minute by minute, posture, the opponents' habits, pace of play, the longest plays to watch back, and how sure each part is. It cannot say who won a rally.

The PDF contains charts only, no photographs of people, so it is safe to pass on. Also in `work/`: `report.md` (the same facts as text), `images/`
(every chart as a picture; `07_posture.png` and `11_how_it_was_seen.png` contain faces), and `analysis_video.mp4` if you ask for it.

## 7. How to read the results

* **"No real gap" or a big p-number** (above 0.2) means the data does not show a difference. It does not prove there is none.
* One game has about 50 rallies. That cannot reveal small effects. Look for patterns that repeat across several games.
* **Moments to check** lists video times. Open your video at those times and see if the numbers match what you remember.
* The **how sure** image shows which parts were independently confirmed and which rest on one guess.

## 8. If something goes wrong

| what you see | do this |
|---|---|
| `setup.sh` says ffmpeg is missing | `brew install ffmpeg`, then run `bash setup.sh` again |
| Labels on the wrong player in a picture | tell Claude; pick the players again or change a shirt colour (white versus grey is the hardest pair) |
| The picker shows no picture with four people | tell Claude a time (in seconds) when all four players are on court and it will use `--time` |
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
