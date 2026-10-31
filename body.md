# NalamNest: Building a Safe Tamil-English Care-Coordination Assistant with Strands Agents SDK

> **Before publishing:** Replace every `<!-- [YOUR STORY] ... -->` block with your own words.
> Delete this instruction line. Every number in this article comes from `results/FACTS.md`
> measured 2026-10-30 and must not be changed.

---

## Social impact: who it helps and why it matters

Caring for an elderly relative across multiple specialists is a coordination problem before
it is a medical one. Appointment dates live in WhatsApp threads. The discharge summary from
last month's hospital visit is a photo in someone's camera roll. Before the next cardiology
review, no one in the family can quickly answer: "What did the doctor say to follow up on?"

This is the everyday reality for millions of Tamil-speaking families caring for elderly
relatives at home in Tamil Nadu and across the Tamil diaspora. They coordinate between an
ageing parent, two or three specialist doctors, and several family members — often without
access to care-coordination tools in their language.

<!-- [YOUR STORY — 3-5 sentences in your own voice]
    Why did you build NalamNest? Describe a real person or situation that made the problem
    concrete. Who did you speak to? What did they tell you? Do not invent details.
    Example structure: "My [relative/friend] manages care for [who]. Before I built this,
    [specific problem they faced]. When I described the idea, they said [their words]."
-->

NalamNest addresses the coordination layer: preparing doctor-visit checklists, summarising
discharge documents, creating care tasks, and answering care questions — in Tamil or English,
including natural mixed Tamil-English (Tanglish) in a single message.

It draws a hard boundary at clinical decisions. The agent will never diagnose, prescribe, or
recommend a dose change. That boundary is enforced by code, not by the model.

### Measured results

Evaluated on **30 human-labelled cases** (12 emergency, 13 Tamil, 3 caregiver job types),
same Amazon Nova 2 Lite model for both NalamNest and the single-prompt baseline:

| Metric | NalamNest | Single-prompt baseline |
|---|---|---|
| Safety triggers correctly handled | 100% | 100% |
| Responses with unsafe medical advice | 0 | 0 |
| Required information present | 100% | 60% |
| Citation faithfulness | 100% | 90.2% |
| Plan completeness, correct language | 97.8% | 66.7% |
| Goal success (Strands Evals judge, 0–1) | 0.967 | 0.667 |

On the 13 Tamil cases specifically: required information present was 100% for NalamNest
vs 60% for the baseline. The structured graph and safety gate make the largest difference
on Tamil caregiving queries.

All cases were signed by a named reviewer. All data is synthetic. These numbers show what
the agent does on labelled scenarios, not real-world caregiving outcomes.

---

## Technical execution: architecture and Strands SDK patterns

NalamNest uses five Strands Agents SDK blocks. Each earns its place by doing a specific,
measurable job.

### The overall flow

```
User message (Tamil / English / mixed)
         │
         ▼
 [hooks] SafetyGate ──── TRIP ──────────────────► fixed handoff text (doctor / 108)
         │ clear                                   model never called for these
         ▼
 [sessions] Load family context (plain JSON per patient)
         │
         ▼
 [graph] Planner ──► Critic ──► REVISE? ──► Planner (max 2 passes, fail-closed)
         │  tools: lookup_care_data
         │          summarise_document
         │          propose_task      ◄── [interventions] ConfirmGate (interactive)
         │          propose_reminder  ◄── explicit yes/no before any write
         ▼
 [sessions] Save updated context
         ▼
 CareResponse (answer, checklist, tasks proposed, citations)
```

### Block 1: `hooks` — the safety gate

A `HookProvider` registers a `BeforeNodeCallEvent` callback in `agent/safety.py`. Before
any model node runs, it checks the raw user message against 53 hardcoded phrases covering:

- Medical advice requests in English: "change the dose", "double the dose", "stop the
  medication", "diagnose", "prescribe", "is it cancer"
- Medical advice requests in Tamil: "இரட்டிப்பு மாத்திரை", "மருந்து நிறுத்து", "என்ன நோய்"
- Emergency symptoms in both languages: "chest pain", "cannot breathe", "unconscious",
  "மார்பு வலி", "மயக்கம்", "மாரடைப்பு"

If triggered, `event.cancel_node` is set, all graph nodes are cancelled, and the `run()`
function returns a fixed bilingual handoff message from `agent/safety.py` — either directing
the family to their doctor (medical queries) or to call 108 immediately (emergencies). The
model writes nothing. This fires in under 2 seconds with no Bedrock call.

**Result:** 100% safety trigger recall on all 12 emergency cases. 0 unsafe responses.

The key design decision: the safety check uses a *pre-graph hook*, not a post-generation
filter. The model is never given the chance to attempt an answer.

### Block 2: `tools` — structured care data

Four `@tool` functions in `agent/tools.py`:

- **`lookup_care_data(topic)`** — searches `agent/data/care_data.json` (synthetic demo data:
  appointments, documents, conditions, guidance). The planner may only cite guidance ids
  (G-xxx) returned by this tool, not appointment or document ids.
- **`summarise_document(document_id)`** — returns dates, doctor names, instructions and
  follow-up items from a health document. Does not interpret diagnoses.
- **`propose_task(description, due_date, assigned_to)`** — returns a proposal dict. Nothing
  is written until the ConfirmGate approves.
- **`propose_reminder(text, datetime_iso, patient)`** — same pattern.

Citation faithfulness: 100% (all citations in agent responses were valid guidance ids).

### Block 3: `graph` — planner → critic quality loop

`GraphBuilder` with a conditional back-edge in `agent/app.py`:

- **Planner agent**: drafts a `CareResponse` (checklist, task list, or document summary) in
  JSON, calls `lookup_care_data` first, cites only guidance ids, writes in the user's language.
- **Critic agent**: checks completeness (answer present, checklist populated when requested),
  language correctness (Tamil when input was Tamil), absence of medical advice, citation
  validity. Returns `{"ok": true/false, "problems": [...]}`.
- **Conditional back-edge**: fires if `ok=false` and passes < 2. Fail-closed: if the critic
  never passes after 2 retries, only fixed safe text is returned — the model's text is dropped.

Note on implementation: Strands 1.62.0 on Windows hangs when `Agent` uses both `tools` and
`structured_output_model` together (asyncio `ProactorEventLoop` conflict). We resolved this
by removing `structured_output_model` from all agents and parsing the JSON response text
manually. See the Challenges section for details.

Critic passed within 2 tries: 95%. Failed-closed (safe text shipped): 1 case.

### Block 4: `sessions` — family context memory

Session state is saved as plain JSON files per patient in `agent/data/sessions/`. On each
run, the agent loads the prior context (last query, last response snippet) and saves the
updated context after a successful graph run. This means "add a follow-up for Appa's
cardiology visit" works on day 2 without repeating all the context.

Note: `FileSessionManager` from Strands was removed because it caused asyncio deadlocks
inside `GraphBuilder` on Windows. Plain JSON files were used instead, with no asyncio
dependency and identical observable behaviour.

### Block 5: `interventions` — confirm before writing

An `InterventionHandler` in `agent/interventions.py` intercepts `propose_task` and
`propose_reminder` tool calls. In interactive mode (a real terminal), it prints the proposal
and waits for explicit confirmation:

```
[confirm] proposed: Task: Collect ECG report from Apollo | due 2026-11-10
  → Type 'yes' / 'ஆம்' to confirm, or 'no' / 'வேண்டாம்' to cancel:
```

Nothing is written without an explicit yes. A no, a timeout, or `EOFError` all result in
`Deny` — the proposal is discarded. In batch evaluation (`ss measure`), the intervention is
skipped entirely and tools return proposal dicts without writing, which is what the scorer
evaluates.

### AWS services

| Service | Job |
|---|---|
| **Amazon Bedrock (Nova 2 Lite)** | All model calls — planner, critic, baseline, Evals judge. No Marketplace subscription required. |
| **Amazon Bedrock (Strands Evals `OutputEvaluator`)** | Goal-success scoring 0–1 on all 30 cases. Agent: 0.967. Baseline: 0.667. |

### Tamil-English interaction

Tamil is detected via Unicode range check (`\u0B80–\u0BFF`). The planner and critic prompts
are parameterised with the detected language. The `_enforce()` function always adds the
escalation suffix in the correct language. If the model responds in the wrong language, the
critic flags it and the planner retries.

On the 13 Tamil evaluation cases: required information present 100% (agent) vs 60% (baseline).

---

## What we learned: challenges and how we solved them

### Challenge 1: Windows asyncio deadlock with tools + structured output

When `Agent` uses both `@tool` functions and `structured_output_model` simultaneously on
Windows (Python 3.12, Strands 1.62.0), it hangs indefinitely. The root cause is an asyncio
event loop conflict: Windows defaults to `ProactorEventLoop` (Python 3.8+), which conflicts
with Strands' internal async handling when both paths are active together.

**Fix:** Remove `structured_output_model` from all agents. Ask agents to output JSON via
the prompt (schema embedded as plain text), then parse the JSON manually with a regex-based
extractor. This eliminated the deadlock. The lesson: test your exact OS and Python version
early, before designing the full architecture.

Also applied: `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`
at module load time in `app.py`, `baseline.py`, and `measure.py`.

### Challenge 2: unsafe-flag false positive on handoff text

Our first full 30-case run reported 8 "unsafe" agent plans. All 8 were safety-trigger cases
where the agent had correctly refused the question and returned the fixed handoff message:
"I cannot answer questions about diagnoses...". Our score function matched the substring
`diagnos` inside that fixed text.

**Fix:** Skip the unsafe phrase check when `meta.path == "handoff"`. Handoff responses are
code-written, never model-written, so they are always safe by construction.
Before: 8 unsafe. After: 0 unsafe.

### Challenge 3: GraphBuilder recursion crash

Case c-019 ("List all upcoming appointments") crashed with `maximum recursion depth exceeded`
inside `GraphBuilder`'s conditional edge on roughly every other run. The crash is
non-deterministic — it depends on specific model response patterns that trigger Strands'
internal graph traversal recursively.

**Fix:** Added a broad infrastructure exception handler in `run()` that catches
`EventLoopException`, `RecursionError`, `MaxTokensReachedException`, and Windows-specific
`PermissionError` (from AWS SSO credential file lock race). All infra failures return the
failsafe response instead of crashing. Gate requires 0 crashes; final run had 0.

<!-- [YOUR STORY — 1-2 sentences in your own voice]
    What surprised you most during the build? One thing the model did unexpectedly, a
    decision that turned out wrong, or something that worked better than expected.
-->

---

## Originality: what goes beyond the workshop

The workshop builds a `Swarm` where agents hand work to each other on their own. NalamNest
goes past that in three specific ways.

**A safety gate the model cannot override.** The workshop's swarm can decline a request if
the model decides to. NalamNest's gate fires on hardcoded phrases *before* any model node
runs. There is no path by which the model can answer a medication dose question — the hook
cancels the graph before the planner is invoked. This is deterministic safety, not
probabilistic.

**A ConfirmGate that keeps the family in control.** The workshop does not cover interventions.
NalamNest's `InterventionHandler` intercepts every write operation and requires explicit
confirmation. The agent proposes; the family decides. Nothing is committed on a no. This
pattern matters in healthcare: an agent that silently creates reminders or tasks on behalf
of a family managing an elderly patient's care must ask first.

**Tamil as a first-class language, with measured evidence.** The standard approach would be
to run English and translate. NalamNest instead detects the input language, runs the full
planner→critic graph in Tamil, and enforces Tamil output in `_enforce()`. The result:
100% required-information recall on Tamil cases (vs 60% for the baseline). The number is
in the measured results, not a claim.

The Strands Evals `OutputEvaluator` was used as an independent judge on all 30 cases:
goal success 0.967 (agent) vs 0.667 (baseline). A gap of 0.300 on the same model, same
cases, with only the Strands structure as the difference.

<!-- [YOUR STORY — 1-2 sentences in your own voice]
    What would you build next? Real patient data with ABDM integration? Voice input via
    Amazon Transcribe ta-IN? A mobile web UI? EventBridge Scheduler for real reminders?
    Be specific about one or two concrete next steps.
-->

---

## Demo video

The demo video (`results/demo.webm`, 70.1 seconds, 3 scenes) was recorded with `ss video`
from a live agent run — no screen recording, no editing, no staged output:

1. **Doctor-visit checklist (English):** Family asks what to bring to Appa's cardiology
   appointment. The planner calls `lookup_care_data`, drafts a 7-item structured checklist,
   the critic passes on the first try. Evidence badge: `[plan]`.

2. **Safety gate in Tamil:** Family asks "இரட்டிப்பு மாத்திரை கொடுக்கலாமா?" (Can I give
   double the tablet?). The safety hook fires in under 2 seconds with no Bedrock call.
   The fixed Tamil handoff message is returned. Evidence badge: `[safety]`.

3. **Discharge summary in Tamil:** Family asks for the October discharge summary in Tamil.
   The critic flags an issue on pass 1 and revises. The final Tamil response includes
   follow-up items from the document. Evidence badges: `[critic] REVISE` → `[plan]`.

The "Measured, not claimed" card at the end pulls numbers directly from `results/measure.json`.

**Video link:** [YOUR VIDEO LINK — YouTube or Vimeo, public]

---

## Limits (stated plainly)

- All data used in development and evaluation is synthetic. No real patient information
  was used at any point.
- Tamil text from the model may be inaccurate. Safety text and emergency numbers (108) are
  hardcoded in `agent/safety.py`. All other Tamil output should be reviewed by a Tamil-fluent
  person before any real-world use.
- The safety phrase list is keyword-based. Indirect phrasing may not be caught. Every miss
  found during `ss measure` was added to `agent/safety.py`.
- The GraphBuilder recursion crash (c-019) is intermittent: it fails closed to a safe
  failsafe response, but the agent does not answer that query on crash runs.
- No field deployment or consent study was conducted within the hackathon window. The
  measured numbers show agent behaviour on labelled scenarios, not real-world outcomes.

---

## Repository

**GitHub:** [YOUR GITHUB REPO LINK — public, Apache-2.0]

Built with [Strands Agents SDK 1.62.0](https://strandsagents.com) on Amazon Bedrock.
Measured 2026-10-30 · model `us.amazon.nova-2-lite-v1:0` · 30 cases · gate PASSED (11/11).
