"""Record the demo video from a LIVE run, the Decider Cookbook way: no screen recorder, no editing.

    ss video                      uses video.json in the project root

A headless browser films a small studio page while your real commands run. Their output streams into
the log panel; every evidence line ([risk] [safety] [critic] [code] [lang] [plan]) becomes a large
badge, and a "Measured" card is built from results/measure.json. Silent; captions carry the story.

video.json:
{"title": "HeatSafe Shift", "subtitle": "...", "tags": ["#strands-agents", "#social-good"], "closing": "...",
 "scenes": [{"title": "...", "caption": "...", "input": "what the worker typed",
             "command": "python -m agent.app \\"...\\" --temp 37 --rh 50", "hold_s": 3.5}]}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

W, H = 1280, 720
PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;width:1280px;height:720px;background:#10151b;color:#e8e8e8;
font-family:-apple-system,Segoe UI,Helvetica,Arial,"Noto Sans Tamil","Tamil MN",sans-serif;overflow:hidden}
#top{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;background:#161e27;
border-bottom:1px solid #27323e}#top b{font-size:24px}#top span{color:#8fa3b8;font-size:16px}
#main{display:flex;height:540px}#left{width:44%;padding:24px 28px}#right{width:56%;padding:18px 22px 18px 0}
#scene{font-size:29px;font-weight:700;margin-bottom:10px}#cap{font-size:19px;color:#b9c8d7;line-height:1.35}
#input{margin-top:18px;background:#1c2631;border-left:4px solid #f0a33a;padding:12px 16px;font-size:19px;
line-height:1.45;white-space:pre-wrap;max-height:150px;overflow:hidden}
#badges{margin-top:16px}.b{margin-top:10px;padding:12px 16px;border-radius:10px;font-size:22px;font-weight:800;
font-family:Menlo,Consolas,monospace}.b small{display:block;font-size:14px;font-weight:500;opacity:.85;margin-top:4px;font-family:inherit}
.ok{background:#123d24;color:#7ef0a6;border:2px solid #2fbf67}.warn{background:#3d3312;color:#ffd970;border:2px solid #d9a92b}
.stop{background:#3d1616;color:#ff9b9b;border:2px solid #d94b4b}.info{background:#13283d;color:#9fd0ff;border:2px solid #3a8ad9}
#log{height:100%;background:#0b0e12;border:1px solid #27323e;border-radius:8px;padding:12px 14px;
font-family:Menlo,Consolas,"Noto Sans Tamil",monospace;font-size:13px;line-height:1.45;overflow:hidden;white-space:pre-wrap}
#log .d{color:#ffd970;font-weight:700}#log .e{color:#ff9b9b}#log .muted{color:#6c7a89}
#sub{height:116px;display:flex;align-items:center;justify-content:center;text-align:center;padding:0 60px;
font-size:24px;line-height:1.35;background:#161e27;border-top:1px solid #27323e}
#card{position:absolute;inset:0;background:#10151b;display:none;flex-direction:column;align-items:center;
justify-content:center;text-align:center;padding:50px}#card h1{font-size:44px;margin:0 0 16px}
#card p{font-size:22px;color:#b9c8d7;margin:6px 0;max-width:1100px;line-height:1.4}
#foot{position:absolute;right:16px;bottom:6px;font-size:12px;color:#6c7a89}
</style></head><body>
<div id="top"><b id="ttl"></b><span id="tag"></span></div>
<div id="main"><div id="left"><div id="scene"></div><div id="cap"></div><div id="input"></div><div id="badges"></div></div>
<div id="right"><div id="log"></div></div></div><div id="sub"></div><div id="card"></div><div id="foot"></div>
<script>
function q(i){return document.getElementById(i)}
function setTop(t,tag,foot){q('ttl').textContent=t;q('tag').textContent=tag;q('foot').textContent=foot}
function scene(t,c,inp){q('scene').textContent=t;q('cap').textContent=c;q('input').textContent=inp;
q('input').style.display=inp?'block':'none';q('badges').innerHTML='';q('log').innerHTML='';q('sub').textContent=''}
function log(line,cls){var d=document.createElement('div');if(cls)d.className=cls;d.textContent=line;var L=q('log');
L.appendChild(d);while(L.scrollHeight>L.clientHeight&&L.children.length>1)L.removeChild(L.firstChild)}
function badge(cls,big,small){var B=q('badges');var b=document.createElement('div');b.className='b '+cls;
b.appendChild(document.createTextNode(big));var s=document.createElement('small');s.textContent=small;b.appendChild(s);
B.appendChild(b);while(B.children.length>3)B.removeChild(B.firstChild)}
function sub(t){q('sub').textContent=t}
function card(h,lines){var c=q('card');c.innerHTML='';var e=document.createElement('h1');e.textContent=h;c.appendChild(e);
lines.forEach(function(l){var p=document.createElement('p');p.textContent=l;c.appendChild(p)});c.style.display='flex'}
function nocard(){q('card').style.display='none'}
</script></body></html>"""

EVIDENCE = re.compile(r"^\[(risk|safety|critic|code|lang|plan|weather|guard|decider|tool|tools|graph|swarm|shell|mcp|evals|session|harness|guardrail)\] (.+)$")


def _badge(kind: str, text: str) -> tuple[str, str, str] | None:
    if kind == "risk":
        lvl = text.rsplit("-> ", 1)[-1]
        return ({"LOWER": "ok", "MODERATE": "info", "HIGH": "warn", "EXTREME": "stop"}.get(lvl, "info"),
                f"RISK {lvl}", "code: NWS heat index + OSHA bands; " + text.split(" -> ")[0])
    if kind == "safety":
        stop = "EMERGENCY" in text
        return ("stop" if stop else "warn", "CALL 108" if stop else "STOP WORK", text)
    if kind == "critic":
        return ("ok" if "PASS" in text else "warn", "CRITIC " + ("PASS" if "PASS" in text else "REVISE"), text[:150])
    if kind == "code":
        return ("warn", "CODE CORRECTED", text[:150])
    if kind == "lang":
        return ("info", "AMAZON TRANSLATE", text)
    if kind == "plan":
        return ("ok", "PLAN READY", text)
    if kind == "guard":
        bad = any(w in text for w in ("DENY", "BROKE", "YES"))
        return ("stop" if bad else "warn", "RULE " + text.split(":")[0][:20], text[:150])
    if kind == "decider":
        return ("info", "STRANDS DECIDER", text[:150])
    if kind == "weather":
        return None
    return ("info", kind.upper(), text[:150])


def _measured() -> list[str]:
    try:
        r = json.loads(Path("results/measure.json").read_text())
    except Exception:
        return []
    a, b, n = r["agent"]["overall"], r["baseline"]["overall"], r["agent"]["overall"]["cases"]
    return [f"{n} human-labelled cases ({r['cases']['emergency']} emergencies, {r['cases']['ta']} in Tamil), same model for both.",
            f"Risk level right: {a['threshold_accuracy']:.0%} vs {b['threshold_accuracy']:.0%} for a single-prompt agent.",
            f"Plans with unsafe advice: {a['unsafe']} vs {b['unsafe']}.   Emergencies sent to 108: {a['emergency_recall']:.0%} vs {b['emergency_recall']:.0%}.",
            f"Strands Evals goal success: {a['goal_success']} vs {b['goal_success']}.   Gate: {'PASSED' if r['passed'] else 'not passed yet'}."]


def _browser(pw):
    try:
        return pw.chromium.launch(headless=True)
    except Exception:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return pw.chromium.launch(headless=True)


def record(spec_path: str = "video.json") -> dict:
    from playwright.sync_api import sync_playwright
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    out_dir = Path("results")
    raw_dir = out_dir / "_raw"
    shutil.rmtree(raw_dir, ignore_errors=True)
    out_dir.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(Path.cwd()) + os.pathsep + os.environ.get("PYTHONPATH", ""),
           "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")}
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    foot = f"live run {time.strftime('%Y-%m-%d %H:%M')}" + (f" | commit {commit}" if commit else "")
    tags = " ".join(spec.get("tags", ["#strands-agents"]))
    log, t0 = {"spec": spec, "scenes": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}, time.time()
    with sync_playwright() as pw:
        browser = _browser(pw)
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(raw_dir),
                                  record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.set_content(PAGE)
        js = lambda fn, *a: page.evaluate(f"{fn}(...{json.dumps(list(a), ensure_ascii=False)})")
        js("setTop", spec.get("title", ""), tags, foot)
        js("card", spec.get("title", ""), [spec.get("subtitle", ""), "Live run on Amazon Bedrock: every output below is real."])
        page.wait_for_timeout(int(spec.get("intro_s", 4) * 1000))
        js("nocard")
        for sc in spec["scenes"]:
            js("scene", sc["title"], sc.get("caption", ""), sc.get("input", ""))
            js("sub", sc.get("caption", ""))
            page.wait_for_timeout(1500)
            js("log", "$ " + sc["command"], "muted")
            lines, ev = [], []
            # On Windows the scene command may be "python -m ..." — ensure it uses the venv interpreter.
            import platform as _plat
            _cmd = sc["command"]
            if _plat.system() == "Windows":
                import re as _re
                _cmd = _re.sub(r'^python3?\b', f'"{sys.executable}"', _cmd, count=1)
            p = subprocess.Popen(_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 env=env, bufsize=1, encoding="utf-8")
            for line in p.stdout:
                line = line.rstrip("\n")
                lines.append(line)
                m = EVIDENCE.match(line)
                b = _badge(m[1], m[2]) if m else None
                if b:
                    ev.append(line)
                    js("badge", *b)
                js("log", line, "d" if m else ("e" if "Traceback" in line or "Error" in line else ""))
            rc = p.wait()
            if sc.get("after"):
                js("sub", sc["after"])
            log["scenes"].append({"title": sc["title"], "command": sc["command"], "exit": rc, "evidence": ev, "output": lines[-80:]})
            page.wait_for_timeout(int(sc.get("hold_s", 4) * 1000))
        m = _measured()
        if m:
            js("card", "Measured, not claimed", m)
            page.wait_for_timeout(int(spec.get("measured_s", 8) * 1000))
        js("card", spec.get("title", ""), [spec.get("closing", ""), tags])
        page.wait_for_timeout(3500)
        video = page.video
        ctx.close()
        browser.close()
        raw = Path(video.path())
    seconds = round(time.time() - t0, 1)
    webm = out_dir / "demo.webm"
    shutil.move(str(raw), webm)
    shutil.rmtree(raw_dir, ignore_errors=True)
    final = webm
    if shutil.which("ffmpeg"):
        mp4 = out_dir / "demo.mp4"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-an", str(mp4)])
        if r.returncode == 0:
            final = mp4
            webm.unlink(missing_ok=True)
    log.update({"seconds": seconds, "file": str(final), "under_3_min": seconds < 180})
    (out_dir / "video_run.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"file": str(final), "seconds": seconds, "under_3_min": seconds < 180,
            "scenes": [{"title": s["title"], "exit": s["exit"], "evidence": s["evidence"]} for s in log["scenes"]]}

