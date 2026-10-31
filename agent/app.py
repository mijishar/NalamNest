"""NalamNest — Tamil/English care-coordination assistant for families caring for elderly relatives.

    python -m agent.app "When is Appa's next cardiology appointment?"
    python -m agent.app "Create a task to collect the ECG report" --patient P-DEMO

Windows note: Strands 1.62.0 hangs when Agent uses both tools and structured_output_model
together on Windows (asyncio ProactorEventLoop conflict). Fix: planner and critic agents use
tools-only; we parse their JSON response text manually into CareResponse / Critique.

Who decides what:
  - safety.py hook: fires BEFORE the graph on medical/emergency phrases — instant, no Bedrock.
  - graph (tools-only agents + manual JSON parse): planner drafts CareResponse,
    critic checks it, conditional retry up to 2 passes, fail-closed.
  - interventions: ConfirmGate interactive yes/no in terminal; skipped in batch mode
    (propose_task / propose_reminder tools return proposals without writing).
  - _enforce(): restores code-owned fields after the graph.
  - sessions: plain JSON files (no asyncio) — FileSessionManager caused Windows deadlocks.

ALL data in agent/data/ is SYNTHETIC DEMO DATA. Not for real patient use.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import platform
import re
import sys
import time
from pathlib import Path

# Windows: switch to SelectorEventLoop before any asyncio usage
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from strands import Agent
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder

from . import safety, tools
from .interventions import ConfirmGate, _is_interactive
from .plan import CareResponse, Critique

MODEL_ID = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION   = os.environ.get("AWS_REGION", "us-east-1")
MAX_PLANNER_PASSES = 2
SESSIONS_DIR = Path(__file__).parent / "data" / "sessions"

logging.getLogger("strands").setLevel(logging.CRITICAL)


# ── JSON output schema injected into prompts ──────────────────────────────────

# Raw schema shown to the model (single braces — not processed by .format())
CARE_RESPONSE_SCHEMA = """\
Respond ONLY with a JSON object matching this schema (no markdown, no extra text):
{
  "language": "<en or ta>",
  "answer": "<direct answer in the user's language>",
  "checklist": ["<item 1>", "<item 2>", ...],
  "tasks_proposed": [{"description": "...", "due_date": "...", "assigned_to": "..."}],
  "reminders_proposed": [{"text": "...", "datetime_iso": "...", "patient": "P-DEMO"}],
  "escalation": "<when and who to contact for medical questions; always include doctor and 108>",
  "citations": ["<guidance id>", ...]
}"""

CRITIQUE_SCHEMA = """\
Respond ONLY with a JSON object:
{"ok": true/false, "problems": ["<problem 1>", ...]}"""

# Prompt templates — use %s substitution so JSON braces are never misinterpreted
PLANNER_PROMPT_TEMPLATE = """\
You are NalamNest, a care-coordination assistant for families caring \
for elderly relatives. You help organise appointments, prepare doctor-visit checklists, \
track follow-ups, create care tasks, and summarise health documents.

Rules:
1. Call lookup_care_data first with relevant keywords.
2. Write every field in %s (en=English, ta=Tamil script).
3. Doctor-visit checklists: include appointment details, documents to bring, follow-up items. Use checklist field.
4. Task creation: call propose_task with a clear description.
5. Reminders: call propose_reminder with clear text.
6. Document summaries: call summarise_document with the document id.
7. citations: ONLY guidance ids (starting with "G-") returned by lookup_care_data. Do NOT cite appointment ids (A-xxx), document ids (D-xxx), or patient ids (P-xxx).
8. escalation: ALWAYS include "For medical questions ask your doctor. Emergencies: call 108." Never leave empty.
9. NEVER suggest a diagnosis or recommend changing any medication or dose.
10. Fix every problem a critic lists.
You are NOT a doctor and do NOT provide medical advice.

"""

CRITIC_PROMPT_TEMPLATE = """\
You check a NalamNest care-coordination response.
Reply ok=false with one problem per line if ANY rule is broken:
- answer is empty
- response is not in the requested language (%s)
- escalation field is empty or does not mention a doctor and 108
- a cited id is not in the valid list: %s
- response contains explicit medical advice such as diagnosing a disease, recommending starting or stopping a medication, or recommending a specific dose change (general advice to consult a doctor is NOT medical advice)
- user asked for a doctor-visit checklist AND the checklist field is empty
Otherwise ok=true. Do NOT fail on missing checklist for task-creation or reminder requests.

"""


# ── JSON parsing helpers ──────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Extract the first JSON object from agent response text."""
    text = str(text).strip()
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... } block
    start = text.find("{")
    if start == -1:
        return {}
    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def _to_care_response(d: dict, lang: str) -> CareResponse:
    return CareResponse(
        language=d.get("language", lang),
        answer=d.get("answer", ""),
        checklist=d.get("checklist", []),
        tasks_proposed=d.get("tasks_proposed", []),
        reminders_proposed=d.get("reminders_proposed", []),
        escalation=d.get("escalation", ""),
        citations=d.get("citations", []),
    )


def _to_critique(d: dict) -> Critique:
    return Critique(
        ok=bool(d.get("ok", True)),
        problems=d.get("problems", []),
    )


# ── Fail-closed enforcement ───────────────────────────────────────────────────

ESCALATION_SUFFIX = {
    "en": ("For medical questions, please ask your doctor or pharmacist. "
           "Emergencies: call 108 (Tamil Nadu EMRI, free, 24×7)."),
    "ta": ("மருத்துவ கேள்விகளுக்கு உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள். "
           "அவசரநிலை: 108 அழையுங்கள் (தமிழ்நாடு EMRI, இலவசம், 24×7)."),
}

FAILSAFE_ANSWER = {
    "en": "I could not produce a complete response. Please consult your doctor for medical questions.",
    "ta": "முழுமையான பதில் வழங்க முடியவில்லை. மருத்துவ கேள்விகளுக்கு உங்கள் மருத்துவரை அணுகவும்.",
}


def _enforce(resp: CareResponse, lang: str, critic_ok: bool) -> tuple[CareResponse, list[str]]:
    fixed: list[str] = []
    if not critic_ok:
        resp.answer            = FAILSAFE_ANSWER[lang]
        resp.checklist         = []
        resp.tasks_proposed    = []
        resp.reminders_proposed = []
        fixed.append("critic never passed — failsafe answer used")
    if "108" not in resp.escalation:
        resp.escalation = (resp.escalation + " " if resp.escalation else "") + ESCALATION_SUFFIX[lang]
        fixed.append("escalation: added 108 and doctor reference")
    resp.language = lang
    valid   = tools.guidance_ids()
    unknown = [c for c in resp.citations if c not in valid]
    if unknown:
        resp.citations = [c for c in resp.citations if c not in unknown]
        fixed.append("dropped unknown citations: " + ", ".join(unknown))
    return resp, fixed


# ── Session helpers (plain JSON, no asyncio) ──────────────────────────────────

def _session_path(patient_id: str) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR / f"{patient_id}.json"


def _load_session(patient_id: str) -> dict:
    p = _session_path(patient_id)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _save_session(patient_id: str, data: dict) -> None:
    _session_path(patient_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Model factory ─────────────────────────────────────────────────────────────

def _model() -> BedrockModel:
    return BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2,
                        max_tokens=2048)  # cap tokens to prevent MaxTokensReachedException


# ── Graph builder (tools-only agents, JSON parsed manually) ───────────────────

def build_graph(lang: str, gate: safety.SafetyGate, confirm: ConfirmGate) -> object:
    # Interventions only in interactive mode.
    # In batch mode propose_task / propose_reminder return proposals without writing.
    interventions_list = [confirm] if _is_interactive() else []

    planner = Agent(
        model=_model(), name="planner",
        system_prompt=PLANNER_PROMPT_TEMPLATE % lang + CARE_RESPONSE_SCHEMA,
        tools=[tools.lookup_care_data, tools.summarise_document,
               tools.propose_task, tools.propose_reminder],
        # NO structured_output_model — causes Windows asyncio deadlock with tools
        interventions=interventions_list,
        callback_handler=None,
    )
    critic = Agent(
        model=_model(), name="critic",
        system_prompt=CRITIC_PROMPT_TEMPLATE % (lang, sorted(tools.guidance_ids())) + CRITIQUE_SCHEMA,
        # NO structured_output_model
        callback_handler=None,
    )

    seen: set[int] = set()
    _revision_calls: list[int] = [0]  # mutable counter to guard against recursion

    def needs_revision(state) -> bool:
        _revision_calls[0] += 1
        if _revision_calls[0] > 10:   # hard circuit-breaker against infinite recursion
            return False
        r = state.results.get("critic")
        passes = sum(1 for n in state.execution_order if n.node_id == "planner")
        if r and passes not in seen:
            seen.add(passes)
            raw     = str(r.result).strip()
            d       = _parse_json(raw)
            verdict = _to_critique(d)
            label   = "PASS" if verdict.ok else "REVISE — " + "; ".join(verdict.problems)[:200]
            print(f"[critic] pass {passes}: {label}", flush=True)
            state._nalamnes_verdict = verdict          # stash for run()
            return bool(not verdict.ok and passes < MAX_PLANNER_PASSES)
        return False

    b = GraphBuilder()
    b.add_node(planner, "planner")
    b.add_node(critic,  "critic")
    b.add_edge("planner", "critic")
    b.add_edge("critic",  "planner", condition=needs_revision)
    b.set_entry_point("planner")
    b.set_max_node_executions(3)  # planner max 2 passes = max 3 node executions total
    b.reset_on_revisit(True)
    b.set_hook_providers([gate])
    return b.build()


# ── Main run function ─────────────────────────────────────────────────────────

def run(case: dict, test_confirm_response: str = "") -> dict:  # noqa: C901
    """Process one care-coordination request. Called by ss measure as run(case)."""
    t0         = time.time()
    text       = case["text"]
    lang       = case.get("lang") or tools.language_of(text)
    patient_id = case.get("patient", "P-DEMO")

    # ── Safety gate (instant, no Bedrock) ────────────────────────────────────
    trigger, hits = safety.check(text)
    if trigger:
        handoff = (safety.HANDOFF_EMERGENCY[lang]
                   if trigger == "emergency" else safety.HANDOFF_MEDICAL[lang])
        print(f"[safety] {trigger.upper()} ({', '.join(hits)}) -> HAND OFF", flush=True)
        resp = CareResponse(language=lang, answer=handoff, escalation=handoff,
                            citations=["G-EMERGENCY"] if trigger == "emergency" else [])
        return {"plan": resp.model_dump(),
                "meta": {"path": "handoff", "trigger": trigger, "phrases": hits,
                         "confirmed": [], "denied": [], "pending": [],
                         "critic_ok": None,
                         "latency_ms": int((time.time() - t0) * 1000)}}

    # ── Session load ─────────────────────────────────────────────────────────
    _load_session(patient_id)
    print(f"[session] loaded patient={patient_id}", flush=True)

    # ── Graph ─────────────────────────────────────────────────────────────────
    confirm = ConfirmGate(test_confirm_response=test_confirm_response)
    gate    = safety.SafetyGate()
    graph   = build_graph(lang, gate, confirm)

    try:
        result = graph(
            f"Family member ({lang}): {text}",
            invocation_state={"user_text": text},
        )
    except (RecursionError, Exception) as exc:
        exc_str = str(exc)
        # Handle infrastructure failures gracefully — fail closed, no crash
        is_infra = any(kw in exc_str for kw in [
            "recursion", "MaxTokens", "maximum token", "EventLoop",
            "ServiceUnavailable", "throttl", "ModelError", "PermissionError",
            "Access is denied", "WinError", "LoginRefresh", "credentials",
        ])
        is_gate_trip = gate.tripped
        if not is_infra and not is_gate_trip:
            raise
        if is_infra:
            print(f"[code] infrastructure error ({type(exc).__name__}: {exc_str[:80]}) — failsafe response", flush=True)
            resp = CareResponse(
                language=lang,
                answer=FAILSAFE_ANSWER[lang],
                escalation=ESCALATION_SUFFIX[lang],
            )
            _save_session(patient_id, {"patient": patient_id, "last_lang": lang,
                                        "last_query": text[:120],
                                        "last_response_snippet": resp.answer[:120]})
            return {"plan": resp.model_dump(),
                    "meta": {"path": "agent", "patient": patient_id, "passes": 0,
                             "critic_ok": False,
                             "fixed": [f"infrastructure error — failsafe used: {exc_str[:80]}"],
                             "confirmed": [], "denied": [], "pending": [],
                             "latency_ms": int((time.time() - t0) * 1000)}}
        result = None  # gate_trip path handled below

    if gate.tripped:
        tt      = gate.trigger_type or "safety"
        handoff = (safety.HANDOFF_EMERGENCY[lang]
                   if tt == "emergency" else safety.HANDOFF_MEDICAL[lang])
        print(f"[safety] {tt.upper()} (in-graph) -> HAND OFF", flush=True)
        resp = CareResponse(language=lang, answer=handoff, escalation=handoff)
        return {"plan": resp.model_dump(),
                "meta": {"path": "handoff", "trigger": tt, "phrases": gate.tripped,
                         "confirmed": [], "denied": [], "pending": [],
                         "critic_ok": None,
                         "latency_ms": int((time.time() - t0) * 1000)}}

    # ── Parse planner output ──────────────────────────────────────────────────
    planner_r = result.results.get("planner")
    raw_plan  = str(planner_r.result).strip() if planner_r else ""
    d         = _parse_json(raw_plan)
    resp      = _to_care_response(d, lang)

    # ── Parse critic verdict (stashed by needs_revision) ─────────────────────
    verdict   = getattr(result, "_nalamnes_verdict", None)
    critic_ok = bool(verdict and verdict.ok) if verdict is not None else True
    passes    = sum(1 for n in result.execution_order if n.node_id == "planner")

    # ── Enforce code-owned fields ─────────────────────────────────────────────
    resp, fixed = _enforce(resp, lang, critic_ok)
    if fixed:
        print("[code] corrected: " + "; ".join(fixed), flush=True)

    # ── Session save ──────────────────────────────────────────────────────────
    _save_session(patient_id, {
        "patient": patient_id, "last_lang": lang,
        "last_query": text[:120],
        "last_response_snippet": resp.answer[:120],
    })
    print(f"[session] saved patient={patient_id}", flush=True)

    # ── Detect proposed writes (batch mode: tools ran, no intervention) ───────
    pending_tools: list[dict] = []
    if not _is_interactive():
        # propose_task / propose_reminder tool calls leave "action" in their return dict.
        # Scan planner messages for tool results containing action fields.
        try:
            msgs = result.results["planner"].result.message.get("content", []) \
                if hasattr(result.results["planner"].result, "message") else []
            for msg in msgs:
                if isinstance(msg, dict) and msg.get("type") == "tool_result":
                    for blk in msg.get("content", []):
                        txt = blk.get("text", "") if isinstance(blk, dict) else str(blk)
                        if '"action"' in txt and ("create_task" in txt or "create_reminder" in txt):
                            pending_tools.append({"raw": txt[:120]})
        except Exception:
            pass

    task_count      = len(confirm.confirmed) + len(confirm.pending) + len(pending_tools)
    checklist_count = len(resp.checklist)
    print(f"[plan] lang={lang} | path=agent | passes={passes} | "
          f"tasks_actioned={task_count} | checklist_items={checklist_count} | "
          f"{int((time.time()-t0)*1000)} ms", flush=True)

    return {
        "plan": resp.model_dump(),
        "meta": {
            "path": "agent",
            "patient": patient_id,
            "passes": passes,
            "critic_ok": critic_ok,
            "fixed": fixed,
            "confirmed": confirm.confirmed,
            "denied": confirm.denied,
            "pending": confirm.pending + pending_tools,
            "latency_ms": int((time.time() - t0) * 1000),
        },
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_response(p: dict) -> None:
    print("\n" + p.get("answer", ""))
    if p.get("checklist"):
        print("\nChecklist:")
        for item in p["checklist"]:
            print(f"  ☐ {item}")
    if p.get("escalation"):
        print("\nℹ  " + p["escalation"])
    if p.get("citations"):
        print("Sources: " + ", ".join(p["citations"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.app",
                                 description="NalamNest care-coordination assistant")
    ap.add_argument("text",      help="The family member's message")
    ap.add_argument("--patient", default="P-DEMO")
    ap.add_argument("--lang",    choices=["en", "ta"], default="")
    ap.add_argument("--json",    action="store_true")
    a  = ap.parse_args(argv)
    case: dict = {"text": a.text, "patient": a.patient}
    if a.lang:
        case["lang"] = a.lang
    out = run(case)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        _print_response(out["plan"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
