"""NalamNest care data tools. Read-only lookups + proposed writes (writes need ConfirmGate approval).

All data in agent/data/care_data.json is synthetic demo data. No real patient information.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from strands import tool

DATA = Path(__file__).parent / "data"
TAMIL = re.compile(r"[\u0B80-\u0BFF]")

# Phrases that indicate a response that handed off to a human (used by score.py)
HANDOFF_MARKERS = [
    "doctor", "pharmacist", "108", "helpline", "மருத்துவர்", "மருந்தாளர்", "அழையுங்கள்"
]


@lru_cache(maxsize=1)
def _care_data() -> dict:
    return json.loads((DATA / "care_data.json").read_text(encoding="utf-8"))


def guidance_ids() -> set[str]:
    return {g["id"] for g in _care_data()["guidance"]}


def language_of(text: str) -> str:
    return "ta" if TAMIL.search(text or "") else "en"


def has_tamil(text: str) -> bool:
    return bool(TAMIL.search(text or ""))


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

@tool
def lookup_care_data(topic: str) -> list[dict]:
    """Search the family's care information: appointments, documents, tasks, guidance.

    Always call this first. The planner may only cite ids returned by this tool.

    Args:
        topic: words to search for (e.g. "cardiology appointment", "discharge summary", "checklist")
    """
    data = _care_data()
    words = [w for w in re.findall(r"\w+", topic.lower()) if len(w) > 2]

    def matches(obj: dict) -> bool:
        haystack = json.dumps(obj, ensure_ascii=False).lower()
        return any(w in haystack for w in words)

    results = []

    # Appointments
    for a in data.get("appointments", []):
        if matches(a):
            results.append({
                "id": a["id"], "type": "appointment",
                "doctor": a["doctor"], "specialty": a["specialty"],
                "date": a["date"], "time": a["time"],
                "location": a["location"], "notes": a["notes"],
                "follow_up_items": a.get("follow_up_items", [])
            })

    # Documents
    for d in data.get("documents", []):
        if matches(d):
            results.append({
                "id": d["id"], "type": "document",
                "document_type": d["type"], "date": d["date"],
                "hospital": d["hospital"], "doctor": d["doctor"],
                "summary": d["summary"],
                "instructions": d.get("instructions", []),
                "follow_up": d.get("follow_up", "")
            })

    # Guidance items
    for g in data.get("guidance", []):
        if matches(g):
            results.append({"id": g["id"], "type": "guidance", "text": g["text"]})

    # Patients
    for p in data.get("patients", []):
        if matches(p):
            results.append({
                "id": p["id"], "type": "patient",
                "name": p["name"], "age": p["age"],
                "conditions": p.get("conditions", [])
            })

    return results[:8] if results else [
        {"id": g["id"], "type": "guidance", "text": g["text"]}
        for g in data.get("guidance", [])[:4]
    ]


@tool
def summarise_document(document_id: str) -> dict:
    """Return a structured summary of a health document (discharge summary, lab report, etc.).

    This tool summarises dates, doctor names, instructions and follow-up items only.
    It does not interpret diagnoses or recommend any actions.

    Args:
        document_id: the id from lookup_care_data (e.g. "D-001")
    """
    docs = {d["id"]: d for d in _care_data().get("documents", [])}
    doc = docs.get(document_id)
    if not doc:
        return {"error": f"Document {document_id!r} not found. Use lookup_care_data to find available documents."}
    return {
        "id": doc["id"],
        "type": doc["type"],
        "date": doc["date"],
        "hospital": doc["hospital"],
        "doctor": doc["doctor"],
        "summary": doc["summary"],
        "instructions": doc.get("instructions", []),
        "follow_up": doc.get("follow_up", ""),
        "note": "This is a document summary only. It does not constitute medical advice."
    }


# ---------------------------------------------------------------------------
# Proposed write tools — these ALWAYS require ConfirmGate approval before
# the data file is actually written. The tool returns a proposal dict;
# the intervention handler intercepts the call for user confirmation.
# ---------------------------------------------------------------------------

@tool
def propose_task(description: str, due_date: str = "", assigned_to: str = "") -> dict:
    """Propose a new care task for the family to confirm.

    This PROPOSES a task — the family must confirm before it is saved.
    Do not call this without enough information to describe the task clearly.

    Args:
        description: what needs to be done (e.g. "Collect Appa's ECG report from Apollo")
        due_date: ISO date YYYY-MM-DD, or empty if not known
        assigned_to: which family member, or empty
    """
    return {
        "action": "create_task",
        "description": description,
        "due_date": due_date,
        "assigned_to": assigned_to,
        "status": "proposed — awaiting family confirmation"
    }


@tool
def propose_reminder(text: str, datetime_iso: str = "", patient: str = "P-DEMO") -> dict:
    """Propose a new reminder for the family to confirm.

    This PROPOSES a reminder — the family must confirm before it is saved.

    Args:
        text: the reminder message (e.g. "Cardiology appointment tomorrow at 10:30")
        datetime_iso: ISO datetime or empty
        patient: patient id, defaults to the demo patient
    """
    return {
        "action": "create_reminder",
        "text": text,
        "datetime_iso": datetime_iso,
        "patient": patient,
        "status": "proposed — awaiting family confirmation"
    }


# ---------------------------------------------------------------------------
# Actual write helpers — called only after ConfirmGate approves
# ---------------------------------------------------------------------------

def _load_data() -> dict:
    """Load care_data.json (not cached — writes need fresh state)."""
    return json.loads((DATA / "care_data.json").read_text(encoding="utf-8"))


def _save_data(data: dict) -> None:
    (DATA / "care_data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def commit_task(description: str, due_date: str = "", assigned_to: str = "") -> dict:
    """Save a confirmed task to care_data.json."""
    data = _load_data()
    import time as _time
    task_id = f"T-{int(_time.time())}"
    task = {"id": task_id, "description": description, "due_date": due_date,
            "assigned_to": assigned_to, "status": "open"}
    data.setdefault("tasks", []).append(task)
    _save_data(data)
    _care_data.cache_clear()
    return {"saved": True, "id": task_id, **task}


def commit_reminder(text: str, datetime_iso: str = "", patient: str = "P-DEMO") -> dict:
    """Save a confirmed reminder to care_data.json."""
    data = _load_data()
    import time as _time
    reminder_id = f"R-{int(_time.time())}"
    reminder = {"id": reminder_id, "text": text, "datetime_iso": datetime_iso, "patient": patient}
    data.setdefault("reminders", []).append(reminder)
    _save_data(data)
    _care_data.cache_clear()
    return {"saved": True, "id": reminder_id, **reminder}
