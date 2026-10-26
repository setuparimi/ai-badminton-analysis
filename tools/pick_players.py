#!/usr/bin/env python3
"""Player picker - click yourself; the partner and the opponents are found for you.

Starts a small web page on your own computer (127.0.0.1 only, nothing leaves the machine). It shows a few
pictures from the start of the game with every person on the court boxed and numbered. Click the box of the
player to analyse ("you" in the report). In doubles your partner (the other person on your half of the court) and the two
opponents (the two on the other half) are filled in automatically; if a picture is not clear about that, click them yourself.
The page then works out how you can be told apart: by shirt colour, by shade, or by shorts (light or dark). Say which hand you
hit with and press Save: players_config.json is written for stage 3.

Run (after stage 3a and the game start are done):
    python tools/pick_players.py --video work/proxy.mp4 --cand work/cand.npz --start 48.8 --out work/players_config.json
    python tools/pick_players.py ... --mode singles --hand left     # singles: you and one opponent
    python tools/pick_players.py ... --time 95                      # a picture near 95 s first
    python tools/pick_players.py --selftest
then:
    python stages/s03_players.py --proxy work/proxy.mp4 --cand work/cand.npz --start 48.8 --out work/players.npz

Output: --out, {"_match": {"mode": "doubles", "hand": "left"}, "A_you": {"shirt": "any", "shorts": "white", "describe": "dark top, light shorts"}, ...}
"""
import argparse
import base64
import http.server
import json
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stages"))
import common  # noqa: E402
import s03_players  # noqa: E402  (candidate filtering and de-duplication are shared with stage 3)

MAX_BODY = 20_000
MAX_FRAMES, MIN_GAP_S, SEARCH_S = 6, 12.0, 400.0
MIN_SHADE_GAP = 25.0                  # Lab lightness (0-255) between two teammates in one colour for the shade to count
EXTERNAL_RE = re.compile(r"(src|href)\s*=\s*[\"']?https?://|@import|url\(\s*[\"']?https?://", re.I)
ROLES = [("A_you", "You (the player to analyse)", "#f5c400"), ("A_partner", "Your partner", "#e03131"),
         ("B_opp1", "Opponent 1", "#2a6fdb"), ("B_opp2", "Opponent 2", "#2f9e44")]
DESCRIBE = {"black": "dark top", "white": "white top"}
MIN_SHORTS_GAP = 35.0                 # Lab lightness (0-255) between two players' shorts for the shorts to count as a cue
STRONG_SHIRT, WEAK_SHIRT = 0.8, 0.5   # how sure the shirt colour guess must be for each players to be told apart by it
WHITE_SHORTS_MIN = 42.0               # the same split as common.shorts_score

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pick yourself</title>
<style>
:root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--tile:#f1f0ec;--line:#c3c2b7;--accent:#2a78d6;--bad:#d03b3b;--good:#0a8a0a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--ink:#f4f3ef;--ink2:#b4b2a9;--tile:#242422;--line:#4a4944;--accent:#6aa7f0;--bad:#f07070;--good:#5fd35f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 40px}h1{font-size:26px;margin:0 0 4px}p.sub{margin:0 0 16px;color:var(--ink2)}
.grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);gap:20px}@media(max-width:860px){.grid{grid-template-columns:1fr}}
canvas{width:100%;height:auto;display:block;border-radius:10px;background:#000;cursor:crosshair}
.roles{display:flex;flex-direction:column;gap:10px}.role{background:var(--tile);border:2px solid transparent;border-radius:10px;padding:10px 12px;cursor:pointer}
.role.active{border-color:var(--accent)}.role .top{display:flex;align-items:center;gap:8px;font-weight:600}.dot{width:14px;height:14px;border-radius:50%;flex:none}
.role .st{margin:4px 0 0 22px;color:var(--ink2);font-size:14px}
input[type=text]{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
button{font:inherit;padding:9px 16px;border-radius:8px;border:1px solid var(--line);background:var(--tile);color:var(--ink);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}button:disabled{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:12px}#msg{margin-top:12px;min-height:22px;font-size:15px}.bad{color:var(--bad)}.good{color:var(--good)}.warn{color:#9a6700}@media (prefers-color-scheme:dark){.warn{color:#e3b341}}
.hint{color:var(--ink2);font-size:14px}fieldset{border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:12px 0 0}legend{font-size:14px;color:var(--ink2);padding:0 6px}
label.opt{margin-right:14px;cursor:pointer}
</style></head><body><main>
<h1>Which one is you?</h1>
<p class="sub" id="sub">Click yourself in the picture. Nothing leaves this computer.</p>
<div class="grid"><div><canvas id="cv" aria-label="Picture of the court with numbered boxes around each person"></canvas>
<div class="row"><button id="prev">Another picture</button><span class="hint" id="where"></span></div></div>
<div><div class="roles" id="roles"></div>
<fieldset><legend>Which hand do you hit with?</legend><label class="opt"><input type="radio" name="hand" value="left"> Left</label><label class="opt"><input type="radio" name="hand" value="right"> Right</label></fieldset>
<div class="row"><label for="nm">Name or nickname (optional, shown on the report cover):</label><input type="text" id="nm" maxlength="40" size="18"></div>
<div class="row"><button class="primary" id="save" disabled>Save</button></div><div id="msg" role="status"></div>
<p class="hint" id="hint"></p></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),ROLES=D.roles,DOUBLES=D.mode==='doubles';
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');let cur=0,active=ROLES[0][0],assign={};const imgs=D.frames.map(f=>{const i=new Image();i.src=f.img;i.onload=draw;return i});
const rolesEl=document.getElementById('roles'),msg=document.getElementById('msg'),saveBtn=document.getElementById('save');let cueOk=false,cueText='',cueWarn=false,seq=0;
document.getElementById('sub').textContent=DOUBLES?'Click yourself in the picture. Your partner and the two opponents are found for you.':'Click yourself in the picture. Your opponent is found for you.';
document.getElementById('hint').textContent=DOUBLES?'Wrong partner or opponent? Click that name on the right, then the right box. Not everyone boxed? Press "Another picture".':'Wrong opponent? Click the name on the right, then the right box.';
if(D.hand){const r=document.querySelector('input[name=hand][value='+D.hand+']');if(r)r.checked=true}
function hand(){const r=document.querySelector('input[name=hand]:checked');return r?r.value:null}
document.querySelectorAll('input[name=hand]').forEach(r=>r.onchange=check);
function box(id){return D.frames[cur].boxes.find(b=>b.id===id)}
function roleOf(id){return Object.keys(assign).find(r=>assign[r]===id)}
function draw(){const f=D.frames[cur],im=imgs[cur];if(!im.complete||!im.naturalWidth)return;cv.width=f.w;cv.height=f.h;ctx.drawImage(im,0,0,f.w,f.h);
 ctx.lineWidth=Math.max(2,f.w/400);ctx.font=Math.round(f.h/22)+'px sans-serif';ctx.textBaseline='top';
 for(const b of f.boxes){const r=roleOf(b.id),col=r?ROLES.find(x=>x[0]===r)[2]:'#ffffff';ctx.strokeStyle=col;ctx.strokeRect(b.x1,b.y1,b.x2-b.x1,b.y2-b.y1);
  const label=String(b.id+1);const w=ctx.measureText(label).width+10;ctx.fillStyle=col;ctx.fillRect(b.x1,b.y1,w,f.h/18);ctx.fillStyle='#000';ctx.fillText(label,b.x1+5,b.y1+2)}
 document.getElementById('where').textContent='Picture '+(cur+1)+' of '+D.frames.length+', at '+Math.floor(f.t/60)+':'+String(Math.floor(f.t%60)).padStart(2,'0')+' of the video'}
function panel(){rolesEl.innerHTML='';for(const [r,label,col] of ROLES){const d=document.createElement('div');d.className='role'+(r===active?' active':'');
 const b=assign[r]!==undefined?box(assign[r]):null;
 d.innerHTML='<div class="top"><span class="dot" style="background:'+col+'"></span>'+label+'</div><div class="st">'+(b?'box '+(b.id+1)+' ('+(b.half==='near'?'near':'far')+' half)':'click a box in the picture')+'</div>';
 d.onclick=()=>{active=r;panel()};rolesEl.appendChild(d)}check()}
async function post(url,body){const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return res.json()}
async function check(){const ok=ROLES.every(([r])=>assign[r]!==undefined);cueOk=false;cueWarn=false;
 if(!ok){cueText='';render();return}
 const my=++seq;try{const j=await post('/cues',{frame:cur,roles:assign});if(my!==seq)return;cueOk=!!j.ok;cueText=j.ok?j.message:j.error;cueWarn=!!j.warn}catch(e){cueText='Could not reach the program: '+e}
 render()}
function render(){msg.className=cueOk?(cueWarn?'warn':''):(cueText?'bad':'');msg.textContent=cueText||'';saveBtn.disabled=!(cueOk&&hand())}
cv.addEventListener('click',async e=>{const f=D.frames[cur],r=cv.getBoundingClientRect(),x=(e.clientX-r.left)*f.w/r.width,y=(e.clientY-r.top)*f.h/r.height;
 const hit=f.boxes.filter(b=>x>=b.x1&&x<=b.x2&&y>=b.y1&&y<=b.y2).sort((a,b)=>(a.x2-a.x1)*(a.y2-a.y1)-(b.x2-b.x1)*(b.y2-b.y1))[0];if(!hit)return;
 const old=roleOf(hit.id);if(old)delete assign[old];assign[active]=hit.id;
 if(active==='A_you'){try{const j=await post('/auto',{frame:cur,you:hit.id});if(j.ok){assign=j.roles;msg.className='';msg.textContent=j.message||''}else{for(const [rr] of ROLES)if(rr!=='A_you')delete assign[rr];
   msg.className='warn';msg.textContent=j.error||'';const nxt=ROLES.find(([rr])=>assign[rr]===undefined);if(nxt)active=nxt[0]}}catch(err){}}
 else{const nxt=ROLES.find(([rr])=>assign[rr]===undefined);if(nxt)active=nxt[0]}
 draw();panel()});
document.getElementById('prev').onclick=()=>{if(Object.keys(assign).length&&!confirm('Show another picture? Your clicks on this one are cleared.'))return;
 cur=(cur+1)%D.frames.length;assign={};active=ROLES[0][0];msg.textContent='';draw();panel()};
saveBtn.onclick=async()=>{saveBtn.disabled=true;try{const j=await post('/save',{frame:cur,roles:assign,hand:hand(),name:document.getElementById('nm').value});
 if(j.ok){msg.className='good';msg.textContent='Saved. You can close this tab; the analysis carries on in the terminal.'}else{msg.className='bad';msg.textContent=j.error||'Could not save';saveBtn.disabled=false}}
 catch(err){msg.className='bad';msg.textContent='Could not reach the program: '+err;saveBtn.disabled=false}};
draw();panel();
</script></main></body></html>
"""


# ---------------------------------------------------------------------------------------------
# choosing pictures and reading shirt colours
# ---------------------------------------------------------------------------------------------
def best_shirt(f):
    """(shirt colour, score) with the best colour_score for one candidate's torso features."""
    scores = {c: float(common.colour_score(c, f)) for c in common.COLOURS}
    name = max(scores, key=scores.get)
    return name, scores[name]


def swatch_rgb(tL, ta, tb):
    lab = np.array([[[tL, ta, tb]]], np.float32).clip(0, 255).astype(np.uint8)
    return [int(v) for v in cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)[0, 0]]


def choose_frames(cand_path, start, at_time=None, n=MAX_FRAMES, mode="doubles"):
    """Frames (sampled by stage 1) where the players are on court (four to six people in doubles, two to four in singles), spread over the game.

    Returns a list of {"f": frame index, "t": seconds, "boxes": [{"id", "x1", "y1", "x2", "y2", "shirt", "score", "rgb"}]}.
    With at_time the pictures nearest that second come first."""
    c, fps, stride = s03_players.load_candidates(cand_path, start, 0.35, height_ratio=s03_players.estimate_height_window(cand_path))
    by_f = {}
    for i in range(len(c["f"])):
        by_f.setdefault(int(c["f"][i]), []).append(i)
    found = []
    for f in sorted(by_f):
        t = f / fps
        if t > start + SEARCH_S and at_time is None:
            break
        idx = s03_players.dedupe(by_f[f], c)
        want = 4 if mode == "doubles" else 2
        if want <= len(idx) <= want + 2:
            guesses = [best_shirt({key: float(c[key][i]) for key in s03_players.FEATS}) for i in idx]
            spread = float(np.std([c["X"][i] for i in idx]) + np.std([c["Y"][i] for i in idx]))
            n_far = int(sum(c["Y"][i] >= common.NET_Y for i in idx))
            tidy = len(idx) == want and n_far == want // 2          # exactly one team on each half
            rank = spread + (2.0 if len(idx) == want else 0.0) + (4.0 if tidy else 0.0) \
                + (1.5 if len({g[0] for g in guesses}) == len(guesses) else 0.0) + float(np.mean([g[1] for g in guesses]))
            found.append((t, f, idx, rank))
    if not found:
        return []
    chosen = []
    if at_time is not None:
        found.sort(key=lambda r: abs(r[0] - at_time))
    else:
        found.sort(key=lambda r: -r[3])
    for t, f, idx, _ in found:
        if all(abs(t - u[0]) >= MIN_GAP_S for u in chosen):
            chosen.append((t, f, idx))
        if len(chosen) == n:
            break
    chosen.sort(key=lambda r: abs(r[0] - at_time)) if at_time is not None else None
    frames = []
    for t, f, idx in chosen:
        idx = sorted(idx, key=lambda i: c["x1"][i])
        boxes = []
        for k, i in enumerate(idx):
            feats = {key: float(c[key][i]) for key in s03_players.FEATS}
            shirt, score = best_shirt(feats)
            boxes.append({"id": k, "x1": float(c["x1"][i]), "y1": float(c["y1"][i]), "x2": float(c["x2"][i]), "y2": float(c["y2"][i]),
                          "shirt": shirt, "score": round(score, 2), "rgb": swatch_rgb(c["tL"][i], c["ta"][i], c["tb"][i]), "tL": round(float(c["tL"][i]), 1),
                          "sL": round(float(c["sL"][i]), 1) if "sL" in c else None, "half": "far" if c["Y"][i] >= common.NET_Y else "near",
                          "X": round(float(c["X"][i]), 2), "Y": round(float(c["Y"][i]), 2),
                          "wide": bool(common.shorts_unreliable(c["x1"][i], c["y1"][i], c["x2"][i], c["y2"][i], c.get("_H", 720.0)))})
        frames.append({"f": f, "t": round(t, 2), "boxes": boxes})
    return frames


def attach_images(frames, video, max_w=1100):
    """Add the picture (JPEG, base64) and its size to every chosen frame."""
    cap = cv2.VideoCapture(str(video))
    out = []
    for fr in frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fr["f"])
        ok, img = cap.read()
        if not ok:
            continue
        h, w = img.shape[:2]
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        out.append(dict(fr, w=w, h=h, img="data:image/jpeg;base64," + base64.b64encode(buf).decode()))
    cap.release()
    return out


def roles_for(mode):
    return [r for r in ROLES if mode == "doubles" or r[0] in common.SINGLES_SLOTS]


def build_page(frames, mode="doubles", hand=None):
    data = {"frames": frames, "roles": roles_for(mode), "mode": mode, "hand": hand}
    blob = json.dumps(data).replace("</", "<\\/")
    return PAGE.replace("__DATA__", blob)


# ---------------------------------------------------------------------------------------------
# validation and saving
# ---------------------------------------------------------------------------------------------
def build_ctx(cand_path, start):
    """What the picker needs to look at the video around a picture: the candidate boxes, grouped by sampled frame."""
    c, fps, stride = s03_players.load_candidates(cand_path, max(0.0, start - 30.0), 0.35, height_ratio=s03_players.estimate_height_window(cand_path))
    by_f = {}
    for i in range(len(c["f"])):
        by_f.setdefault(int(c["f"][i]), []).append(i)
    return {"c": c, "fps": fps, "stride": stride, "by_f": by_f}


def _features(c, i):
    f = {key: float(c[key][i]) for key in s03_players.FEATS}
    if "sL" in c:
        f["sL"] = float(c["sL"][i])
    f["wide"] = bool(common.shorts_unreliable(c["x1"][i], c["y1"][i], c["x2"][i], c["y2"][i], c.get("_H", 720.0)))
    return f


NEAR_STEPS = 12      # how many readable moments nearest the click set the direction of the cue (about 1.2 s when the boxes are always readable)


def seed_pairs(ctx, frame_no, a, b, seconds=6.0, gate=0.9):
    """Follow two people (boxes a and b of the picture at frame_no) for `seconds` either side by position alone, and return their
    clothing features in every sampled frame where both were found: [(features of a, features of b, steps from the picture), ...]."""
    c, fps, stride, by_f = ctx["c"], ctx["fps"], ctx["stride"], ctx["by_f"]
    half_far = a["half"] == "far"
    pairs = []
    for direction in (1, -1):
        pa, pb, f = (a["X"], a["Y"]), (b["X"], b["Y"]), frame_no
        for step in range(1, int(seconds * fps / stride) + 1):
            f += direction * stride
            idx = [i for i in s03_players.dedupe(by_f.get(f, []), c) if (c["Y"][i] >= common.NET_Y) == half_far]
            if len(idx) < 2:
                continue
            cost = np.array([[np.hypot(c["X"][i] - p[0], c["Y"][i] - p[1]) for p in (pa, pb)] for i in idx])
            ri, ci = linear_sum_assignment(cost)
            if len(ri) < 2 or cost[ri, ci].max() > gate:
                continue
            ia, ib = (idx[ri[list(ci).index(k)]] for k in (0, 1))
            pa, pb = (c["X"][ia], c["Y"][ia]), (c["X"][ib], c["Y"][ib])
            pairs.append((_features(c, ia), _features(c, ib), step))
    return pairs


def cue_agreement(kind, cfg_a, cfg_b, pairs):
    """Share of the followed moments in which the cue puts the right person in the right place (1.0 = always). Moments where a box is wide
    (an arm out can put floor in the middle of it) say nothing about shorts and are skipped for them."""
    ok = []
    for fa, fb, _ in pairs:
        if kind == "shorts":
            if fa.get("wide") or fb.get("wide"):
                continue
            ok.append(common.shorts_score(cfg_a["shorts"], fa) + common.shorts_score(cfg_b["shorts"], fb)
                      > common.shorts_score(cfg_a["shorts"], fb) + common.shorts_score(cfg_b["shorts"], fa))
        else:
            sa = lambda f: common.colour_score(cfg_a["shirt"], f, cfg_a.get("tone"), cfg_a.get("tone_split", 112.0))
            sb = lambda f: common.colour_score(cfg_b["shirt"], f, cfg_b.get("tone"), cfg_b.get("tone_split", 112.0))
            ok.append(sa(fa) + sb(fb) > sa(fb) + sb(fa))
    return float(np.mean(ok)) if len(ok) >= 8 else 0.0


def smooth_box(box, feats):
    """The box with its clothing numbers replaced by the median over several moments (one picture can be a bad one: an arm in front, a shadow).
    The shorts reading is taken only from moments when the box was not wide (an arm out can put bright floor in the middle of it)."""
    out = dict(box)
    med = {k: float(np.median([f[k] for f in feats if k in f])) for k in feats[0] if k != "wide"}
    out["tL"] = round(med["tL"], 1)
    slim = [f["sL"] for f in feats if "sL" in f and not f.get("wide")]
    out["sL"] = round(float(np.median(slim)), 1) if len(slim) >= 3 else None
    out["wide"] = out["sL"] is None                                  # readable now if enough readable moments were seen
    out["shirt"], out["score"] = best_shirt({k: med[k] for k in s03_players.FEATS})
    return out


def proposals(a, b):
    """Every way two teammates (boxes a and b) might be told apart, from the one picture: [(kind, config a, config b, words), ...]."""
    out = []
    if a["shirt"] != b["shirt"]:
        out.append(("shirt", {"shirt": a["shirt"]}, {"shirt": b["shirt"]}, f"by shirt colour ({a['shirt']} and {b['shirt']})"))
    if a.get("sL") is not None and b.get("sL") is not None and not a.get("wide") and not b.get("wide") and abs(a["sL"] - b["sL"]) >= 20.0:
        a_light = a["sL"] > b["sL"]
        out.append(("shorts", {"shirt": "any", "shorts": "white" if a_light else "dark"}, {"shirt": "any", "shorts": "dark" if a_light else "white"},
                    "by shorts (one light, one dark)"))
    if a["shirt"] == b["shirt"] and abs(a["tL"] - b["tL"]) >= 15.0:
        split = round((a["tL"] + b["tL"]) / 2, 1)
        a_light = a["tL"] > split
        out.append(("tone", {"shirt": a["shirt"], "tone": "light" if a_light else "dark", "tone_split": split},
                    {"shirt": b["shirt"], "tone": "dark" if a_light else "light", "tone_split": split}, f"by shade (one lighter, one darker {a['shirt']} top)"))
    return out


def auto_roles(frame, you_id, mode="doubles"):
    """Fill in the other roles from the box the user clicked. Your partner is the other person on your half of the court; the opponents
    are the people on the other half. Raises ValueError (with a plain message) when the picture does not show that clearly."""
    boxes = {b["id"]: b for b in frame["boxes"]}
    if you_id not in boxes:
        raise ValueError("that box does not exist")
    mine = boxes[you_id]["half"]
    mates = [b for b in frame["boxes"] if b["half"] == mine and b["id"] != you_id]
    others = [b for b in frame["boxes"] if b["half"] != mine]
    roles = {"A_you": you_id}
    if mode == "singles":
        if len(others) != 1:
            raise ValueError("this picture does not show exactly one person on the other half of the court: click your opponent yourself, or press Another picture")
        roles["B_opp1"] = others[0]["id"]
        return roles
    if len(mates) != 1 or len(others) != 2:
        raise ValueError(f"this picture shows {len(mates) + 1} on your half and {len(others)} on the other, not two and two: click your partner and the "
                         "opponents yourself, or press Another picture")
    roles["A_partner"] = mates[0]["id"]
    roles["B_opp1"], roles["B_opp2"] = sorted((b["id"] for b in others), key=lambda i: boxes[i]["x1"])
    return roles


def _describe(box, cfg):
    top = DESCRIBE.get(box["shirt"], f"{box['shirt']} top")
    if "shorts" in cfg:
        return f"{top}, {'light' if cfg['shorts'] == 'white' else 'dark'} shorts"
    if "tone" in cfg:
        return f"{cfg['tone']} {box['shirt']} top"
    return top if cfg["shirt"] != "any" else top


def team_cues(a, b, pairs=None):
    """How two teammates (boxes a and b) can be told apart. Returns (config for a, config for b, how it was done) or None.
    pairs: what the same two people looked like in the seconds around the picture (see seed_pairs). With it, every possible cue is
    tried on all those moments and the best one that works almost every time is used: shirt colour first, then shorts, then shade.
    Without it only the one picture is used: a clearly different shirt colour, then light against dark shorts, then two shades, then a weak colour."""
    if pairs and len(pairs) >= 15:
        # who is who is fixed by the click, so the cue's direction (who is the lighter one) comes from the moments right around the click, before the
        # followed tracks can have swapped people at a crossing; the rest of the moments only test whether the cue holds
        slim = sorted((p for p in pairs if not p[0].get("wide") and not p[1].get("wide")), key=lambda p: p[2])
        close = slim[:NEAR_STEPS]                      # the moments nearest the click in which both boxes can be read
        props = proposals(smooth_box(a, [p[0] for p in close]), smooth_box(b, [p[1] for p in close])) if len(close) >= 8 else proposals(a, b)
        scored = [(cue_agreement(k, ca, cb, pairs), i, k, ca, cb, text) for i, (k, ca, cb, text) in enumerate(props)]
        for need, kinds in ((0.8, ("shirt", "shorts", "tone")), (0.65, ("shirt", "shorts", "tone"))):
            good = [r for r in scored if r[2] in kinds and r[0] >= need]
            if good:
                best = max(good, key=lambda r: (round(r[0], 2), -r[1]))
                note = "" if need >= 0.8 else "; only roughly, check the labels on the tracking sheet"
                return best[3], best[4], f"{best[5]} (right in {100 * best[0]:.0f}% of the {len(pairs)} moments checked{note})"
        return None
    props = proposals(a, b)
    if a["shirt"] != b["shirt"] and min(a["score"], b["score"]) >= STRONG_SHIRT:
        return {"shirt": a["shirt"]}, {"shirt": b["shirt"]}, f"by shirt colour ({a['shirt']} and {b['shirt']})"
    for kind, ca, cb, text in props:
        if kind == "shorts" and abs(a["sL"] - b["sL"]) >= MIN_SHORTS_GAP:
            return ca, cb, text
        if kind == "tone" and abs(a["tL"] - b["tL"]) >= MIN_SHADE_GAP:
            return ca, cb, text
    if a["shirt"] != b["shirt"] and min(a["score"], b["score"]) >= WEAK_SHIRT:
        return {"shirt": a["shirt"]}, {"shirt": b["shirt"]}, f"by shirt colour, but only roughly ({a['shirt']} and {b['shirt']}); check the labels on the tracking sheet"
    return None


def build_config(frame, roles, mode="doubles", hand=None, name="", ctx=None):
    """Turn a chosen picture and its roles into the players_config.json content (and a plain sentence about how people are told apart).
    Raises ValueError with a plain message when it cannot be done."""
    need = [r[0] for r in roles_for(mode)]
    if not isinstance(roles, dict) or set(roles) != set(need):
        raise ValueError("choose all " + ("four players" if mode == "doubles" else "two players"))
    by_id = {b["id"]: dict(b) for b in frame["boxes"]}
    picked = [roles[s] for s in need]
    if not all(isinstance(v, int) and not isinstance(v, bool) and v in by_id for v in picked):
        raise ValueError("a chosen box does not exist in this picture")
    if len(set(picked)) != len(picked):
        raise ValueError("each box can be only one person")
    box = {s: by_id[roles[s]] for s in need}
    if mode == "doubles":
        for s in ("A_you", "A_partner"):
            if box[s]["half"] != box["A_you"]["half"]:
                raise ValueError("you and your partner are on different halves of the court in this picture: check your clicks")
        if box["B_opp1"]["half"] == box["A_you"]["half"] or box["B_opp2"]["half"] == box["A_you"]["half"]:
            raise ValueError("an opponent is on your half of the court in this picture: check your clicks")
    elif box["B_opp1"]["half"] == box["A_you"]["half"]:
        raise ValueError("your opponent is on your half of the court in this picture: check your clicks")
    cfg, notes = {}, []
    if mode == "doubles":
        mine = team_cues(box["A_you"], box["A_partner"], seed_pairs(ctx, frame["f"], box["A_you"], box["A_partner"]) if ctx else None)
        if mine is None:
            if box["A_you"].get("wide") or box["A_partner"].get("wide"):
                raise ValueError("one of you is very close to the camera or cut off at the edge of this picture, so the clothes cannot be read well enough to tell you apart. "
                                 "Press Another picture and click yourself in one where you are both fully in view.")
            raise ValueError("you and your partner cannot be told apart: same shirt colour and shade and the same kind of shorts. Press Another picture; "
                             "if it stays like this, one of you needs something different to wear (a cap does not count).")
        cfg["A_you"], cfg["A_partner"], how = mine
        notes.append(f"You and your partner are told apart {how}.")
        theirs = team_cues(box["B_opp1"], box["B_opp2"], seed_pairs(ctx, frame["f"], box["B_opp1"], box["B_opp2"]) if ctx else None)
        if theirs is None:
            cfg["B_opp1"], cfg["B_opp2"] = {"shirt": "any"}, {"shirt": "any"}
            notes.append("The two opponents look alike, so they are tracked as a pair (their individual numbers will not be reported).")
        else:
            cfg["B_opp1"], cfg["B_opp2"], how = theirs
            notes.append(f"The opponents are told apart {how}.")
        for s in need:
            cfg[s]["describe"] = _describe(box[s], cfg[s])
    else:
        both = team_cues(box["A_you"], box["B_opp1"])
        if both is None:
            cfg["A_you"], cfg["B_opp1"] = {"shirt": "any"}, {"shirt": "any"}
            notes.append("You and your opponent look alike, so the side you start on has to be given by hand (--first-near).")
        else:
            cfg["A_you"], cfg["B_opp1"], how = both
            notes.append(f"You and your opponent are told apart {how}.")
        for s in need:
            cfg[s]["describe"] = _describe(box[s], cfg[s])
    if hand not in common.HANDS:
        raise ValueError("say which hand you hit with")
    name = name if isinstance(name, str) else ""
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()[:40]
    if name:
        cfg["A_you"]["name"] = name
    seen = {"t": frame.get("t"), "you_half": box["A_you"]["half"]}
    for key, slot in (("you_xy", "A_you"), ("partner_xy", "A_partner")):
        if slot in box and box[slot].get("X") is not None:
            seen[key] = [box[slot]["X"], box[slot]["Y"]]
    out = {"_match": {"mode": mode, "hand": hand, "seen": seen}}
    out.update({k: cfg[k] for k in ("A_you", "A_partner", "B_opp1", "B_opp2") if k in cfg})
    return out, " ".join(notes)


def save_config(path, cfg):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n")
    tmp.replace(path)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "PlayerPicker"

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, self.server.page, "text/html; charset=utf-8")
        elif path == "/favicon.ico":
            self._send(204)
        else:
            self._send(404, b"not found")

    def do_POST(self):
        if self.path not in ("/save", "/auto", "/cues"):
            return self._send(404, b"not found")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(411, {"ok": False, "error": "Content-Length required"})
        if not 0 < length <= MAX_BODY:
            return self._json(413, {"ok": False, "error": "body too large"})
        body = self.rfile.read(length)
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self._json(403, {"ok": False, "error": "unexpected Host header"})
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(415, {"ok": False, "error": "send application/json"})
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("expected an object")
            fi = data.get("frame")
            if not isinstance(fi, int) or isinstance(fi, bool) or not 0 <= fi < len(self.server.frames):
                raise ValueError("unknown picture")
            frame, mode = self.server.frames[fi], self.server.mode
            if self.path == "/auto":
                you = data.get("you")
                if not isinstance(you, int) or isinstance(you, bool):
                    raise ValueError("click a box")
                roles = auto_roles(frame, you, mode)
                _, msg = build_config(frame, roles, mode, self.server.hand or "right", "", self.server.ctx)
                return self._json(200, {"ok": True, "roles": roles, "message": msg})
            if self.path == "/cues":
                _, msg = build_config(frame, data.get("roles"), mode, self.server.hand or "right", "", self.server.ctx)
                return self._json(200, {"ok": True, "message": msg, "warn": "alike" in msg or "roughly" in msg})
            cfg, _ = build_config(frame, data.get("roles"), mode, data.get("hand"), data.get("name", ""), self.server.ctx)
        except ValueError as e:
            return self._json(400, {"ok": False, "error": str(e)})
        save_config(self.server.out_path, cfg)
        self.server.saved = cfg
        self._json(200, {"ok": True, "path": str(self.server.out_path)})
        threading.Thread(target=self.server.shutdown, daemon=True).start()


class PickerServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, frames, out_path, mode="doubles", hand=None, ctx=None):
        super().__init__(("127.0.0.1", port), Handler)
        self.frames = frames
        self.mode, self.hand, self.ctx = mode, hand, ctx
        self.page = build_page(frames, mode, hand).encode("utf-8")
        self.out_path = Path(out_path)
        self.saved = None


# ---------------------------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------------------------
def synthetic_frames(w=640, h=360):
    img = np.full((h, w, 3), 90, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    uri = "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    # two near (white shirt, red shirt) and two far (black, grey); shorts are alike, so the shirts tell people apart
    spec = [("white", 200, 70.0), ("red", 90, 72.0), ("black", 40, 20.0), ("grey", 120, 22.0)]
    boxes = [{"id": i, "x1": 40.0 + 120 * i, "y1": 80.0, "x2": 100.0 + 120 * i, "y2": 300.0, "shirt": sh, "score": 0.9, "rgb": [200, 200, 200],
              "half": "near" if i < 2 else "far", "tL": tl, "sL": sl, "X": 1.0 + 1.0 * i, "Y": 3.0 if i < 2 else 10.0} for i, (sh, tl, sl) in enumerate(spec)]
    return [{"f": 0, "t": 10.0, "w": w, "h": h, "img": uri, "boxes": boxes}]


def _post(base, payload, ctype="application/json", path="/save"):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


GOOD = {"frame": 0, "roles": {"A_you": 0, "A_partner": 1, "B_opp1": 2, "B_opp2": 3}, "hand": "left", "name": " Sam "}


def selftest(log=print):
    """Serve on an ephemeral port in a thread, POST good and bad choices, check the file and the shutdown."""
    failures = []

    def check(label, cond):
        log(("PASS  " if cond else "FAIL  ") + label)
        if not cond:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sub" / "players_config.json"
        server = PickerServer(0, synthetic_frames(), out, "doubles", "left")
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(base + "/", timeout=10) as r:
                page = r.read().decode()
            check("page is served", r.status == 200 and "<canvas" in page and "data:image/jpeg;base64," in page)
            check("page has no external resources", not EXTERNAL_RE.search(page))
            code, reply = _post(base, {"frame": 0, "you": 0}, path="/auto")
            check("finds partner and opponents from one click", code == 200 and reply["roles"] == {"A_you": 0, "A_partner": 1, "B_opp1": 2, "B_opp2": 3})
            code, reply = _post(base, {"frame": 0, "roles": GOOD["roles"]}, path="/cues")
            check("says how people are told apart", code == 200 and "shirt colour" in reply["message"])
            bad = [("not json", b"{nope", "application/json"), ("wrong content type", GOOD, "text/plain"),
                   ("unknown picture", dict(GOOD, frame=3), "application/json"),
                   ("missing player", dict(GOOD, roles={k: v for k, v in GOOD["roles"].items() if k != "B_opp2"}), "application/json"),
                   ("one box twice", dict(GOOD, roles=dict(GOOD["roles"], B_opp2=0)), "application/json"),
                   ("box that does not exist", dict(GOOD, roles=dict(GOOD["roles"], B_opp2=9)), "application/json"),
                   ("partner on the other half", dict(GOOD, roles=dict(GOOD["roles"], A_partner=2, B_opp1=1)), "application/json"),
                   ("no hand", dict(GOOD, hand=None), "application/json")]
            for label, payload, ctype in bad:
                code, _ = _post(base, payload, ctype)
                check(f"refuses {label}", 400 <= code < 500 and not out.exists())
            code, reply = _post(base, GOOD)
            check("accepts a good choice", code == 200 and reply.get("ok"))
            thread.join(10)
            check("server shut down after saving", not thread.is_alive())
            cfg = json.loads(out.read_text()) if out.exists() else {}
            check("config has the four shirts, the hand and the name", [cfg.get(s, {}).get("shirt") for s in common.SLOTS] == ["red", "white", "black", "grey"]
                  and cfg.get("A_you", {}).get("name") == "Sam" and cfg.get("_match", {}).get("hand") == "left")
            check("stage 3 accepts the file", bool(out.exists()) and bool(common.load_config(out)))
        except Exception as e:
            check(f"no exception ({type(e).__name__}: {e})", False)
        finally:
            if thread.is_alive():
                server.shutdown()
            server.server_close()
    log("SELFTEST " + ("PASSED" if not failures else "FAILED: " + "; ".join(failures)))
    return not failures


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", help="proxy video (stage 0 output)")
    ap.add_argument("--cand", help="cand.npz (stage 3a output)")
    ap.add_argument("--start", type=float, help="second the game starts (game_start.json)")
    ap.add_argument("--time", type=float, help="show the pictures nearest this second first")
    ap.add_argument("--mode", choices=common.MODES, default="doubles", help="doubles (default): you, your partner and two opponents; singles: you and one opponent")
    ap.add_argument("--hand", choices=common.HANDS, help="the hand you hit with (can also be chosen on the page)")
    ap.add_argument("--out", default="work/players_config.json", help="players_config.json to write (default: %(default)s)")
    ap.add_argument("--port", type=int, default=8766, help="local port (default: %(default)s; 0 picks a free one)")
    ap.add_argument("--no-browser", action="store_true", help="only print the address, do not open a browser")
    ap.add_argument("--selftest", action="store_true", help="check the server and exit 0 (ok) or 1 (failed)")
    args = ap.parse_args(argv)
    if not args.selftest and not (args.video and args.cand and args.start is not None):
        ap.error("give --video, --cand and --start (or --selftest)")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    for p in (args.video, args.cand):
        if not Path(p).exists():
            sys.exit(f"not found: {p}")
    frames = attach_images(choose_frames(args.cand, args.start, args.time, mode=args.mode), args.video)
    if not frames:
        sys.exit("Could not find a picture with the players on the court. Check the court points (stage 2) and the start second, "
                 "try --time SECONDS with a moment when all four players are on court, or write players_config.json by hand "
                 "(see examples/reference-match/players_config.json).")
    try:
        server = PickerServer(args.port, frames, args.out, args.mode, args.hand, build_ctx(args.cand, args.start))
    except OSError as e:
        sys.exit(f"cannot listen on port {args.port} ({e.strerror}); try --port {args.port + 1} or --port 0")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Player picker is running ({len(frames)} pictures).")
    print(f"Open this address in your browser: {url}")
    print("Click yourself in the picture, check the others, choose your hand and press Save; this program then stops by itself.")
    if Path(args.out).exists():
        print(f"Note: {args.out} already exists and will be replaced when you save.")
    if not args.no_browser and not webbrowser.open(url):
        print("(could not open a browser automatically; open the address above yourself)")
    sys.stdout.flush()
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("\nStopped without saving.")
    finally:
        server.server_close()
    if not server.saved:
        sys.exit(1)
    print(f"Saved {args.out}:")
    for s in ("A_you", "A_partner", "B_opp1", "B_opp2"):
        if s in server.saved:
            print(f"  {s:10s} {server.saved[s]['describe']}")
    print(f"Next: python stages/s03_players.py --proxy {args.video} --cand {args.cand} --start {args.start} --out {Path(args.out).with_name('players.npz')}")


if __name__ == "__main__":
    main()
