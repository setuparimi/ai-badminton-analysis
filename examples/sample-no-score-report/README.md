# Sample report (invented data)

`match_report.pdf` is what the route **without a score on screen** produces. **Nobody played this match**: two games of doubles were simulated by `tools/make_sample_report.py` and run through the same statistics, rule-based words and PDF stages as a real video. Every number, chart and sentence is invented; the first page and the header of every page say so. It exists so you can see the report without anyone's real weaknesses being published.

Rebuild it with `python tools/make_sample_report.py` (seeded, so the result is the same each time). `data/` holds what it was made from.

The scoreboard route has its own example in [`../reference-match/`](../reference-match/) (a real game, anonymised).
