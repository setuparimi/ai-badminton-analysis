#!/usr/bin/env python3
"""Court point picker - click the court landmarks on a photo instead of reading pixels off a grid.

Starts a small web page on your own computer (127.0.0.1 only, nothing leaves the machine). The page shows
the photo of the court next to a court diagram: click a dot on the diagram, then click the same spot on the
photo. Repeat for at least 6 spots you can see clearly. A magnifier helps to place points precisely and a
live overlay of the court model shows whether the points fit. Save writes the JSON that stage 2 reads.

Court frame (metres), the same as stage 2: X across the court 0..6.1 and Y along it 0..13.4.
    Y = 0 is the near baseline (closest to the camera), the net is at Y = 6.7.
    X = 0 is the LEFT doubles sideline for a player standing on the near baseline facing the net.
Landmarks: every crossing of the painted lines (30) plus the two net-post bases (2).

Run:
    python tools/pick_court_points.py --video work/proxy.mp4 --out work/court_points.json
    python tools/pick_court_points.py --image work/bg_median.png --out work/court_points.json --no-browser
    python tools/pick_court_points.py --selftest
then:
    python stages/s02_calibrate.py --proxy work/proxy.mp4 --points work/court_points.json --out work/calib.json

With --video the photo is the stage 2 median background (players disappear in a median). It is reused from
bg_median.png next to --out if that file exists, and written there otherwise, so stage 2 reuses it too.
Output: --out, a JSON list of {"name": str, "px": [x, y], "court": [X, Y]} with px in original image pixels.
"""
import argparse
import base64
import http.server
import json
import math
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stages"))
import s02_calibrate as s02  # noqa: E402  (court model and median_background live in stage 2)

MIN_POINTS = 6        # the page keeps Save disabled below this
MAX_BODY = 1_000_000  # bytes accepted by POST /save

# Painted-line crossings: rows are Y (metres from the near baseline), columns are X (across the court).
LM_Y = [(0, "near baseline"), (0.76, "near doubles long service line"), (4.72, "near short service line"),
        (8.68, "far short service line"), (12.64, "far doubles long service line"), (13.4, "far baseline")]
LM_X = [(0, "left doubles sideline"), (0.46, "left singles sideline"), (3.05, "centre line"),
        (5.64, "right singles sideline"), (6.1, "right doubles sideline")]


def build_landmarks():
    out = []
    for y, yname in LM_Y:
        for x, xname in LM_X:
            if x == 3.05 and y in (4.72, 8.68):
                xname += " (T)"
            out.append({"name": f"{yname} x {xname}", "court": [x, y]})
    for x, side in ((0, "left"), (6.1, "right")):
        out.append({"name": f"{side} net post base", "court": [x, 6.7]})
    return out


LANDMARKS = build_landmarks()

# Nine hand-picked points on the 1280x720 median background of one test video, used by --selftest.
SELFTEST_POINTS = [
    {"name": "near short service line x right doubles sideline", "px": [1188, 547], "court": [6.1, 4.72]},
    {"name": "near short service line x right singles sideline", "px": [1104, 537], "court": [5.64, 4.72]},
    {"name": "near short service line x centre line (T)", "px": [729, 495], "court": [3.05, 4.72]},
    {"name": "near short service line x left singles sideline", "px": [454, 464], "court": [0.46, 4.72]},
    {"name": "near short service line x left doubles sideline", "px": [413, 459], "court": [0, 4.72]},
    {"name": "far short service line x right doubles sideline", "px": [1178, 451], "court": [6.1, 8.68]},
    {"name": "far short service line x centre line (T)", "px": [866, 425], "court": [3.05, 8.68]},
    {"name": "right net post base", "px": [1185, 488], "court": [6.1, 6.7]},
    {"name": "near doubles long service line x centre line", "px": [400, 670], "court": [3.05, 0.76]},
]

EXTERNAL_RE = re.compile(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import""", re.I)


# ---------------------------------------------------------------------------------------------
# the page (all CSS and JS inline, no external resources)
# ---------------------------------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Court point picker</title>
<style>
:root { --bg:#f3f4f6; --card:#fff; --ink:#1f2937; --mute:#6b7280; --line:#d1d5db; --blue:#2563eb;
        --good:#15803d; --warn:#b45309; --bad:#dc2626; --sel:#f59e0b; color-scheme: light; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; font: 14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--ink); }
header { padding: 10px 16px; background: #111827; color: #cbd5e1; display: flex; gap: 6px 14px; align-items: baseline; flex-wrap: wrap; }
header h1 { font-size: 17px; margin: 0; color: #fff; }
main { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 12px; padding: 12px; align-items: start; }
aside { display: grid; gap: 12px; position: sticky; top: 8px; max-height: calc(100vh - 16px); overflow: auto; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
h2 { font-size: 14px; margin: 0 0 6px; }
summary { cursor: pointer; font-weight: 600; }
ol, ul { margin: 6px 0; padding-left: 20px; }
li { margin: 3px 0; }
.mute, #saveinfo { color: var(--mute); }
.banner { margin: 10px 0; padding: 9px 12px; border-radius: 8px; background: #dbeafe; color: #1e3a8a; font-weight: 600; }
.banner.warn { background: #fef3c7; color: #78350f; }
#photo { display: block; width: 100%; height: auto; background: #000; border-radius: 6px; cursor: crosshair; touch-action: none; }
.bar { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; margin-top: 10px; }
.bar.save { gap: 4px 12px; }
button { font: inherit; padding: 6px 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; }
button:hover:not(:disabled) { background: #f3f4f6; }
button:disabled { opacity: .45; cursor: not-allowed; }
button.primary { background: var(--blue); border-color: var(--blue); color: #fff; font-weight: 600; padding: 9px 18px; }
button.primary:hover:not(:disabled) { background: #1d4ed8; }
label { display: inline-flex; gap: 5px; align-items: center; }
#diagram svg { display: block; width: 100%; max-width: 300px; height: auto; margin: 0 auto; }
#dotname { min-height: 2.9em; margin-top: 4px; text-align: center; }
.court { fill: #e6efe9; stroke: none; }
#diagram line { stroke: #51635a; stroke-width: 1.4; }
#diagram line.net { stroke: #d6249f; stroke-width: 3; }
#diagram text { font-size: 11px; fill: #51635a; text-anchor: middle; }
#diagram text.netlbl { fill: #d6249f; font-weight: 700; }
.dot { cursor: pointer; }
.dot .hit { fill: transparent; }
.dot .mark { fill: #fff; stroke: #1d4ed8; stroke-width: 2; }
.dot .ring { display: none; fill: none; stroke: var(--sel); stroke-width: 3; }
.dot.placed .mark { fill: #22c55e; stroke: #166534; }
.dot.sel .mark { fill: var(--sel); stroke: #92400e; }
.dot.sel .ring, .dot.hov .ring { display: block; }
.dot.hov:not(.sel) .ring { stroke: #94a3b8; }
#reqs { list-style: none; padding: 0; }
#reqs li::before { content: ""; display: inline-block; width: 11px; height: 11px; margin-right: 8px; border: 2px solid #9ca3af; border-radius: 50%; vertical-align: -1px; }
#reqs li.ok::before { background: #22c55e; border-color: #15803d; }
.good { color: var(--good); } .warn { color: var(--warn); } .bad { color: var(--bad); }
#fitinfo p { margin: 6px 0 0; }
#list { list-style: none; padding: 0; max-height: 240px; overflow: auto; }
#list li { display: flex; gap: 6px; align-items: center; padding: 3px 4px; border-radius: 5px; cursor: pointer; }
#list li:hover { background: #f3f4f6; }
#list li.sel { background: #fef3c7; }
#list .n { flex: none; width: 22px; height: 22px; border-radius: 50%; background: #16a34a; color: #fff; font-size: 12px; font-weight: 700; text-align: center; line-height: 22px; }
#list li.bad .n { background: var(--bad); }
#list .nm { flex: 1; min-width: 0; font-size: 12.5px; }
#list .er { flex: none; color: var(--mute); font-size: 12px; }
#list li.bad .er { color: var(--bad); font-weight: 700; }
#list button { padding: 0 7px; line-height: 20px; }
#loupe { position: fixed; z-index: 5; width: 170px; height: 170px; border: 3px solid #fff; border-radius: 50%; box-shadow: 0 2px 12px rgba(0,0,0,.55); pointer-events: none; }
#done { position: fixed; inset: 0; z-index: 9; display: grid; place-items: center; background: rgba(17,24,39,.6); }
#done div { background: #fff; border-radius: 10px; padding: 22px 26px; max-width: 460px; }
@media (max-width: 860px) { main { grid-template-columns: minmax(0, 1fr); } aside { position: static; max-height: none; } }
</style>
</head>
<body>
<header><h1>Court point picker</h1><span>Mark the court lines on the photo, then press Save. Everything stays on this computer.</span></header>
<main>
<section>
  <details class="card" id="help" open>
    <summary>How to use this (click to hide)</summary>
    <ol>
      <li><b>Click a dot</b> on the court diagram. It turns orange: that is the spot you will mark.</li>
      <li><b>Click the same spot on the photo.</b> Hold the button and drag to fine-tune; the magnifier shows the exact pixel. The dot turns green and a numbered marker appears.</li>
      <li>Repeat for <b>at least 6 spots that you can see clearly</b>, spread across the court: left and right, near and far (at least 3 different distances from the camera and 2 different left-right positions). Skip spots that are hidden by a player or the net, or that are outside the picture.</li>
      <li>From 4 points on, the red court model is drawn on the photo (the net is pink). It should lie on the painted lines. If a point is far off, drag its marker or remove it.</li>
      <li>When every check on the right is ticked, press <b>Save</b>.</li>
    </ol>
    <p class="mute">Keys: Esc deselects, Delete removes the selected point, arrow keys nudge it, Ctrl/Cmd+Z undoes.</p>
  </details>
  <div id="banner" class="banner"></div>
  <canvas id="photo"></canvas>
  <div class="bar">
    <button id="undo">Undo</button><button id="rm">Remove selected</button><button id="clear">Clear all</button>
    <label><input type="checkbox" id="showModel" checked> Show court model</label>
    <label><input type="checkbox" id="showLoupe" checked> Magnifier</label>
  </div>
  <div class="bar save"><button id="save" class="primary" disabled>Save court points</button><span id="saveinfo"></span></div>
</section>
<aside>
  <div class="card"><h2>Court diagram (seen from the camera side)</h2><div id="diagram"></div><p id="dotname" class="mute"></p></div>
  <div class="card">
    <h2>Checks</h2>
    <ul id="reqs"></ul>
    <div id="fitinfo"></div>
  </div>
  <div class="card"><h2>Placed points <span id="count"></span></h2><ol id="list"></ol><p class="mute" id="listempty">None yet.</p></div>
</aside>
</main>
<canvas id="loupe" width="170" height="170" hidden></canvas>
<div id="done" hidden><div><h2>Saved</h2><p id="donetext"></p><p>The picker has stopped. You can close this tab and go back to the terminal.</p></div></div>
<img id="src" alt="" hidden src="data:image/jpeg;base64,__IMAGE__">
<script type="application/json" id="data">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const W = D.width, H = D.height, LM = D.landmarks, MIN_PTS = D.minPoints;
const $ = id => document.getElementById(id);
const photo = $("photo"), ctx = photo.getContext("2d"), loupe = $("loupe"), lctx = loupe.getContext("2d");
const img = $("src");
const LOUPE = 170, ZOOM = 4, HIT = 9, BAD_PX = 4;   // loupe size (css px), loupe px per image px, marker grab radius, error limit

let pts = [];          // placed points in placement order: {i: landmark index, x, y} (x, y in image pixels, OpenCV convention)
let sel = null, hov = null, drag = null, mouse = null, fit = null, history = [];
let flash = "", flashTimer = 0, saved = false, dotEls = [];

const find = i => pts.find(p => p.i === i);
const num = i => pts.findIndex(p => p.i === i) + 1;
const r1 = v => Math.round(v * 10) / 10;

// ---- homography: court metres -> image pixels ------------------------------------------------
// Gaussian elimination with partial pivoting for the square system M x = b.
function solve(M, b) {
  const n = b.length, A = M.map((row, i) => row.concat(b[i]));
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < 1e-10) return null;
    [A[c], A[p]] = [A[p], A[c]];
    for (let r = c + 1; r < n; r++) {
      const f = A[r][c] / A[c][c];
      for (let k = c; k <= n; k++) A[r][k] -= f * A[c][k];
    }
  }
  const x = new Array(n);
  for (let r = n - 1; r >= 0; r--) {
    let s = A[r][n];
    for (let k = r + 1; k < n; k++) s -= A[r][k] * x[k];
    x[r] = s / A[r][r];
  }
  return x;
}
// Hartley normalisation: centroid to the origin, mean distance sqrt(2).
function normalise(P) {
  const n = P.length, cx = P.reduce((s, p) => s + p[0], 0) / n, cy = P.reduce((s, p) => s + p[1], 0) / n;
  const d = P.reduce((s, p) => s + Math.hypot(p[0] - cx, p[1] - cy), 0) / n, k = d > 1e-9 ? Math.SQRT2 / d : 1;
  return {k, cx, cy, P: P.map(p => [(p[0] - cx) * k, (p[1] - cy) * k])};
}
const mul = (A, B) => [0, 1, 2].flatMap(r => [0, 1, 2].map(c => A[3*r] * B[c] + A[3*r+1] * B[3+c] + A[3*r+2] * B[6+c]));
// Least squares on normalised coordinates (normal equations, h33 = 1), re-weighted a few times so that
// the minimised quantity is the pixel error like OpenCV's findHomography, not the algebraic one.
function fitHomography(C, Q) {
  const nc = normalise(C), nq = normalise(Q);
  let w = C.map(() => 1), h = null;
  for (let it = 0; it < 8; it++) {
    const AtA = Array.from({length: 8}, () => new Array(8).fill(0)), Atb = new Array(8).fill(0);
    const add = (row, b, wi) => {
      for (let i = 0; i < 8; i++) { Atb[i] += wi * wi * row[i] * b; for (let j = 0; j < 8; j++) AtA[i][j] += wi * wi * row[i] * row[j]; }
    };
    nc.P.forEach(([x, y], n) => {
      const [u, v] = nq.P[n];
      add([x, y, 1, 0, 0, 0, -u * x, -u * y], u, w[n]);
      add([0, 0, 0, x, y, 1, -v * x, -v * y], v, w[n]);
    });
    const s = solve(AtA, Atb);
    if (!s) return null;
    h = s.concat(1);
    w = nc.P.map(([x, y]) => { const d = h[6] * x + h[7] * y + 1; return d > 1e-6 ? 1 / d : 1; });
  }
  const Tc = [nc.k, 0, -nc.k * nc.cx, 0, nc.k, -nc.k * nc.cy, 0, 0, 1];
  const Tqi = [1 / nq.k, 0, nq.cx, 0, 1 / nq.k, nq.cy, 0, 0, 1];
  return mul(Tqi, mul(h, Tc));
}
function project(h, c) {
  const w = h[6] * c[0] + h[7] * c[1] + h[8];
  return w > 1e-9 ? [(h[0] * c[0] + h[1] * c[1] + h[2]) / w, (h[3] * c[0] + h[4] * c[1] + h[5]) / w] : null;
}
function computeFit() {
  if (pts.length < 4) return null;
  const C = pts.map(p => LM[p.i].court), h = fitHomography(C, pts.map(p => [p.x, p.y]));
  if (!h) return null;
  const errs = pts.map((p, k) => { const q = project(h, C[k]); return q ? Math.hypot(q[0] - p.x, q[1] - p.y) : Infinity; });
  const rms = Math.sqrt(errs.reduce((s, e) => s + e * e, 0) / errs.length);
  return isFinite(rms) ? {h, errs, rms} : null;
}

// ---- checks ----------------------------------------------------------------------------------
function requirements() {
  const ys = new Set(pts.map(p => LM[p.i].court[1])).size, xs = new Set(pts.map(p => LM[p.i].court[0])).size;
  return [
    {ok: pts.length >= MIN_PTS, text: `At least ${MIN_PTS} points placed (${pts.length} so far)`, why: `place ${Math.max(0, MIN_PTS - pts.length)} more point(s)`},
    {ok: ys >= 3, text: `At least 3 different distances from the camera (${ys} so far)`, why: "use dots from at least 3 different horizontal lines of the diagram (near, middle, far)"},
    {ok: xs >= 2, text: `At least 2 different left-right positions (${xs} so far)`, why: "use dots from at least 2 different vertical lines of the diagram (left and right)"},
  ];
}
function spreadWarning() {
  if (pts.length < 4) return "";
  const xs = pts.map(p => LM[p.i].court[0]), ys = pts.map(p => LM[p.i].court[1]);
  const rx = Math.max(...xs) - Math.min(...xs), ry = Math.max(...ys) - Math.min(...ys);
  return rx < 3 || ry < 6 ? "Your points are bunched together, so the court model may drift where you marked nothing. Add points further apart: left and right, and both near and far." : "";
}

// ---- drawing ---------------------------------------------------------------------------------
// Draw photo, court model and markers. Image pixel (x, y) lands at (ox + (x + .5) * k, oy + (y + .5) * k):
// OpenCV pixel coordinates refer to pixel centres.
function render(c, k, ox, oy, vw, vh) {                 // vw x vh: visible size of the canvas in css px
  const X = x => ox + (x + 0.5) * k, Y = y => oy + (y + 0.5) * k;
  const x0 = Math.max(0, -ox / k), y0 = Math.max(0, -oy / k), x1 = Math.min(W, (vw - ox) / k), y1 = Math.min(H, (vh - oy) / k);
  c.imageSmoothingEnabled = true;
  if (x1 > x0 && y1 > y0) c.drawImage(img, x0, y0, x1 - x0, y1 - y0, ox + x0 * k, oy + y0 * k, (x1 - x0) * k, (y1 - y0) * k);
  if (fit && $("showModel").checked) {
    const seg = (a, b) => { const p = project(fit.h, a), q = project(fit.h, b); if (p && q) { c.moveTo(X(p[0]), Y(p[1])); c.lineTo(X(q[0]), Y(q[1])); } };
    c.beginPath(); D.lines.forEach(([a, b]) => seg(a, b));
    c.strokeStyle = "rgba(255,40,40,.9)"; c.lineWidth = 1.5; c.stroke();
    c.beginPath(); seg(D.net[0], D.net[1]);
    c.strokeStyle = "#ff00ff"; c.lineWidth = 2.5; c.stroke();
  }
  if (fit && sel !== null && !find(sel)) {            // where the current model expects the selected spot
    const q = project(fit.h, LM[sel].court);
    if (q) { c.beginPath(); c.arc(X(q[0]), Y(q[1]), 14, 0, 7); c.setLineDash([4, 3]); c.strokeStyle = "#f59e0b"; c.lineWidth = 2; c.stroke(); c.setLineDash([]); }
  }
  pts.forEach((p, n) => {
    const bad = fit && pts.length > 4 && fit.errs[n] > BAD_PX, col = bad ? "#ef4444" : "#22c55e", x = X(p.x), y = Y(p.y);
    if (p.i === sel || p.i === hov) { c.beginPath(); c.arc(x, y, 11, 0, 7); c.strokeStyle = "#f59e0b"; c.lineWidth = 3; c.stroke(); }
    c.beginPath(); c.arc(x, y, 6, 0, 7); c.strokeStyle = "rgba(0,0,0,.65)"; c.lineWidth = 3.5; c.stroke();
    c.strokeStyle = col; c.lineWidth = 1.8; c.stroke();
    c.beginPath(); c.arc(x, y, 1.2, 0, 7); c.fillStyle = col; c.fill();
    c.font = "bold 12px system-ui, sans-serif"; c.lineWidth = 3; c.lineJoin = "round";
    c.strokeStyle = "rgba(0,0,0,.8)"; c.strokeText(n + 1, x + 8, y - 8);
    c.fillStyle = "#fff"; c.fillText(n + 1, x + 8, y - 8);
  });
}
function draw() {
  const dpr = photo.width / Math.max(1, photo.clientWidth);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  render(ctx, photo.clientWidth / W, 0, 0, photo.clientWidth, photo.clientHeight);
}
function drawLoupe() {
  loupe.hidden = !(mouse && $("showLoupe").checked);
  if (loupe.hidden) return;
  const dpr = loupe.width / LOUPE, h = LOUPE / 2;
  lctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  lctx.save(); lctx.beginPath(); lctx.arc(h, h, h, 0, 7); lctx.clip();
  lctx.fillStyle = "#000"; lctx.fillRect(0, 0, LOUPE, LOUPE);
  render(lctx, ZOOM, h - (mouse.x + 0.5) * ZOOM, h - (mouse.y + 0.5) * ZOOM, LOUPE, LOUPE);
  lctx.restore();
  lctx.beginPath();                                    // crosshair with a gap around the centre
  for (const [ux, uy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { lctx.moveTo(h + ux * 4, h + uy * 4); lctx.lineTo(h + ux * 16, h + uy * 16); }
  lctx.strokeStyle = "#000"; lctx.lineWidth = 3; lctx.stroke(); lctx.strokeStyle = "#fff"; lctx.lineWidth = 1; lctx.stroke();
}
function sizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  photo.style.aspectRatio = W + " / " + H;
  photo.width = Math.round(photo.clientWidth * dpr); photo.height = Math.round(photo.clientWidth * H / W * dpr);
  loupe.width = loupe.height = Math.round(LOUPE * dpr);
  draw(); drawLoupe();
}

// ---- diagram ---------------------------------------------------------------------------------
const S = 36, M = 30;                                  // diagram: pixels per metre and margin
const dx = x => M + x * S, dy = y => M + (D.courtL - y) * S;
function buildDiagram() {
  const ln = ([a, b], cls) => `<line class="${cls || ""}" x1="${dx(a[0])}" y1="${dy(a[1])}" x2="${dx(b[0])}" y2="${dy(b[1])}"/>`;
  $("diagram").innerHTML = `<svg viewBox="0 0 ${2 * M + D.courtW * S} ${2 * M + D.courtL * S}">`
    + `<rect class="court" x="${dx(0)}" y="${dy(D.courtL)}" width="${D.courtW * S}" height="${D.courtL * S}"/>`
    + D.lines.map(l => ln(l)).join("") + ln(D.net, "net")
    + `<text x="${dx(D.courtW / 2)}" y="${M - 10}">FAR end (away from camera)</text>`
    + `<text x="${dx(D.courtW / 2)}" y="${dy(0) + 22}">NEAR end (camera side)</text>`
    + `<text x="${dx(0)}" y="${dy(0) + 22}">left</text><text x="${dx(D.courtW)}" y="${dy(0) + 22}">right</text>`
    + `<text class="netlbl" x="${dx(D.courtW) + 17}" y="${dy(D.netY) + 4}">NET</text>`
    + LM.map((m, i) => `<g class="dot" data-i="${i}" transform="translate(${dx(m.court[0])} ${dy(m.court[1])})"><circle class="hit" r="8"/>`
        + `<circle class="ring" r="9.5"/><circle class="mark" r="5.5"/><title>${m.name}</title></g>`).join("")
    + `</svg>`;
  dotEls = [...document.querySelectorAll("#diagram .dot")];
}

// ---- state changes and UI --------------------------------------------------------------------
function hint(msg) {
  flash = msg; clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { flash = ""; updateBanner(); }, 4500);
  updateBanner();
}
function updateBanner() {
  let t;
  if (flash) t = flash;
  else if (saved) t = "Saved.";
  else if (sel === null) t = pts.length ? "Pick the next spot: click a dot on the court diagram. (To adjust a placed point, drag its marker on the photo.)" : "Start here: click any dot on the court diagram that you can clearly see on the photo.";
  else if (find(sel)) t = `"${LM[sel].name}" is placed as point ${num(sel)}. Drag its marker to adjust it, or press Remove selected.`;
  else t = `Now click the photo where "${LM[sel].name}" is. Cannot see it? Just pick another dot.`;
  $("banner").textContent = t; $("banner").classList.toggle("warn", !!flash);
}
function refresh() {
  fit = computeFit();
  dotEls.forEach(g => { const i = +g.getAttribute("data-i"); g.classList.toggle("placed", !!find(i)); g.classList.toggle("sel", i === sel); g.classList.toggle("hov", i === hov); });
  const shown = hov !== null ? hov : sel;
  $("dotname").textContent = shown !== null ? LM[shown].name : "Hover over a dot to see which spot it is.";
  // placed list
  $("count").textContent = pts.length ? `(${pts.length})` : "";
  $("listempty").hidden = pts.length > 0;
  $("list").innerHTML = pts.map((p, k) => {
    const bad = fit && pts.length > 4 && fit.errs[k] > BAD_PX;
    return `<li data-i="${p.i}" class="${p.i === sel ? "sel " : ""}${bad ? "bad" : ""}"><span class="n">${k + 1}</span><span class="nm">${LM[p.i].name}</span>`
      + `<span class="er">${fit && pts.length > 4 ? fit.errs[k].toFixed(1) + " px" : ""}</span><button data-rm="${p.i}" title="Remove this point">x</button></li>`;
  }).join("");
  // checks
  const reqs = requirements(), ok = reqs.every(r => r.ok), unmet = reqs.filter(r => !r.ok);
  $("reqs").innerHTML = reqs.map(r => `<li class="${r.ok ? "ok" : ""}">${r.text}</li>`).join("");
  let html;
  if (!fit) html = pts.length < 4 ? `<p>Place ${4 - pts.length} more point(s) to see the court model on the photo.</p>` : `<p class="bad">The court model cannot be computed yet: too many of these points lie on one painted line. Add points from other lines (near, middle and far).</p>`;
  else {
    const worst = fit.errs.indexOf(Math.max(...fit.errs)), bad = fit.rms > BAD_PX;
    html = `<p>Fit error: <b class="${bad ? "bad" : "good"}">${fit.rms.toFixed(1)} px</b> (RMS)`
      + (pts.length <= 4 ? " - always about 0 with only 4 points, add more to get a real check." : bad ? "" : " - good, the target is under 4 px.") + `</p>`;
    if (bad) html += `<p class="bad">The error is above 4 px, so one or more points are probably misplaced. The worst is point ${worst + 1} (${LM[pts[worst].i].name}), ${fit.errs[worst].toFixed(1)} px off. Drag it or remove it and place it again.</p>`;
  }
  const sw = spreadWarning();
  $("fitinfo").innerHTML = html + (sw ? `<p class="warn">${sw}</p>` : "");
  $("save").disabled = !ok || saved;
  const highErr = ok && fit && pts.length > 4 && fit.rms > BAD_PX;
  $("saveinfo").textContent = !ok ? "Save is locked. To unlock it: " + unmet.map(r => r.why).join("; ") + "."
    : highErr ? "You can save, but stage 2 only passes below 4 px RMS error: check the red points first." : "Ready to save.";
  $("undo").disabled = !history.length || saved; $("rm").disabled = sel === null || !find(sel) || saved; $("clear").disabled = !pts.length || saved;
  updateBanner(); draw(); drawLoupe();
}
const snap = () => { history.push(pts.map(p => ({...p}))); if (history.length > 300) history.shift(); };
function choose(i) { if (saved) return; sel = sel === i ? null : i; refresh(); }
function removePoint(i) { snap(); pts = pts.filter(p => p.i !== i); refresh(); }
function removeSelected() {
  if (sel === null || !find(sel)) return hint("Select a placed point first: click its marker on the photo, or its green dot on the diagram.");
  removePoint(sel);
}
function undo() { if (history.length) { pts = history.pop(); refresh(); } else hint("Nothing to undo."); }

// ---- mouse on the photo ----------------------------------------------------------------------
function toImg(e) {
  const r = photo.getBoundingClientRect();
  return {x: Math.min(W - 1, Math.max(0, (e.clientX - r.left) * W / r.width - 0.5)), y: Math.min(H - 1, Math.max(0, (e.clientY - r.top) * H / r.height - 0.5))};
}
function nearestMarker(p) {
  let best = null, bd = HIT;
  pts.forEach(q => { const d = Math.hypot(q.x - p.x, q.y - p.y) * photo.clientWidth / W; if (d <= bd) { bd = d; best = q.i; } });
  return best;
}
function moveLoupe(e) {
  const m = 26;
  let x = e.clientX + m, y = e.clientY - m - LOUPE;
  if (x + LOUPE > innerWidth - 4) x = e.clientX - m - LOUPE;
  if (y < 4) y = e.clientY + m;
  loupe.style.left = x + "px"; loupe.style.top = y + "px";
}
photo.addEventListener("pointerdown", e => {
  if (saved || e.button !== 0) return;
  const p = toImg(e), hit = nearestMarker(p);
  if (sel !== null && !find(sel)) {                     // place the selected spot here
    snap(); pts.push({i: sel, x: p.x, y: p.y}); drag = {i: sel, fresh: true, ox: 0, oy: 0, snapped: true};
    $("help").open = false;
  } else if (hit !== null) {                            // grab an existing marker to adjust it
    const q = find(hit); sel = hit; drag = {i: hit, fresh: false, ox: q.x - p.x, oy: q.y - p.y, snapped: false};
  } else if (sel !== null) {
    return hint(`Point ${num(sel)} is already placed. Drag its marker to move it, or press Remove selected and click again.`);
  } else {
    return hint("First click a dot on the court diagram to choose which spot you are marking, then click that spot on the photo.");
  }
  try { photo.setPointerCapture(e.pointerId); } catch (_) { /* synthetic events have no active pointer */ }
  mouse = p; moveLoupe(e); refresh();
});
photo.addEventListener("pointermove", e => {
  const p = toImg(e);
  mouse = p; moveLoupe(e);
  const q = drag && find(drag.i);                      // the marker being dragged (it may have been removed meanwhile)
  if (q) {
    const nx = Math.min(W - 1, Math.max(0, p.x + drag.ox)), ny = Math.min(H - 1, Math.max(0, p.y + drag.oy));
    if (nx !== q.x || ny !== q.y) { if (!drag.snapped) { snap(); drag.snapped = true; } q.x = nx; q.y = ny; }
    photo.style.cursor = "grabbing"; refresh();
  } else {
    photo.style.cursor = nearestMarker(p) !== null && !(sel !== null && !find(sel)) ? "grab" : "crosshair";
    drawLoupe();
  }
});
function endDrag() {
  if (!drag) return;
  if (drag.fresh) sel = null;                           // placed: the next click needs a new dot
  drag = null; photo.style.cursor = "crosshair"; refresh();
}
photo.addEventListener("pointerup", endDrag);
photo.addEventListener("pointercancel", endDrag);
photo.addEventListener("pointerleave", () => { if (!drag) { mouse = null; drawLoupe(); } });

// ---- other controls --------------------------------------------------------------------------
$("diagram").addEventListener("click", e => { const g = e.target.closest("[data-i]"); if (g) choose(+g.getAttribute("data-i")); });
$("diagram").addEventListener("mouseover", e => { const g = e.target.closest("[data-i]"); hov = g ? +g.getAttribute("data-i") : null; refresh(); });
$("diagram").addEventListener("mouseleave", () => { hov = null; refresh(); });
$("list").addEventListener("click", e => {
  const rm = e.target.closest("[data-rm]"), li = e.target.closest("li");
  if (saved) return;
  if (rm) removePoint(+rm.getAttribute("data-rm")); else if (li) choose(+li.getAttribute("data-i"));
});
$("undo").onclick = undo; $("rm").onclick = removeSelected;
$("clear").onclick = () => { if (pts.length) { snap(); pts = []; refresh(); } };
$("showModel").onchange = $("showLoupe").onchange = refresh;
addEventListener("keydown", e => {
  if (saved) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
  else if (e.key === "Escape") { sel = null; refresh(); }
  else if ((e.key === "Delete" || e.key === "Backspace") && sel !== null) { e.preventDefault(); removeSelected(); }
  else if (e.key.startsWith("Arrow") && sel !== null && find(sel)) {
    e.preventDefault();
    const q = find(sel), s = e.shiftKey ? 2 : 0.5;
    snap();
    q.x = Math.min(W - 1, Math.max(0, q.x + (e.key === "ArrowRight" ? s : e.key === "ArrowLeft" ? -s : 0)));
    q.y = Math.min(H - 1, Math.max(0, q.y + (e.key === "ArrowDown" ? s : e.key === "ArrowUp" ? -s : 0)));
    refresh();
  }
});
$("save").onclick = async () => {
  const body = pts.map(p => ({name: LM[p.i].name, px: [r1(p.x), r1(p.y)], court: LM[p.i].court}));
  $("save").disabled = true; $("saveinfo").textContent = "Saving...";
  try {
    const r = await fetch("/save", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || r.statusText);
    saved = true; mouse = null; refresh();
    $("donetext").textContent = `Wrote ${j.count} points to ${j.path}.`; $("done").hidden = false;
  } catch (err) {
    refresh(); $("saveinfo").textContent = "Could not save (is the picker still running in the terminal?): " + err.message;
  }
};

// ---- start -----------------------------------------------------------------------------------
function start() {
  if (innerWidth < 1000) $("help").open = false;       // leave room for the photo on small windows
  buildDiagram(); sizeCanvas(); refresh();
  new ResizeObserver(sizeCanvas).observe(photo);       // window resize, layout change
  addEventListener("resize", sizeCanvas);              // browser zoom changes devicePixelRatio
}
img.addEventListener("error", () => { $("banner").textContent = "The photo could not be loaded."; });
if (img.complete && img.naturalWidth) start(); else img.addEventListener("load", start);
</script>
</body>
</html>
"""


def build_page(img):
    """Return the one self-contained HTML page for a BGR image."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        sys.exit("could not encode the image")
    data = {"width": int(img.shape[1]), "height": int(img.shape[0]), "landmarks": LANDMARKS, "minPoints": MIN_POINTS,
            "courtW": s02.W_D, "courtL": s02.L, "netY": s02.NET_Y,
            "lines": [[list(a), list(b)] for a, b in s02.LINES], "net": [list(p) for p in s02.NET]}
    blob = json.dumps(data).replace("</", "<\\/")
    return PAGE.replace("__DATA__", blob).replace("__IMAGE__", base64.b64encode(buf).decode())


# ---------------------------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------------------------
def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_points(data, size):
    """Check a posted point list for an image of size (width, height); return the clean list.

    Raises ValueError with a plain message. Court coordinates must be a known landmark, each at most once."""
    if not isinstance(data, list) or not 4 <= len(data) <= len(LANDMARKS):
        raise ValueError("expected a list of 4 or more points")
    clean, seen = [], set()
    for k, p in enumerate(data, 1):
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"].strip():
            raise ValueError(f"point {k}: needs a name")
        px, co = p.get("px"), p.get("court")
        if not (isinstance(px, list) and len(px) == 2 and all(_is_num(v) for v in px)):
            raise ValueError(f"point {k}: px must be two numbers")
        if not (0 <= px[0] <= size[0] and 0 <= px[1] <= size[1]):
            raise ValueError(f"point {k}: px is outside the {size[0]}x{size[1]} image")
        if not (isinstance(co, list) and len(co) == 2 and all(_is_num(v) for v in co)):
            raise ValueError(f"point {k}: court must be two numbers")
        match = [m["court"] for m in LANDMARKS if abs(m["court"][0] - co[0]) < 1e-6 and abs(m["court"][1] - co[1]) < 1e-6]
        if not match:
            raise ValueError(f"point {k}: court {co} is not one of the landmarks")
        if tuple(match[0]) in seen:
            raise ValueError(f"point {k}: the same court spot was sent twice")
        seen.add(tuple(match[0]))
        clean.append({"name": p["name"].strip(), "px": px, "court": list(match[0])})
    return clean


def save_points(path, pts):
    """Write the point list, one point per line (the layout stage 2 documents)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("[\n" + ",\n".join("  " + json.dumps(p) for p in pts) + "\n]\n")
    tmp.replace(path)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "CourtPicker"

    def log_message(self, *args):  # keep the terminal quiet
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
        if self.path != "/save":
            return self._send(404, b"not found")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(411, {"ok": False, "error": "Content-Length required"})
        if not 0 < length <= MAX_BODY:
            return self._json(413, {"ok": False, "error": "body too large"})
        body = self.rfile.read(length)
        # Only the page served by this program may save: a web page on another site cannot send JSON
        # to us without a CORS preflight (which we never answer), and a rebinding host name is refused.
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self._json(403, {"ok": False, "error": "unexpected Host header"})
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(415, {"ok": False, "error": "send application/json"})
        try:
            pts = validate_points(json.loads(body), self.server.size)
        except ValueError as e:  # includes json.JSONDecodeError and UnicodeDecodeError
            return self._json(400, {"ok": False, "error": str(e)})
        save_points(self.server.out_path, pts)
        self.server.saved = len(pts)
        self._json(200, {"ok": True, "count": len(pts), "path": str(self.server.out_path)})
        threading.Thread(target=self.server.shutdown, daemon=True).start()  # stop serving once the reply is out


class PickerServer(http.server.ThreadingHTTPServer):
    daemon_threads = True  # a browser's idle spare connection must not keep the program alive

    def __init__(self, port, img, out_path):
        super().__init__(("127.0.0.1", port), Handler)
        self.page = build_page(img).encode("utf-8")
        self.size = (img.shape[1], img.shape[0])
        self.out_path = Path(out_path)
        self.saved = 0  # number of points written, 0 until Save


# ---------------------------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------------------------
def synthetic_image(w=1280, h=720):
    """A plain gradient with a few lines: enough of a 'photo' to exercise the page and the server."""
    x = np.linspace(40, 200, w, dtype=np.uint8)[None, :, None]
    img = np.repeat(np.repeat(x, h, axis=0), 3, axis=2).copy()
    cv2.line(img, (100, h - 50), (w - 100, h - 50), (255, 255, 255), 3)
    cv2.line(img, (300, h // 2), (w - 300, h // 2), (255, 255, 255), 2)
    return img


def _post(base, payload, ctype="application/json"):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    req = urllib.request.Request(base + "/save", data=data, headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def selftest(img=None, log=print):
    """Serve on an ephemeral port in a thread, POST the reference points, check the file and the shutdown."""
    img = synthetic_image() if img is None else img
    failures = []

    def check(label, cond):
        log(("PASS  " if cond else "FAIL  ") + label)
        if not cond:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sub" / "court_points.json"
        server = PickerServer(0, img, out)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(base + "/", timeout=10) as r:
                page = r.read().decode()
            check("page is served", r.status == 200 and "<canvas" in page and "data:image/jpeg;base64," in page)
            check("page has no external resources", not EXTERNAL_RE.search(page))
            bad = [("not json", b"{nope", "application/json"), ("wrong content type", [], "text/plain"),
                   ("too few points", SELFTEST_POINTS[:3], "application/json"),
                   ("px outside the image", [dict(p, px=[5000, 5]) for p in SELFTEST_POINTS], "application/json"),
                   ("unknown court spot", [dict(p, court=[1, 1]) for p in SELFTEST_POINTS], "application/json"),
                   ("duplicate court spot", [SELFTEST_POINTS[0]] * 4, "application/json")]
            for label, payload, ctype in bad:
                code, _ = _post(base, payload, ctype)
                check(f"refuses {label}", 400 <= code < 500 and not out.exists())
            code, reply = _post(base, SELFTEST_POINTS)
            check("accepts the reference points", code == 200 and reply.get("count") == len(SELFTEST_POINTS))
            thread.join(10)
            check("server shut down after saving", not thread.is_alive() and server.saved == len(SELFTEST_POINTS))
            check("saved file equals the reference points", out.exists() and json.loads(out.read_text()) == SELFTEST_POINTS)
        except Exception as e:  # a crash is a failure, not a traceback
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
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--video", help="proxy video; a clean median background is built from it")
    src.add_argument("--image", help="a photo of the court (png/jpg) instead of a video")
    ap.add_argument("--out", default="work/court_points.json", help="court_points.json to write (default: %(default)s)")
    ap.add_argument("--port", type=int, default=8765, help="local port (default: %(default)s; 0 picks a free one)")
    ap.add_argument("--no-browser", action="store_true", help="only print the address, do not open a browser")
    ap.add_argument("--selftest", action="store_true", help="check the server and exit 0 (ok) or 1 (failed)")
    args = ap.parse_args(argv)
    if not (args.selftest or args.video or args.image):
        ap.error("give --video or --image (or --selftest)")
    return args


def load_background(args):
    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            sys.exit(f"cannot read the image: {args.image}")
        return img
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"video not found: {video}")
    bg_path = Path(args.out).parent / "bg_median.png"
    img = cv2.imread(str(bg_path)) if bg_path.exists() else None
    if img is None:
        print("building a clean background from the video (players disappear in a median)...")
        try:
            img = s02.median_background(video)
        except ValueError:
            sys.exit(f"could not read any frames from {video}")
        bg_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(bg_path), img)
    return img


def main(argv=None):
    args = parse_args(argv)
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    img = load_background(args)
    try:
        server = PickerServer(args.port, img, args.out)
    except OSError as e:
        sys.exit(f"cannot listen on port {args.port} ({e.strerror}); try --port {args.port + 1} or --port 0")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Court point picker is running ({img.shape[1]}x{img.shape[0]} photo).")
    print(f"Open this address in your browser: {url}")
    print("Mark your points and press Save; this program then stops by itself. Press Ctrl+C to quit without saving.")
    if Path(args.out).exists():
        print(f"Note: {args.out} already exists and will be replaced when you save.")
    if not args.no_browser and not webbrowser.open(url):
        print("(could not open a browser automatically; open the address above yourself)")
    sys.stdout.flush()  # so the address shows at once even when the output is piped or logged
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        print("\nStopped without saving.")
    finally:
        server.server_close()
    if not server.saved:
        sys.exit(1)
    proxy = args.video or "<proxy.mp4>"
    calib = Path(args.out).parent / "calib.json"
    print(f"Saved {server.saved} court points to {args.out}")
    print(f"Next: python stages/s02_calibrate.py --proxy {proxy} --points {args.out} --out {calib}")


if __name__ == "__main__":
    main()
