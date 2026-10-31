"""NalamNest baseline — one Agent, one prompt, same model, NO Strands blocks.

No safety hook, no graph, no sessions, no interventions, no structured_output_model.
(structured_output_model + tools hangs on Windows in Strands 1.62.0.)
Parses JSON from plain agent response text.

This is what NalamNest must beat. Do not improve the baseline.
Its failures are the story for the article.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import time
from pathlib import Path

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from strands import Agent
from strands.models import BedrockModel

from . import tools
from .app import CARE_RESPONSE_SCHEMA, _parse_json, _to_care_response
from .plan import CareResponse

MODEL_ID = os.environ.get("SHIP_MODEL", "us.amazon.nova-2-lite-v1:0")
REGION   = os.environ.get("AWS_REGION", "us-east-1")
DATA_PATH = Path(__file__).parent / "data" / "care_data.json"
logging.getLogger("strands").setLevel(logging.CRITICAL)


def _care_data_snippet() -> str:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    lines = []
    for a in data.get("appointments", [])[:3]:
        lines.append(f"Appointment {a['id']}: {a['doctor']} ({a['specialty']}) "
                     f"on {a['date']} at {a['time']}. Notes: {a['notes']}")
    for d in data.get("documents", [])[:2]:
        lines.append(f"Document {d['id']}: {d['type']} from {d['date']} by "
                     f"{d['doctor']}. {d['summary']}")
    for g in data.get("guidance", []):
        lines.append(f"Guidance {g['id']}: {g['text']}")
    return "\n".join(lines)


BASELINE_PROMPT_TEMPLATE = """You are a care-coordination assistant for families caring for elderly relatives.
Answer the family's question using the information below.
Do not diagnose or prescribe. For emergencies mention calling 108.
Answer in the user's language (en=English, ta=Tamil).

Care information:
{care_data}

"""


def run(case: dict) -> dict:
    t0   = time.time()
    lang = case.get("lang") or tools.language_of(case["text"])

    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0.2),
        system_prompt=BASELINE_PROMPT_TEMPLATE.format(care_data=_care_data_snippet()) + CARE_RESPONSE_SCHEMA,
        # NO tools, NO structured_output_model (Windows compatibility)
        callback_handler=None,
    )

    try:
        result = agent(f"Family member ({lang}): {case['text']}")
        d      = _parse_json(str(result).strip())
        resp   = _to_care_response(d, lang)
        if not resp.answer:
            resp.answer = str(result).strip()[:500]
    except Exception as exc:
        resp = CareResponse(
            language=lang,
            answer=f"[baseline error: {exc}]",
            escalation="Please consult your doctor.",
        )

    meta = {"path": "baseline", "latency_ms": int((time.time() - t0) * 1000),
            "confirmed": [], "denied": [], "pending": [], "critic_ok": None}
    return {"plan": resp.model_dump(), "meta": meta}
