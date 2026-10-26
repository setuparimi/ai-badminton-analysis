---
description: Analyse a badminton video (singles or doubles) and give me a PDF report, following the playbook in CLAUDE.md
argument-hint: [path/to/your/video.mp4 or a YouTube link]
---

Analyse my badminton match video: $ARGUMENTS

If nothing is given above, ask me for it first ("What is the path to your match video, or a YouTube link to one you filmed?") and wait for my answer. If it is a YouTube link, follow step 1b of `CLAUDE.md`: ask whether I filmed it or may use it, show me the title, length and size, and download it only after I say yes.

Follow `CLAUDE.md` exactly: read `README.md` and `docs/HOW_IT_WORKS.md` first, then ask me the questions of step 1 in one message before running anything: what to call the match, **singles or doubles**,
**which hand I hit with**, whether the video shows a live score, when each game starts and ends, and the final score of each game if I know it. Run `tools/analyze.py` (step 1c) yourself and stop and tell me if
something looks wrong. Keep everything on this computer. Do not download anything except that one video, and do not commit or push anything.

The journey I expect: you ask the questions, you run the early stages, a page opens where I click the court lines and a page where I click myself (my partner and the opponents are found for me), you run the rest,
you look at the court picture and the label check sheets and tell me honestly how many labels were wrong, you build the PDF, and you tell me where it is, the three most important findings, and plainly which results are
solid and which are weak.
