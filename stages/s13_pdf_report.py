#!/usr/bin/env python3
"""Stage 13 - PDF REPORT.

One document a player can read and share: the match in numbers, a coaching plan (what is working, what to work on,
what to check on video), scouting notes on the opponents (strengths, weaknesses, a game plan), the charts, the
moments to watch, and how sure each number is.

Every figure is read from the stage outputs. The coaching and scouting WORDS are written by an AI assistant (or you)
from those numbers and saved as tips.json and scouting.json (rules and format: CLAUDE.md); this script lays them out.
Without those files the report says they are missing.

By default the PDF contains charts only, no photographs of people, so it is safe to pass on. --photos adds the
posture photo strip and the "how the computer saw the match" page; those pictures show faces unless the images were
made with a face-blurred --evidence-dir.

Run:
    python stages/s13_pdf_report.py --work work [--label "Saturday doubles"] [--page A4|letter] [--photos]
Needs: images made by stage 12 (work/images), report_data.json, opponents.json and, for the words, tips.json + scouting.json.
Writes: work/match_report.pdf
"""
import argparse
import datetime
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, HRFlowable, Image, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from common import NO_CHANGE, chain_status, load_config, mmss, pword

INK, INK2, MUT = colors.HexColor("#0b0b0b"), colors.HexColor("#52514e"), colors.HexColor("#898781")
TILE, LINE, SURF = colors.HexColor("#f1f0ec"), colors.HexColor("#c3c2b7"), colors.HexColor("#fcfcfb")
BLUE, ORANGE, GOOD = colors.HexColor("#2a78d6"), colors.HexColor("#eb6834"), colors.HexColor("#0a8a0a")
MARGIN = 18 * mm
KIND_ORDER = ("improve", "check", "strength")
KIND_COLOUR = {"strength": GOOD, "improve": BLUE, "check": MUT}
SCOUT_COLOUR = {"strengths": ORANGE, "weaknesses": BLUE, "plan": INK}

_REPLACE = {"\u2192": "->", "\u2190": "<-", "\u2713": "yes", "\u2717": "no", "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u2011": "-"}


def safe(text):
    """A few symbols that Arial may lack are written out; everything else (including accents in names) is drawn by the embedded font."""
    text = str(text)
    for a, b in _REPLACE.items():
        text = text.replace(a, b)
    return text


def register_fonts():
    """Embed a font family so the PDF looks the same everywhere: Arial if this computer has it, else the DejaVu Sans that ships with matplotlib."""
    import matplotlib
    dv = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    sets = [["/System/Library/Fonts/Supplemental/" + n for n in ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf")],
            ["C:/Windows/Fonts/" + n for n in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")],
            ["/usr/share/fonts/truetype/msttcorefonts/" + n for n in ("Arial.ttf", "Arial_Bold.ttf", "Arial_Italic.ttf", "Arial_Bold_Italic.ttf")],
            [str(dv / n) for n in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf")]]
    files = next((f for f in sets if all(Path(x).exists() for x in f)), None)
    if files is None:
        raise SystemExit("no usable font found: reinstall matplotlib (it ships DejaVu Sans)")
    for name, path in zip(("Body", "Body-Bold", "Body-Italic", "Body-BoldItalic"), files):
        pdfmetrics.registerFont(TTFont(name, path))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")


def esc(text):
    return escape(safe(text))


def pc(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def ratio(a):
    return f"{a[0]} of {a[1]} ({pc(*a)})"


# ---------------------------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------------------------
def make_styles():
    f = dict(fontName="Body", textColor=INK)
    fb = dict(fontName="Body-Bold", textColor=INK)
    return {
        "kicker": ParagraphStyle("kicker", fontName="Body-Bold", fontSize=8.5, leading=11, textColor=MUT, spaceAfter=8),
        "title": ParagraphStyle("title", fontSize=31, leading=35, spaceAfter=6, **fb),
        "subtitle": ParagraphStyle("subtitle", fontName="Body", fontSize=13, leading=17, textColor=INK2, spaceAfter=14),
        "h1": ParagraphStyle("h1", fontSize=19, leading=23, spaceAfter=3, **fb),
        "h2": ParagraphStyle("h2", fontSize=12.5, leading=16, spaceBefore=11, spaceAfter=4, **fb),
        "h3": ParagraphStyle("h3", fontSize=10, leading=13, spaceBefore=4, spaceAfter=2, **fb),
        "body": ParagraphStyle("body", fontSize=9.7, leading=14, spaceAfter=5, **f),
        "lead": ParagraphStyle("lead", fontSize=10.5, leading=15, spaceAfter=6, fontName="Body", textColor=INK2),
        "bullet": ParagraphStyle("bullet", fontSize=9.7, leading=13.5, leftIndent=11, bulletIndent=1, spaceAfter=2.5, **f),
        "small": ParagraphStyle("small", fontName="Body", fontSize=8.2, leading=11, textColor=INK2, spaceAfter=3),
        "caption": ParagraphStyle("caption", fontName="Body", fontSize=8.4, leading=11.5, textColor=INK2, spaceBefore=2, spaceAfter=7),
        "tile_big": ParagraphStyle("tile_big", fontSize=21, leading=24, **fb),
        "tile_cap": ParagraphStyle("tile_cap", fontName="Body", fontSize=8, leading=10, textColor=INK2),
        "card_num": ParagraphStyle("card_num", fontSize=17, leading=20, alignment=1, textColor=BLUE, fontName="Body-Bold"),
        "card_title": ParagraphStyle("card_title", fontSize=10.8, leading=13.5, spaceAfter=3, **fb),
        "card_body": ParagraphStyle("card_body", fontSize=9.3, leading=12.8, spaceAfter=3, **f),
        "card_try": ParagraphStyle("card_try", fontSize=9.3, leading=12.8, spaceAfter=3, fontName="Body", textColor=colors.HexColor("#1a5fb4")),
        "card_meta": ParagraphStyle("card_meta", fontName="Body-Bold", fontSize=8.5, leading=11.5, textColor=INK2, spaceAfter=2),
        "card_sure": ParagraphStyle("card_sure", fontName="Body", fontSize=8.3, leading=11, textColor=MUT),
        "cell": ParagraphStyle("cell", fontSize=8.8, leading=11.5, **f),
        "cell_b": ParagraphStyle("cell_b", fontSize=8.8, leading=11.5, **fb),
        "cell_h": ParagraphStyle("cell_h", fontName="Body-Bold", fontSize=8, leading=10, textColor=MUT),
        "tag": ParagraphStyle("tag", fontName="Body-Bold", fontSize=8.4, leading=11, textColor=INK2),
    }


# ---------------------------------------------------------------------------------------------
# small building blocks
# ---------------------------------------------------------------------------------------------
def heading(text, S, intro=None):
    out = [Paragraph(esc(text), S["h1"]), HRFlowable(width="100%", thickness=0.8, color=LINE, spaceBefore=1, spaceAfter=8)]
    if intro:
        out.append(Paragraph(esc(intro), S["lead"]))
    return out


def bullets(lines, S):
    return [Paragraph(esc(t), S["bullet"], bulletText="•") for t in lines if t]


def figure(path, width, S, caption=None, max_h=None):
    w0, h0 = ImageReader(str(path)).getSize()
    w = width
    if max_h and w * h0 / w0 > max_h:
        w = max_h * w0 / h0
    img = Image(str(path), width=w, height=w * h0 / w0)
    img.hAlign = "CENTER"
    if not caption:
        return img                       # one plain flowable, so callers can put it in their own KeepTogether
    return KeepTogether([img, Paragraph(esc(caption), S["caption"])])


def tiles(items, S, total_w, gap=3 * mm):
    n = len(items)
    w = (total_w - gap * (n - 1)) / n
    row, widths = [], []
    for i, (big, cap) in enumerate(items):
        t = Table([[Paragraph(esc(big), S["tile_big"])], [Paragraph(esc(cap), S["tile_cap"])]], colWidths=[w], rowHeights=[13 * mm, 14 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TILE), ("ROUNDEDCORNERS", [5, 5, 5, 5]), ("LEFTPADDING", (0, 0), (-1, -1), 7),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
                               ("TOPPADDING", (0, 1), (-1, 1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        row.append(t)
        widths.append(w)
        if i < n - 1:
            row.append("")
            widths.append(gap)
    out = Table([row], colWidths=widths)
    out.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return out


def card(item, number, accent, S, width):
    parts = [Paragraph(esc(item["title"]), S["card_title"]), Paragraph(esc(item["body"]), S["card_body"])]
    if item.get("try"):
        parts.append(Paragraph("<b>Try next time:</b> " + esc(item["try"]), S["card_try"]))
    if item.get("watch"):
        parts.append(Paragraph(esc(item["watch"]), S["card_meta"]))
    if item.get("sure"):
        parts.append(Paragraph(esc(item["sure"]), S["card_sure"]))
    left = Paragraph(str(number), S["card_num"]) if number else ""
    t = Table([[left, parts]], colWidths=[11 * mm, width - 11 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TILE), ("LINEBEFORE", (0, 0), (0, -1), 3.2, accent), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (0, -1), 3), ("RIGHTPADDING", (0, 0), (0, -1), 2), ("LEFTPADDING", (1, 0), (1, -1), 4),
                           ("RIGHTPADDING", (1, 0), (1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return KeepTogether([t, Spacer(1, 2.6 * mm)])


def grid(rows, widths, S, header=True, bold_first_col=True):
    data = []
    for i, r in enumerate(rows):
        style = S["cell_h"] if header and i == 0 else (S["cell_b"] if bold_first_col else S["cell"])
        data.append([Paragraph(esc(c), style if j == 0 else (S["cell_h"] if header and i == 0 else S["cell"])) for j, c in enumerate(r)])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]
    for i in range(1 if header else 0, len(rows)):
        if (i - (1 if header else 0)) % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), TILE))
    t.setStyle(TableStyle(style))
    return t


def callout(title, lines, S, width, colour=MUT):
    inner = [Paragraph("<b>" + esc(title) + "</b>", S["card_body"])] + [Paragraph(esc(t), S["card_body"]) for t in lines]
    t = Table([[inner]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TILE), ("LINEBEFORE", (0, 0), (0, -1), 3.2, colour), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return KeepTogether([t, Spacer(1, 3 * mm)])


# ---------------------------------------------------------------------------------------------
# the words an assistant writes
# ---------------------------------------------------------------------------------------------
def load_items(path, what):
    """tips.json: a list of {"title", "body", optional "kind", "try", "watch", "sure"}; returns a clean list."""
    try:
        items = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"{path}: cannot read {what} ({e})")
    if not isinstance(items, list):
        raise SystemExit(f"{path}: {what} must be a list of items")
    return [clean_item(i, f"{path} item {n}") for n, i in enumerate(items, 1)]


def clean_item(i, where):
    if not isinstance(i, dict):
        raise SystemExit(f"{where}: must be an object with 'title' and 'body'")
    for k in ("title", "body"):
        if not isinstance(i.get(k), str) or not i[k].strip():
            raise SystemExit(f"{where}: needs a non-empty text '{k}'")
    out = {k: i[k].strip() for k in ("title", "body")}
    for k in ("try", "watch", "sure"):
        if i.get(k) is not None:
            if not isinstance(i[k], str):
                raise SystemExit(f"{where}: '{k}' must be text")
            if i[k].strip():
                out[k] = i[k].strip()
    kind = i.get("kind")
    out["kind"] = kind if kind in KIND_ORDER else "improve"
    return out


def load_scouting(path):
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"{path}: cannot read the scouting notes ({e})")
    if not isinstance(doc, dict):
        raise SystemExit(f"{path}: must be an object with 'strengths', 'weaknesses' and 'plan' lists")
    return {k: [clean_item(i, f"{path} {k} item {n}") for n, i in enumerate(doc.get(k) or [], 1)] for k in ("strengths", "weaknesses", "plan")}


# ---------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------
def load(W):
    L = lambda n: json.loads((W / n).read_text())
    d = dict(R=L("report_data.json"), P=L("points.json")["rallies"], S=L("serves.json"), M=L("motion.json"), PO=L("pose_stats.json")["stats"],
             PK=L("pickups.json"), PL=L("players.json"), CAL=L("calib.json"), SC=L("score.json"), CFG=load_config(W / "players_config.json"),
             OPP=L("opponents.json") if (W / "opponents.json").exists() else None, TIPS=None, SCOUT=None)
    if (W / "tips.json").exists():
        d["TIPS"] = load_items(W / "tips.json", "the coaching tips")
    if (W / "scouting.json").exists():
        d["SCOUT"] = load_scouting(W / "scouting.json")
    return d


def near_pose(d):
    a, b = d["PO"].get("A_you", {}).get("by_side", {}).get("near"), d["PO"].get("A_partner", {}).get("by_side", {}).get("near")
    return (a, b) if a and b else (None, None)


def gap_words(p):
    return {"probably real": "That gap is probably real.", "suggestive": "That gap is suggestive but not settled.",
            "a hint only": "That gap is a hint only; luck alone could produce it.", "no real gap": "No real gap: luck alone explains this."}[pword(p)]


# ---------------------------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------------------------
def cover(d, S, W_, label, today):
    R, P, CFG, PL = d["R"], d["P"], d["CFG"], d["PL"]
    name = CFG["A_you"].get("name")
    last = R["last_scoreboard"]
    sa, sb = (last["score"][0], last["score"][1]) if last["server_team"] == "A" else (last["score"][1], last["score"][0])
    durations = [p["duration"] for p in P]
    story = [Paragraph("BADMINTON ANALYSIS  |  MATCH REPORT", S["kicker"]), Spacer(1, 4 * mm),
             Paragraph("Match analysis report", S["title"]),
             Paragraph(esc(f"For {name}. " if name else "") + esc(f"{label}. Doubles, one game. Made {today}."), S["subtitle"])]
    facts = [["Player analysed", f"{CFG['A_you']['describe']} (\"you\" in this report)"],
             ["Partner", CFG["A_partner"]["describe"]],
             ["Opponents", f"{CFG['B_opp1']['describe']} and {CFG['B_opp2']['describe']}"],
             ["The game", f"{len(P)} rallies, {sum(durations) / 60:.1f} minutes of play, analysed from {mmss(PL['start'])} of the video"],
             ["Result", f"{sa}-{sb} to your team before the last rally ({'your team' if last['server_team'] == 'A' else 'the opponents'} serving); "
                        "the last rally's winner is not shown in the video"]]
    story += [grid(facts, [34 * mm, W_ - 34 * mm], S, header=False), Spacer(1, 6 * mm)]
    story.append(tiles([(f"{sa}-{sb}", "score before the final rally"), (str(len(P)), "rallies"), (f"{R['ties']} / {R['lead_changes']}", "ties / lead changes"),
                        (str(max(R["streak_A"][0], R["streak_B"][0])), f"longest run (yours {R['streak_A'][0]}, theirs {R['streak_B'][0]})"),
                        (f"{sum(durations) / len(durations):.1f} s", "average rally")], S, W_))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("The short version", S["h2"]))
    rows = []
    tips, scout = d["TIPS"], d["SCOUT"]
    if tips:
        by = {k: [t for t in tips if t["kind"] == k] for k in KIND_ORDER}
        for t in by["improve"][:2]:
            rows.append(("Work on", t["title"], BLUE))
        for t in by["check"][:1]:
            rows.append(("Check on video", t["title"], MUT))
        for t in by["strength"][:1]:
            rows.append(("Working well", t["title"], GOOD))
    if scout and scout["weaknesses"]:
        rows.append(("Opponents", scout["weaknesses"][0]["title"], ORANGE))
    if rows:
        t = Table([[Paragraph(f"<font color='#{c.hexval()[2:]}'><b>{esc(a)}</b></font>", S["cell"]), Paragraph(esc(b), S["cell"])] for a, b, c in rows],
                  colWidths=[32 * mm, W_ - 32 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)
    else:
        story.append(callout("Coaching notes are missing", ["tips.json and scouting.json have not been written yet, so this report has the numbers "
                                                            "but no coaching or scouting words. Ask your AI assistant to write them (rules in CLAUDE.md), then build the report again."],
                             S, W_, ORANGE))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("In this report", S["h2"]))
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("toc0", fontName="Body", fontSize=9.5, leading=12.8, textColor=INK, rightIndent=14)]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(Spacer(1, 3 * mm))
    chains = chain_status(d["S"], d["SC"])
    n_conf = sum(c["n"] for c in chains if c["status"] == "confirmed")
    story.append(callout("How sure should you be?", [
        "Positions, distances, speeds and rally times are measured from the video. Who won each rally is inferred from the scoreboard and "
        f"from how the players stand: {n_conf} of {len(P)} rallies are independently confirmed.",
        "This is one game with about 50 rallies, so small differences cannot be detected. Treat every pattern as a question to check on video "
        "(times are given), not a verdict. The 'How sure' page near the end shows how sure each part is."], S, W_))
    return story


def match_section(d, S, W_, img):
    R, PL = d["R"], d["PL"]
    q, sa, sb = R["quarters"], R["streak_A"], R["streak_B"]
    swap = None if PL["tc"] >= NO_CHANGE else mmss(PL["tc"])
    story = heading("The match", S, "How the game unfolded, rally by rally.")
    story.append(figure(img["01"], W_, S))
    quarters = ", ".join(f"{x['A']} of {x['n']}" for x in q)
    rows = [["Points won by your team, by quarter of the game", quarters],
            ["Longest run, your team", f"{sa[0]} points from rally {sa[1][0]} at {mmss(sa[1][1])}"],
            ["Longest run, opponents", f"{sb[0]} points from rally {sb[1][0]} at {mmss(sb[1][1])}"],
            ["Ties and lead changes", f"{R['ties']} ties, {R['lead_changes']} lead changes"],
            ["Teams swapped ends", f"at {swap}" if swap else "no"]]
    story += [Spacer(1, 2 * mm), grid(rows, [66 * mm, W_ - 66 * mm], S, header=False)]
    return story


def coaching_section(d, S, W_):
    tips = d["TIPS"]
    story = heading("Your coaching plan", S, "Written by an AI assistant from the numbers in this report. Each point cites a number, gives video times to "
                    "check and says how sure it is. They are ideas to test on court, not verdicts; advice the video cannot test is labelled as general advice.")
    if not tips:
        return story + [callout("No coaching tips yet", ["tips.json is missing. Ask your AI assistant to write it from report_data.json "
                                                          "(rules in CLAUDE.md), then build the report again."], S, W_, ORANGE)]
    story.append(callout("How to use this plan", ["Watch the clips under 'Moments to check' before you decide anything. Pick one or two points under "
                                                  "'What to work on', not all of them. Film your next game from the same spot and run the analysis again; compare the same numbers."],
                         S, W_, BLUE))
    titles = {"strength": ("What is working", "Keep doing these."), "improve": ("What to work on", "Ordered by how well the video supports them."),
              "check": ("Questions to check on the video", "The data hints at these but cannot settle them: watch the clip before changing anything.")}
    n = 0
    for k in KIND_ORDER:
        items = [t for t in tips if t["kind"] == k]
        if not items:
            continue
        story += [CondPageBreak(55 * mm), Paragraph(esc(titles[k][0]), S["h2"]), Paragraph(esc(titles[k][1]), S["small"]), Spacer(1, 1.5 * mm)]
        for t in items:
            n += 1
            story.append(card(t, n, KIND_COLOUR[k], S, W_))
    return story


def play_section(d, S, W_, img):
    R, M = d["R"], d["M"]["summary"]
    ar, ac, w, r = R["A_when_serving"], R["A_when_receiving"], R["A_when_serving_you"], R["A_when_serving_partner"]
    bl = R["by_length"]
    short, longer = bl[0], [sum(b["n"] for b in bl[1:]), sum(b["A_won"] for b in bl[1:])]
    tot = R["motion_totals"]
    story = [PageBreak()] + heading("How you played", S, "The charts behind the coaching plan, each with what it says in plain words.")
    story.append(KeepTogether([Paragraph("Serving and receiving", S["h2"]), figure(img["02"], W_, S, max_h=92 * mm)] +
                              bullets([f"When your team served it won {ratio(ar)} of rallies; when receiving, {ratio(ac)}. {gap_words(R['serve_vs_receive_p'])}",
                                       f"You won {ratio(w)} of the rallies you served, your partner {ratio(r)}. A handful of serves is too few to call a difference."], S)))
    story.append(KeepTogether([Paragraph("Rally length", S["h2"]), figure(img["03"], W_, S, max_h=84 * mm)] +
                              bullets([f"Rallies under 6 seconds: your team won {ratio([short['A_won'], short['n']])}. Longer rallies: {ratio([longer[1], longer[0]])}.",
                                       f"Average rally: {R['duration_won_lost'][0]:.1f} s when you won, {R['duration_won_lost'][1]:.1f} s when you lost."], S)))
    shown = [("you", k, lab) for k, lab in (("distance_m", "distance per rally"), ("mean_speed", "mean speed"), ("peak_speed", "peak speed"), ("front", "time at the net"),
                                              ("mid", "time mid-court"), ("back", "time at the back"), ("mean_depth", "distance from the net"))] + \
            [("pair", "open_gap_mean", "open gap in your half"), ("pair", "crowded", "time within 1.5 m of your partner")]
    small = [(lab, M[g][k]) for g, k, lab in shown if M[g][k]["p"] < 0.05]
    line = (f"{len(small)} of the {len(shown)} comparisons has p below 0.05: " + "; ".join(f"{lab} (p = {m['p']:.2f})" for lab, m in small) +
            f". With {len(shown)} comparisons about one is expected by chance, so treat it as a question for the video, not a finding.") if small else \
        f"None of the {len(shown)} comparisons reaches p below 0.05: no sign that you move differently in rallies you win and lose."
    story.append(KeepTogether([Paragraph("Movement: rallies won versus lost", S["h2"]), figure(img["04"], W_, S, max_h=122 * mm)] + bullets([
        line, f"Over the game you ran {tot['A_you']['total_distance_m']:.0f} m ({tot['A_you']['distance_per_rally']:.1f} m per rally); your partner {tot['A_partner']['total_distance_m']:.0f} m."], S)))
    story.append(KeepTogether([Paragraph("Where you and your partner stood", S["h2"]), figure(img["05"], 112 * mm, S, max_h=112 * mm)]))
    story.append(KeepTogether([Paragraph("All four players", S["h2"]), figure(img["06"], W_, S, max_h=88 * mm)]))
    near = near_pose(d)
    post = [Paragraph("Posture", S["h2"]), Paragraph("Body landmarks need a large person, so this only works while a player is near the camera.", S["small"]), figure(img["07"], W_, S)]
    if near[0]:
        you, mate = near
        pa = d["PO"]["A_you"]
        arm = pa.get("racket_hand") or ("left" if pa.get("racket_arm") == "L" else "right")
        how = "You told us which hand you use." if pa.get("racket_hand") else "The hand is guessed from a small number of overhead frames: check it on a few swings."
        post += bullets([f"Knees were bent (under 150 degrees) in {you['bent_lt150']:.0%} of your frames and {mate['bent_lt150']:.0%} of your partner's; "
                         f"a straight leg is 180 degrees and your typical angle was {you['knee_median']:.0f} degrees.",
                         f"Your racket hand ({arm}) was held above the hip in {you['racket_up_share']:.0%} of frames (partner {mate['racket_up_share']:.0%}). "
                         + how], S)
    story.append(KeepTogether(post))
    return story


def opponents_section(d, S, W_, img):
    O, CFG, scout = d["OPP"], d["CFG"], d["SCOUT"]
    story = [PageBreak()] + heading("Scouting the opponents", S, "What the video can say about the other team. There is no shuttle tracking, so this is about "
                                    "results, tempo and where they stood, not shot types or where the shuttle landed.")
    if not O:
        return story + [callout("No opponent numbers", ["opponents.json is missing: run stage 7b."], S, W_, ORANGE)]
    R, Q = O["results"], O["players"]
    story.append(figure(img["12"], W_, S, max_h=120 * mm))
    k1, k2 = "B_opp1", "B_opp2"

    def hand(q):
        p = q.get("pose")
        if not p:
            return "not measured"
        n = p["overhead_left"] + p["overhead_right"]
        word = "right" if p["racket_arm"] == "R" else "left"
        return f"{word} ({'fairly clear' if p['racket_arm_clear'] else 'unclear'}: {p['overhead_right']} right vs {p['overhead_left']} left overhead frames of {n})" if n else "not measured"

    rows = [["", f"Opponent 1 ({CFG[k1]['describe']})", f"Opponent 2 ({CFG[k2]['describe']})"],
            ["Distance per rally", *(f"{Q[k]['distance_per_rally']:.1f} m" for k in (k1, k2))],
            ["Mean speed", *(f"{Q[k]['mean_speed']:.2f} m/s" for k in (k1, k2))],
            [f"Net / mid / back ({O['rallies_used_for_depth']} {O['depth_numbers_from']}-half rallies)", *(f"{Q[k]['front']:.0%} / {Q[k]['mid']:.0%} / {Q[k]['back']:.0%}" for k in (k1, k2))],
            ["Nearer the net than their partner", *(f"{Q[k]['net_side_share']:.0%} of rallies" for k in (k1, k2))],
            ["Points won on their own serve", *(ratio(R["by_server"][k]) for k in (k1, k2))],
            ["Racket hand (a guess)", hand(Q[k1]), hand(Q[k2])]]
    if Q[k1].get("pose") and Q[k2].get("pose"):
        rows.append(["Knees bent under 150 degrees", *(f"{Q[k]['pose']['bent_lt150']:.0%} of frames" for k in (k1, k2))])
    story += [Spacer(1, 2 * mm), grid(rows, [52 * mm, (W_ - 52 * mm) / 2, (W_ - 52 * mm) / 2], S)]
    pw = O["pair"]["won_vs_lost"]
    side = pw.get("side_by_side")
    lines = [f"When serving the opponents won {ratio(R['serving'])}; when receiving, {ratio(R['receiving'])}. {gap_words(R['serve_vs_receive_p'])}"]
    sl = R["short_vs_long"]
    if sl["p"] is not None:
        lines.append(f"Rallies under 6 seconds: they won {ratio(sl['short'])}. Longer rallies: {ratio(sl['longer'])}. {gap_words(sl['p'])}")
    lines.append(f"Their longest run was {R['longest_run']['length']} points" + (f" from rally {R['longest_run']['rally']} at {mmss(R['longest_run']['start'])}." if R["longest_run"]["start"] is not None else "."))
    if side and side["p"] is not None:
        lines.append(f"Their pair stood side by side {side['won']:.0%} of the time in rallies they won and {side['lost']:.0%} in rallies they lost "
                     f"(p = {side['p']:.2f}, one of {O['pair']['n_comparisons']} comparisons).")
    story += [Spacer(1, 3 * mm)] + bullets(lines, S)
    if not scout:
        story.append(callout("No scouting notes yet", ["scouting.json is missing. Ask your AI assistant to write it from opponents.json "
                                                       "(rules in CLAUDE.md), then build the report again."], S, W_, ORANGE))
    else:
        names = {"strengths": ("What they do well", "Where they were hard to beat in this game."), "weaknesses": ("Possible openings", "Hints from this one game; none of them is proven."),
                 "plan": ("Game plan to try", "Ideas to test next time you play them. The video cannot prove they work.")}
        story.append(PageBreak())
        n = 0
        for k in ("strengths", "weaknesses", "plan"):
            if not scout[k]:
                continue
            story += [CondPageBreak(50 * mm), Paragraph(esc(names[k][0]), S["h2"]), Paragraph(esc(names[k][1]), S["small"]), Spacer(1, 1.5 * mm)]
            for t in scout[k]:
                n += 1
                story.append(card(t, n, SCOUT_COLOUR[k], S, W_))
    story += [CondPageBreak(120 * mm), Paragraph("Where the opponents stood", S["h2"]), figure(img["13"], W_, S, max_h=100 * mm)]
    z = O.get("zones")
    if z:
        story += bullets([f"The middle lane was covered most: at least one of them stood near it {z['coverage']['mid centre']:.0%} of the time in mid-court and "
                          f"{z['coverage']['back centre']:.0%} at the back. The two side lanes were covered least ({z['coverage']['mid left']:.0%} and "
                          f"{z['coverage']['mid right']:.0%} in mid-court). That shows where they stood, not where they lost points."], S)
    story.append(callout("What the video cannot tell us about the opponents", [
        "Shot types, where the shuttle landed, who made the error, whether a player is tired (the camera sees the two halves differently), "
        "or anything about how they play against other opponents. Racket hand and knee bend come from a few dozen frames at most."], S, W_))
    return story


def moments_section(d, S, W_, img):
    story = [PageBreak()] + heading("Moments to check on the video", S, "In order of video time. Open the clip at these times and see whether the numbers match what you saw.")
    story.append(figure(img["09"], W_, S, max_h=92 * mm))
    return story


def reliability_section(d, S, W_, img):
    R, SC, CAL, S_, P = d["R"], d["SC"], d["CAL"], d["S"], d["P"]
    chains = chain_status(S_, SC)
    n_conf = sum(c["n"] for c in chains if c["status"] == "confirmed")
    story = [Spacer(1, 9 * mm), CondPageBreak(135 * mm)] + heading("How sure is each number?", S, "Left: how well each block of rallies is backed up. Right: the check run at every stage.")
    story.append(figure(img["10"], W_, S, max_h=108 * mm))
    chk = SC["same_server_checks"]
    story.append(KeepTogether([Paragraph("What limits these numbers", S["h2"])] + bullets([
        f"Who won each rally is inferred: the scoreboard shows the server's score, not the team. Independent confirmation covers {n_conf} of {len(P)} rallies; "
        f"in the independent test the same player kept serving in {chk['same_player']} of {chk['pairs']} pairs, against {chk['if_direction_were_wrong']['same_player']} of "
        f"{chk['if_direction_were_wrong']['pairs']} if the inference were backwards.",
        f"Far-court positions are rougher: the camera sees about {max(CAL['pixels_per_metre'].values()):.0f} pixels per metre near the camera but only "
        f"{min(CAL['pixels_per_metre'].values()):.0f} at the far end, so far-half positions (and anything that depends on depth there) are less precise.",
        f"Tracking coverage per player: {', '.join(f'{k} {v:.0%}' for k, v in R['tracking'].items())} of frames.",
        "The last rally is left out of per-rally statistics: after the final point the players keep moving.",
        "No shuttle tracking: shot types, smash counts and landing spots are not measured.",
        "One game, about 50 rallies: most comparisons cannot detect small effects, and with many comparisons some p below 0.05 are expected by chance.",
        "Posture only works while a player is near the camera; opponent posture rests on a few dozen frames."], S)))
    return story


def appendix(d, S, W_, img, photos):
    story = [Spacer(1, 9 * mm), CondPageBreak(150 * mm)] + heading("Appendix: reading the numbers", S)
    rows = [["p-value", "The chance of a gap this big if there were really no difference. Small means a real difference is more likely. "
                        "Below 0.01 reads 'probably real', 0.01 to 0.05 'suggestive', 0.05 to 0.2 'a hint only', above 0.2 'no real gap'. It says nothing about why."],
            ["Rally", "From the moment the serve is set up to the end of the point, found from the player positions and the scoreboard."],
            ["Net / mid / back", "How far a player stood from the net: up to 2.5 m, 2.5 to 4.5 m, beyond 4.5 m."],
            ["Open gap", "The widest stretch of a team's half, across the court, with nobody in it."],
            ["Within 1.5 m", "The share of time the two partners stood closer than 1.5 m to each other."],
            ["Side by side / front-back", "Partners at least 2 m apart sideways and within 2 m of the net: side by side; "
                                          "at least 2 m apart in depth and within 2 m sideways: front-back."],
            ["Measured / inferred", "Measured: positions, distance, speed, posture. Inferred: who served and who won each rally."]]
    story.append(grid(rows, [34 * mm, W_ - 34 * mm], S, header=False))
    if photos and "11" in img:
        story += [Paragraph("How the computer saw the match", S["h2"]), figure(img["11"], W_, S, max_h=165 * mm)]
    story += [Paragraph("How this report was made", S["h2"]),
              Paragraph(esc("The video was analysed on one computer with free, open-source tools: a person detector and a pose model (Ultralytics YOLO), "
                            "the court fitted to hand-picked points, and the scoreboard read by text recognition. The coaching and scouting words were written by an AI "
                            "assistant from the numbers. The video was never uploaded by the program. "
                            + ("This PDF contains charts only, no photographs of people." if not photos else
                               "This PDF includes pictures from the video: check them for faces before you share it.")), S["body"]),
              Paragraph(esc("Badminton Analysis is alpha software, licensed AGPL-3.0: github.com/setuparimi/ai-badminton-analysis. It was checked end to end on only a few videos, "
                            "so treat its output as a measurement with error bars."), S["small"])]
    return story


# ---------------------------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            w = self._pagesize[0]
            self.setFont("Body", 7.8)
            self.setFillColor(MUT)
            self.drawString(MARGIN, 10 * mm, "Numbers are estimates from video. Alpha software: read the 'How sure' page before acting on any of them.")
            self.drawRightString(w - MARGIN, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


class Doc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))


def build(W, out, label, page, photos, today):
    d = load(W)
    register_fonts()
    S = make_styles()
    imgdir = W / "images"
    need = {"01": "01_match_summary.png", "02": "02_serving.png", "03": "03_rally_length.png", "04": "04_you_won_vs_lost.png", "05": "05_heatmaps.png",
            "06": "06_players.png", "07": "07_posture_charts.png", "09": "09_moments_to_check.png", "10": "10_how_sure.png"}
    if d["OPP"]:
        need.update({"12": "12_opponents.png", "13": "13_opponent_positions.png"})
    if photos:
        need.update({"07": "07_posture.png", "11": "11_how_it_was_seen.png"})
    missing = [f for f in need.values() if not (imgdir / f).exists()]
    if missing:
        raise SystemExit(f"missing images in {imgdir}: {', '.join(missing)}. Run stage 12 first (python stages/s12_images.py --work {W}).")
    img = {k: imgdir / f for k, f in need.items()}
    size = A4 if page == "A4" else letter
    W_ = size[0] - 2 * MARGIN
    doc = Doc(str(out), pagesize=size, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=22 * mm, bottomMargin=17 * mm,
                          title=f"Match analysis report: {label}", author="Badminton Analysis (alpha)", subject="Doubles badminton match analysis",
                          creator="Badminton Analysis stage 13")

    def decorate(c, doc_, first):
        w, h = size
        c.saveState()
        c.setFillColor(SURF)
        c.rect(0, 0, w, h, stroke=0, fill=1)
        if first:
            c.setFillColor(BLUE)
            c.rect(0, h - 7 * mm, w * 0.72, 7 * mm, stroke=0, fill=1)
            c.setFillColor(ORANGE)
            c.rect(w * 0.72, h - 7 * mm, w * 0.28, 7 * mm, stroke=0, fill=1)
        else:
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.line(MARGIN, h - 15 * mm, w - MARGIN, h - 15 * mm)
            c.setFont("Body", 7.8)
            c.setFillColor(MUT)
            c.drawString(MARGIN, h - 12.5 * mm, "BADMINTON ANALYSIS  |  MATCH REPORT")
            c.drawRightString(w - MARGIN, h - 12.5 * mm, safe(label))
        c.restoreState()

    frame = Frame(MARGIN, 17 * mm, W_, size[1] - 39 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
    front = Frame(MARGIN, 17 * mm, W_, size[1] - 31 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="cover")
    doc.addPageTemplates([PageTemplate("cover", [front], onPage=lambda c, dd: decorate(c, dd, True)),
                          PageTemplate("body", [frame], onPage=lambda c, dd: decorate(c, dd, False))])
    story = (cover(d, S, W_, label, today) + [NextPageTemplate("body"), PageBreak()] + match_section(d, S, W_, img) + [PageBreak()] +
             coaching_section(d, S, W_) + play_section(d, S, W_, img) + opponents_section(d, S, W_, img) +
             moments_section(d, S, W_, img) + reliability_section(d, S, W_, img) + appendix(d, S, W_, img, photos))
    doc.multiBuild(story, canvasmaker=NumberedCanvas)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--label", default="Match report", help="what to call this match on the cover")
    ap.add_argument("--out", help="PDF to write (default: <work>/match_report.pdf)")
    ap.add_argument("--page", choices=["A4", "letter"], default="A4")
    ap.add_argument("--photos", action="store_true", help="include pictures from the video (faces!) in the PDF")
    ap.add_argument("--date", help="date shown on the cover (default: today)")
    args = ap.parse_args()
    W = Path(args.work)
    out = Path(args.out) if args.out else W / "match_report.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    today = args.date or datetime.date.today().strftime("%d %B %Y").lstrip("0")
    d = build(W, out, args.label, args.page, args.photos, today)
    for name, ok in (("tips.json", d["TIPS"]), ("scouting.json", d["SCOUT"]), ("opponents.json", d["OPP"])):
        if not ok:
            print(f"WARNING: {name} is missing, so that part of the report is a placeholder.")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)" + ("" if args.photos else "; charts only, no photographs"))


if __name__ == "__main__":
    main()
