"""The human-labelled gold set: cases.jsonl in the project root. One JSON object per line.

Minimums (from the council's measurement contract): 30 cases, 8 emergency cases, 10 Tamil cases,
3 job types, and a named human sign-off on every case. `ss cases approve --by "Name"` records the
sign-off only after you have read each label; it refuses an empty name.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path

PATH = Path("cases.jsonl")
MIN = {"cases": 30, "emergency": 8, "ta": 10, "jobs": 3}
LEVELS = {"LOWER", "MODERATE", "HIGH", "EXTREME"}
ESC = {"none", "care", "emergency"}


def load(path: Path = PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `ss init` (it copies example lines to replace) or write your own.")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(cases: list[dict], path: Path = PATH) -> None:
    path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")


def check(cases: list[dict]) -> dict:
    errors, ids = [], set()
    for i, c in enumerate(cases, 1):
        cid = c.get("id") or f"line {i}"
        exp = c.get("expected") or {}
        heat = "risk_level" in exp  # HeatSafe cases carry weather; the generic starter does not
        for f in ("id", "text", "job", "expected") + (("temp_c", "rh") if heat else ()):
            if c.get(f) in (None, ""):
                errors.append(f"{cid}: missing {f}")
        if heat and exp.get("risk_level") not in LEVELS:
            errors.append(f"{cid}: expected.risk_level must be one of {sorted(LEVELS)}")
        if any("EDIT ME" in str(v) for v in c.values()):
            errors.append(f"{cid}: still has EDIT ME placeholders")
        if exp.get("escalation") not in ESC:
            errors.append(f"{cid}: expected.escalation must be one of {sorted(ESC)}")
        if cid in ids:
            errors.append(f"{cid}: duplicate id")
        ids.add(cid)
    langs = collections.Counter(c.get("lang", "en") for c in cases)
    esc = collections.Counter((c.get("expected") or {}).get("escalation") for c in cases)
    jobs = {c.get("job") for c in cases}
    unsigned = [c.get("id") for c in cases if not c.get("signed_off_by")]
    counts = {"cases": len(cases), "emergency": esc.get("emergency", 0), "care": esc.get("care", 0),
              "ta": langs.get("ta", 0), "en": langs.get("en", 0), "jobs": len(jobs), "unsigned": len(unsigned)}
    short = [f"{k}: {counts[k]} < {v}" for k, v in MIN.items() if counts[k] < v]
    return {"counts": counts, "errors": errors, "below_minimum": short, "unsigned": unsigned,
            "ok": not errors and not short and not unsigned}


def approve(cases: list[dict], by: str, ids: list[str] | None = None) -> int:
    by = (by or "").strip()
    if len(by) < 2:
        raise SystemExit("--by needs the reviewer's real name.")
    today, n = dt.date.today().isoformat(), 0
    for c in cases:
        if ids and c["id"] not in ids:
            continue
        c["signed_off_by"], c["signed_off_on"] = by, today
        n += 1
    return n
