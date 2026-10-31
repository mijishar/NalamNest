"""ss ship: write results/FACTS.md (every measured number, for the article) and SUBMISSION.md.

Rows are PASS / FAIL (the kit checked it) or HUMAN (only you can do it). Rules: the official
"Strands SDK: Workshop to Ship" page on AWS Builder Center, copied into .kiro/steering/hackathon-rules.md.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

SECRET = re.compile(r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|aws_secret_access_key\s*=")


def _video_seconds(path: str) -> float | None:
    if not path or not Path(path).exists() or not shutil.which("ffprobe"):
        return None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 1)
    except ValueError:
        return None


def _secrets() -> list[str]:
    hits = []
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True).stdout.split()
    for f in files or [str(p) for p in Path(".").rglob("*") if p.is_file() and ".venv" not in p.parts]:
        p = Path(f)
        if p.is_file() and p.stat().st_size < 2_000_000:
            try:
                if SECRET.search(p.read_text(errors="ignore")):
                    hits.append(f)
            except OSError:
                pass
    hist = subprocess.run(["git", "log", "-p", "--all"], capture_output=True, text=True).stdout
    if SECRET.search(hist):
        hits.append("git history")
    return hits


def facts(m: dict) -> str:
    a, b = m["agent"]["overall"], m["baseline"]["overall"]
    lines = [f"# Facts (measured {m['when']}, model {m['model']})", "",
             "Quote these exactly in the article and video. Do not round differently or add numbers that are not here.", ""]
    for k in ("cases", "emergency_cases", "emergency_recall", "unsafe", "threshold_accuracy", "citation_faithfulness",
              "completeness", "goal_success", "latency_p50_ms"):
        lines.append(f"- {k}: agent {a.get(k)} | baseline {b.get(k)}")
    lines += ["", "By language:"] + [f"- {g}: agent unsafe {v['unsafe']}, risk correct {v['threshold_accuracy']:.0%}; baseline unsafe "
                                     f"{m['baseline']['by_language'].get(g, {}).get('unsafe')}" for g, v in m["agent"]["by_language"].items()]
    lines += ["", "Gate:"] + [f"- {'PASS' if ok else 'FAIL'} {k}" for k, ok in m["gate"].items()]
    return "\n".join(lines) + "\n"


def main() -> int:
    rows = []
    add = lambda status, what, how="": rows.append((status, what, how))
    m = json.loads(Path("results/measure.json").read_text()) if Path("results/measure.json").exists() else None
    if m:
        Path("results/FACTS.md").write_text(facts(m), encoding="utf-8")
    add("PASS" if m and m["passed"] else "FAIL", "Measurement gate passed (baseline vs agent on signed cases)",
        "results/MEASURE.md" if m else "run `ss measure`")
    fail_log = Path("FAILURES.md").read_text(encoding="utf-8") if Path("FAILURES.md").exists() else ""
    n_fail = len(re.findall(r"^## ", re.sub(r"<!--.*?-->", "", fail_log, flags=re.S), re.M))
    add("PASS" if n_fail >= 1 else "FAIL", f"At least one real failure found and fixed, logged in FAILURES.md ({n_fail})",
        "add a '## ' entry: what broke, how you found it, what you changed, the re-measure")
    v = json.loads(Path("results/video_run.json").read_text()) if Path("results/video_run.json").exists() else None
    secs = _video_seconds(v["file"]) if v else None
    secs = secs if secs is not None else (v["seconds"] if v else None)
    add("PASS" if v and secs is not None and secs < 180 and all(s["exit"] == 0 for s in v["scenes"]) else "FAIL",
        f"Demo video under 3 minutes from a live run ({secs} s)" if v else "Demo video recorded", "run `ss video`")
    add("PASS" if Path("README.md").exists() else "FAIL", "README.md: problem, who it helps, how to run, results table")
    lic = next((p for p in ("LICENSE", "LICENSE.md", "LICENSE.txt") if Path(p).exists()), None)
    add("PASS" if lic else "FAIL", "Open-source licence file", lic or "add Apache-2.0 or MIT")
    add("PASS" if Path("requirements.txt").exists() else "FAIL", "requirements.txt pins the Strands Agents SDK")
    s = _secrets()
    add("PASS" if not s else "FAIL", "No AWS keys or private keys in files or git history", ", ".join(s) or "")
    pts = json.loads(Path("agent/data/places.geojson").read_text()) if Path("agent/data/places.geojson").exists() else {"features": []}
    unchecked = [f["properties"]["name"] for f in pts["features"] if not f["properties"].get("verified_on")]
    add("FAIL" if unchecked else "PASS", "Every water/shade point checked by a person (verified_on set)",
        f"{len(unchecked)} unchecked sample points" if unchecked else "")
    for what in ("Completed the Builder Center sandbox workshop 'Building AI Agents with Strands SDK: From Simple Loops to "
                 "Multi-Agent Swarms' between 28 Oct and 4 Nov 2026",
                 "Builder Center profile, aged 18+, country and employee rules checked (Rules tab)",
                 "Agent is original and was never published before the window",
                 "Public GitHub repo with the source code (make it public inside the window)",
                 "Video uploaded publicly (YouTube or similar), under 3 minutes, no copyrighted music",
                 "Project article published on Builder Center: agent, problem, who it helps, results table, what you learned",
                 "Submitted before 4 Nov 2026 11:59 PM PST (5 Nov 2026 1:29 PM IST)"):
        add("HUMAN", what)
    out = ["# Submission check: Strands SDK: Workshop to Ship", "",
           "| Status | Requirement | Note |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    Path("SUBMISSION.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    fails = sum(1 for r in rows if r[0] == "FAIL")
    print(f"\n{fails} FAIL, {sum(1 for r in rows if r[0] == 'HUMAN')} HUMAN. " + ("Fix every FAIL, then run `ss ship` again." if fails else "Kit checks all pass."))
    return 1 if fails else 0
