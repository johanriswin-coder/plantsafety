"""
plantui.py - turns a plant snapshot (from plantsim.py) into HTML / SVG pieces.

Pure Python, no Streamlit import, so the live app AND the preview builder share the
exact same drawing code. Every function takes the snapshot dict and returns one
single-line HTML string (Streamlit's markdown would break on blank lines).

All text that comes from the simulation goes through esc() before it reaches HTML.
"""
from __future__ import annotations

import base64
import html
import math

from plantsim import MODE_LABEL, MUSTER_NAME, MUSTER_RECT, ZONES

PLANT_NAME = "Riverside Works"

MODE_COLOR = {"NORMAL": "#39FFB0", "WARNING": "#FFC531", "CRITICAL": "#FF7A1A",
              "FAILURE": "#FF3B6B", "EVACUATE": "#FF1744"}
STATE_COLOR = {"OK": "#39FFB0", "WARN": "#FFC531", "CRIT": "#FF7A1A", "FAILED": "#FF3B6B", "STOPPED": "#7D8BA8"}
STATE_LABEL = {"OK": "Running", "WARN": "Warning", "CRIT": "Critical", "FAILED": "FAILED", "STOPPED": "Stopped"}
STATUS_COLOR = {"ok": "#39FFB0", "warn": "#FFC531", "crit": "#FF7A1A", "off": "#4B5875"}
LEVEL_COLOR = {"WARNING": "#FFC531", "CRITICAL": "#FF7A1A", "FAILURE": "#FF3B6B", "EVACUATE": "#FF1744",
               "INFO": "#29E3FF", "CLEAR": "#39FFB0", "OPERATOR": "#29E3FF", "SIM": "#9AA9D6"}
PRIO_COLOR = {1: "#FF3B6B", 2: "#FFC531", 3: "#29E3FF"}
EMP_COLOR = {"ok": "#7D8BA8", "notified": "#FFC531", "acked": "#29E3FF", "safe": "#39FFB0"}


def esc(text) -> str:
    """Escape text for HTML. '$' is also escaped so Streamlit never treats it as maths."""
    return html.escape(str(text)).replace("$", "&#36;")


def one(s: str) -> str:
    return s.replace("\n", "")


def data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root { --text:#E6EEFF; --muted:#8FA3C8; --line:#1F3050; --panel:rgba(12,20,36,.88);
        --display:'Chakra Petch', system-ui, sans-serif; --mono:'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace; }
.stApp { background-color:#060B15;
  background-image: linear-gradient(rgba(80,120,200,.06) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(80,120,200,.06) 1px, transparent 1px),
                    radial-gradient(1000px 520px at 85% -10%, rgba(40,90,200,.28), transparent 62%),
                    radial-gradient(800px 500px at 0% 105%, rgba(255,122,26,.10), transparent 62%);
  background-size: 36px 36px, 36px 36px, auto, auto; color:var(--text); }
[data-testid="stHeader"], [data-testid="stAppViewContainer"], [data-testid="stMain"] { background:transparent; }
#MainMenu, footer { visibility:hidden; }
.block-container, [data-testid="stMainBlockContainer"] { max-width:1640px; padding:1rem 1.4rem 2rem; }
[data-testid="stSidebar"] { background:#0A1220; border-right:1px solid var(--line); }
[data-testid="stSidebar"] [data-testid="stButton"] button { border:1px solid rgba(255,122,26,.7); border-radius:8px; }

.pg-head { display:flex; flex-wrap:wrap; align-items:center; gap:12px 22px; padding:12px 18px; border-radius:12px;
  background:var(--panel); border:1px solid var(--line); }
.pg-brand { font:700 1.25rem var(--display); display:flex; align-items:center; gap:10px; }
.pg-brand i { width:12px; height:12px; border-radius:50%; background:var(--mc); box-shadow:0 0 14px var(--mc); animation:pg-blink 1.6s infinite; }
.pg-brand span { font:500 .85rem var(--display); color:var(--muted); }
.pg-mode { margin-left:auto; display:flex; align-items:center; gap:12px; padding:6px 18px; border-radius:10px;
  border:2px solid var(--mc); background:color-mix(in srgb, var(--mc) 16%, transparent); box-shadow:0 0 22px color-mix(in srgb, var(--mc) 45%, transparent); }
.pg-mode b { font:700 1.35rem var(--display); color:var(--mc); letter-spacing:.02em; }
.pg-mode em { font-style:normal; color:var(--text); font-size:.9rem; }
.pg-stats { display:flex; flex-wrap:wrap; gap:6px 18px; font-size:.86rem; color:var(--muted); width:100%; }
.pg-stats b { color:var(--text); font-family:var(--mono); }
.pg-stats i { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; }
.pg-banner { margin:10px 0 0; padding:10px 18px; border-radius:10px; font:700 1.05rem var(--display);
  color:#fff; background:color-mix(in srgb, var(--mc) 78%, #000); border:1px solid var(--mc);
  box-shadow:0 0 24px color-mix(in srgb, var(--mc) 50%, transparent); }
.pg-banner.quiet { background:color-mix(in srgb, var(--mc) 12%, transparent); color:var(--mc); font-weight:600; box-shadow:none; }
.pg-banner.flash { animation:pg-flash .8s infinite; }
@keyframes pg-flash { 50% { opacity:.55; } }
@keyframes pg-blink { 50% { opacity:.35; } }

.pg-card { padding:14px 16px; border-radius:12px; background:var(--panel); border:1px solid var(--line); margin:0 0 12px; }
.pg-h { font:700 1.02rem var(--display); margin:0 0 10px; display:flex; align-items:center; gap:10px; }
.pg-h::before { content:""; width:5px; height:1.05em; border-radius:3px; background:#FF7A1A; box-shadow:0 0 10px #FF7A1A; }
.pg-h small { margin-left:auto; font:500 .78rem var(--display); color:var(--muted); }

.pg-pie { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.pg-pie img.p { width:176px; height:176px; flex:none; filter:drop-shadow(0 0 16px color-mix(in srgb, var(--mc) 55%, transparent)); }
.pg-big { font:700 3.3rem/1 var(--display); color:var(--mc); text-shadow:0 0 24px color-mix(in srgb, var(--mc) 55%, transparent); }
.pg-big small { font-size:.4em; color:var(--muted); text-shadow:none; margin-left:4px; font-weight:500; }
.pg-sub { color:var(--muted); font-size:.82rem; margin-top:4px; }
.pg-trend { width:100%; height:30px; margin-top:8px; }
.pg-legend { display:flex; flex-wrap:wrap; gap:4px 14px; margin-top:8px; font-size:.8rem; color:var(--muted); }
.pg-legend i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; vertical-align:-1px; }

.pg-plan { width:100%; display:block; border-radius:10px; }
.pg-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(188px, 1fr)); gap:10px; }
.pg-tile { padding:10px 11px 9px; border-radius:11px; background:var(--panel); border:1px solid var(--line); border-top:3px solid var(--sc);
  box-shadow:0 0 14px color-mix(in srgb, var(--sc) 14%, transparent); }
.pg-tile.st-CRIT, .pg-tile.st-FAILED { box-shadow:0 0 22px color-mix(in srgb, var(--sc) 45%, transparent); }
.pg-tile.st-FAILED { animation:pg-blink 1.1s infinite; }
.pg-tile.st-STOPPED { opacity:.78; }
.pg-th { display:flex; align-items:center; gap:7px; }
.pg-th b { font:700 1rem var(--display); }
.pg-tn { color:var(--muted); font-size:.74rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; }
.pg-chip { margin-left:auto; font:600 .68rem var(--display); padding:1px 8px; border-radius:999px; color:var(--sc); border:1px solid var(--sc); white-space:nowrap; }
.pg-rk { display:flex; align-items:center; gap:8px; margin:7px 0 5px; }
.pg-rk div { flex:1; height:6px; border-radius:3px; background:#14213A; overflow:hidden; }
.pg-rk div i { display:block; height:100%; background:var(--sc); box-shadow:0 0 8px var(--sc); }
.pg-rk span { font:600 .78rem var(--mono); color:var(--sc); min-width:34px; text-align:right; }
.s { position:relative; display:flex; justify-content:space-between; gap:6px; font-size:.74rem; color:var(--muted); padding:3px 0 5px; }
.s b { font:600 .76rem var(--mono); color:var(--text); white-space:nowrap; }
.s i { position:absolute; left:0; bottom:1px; height:2px; border-radius:2px; background:var(--bc); box-shadow:0 0 5px var(--bc); }
.s.warn b { color:#FFC531; } .s.crit b { color:#FF7A1A; } .s.off b { color:#5F6C8A; }
.s u { text-decoration:none; position:absolute; right:0; bottom:-9px; font-size:.62rem; color:#FF7A1A; }
.pg-spark { width:100%; height:24px; display:block; margin-top:6px; }
.pg-notes { margin-top:4px; font-size:.7rem; color:#29E3FF; min-height:.9em; }

.pg-alert { margin:0 0 9px; padding:9px 11px; border-radius:9px; background:rgba(8,14,28,.8); border:1px solid var(--line); border-left:4px solid var(--ac); }
.pg-alert b { font:600 .88rem var(--display); color:var(--ac); }
.pg-alert p { margin:3px 0 6px; font-size:.8rem; color:#C3CFF2; }
.pg-meta { display:flex; flex-wrap:wrap; gap:4px 6px; font-size:.68rem; color:var(--muted); align-items:center; }
.pg-meta span { padding:0 7px; border:1px solid var(--line); border-radius:999px; }
.pg-ack { height:4px; border-radius:2px; background:#14213A; margin-top:6px; overflow:hidden; }
.pg-ack i { display:block; height:100%; background:#29E3FF; }
.pg-ackt { font-size:.68rem; color:var(--muted); margin-top:3px; }
.pg-quiet { color:var(--muted); font-size:.85rem; padding:6px 2px; }

.pg-phone-wrap { display:flex; flex-direction:column; align-items:center; gap:6px; }
.pg-phone { width:230px; padding:12px 10px 14px; border-radius:26px; background:#04070E; border:2px solid #2A3C60; box-shadow:0 0 18px rgba(41,227,255,.12); }
.pg-phone .bar { display:flex; justify-content:space-between; font:600 .66rem var(--mono); color:var(--muted); padding:0 8px 8px; }
.pg-phone .n { margin:0 3px; padding:10px 11px; border-radius:14px; background:#101A30; border-left:4px solid var(--ac); }
.pg-phone .n b { display:block; font:700 .92rem var(--display); color:var(--ac); }
.pg-phone .n p { margin:4px 0 6px; font-size:.76rem; color:#D5DEF7; }
.pg-phone .n small { color:var(--muted); font-size:.64rem; }
.pg-phone .n.big { background:var(--ac); border:0; }
.pg-phone .n.big b, .pg-phone .n.big p, .pg-phone .n.big small { color:#fff; }
.pg-phone .n.big b { font-size:1.15rem; animation:pg-flash .8s infinite; }
.pg-phone .btn { margin:8px 3px 0; text-align:center; padding:6px; border-radius:10px; background:#162546; color:#29E3FF; font:600 .74rem var(--display); }
.pg-phone .none { margin:18px 6px; text-align:center; color:var(--muted); font-size:.78rem; }
.pg-who { font-size:.74rem; color:var(--muted); text-align:center; }

.pg-adv { display:flex; gap:9px; align-items:flex-start; margin:0 0 8px; font-size:.83rem; color:#D5DEF7; }
.pg-adv em { flex:none; font:700 .68rem var(--display); font-style:normal; color:#050B15; padding:2px 7px; border-radius:6px; margin-top:1px; }
.pg-adv span.tag { color:#29E3FF; font-size:.72rem; white-space:nowrap; }
.pg-log { font:400 .72rem/1.55 var(--mono); color:var(--muted); }
.pg-log div { display:flex; gap:8px; }
.pg-log b { font-weight:600; flex:none; }
.pg-foot { color:#6F82AD; font-size:.74rem; margin-top:8px; }

.pg-main { display:grid; grid-template-columns:minmax(250px, 1fr) minmax(0, 3.1fr) minmax(270px, 1.15fr); gap:16px; align-items:start; margin-top:14px; }
@media (max-width: 1150px) { .pg-main { grid-template-columns:1fr; } }
@media (prefers-reduced-motion: reduce) { .pg-banner.flash, .pg-brand i, .pg-tile.st-FAILED, .pg-phone .n.big b { animation:none; } }
</style>
"""


def mode_css(mode: str) -> str:
    """A glowing frame around the whole screen: calm in normal mode, loud in a crisis."""
    c = MODE_COLOR[mode]
    if mode == "NORMAL":
        return "<style>.stApp::after { display:none; }</style>"
    spec = {"WARNING": (2, 60, 0.16, None), "CRITICAL": (3, 90, 0.26, "2.2s"),
            "FAILURE": (4, 110, 0.34, "1.6s"), "EVACUATE": (6, 150, 0.50, "0.8s")}[mode]
    width, blur, alpha, pulse = spec
    anim = f"animation:pg-frame {pulse} ease-in-out infinite;" if pulse else ""
    return one(
        f"<style>.stApp::after {{ content:''; position:fixed; inset:0; pointer-events:none; z-index:999; {anim}"
        f"box-shadow: inset 0 0 0 {width}px {c}, inset 0 0 {blur}px rgba({_rgb(c)},{alpha}); }}"
        f"@keyframes pg-frame {{ 50% {{ opacity:.35; }} }}"
        f"@media (prefers-reduced-motion: reduce) {{ .stApp::after {{ animation:none; }} }}</style>")


def _rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"


# --------------------------------------------------------------------------- #
# Small SVG helpers
# --------------------------------------------------------------------------- #
def pie_svg(risk: int, color: str) -> str:
    """Risk pie: starts at 12 o'clock, runs clockwise."""
    R, C = 92, 100

    def pt(radius, deg):
        a = math.radians(deg - 90)
        return C + radius * math.cos(a), C + radius * math.sin(a)

    end = 360 * risk / 100
    x1, y1 = pt(R, 0)
    x2, y2 = pt(R, end)
    path = f"M{C} {C} L{x1:.2f} {y1:.2f} A{R} {R} 0 {1 if end > 180 else 0} 1 {x2:.2f} {y2:.2f} Z"

    def label(deg, text, fill):
        x, y = pt(R * 0.62, deg)
        return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" text-anchor="middle" dominant-baseline="central" '
                f'font-family="system-ui,sans-serif" font-size="19" font-weight="700">{text}</text>')

    labels = ""
    if risk >= 12:
        labels += label(end / 2, f"{risk}%", "#050B15")
    if risk <= 88:
        labels += label(end + (360 - end) / 2, f"{100 - risk}%", "#C9D6FF")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -8 216 216" width="200" height="200">'
            f'<circle cx="100" cy="100" r="{R}" fill="#14213A" stroke="#2B4272" stroke-width="1.5"/>'
            f'<path d="{path}" fill="{color}" stroke="#060B15" stroke-width="2" stroke-linejoin="round"/>{labels}</svg>')


def spark_svg(values, color: str, w: int = 160, h: int = 26) -> str:
    vals = list(values)[-30:]
    n = max(len(vals) - 1, 1)
    pts = " ".join(f"{i * w / n:.1f},{h - 2 - (min(max(v, 0), 100) / 100) * (h - 4):.1f}" for i, v in enumerate(vals))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" preserveAspectRatio="none">'
            f'<polyline points="{pts} {w},{h} 0,{h}" fill="{color}" fill-opacity=".14" stroke="none"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round"/></svg>')


def _worst_zone_state(snap) -> dict:
    rank = {"OK": 0, "STOPPED": 0, "WARN": 1, "CRIT": 2, "FAILED": 3}
    worst = {}
    for m in snap["machines"]:
        z = m["zone"]
        if z not in worst or rank[m["state"]] > rank[worst[z]]:
            worst[z] = m["state"]
    return worst


def plan_svg(snap) -> str:
    evac = snap["mode"] == "EVACUATE"
    zstate = _worst_zone_state(snap)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 300" width="640" height="300" font-family="system-ui,sans-serif">',
           '<rect width="640" height="300" rx="10" fill="#08101D"/>']
    for zid, (name, (x, y, w, h)) in ZONES.items():
        state = zstate.get(zid, "OK")
        col = "#FF1744" if evac and zid != "CR" else STATE_COLOR.get(state, "#39FFB0") if zid != "CR" else "#3B5B91"
        if zid != "CR" and state in ("OK", "STOPPED") and not evac:
            col = "#2A4A7A"
        fill = 0.10 if (evac and zid != "CR") or state in ("WARN", "CRIT", "FAILED") else 0.04
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{col}" fill-opacity="{fill}" stroke="{col}" stroke-opacity=".75" stroke-width="1.4"/>')
        out.append(f'<text x="{x + 8}" y="{y + 15}" font-size="11" fill="#8FA3C8" font-weight="600">{esc(zid if zid != "CR" else "")} {esc(name)}</text>')
    mx, my, mw, mh = MUSTER_RECT
    out.append(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="9" fill="#39FFB0" fill-opacity="{0.14 if evac else 0.05}" stroke="#39FFB0" stroke-dasharray="5 4" stroke-width="1.5"/>')
    out.append(f'<text x="{mx + 8}" y="{my + 15}" font-size="11" fill="#39FFB0" font-weight="700">{esc(MUSTER_NAME)}</text>')
    for m in snap["machines"]:
        x, y = m["pos"]
        col = STATE_COLOR[m["state"]]
        pulse = ""
        if m["state"] in ("CRIT", "FAILED"):
            pulse = '<animate attributeName="stroke-opacity" values="1;.25;1" dur="0.9s" repeatCount="indefinite"/>'
        out.append(f'<rect x="{x}" y="{y}" width="64" height="40" rx="8" fill="#0D1830" stroke="{col}" stroke-width="2.4">{pulse}</rect>')
        out.append(f'<text x="{x + 32}" y="{y + 17}" font-size="13" font-weight="700" fill="{col}" text-anchor="middle">{esc(m["id"])}</text>')
        sub = "FAILED" if m["state"] == "FAILED" else "stopped" if m["state"] == "STOPPED" else f'{m["risk"]}%'
        out.append(f'<text x="{x + 32}" y="{y + 32}" font-size="10" fill="#9FB3D9" text-anchor="middle">{sub}</text>')
    for e in snap["employees"]:
        col = EMP_COLOR[e["status"]]
        out.append(f'<circle cx="{e["x"]:.1f}" cy="{e["y"]:.1f}" r="4.6" fill="{col}" stroke="#060B15" stroke-width="1.2"/>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# HTML pieces
# --------------------------------------------------------------------------- #
def _names(snap, state):
    return ", ".join(f'{m["name"]} ({m["id"]})' for m in snap["machines"] if m["state"] == state)


def header_html(snap) -> str:
    c = MODE_COLOR[snap["mode"]]
    n, p = snap["counts"], snap["people"]
    stats = "".join(
        f'<span><i style="background:{STATE_COLOR[k]}"></i><b>{n[k]}</b> {lbl}</span>'
        for k, lbl in (("OK", "running"), ("WARN", "warning"), ("CRIT", "critical"), ("FAILED", "failed"), ("STOPPED", "stopped")))
    people = (f'<span>Employees notified <b>{p["notified"]}/{p["total"]}</b></span>'
              f'<span>acknowledged <b>{p["acked"]}/{p["total"]}</b></span>'
              f'<span>at {esc(MUSTER_NAME.lower())} <b>{p["at_muster"]}/{p["total"]}</b></span>')
    banner = ""
    mode = snap["mode"]
    if mode == "EVACUATE":
        banner = (f'<div class="pg-banner flash" style="--mc:{c}">LIFE RISK: {esc(snap["hazard"] or "")}. '
                  f'EVACUATE TO THE {esc(MUSTER_NAME.upper())} NOW.</div>')
    elif mode == "FAILURE":
        banner = f'<div class="pg-banner" style="--mc:{c}">PLANT FAILURE: {esc(_names(snap, "FAILED"))} has tripped. Zone restricted.</div>'
    elif mode == "CRITICAL":
        banner = f'<div class="pg-banner" style="--mc:{c}">CRITICAL: {esc(_names(snap, "CRIT") or "plant risk is high")}. Failure possible. Act now.</div>'
    elif mode == "WARNING":
        banner = f'<div class="pg-banner quiet" style="--mc:{c}">Warning: {esc(_names(snap, "WARN") or "plant risk is rising")}. Investigate.</div>'
    else:
        banner = f'<div class="pg-banner quiet" style="--mc:{c}">All systems normal. No alerts.</div>'
    return one(
        f'<div class="pg-head" style="--mc:{c}"><div class="pg-brand"><i></i>PlantGuard'
        f'<span>{esc(PLANT_NAME)} · control room</span></div>'
        f'<div class="pg-mode"><b>{esc(snap["mode"])}</b><em>{esc(MODE_LABEL[snap["mode"]])}</em></div>'
        f'<div class="pg-stats"><span>Plant time <b>{esc(snap["clock"])}</b></span>{stats}{people}</div></div>{banner}')


def pie_html(snap) -> str:
    c = MODE_COLOR[snap["mode"]]
    r = snap["risk"]
    top = max(snap["machines"], key=lambda m: m["risk"])
    return one(
        f'<div class="pg-card" style="--mc:{c}"><div class="pg-h">Overall plant risk<small>{esc(snap["mode_label"])}</small></div>'
        f'<div class="pg-pie"><img class="p" src="{data_uri(pie_svg(r, c))}" alt="Pie chart: plant risk {r}%">'
        f'<div><div class="pg-big">{r}<small>% risk</small></div>'
        f'<div class="pg-sub">Highest: {esc(top["id"])} at {top["risk"]}%</div></div></div>'
        f'<img class="pg-trend" src="{data_uri(spark_svg(snap["risk_history"], c, 260, 30))}" alt="Risk trend">'
        f'<div class="pg-legend"><span><i style="background:{c}"></i>Risk {r}%</span>'
        f'<span><i style="background:#14213A;border:1px solid #2B4272"></i>Safe margin {100 - r}%</span></div></div>')


def plan_html(snap) -> str:
    legend = "".join(f'<span><i style="background:{EMP_COLOR[k]};border-radius:50%"></i>{t}</span>'
                     for k, t in (("ok", "at work"), ("notified", "alert received"), ("acked", "acknowledged"), ("safe", "at muster point")))
    return one(
        f'<div class="pg-card"><div class="pg-h">Plant floor<small>machines and people, live</small></div>'
        f'<img class="pg-plan" src="{data_uri(plan_svg(snap))}" alt="Plant floor plan">'
        f'<div class="pg-legend">{legend}</div></div>')


def tiles_html(snap) -> str:
    tiles = []
    for m in snap["machines"]:
        col = STATE_COLOR[m["state"]]
        rows = []
        for s in m["sensors"]:
            bc = STATUS_COLOR[s["status"]]
            eta = f'<u>critical in {s["eta"]} s</u>' if s["eta"] and s["status"] != "crit" else ""
            width = max(3, round(s["risk"])) if s["status"] != "off" else 3
            rows.append(f'<div class="s {s["status"]}" style="--bc:{bc}"><span>{esc(s["label"])}</span>'
                        f'<b>{esc(s["text"])} {esc(s["unit"])}</b><i style="width:{width}%"></i>{eta}</div>')
        notes = " · ".join(esc(n) for n in m["notes"])
        risk_txt = "-" if m["state"] == "STOPPED" else f'{m["risk"]}%'
        tiles.append(
            f'<div class="pg-tile st-{m["state"]}" style="--sc:{col}"><div class="pg-th"><b>{esc(m["id"])}</b>'
            f'<span class="pg-tn">{esc(m["name"])}</span><span class="pg-chip">{STATE_LABEL[m["state"]]}</span></div>'
            f'<div class="pg-rk"><div><i style="width:{m["risk"]}%"></i></div><span>{risk_txt}</span></div>'
            + "".join(rows) +
            f'<img class="pg-spark" src="{data_uri(spark_svg(m["risk_history"], col))}" alt="">'
            f'<div class="pg-notes">{notes}</div></div>')
    return one(f'<div class="pg-card"><div class="pg-h">Machines<small>risk per machine, 4 key sensors each</small></div>'
               f'<div class="pg-grid">{"".join(tiles)}</div></div>')


def feed_html(snap) -> str:
    items = []
    for a in snap["alerts"][:4]:
        col = LEVEL_COLOR[a["level"]]
        chips = "".join(f"<span>{esc(c)}</span>" for c in a["channels"])
        ack = ""
        if a["level"] != "CLEAR" and a["total"]:
            pct = round(100 * a["acked"] / a["total"])
            ack = (f'<div class="pg-ack"><i style="width:{pct}%"></i></div>'
                   f'<div class="pg-ackt">Acknowledged {a["acked"]}/{a["total"]}</div>')
        items.append(
            f'<div class="pg-alert" style="--ac:{col}"><b>{esc(a["title"])}</b><p>{esc(a["body"])}</p>'
            f'<div class="pg-meta"><span>{esc(a["clock"])}</span><span>to {esc(a["group"])}</span>{chips}</div>{ack}</div>')
    body = "".join(items) or '<div class="pg-quiet">No alerts sent. All quiet.</div>'
    return one(f'<div class="pg-card"><div class="pg-h">Alerts sent to employees<small>{len(snap["alerts"])} recent</small></div>{body}</div>')


def phone_html(snap) -> str:
    ph = snap["phone"]
    a = ph["alert"]
    if a is None:
        inner = '<div class="none">No alerts for you.<br>You are not in the alert group.</div>'
    else:
        col = LEVEL_COLOR[a["level"]]
        big = " big" if a["level"] == "EVACUATE" else ""
        inner = (f'<div class="n{big}" style="--ac:{col}"><b>{esc(a["title"])}</b><p>{esc(a["body"])}</p>'
                 f'<small>{esc(a["clock"])} · {esc(" + ".join(a["channels"][:3]))}</small></div>'
                 f'<div class="btn">Acknowledge</div>')
    return one(
        f'<div class="pg-card"><div class="pg-h">Employee phone<small>what a worker sees</small></div><div class="pg-phone-wrap">'
        f'<div class="pg-phone"><div class="bar"><span>{esc(snap["clock"])}</span><span>PlantGuard</span></div>{inner}</div>'
        f'<div class="pg-who">{esc(ph["name"])} · {esc(ph["role"])} · {esc(ph["zone"])}</div></div></div>')


def advice_html(snap) -> str:
    from plantsim import ACTION_LABELS
    rows = []
    for a in snap["advice"]:
        tag = f' <span class="tag">[{esc(ACTION_LABELS[a["action"]])}]</span>' if a["action"] else ""
        rows.append(f'<div class="pg-adv"><em style="background:{PRIO_COLOR[a["prio"]]}">P{a["prio"]}</em>'
                    f'<div>{esc(a["text"])}{tag}</div></div>')
    return one(f'<div class="pg-card"><div class="pg-h">Prevent further damage<small>P1 = do now</small></div>{"".join(rows)}</div>')


def log_html(snap) -> str:
    rows = "".join(f'<div><b style="color:{LEVEL_COLOR.get(e["level"], "#9AA9D6")}">{esc(e["clock"])}</b><span>{esc(e["text"])}</span></div>'
                   for e in snap["log"][:8])
    return one(f'<div class="pg-card"><div class="pg-h">Event log</div><div class="pg-log">{rows or "<div>No events yet.</div>"}</div></div>')


def disclaimer_html() -> str:
    return ('<div class="pg-foot">Prototype with simulated sensors and simulated notifications. '
            'It is not a safety system: real plants need certified safety instrumented systems and trained staff.</div>')
