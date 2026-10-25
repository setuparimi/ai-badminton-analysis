# Contributing

Thank you. This is an alpha project built on one video, so the most valuable contribution is **evidence from other videos**.

## The most useful things

1. **Run it on your own match and open an issue** with: what camera view you had, which stages passed, which images looked wrong, and (if you are
   comfortable) a blurred check image. Never attach unblurred frames of other people.
2. **Score entry**: a small tool that builds `overlay.json` from a written list of who won each rally (see `docs/HOW_IT_WORKS.md`, "Scores").
3. **A scoreboard reader** that works on Linux and Windows (the current one uses Apple's Vision framework, macOS only).
4. **Singles support** and **more than one end change**.
5. **Shuttle tracking** (needs a video of about 1080p or better) and **racket-hit detection from the audio**.
6. Tests for logic that is not images or models.

## Ground rules

* **No personal data.** Never commit videos, frames with faces, `work/` outputs, absolute paths or names. `.gitignore` blocks the obvious ones; check `git status` anyway.
* **Be honest in text.** Every claim in a report, image or doc must come from a number in a file, with its sample size. No "because".
* **Keep stages checkable.** A stage ends with `PASSED`/`FAILED`, and anything a person must judge gets a check image.
* **Licence.** By contributing you agree your work is licensed under AGPL-3.0, like the rest of the project.
* Run `python -m unittest discover -s tests` before opening a pull request.
