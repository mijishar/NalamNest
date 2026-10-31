# NalamNest

A Tamil/English AI care-coordination assistant for families caring for elderly relatives.

Built with [Strands Agents SDK](https://strandsagents.com) on Amazon Bedrock for the
**AWS Builder Center "Strands SDK: Workshop to Ship" Hackathon** (28 Oct – 4 Nov 2026).

> **ALL DATA IS SYNTHETIC.** No real patient information is used anywhere in this project.

---

## What it does

NalamNest helps caregiving families:
- Prepare doctor-visit checklists (with appointment details, documents to bring, follow-up items)
- Summarise health documents (discharge summaries, lab reports)
- Create and track care tasks (collect reports, arrange transport)
- Set reminders for appointments
- Answer care coordination questions in Tamil or English

**What it never does:**
- Diagnose illnesses
- Recommend starting, stopping, or changing medications or doses
- Answer questions about specific drugs or dosages
- Write any response for medical or emergency queries — code hands those off immediately

---

## Architecture

```
User message (Tamil / English / mixed)
        │
        ▼
[hook] SafetyGate ── TRIP ──────────────────► fixed handoff text (doctor / 108)
        │ clear                                (model never called for these)
        ▼
[sessions] Load FamilyContext (FileSessionManager)
        │
        ▼
[graph] Planner ──► Critic ──► (REVISE?) ──► Planner (max 2 passes, fail-closed)
        │  tools: lookup_care_data
        │          summarise_document
        │          propose_task          ◄── [interventions] ConfirmGate
        │          propose_reminder      ◄── interactive yes/no before any write
        ▼
[sessions] Save updated FamilyContext
        ▼
Structured CareResponse (language, answer, checklist, tasks, reminders, citations)
```

### Strands blocks used

| Block | Job |
|---|---|
| `hooks` | Safety gate — cancels all agents on medical/emergency phrases; returns fixed text |
| `tools` | 4 `@tool` functions + Pydantic `CareResponse` structured output |
| `graph` | Planner → critic quality loop, fail-closed after 2 retries |
| `sessions` | `FileSessionManager` — family context persists across conversations |
| `interventions` | `ConfirmGate` — interactive yes/no before any task or reminder is saved |

### AWS services

| Service | Job |
|---|---|
| Amazon Bedrock (Nova 2 Lite) | All model calls — planner, critic, baseline, evals judge |
| Amazon Translate | Tamil ↔ English fallback when the model outputs in the wrong language |

---

## Setup

**Requirements:** Python 3.10–3.13, git, AWS account with Amazon Bedrock (Amazon Nova enabled, us-east-1).

```bash
# 1. Install the strands-ship power (Windows)
python "%USERPROFILE%\.kiro\powers\installed\strands-ship\skills\ship-setup\scripts\ship_windows.py" setup

# 2. Install project dependencies
pip install -r requirements.txt

# 3. Configure AWS credentials
aws configure
# or
aws sso login

# 4. Verify Bedrock access
"%USERPROFILE%\.strands-ship\bin\ss.cmd" bedrock
```

---

## Running the agent

```bash
# Ask a question (English)
python -m agent.app "Prepare a checklist for Appa's cardiology appointment on November 15"

# Ask in Tamil
python -m agent.app "கார்டியாலஜி appointment-க்கு என்ன கொண்டு போக வேண்டும்?"

# Create a task (will ask for confirmation)
python -m agent.app "Create a task to collect the ECG report from Apollo" --patient P-DEMO

# Safety gate test (no Bedrock call made)
python -m agent.app "Can I double the dose tonight?"
```

---

## Evaluation

```bash
# Check cases are ready
"%USERPROFILE%\.strands-ship\bin\ss.cmd" cases check

# Sign off cases (read every label first)
"%USERPROFILE%\.strands-ship\bin\ss.cmd" cases show
"%USERPROFILE%\.strands-ship\bin\ss.cmd" cases approve --by "Your Full Name"

# Quick test (6 cases, ~1 min)
"%USERPROFILE%\.strands-ship\bin\ss.cmd" measure --limit 6

# Full evaluation (30 cases, ~5-8 min)
"%USERPROFILE%\.strands-ship\bin\ss.cmd" measure
```

### Measurement gate (from hackathon council)
| Metric | NalamNest | Single-prompt baseline |
|---|---|---|
| Safety triggers correctly handled | 100% | 100% |
| Plans with unsafe advice | 0 | 0 |
| Required information present | 100% | 60% |
| Citation faithfulness | 100% | 90% |
| Plan completeness, right language | 98% | 67% |
| Goal success (Strands Evals judge, 0–1) | 0.967 | 0.667 |

30 human-labelled cases · 12 emergency · 13 Tamil · 3 job types · model: `us.amazon.nova-2-lite-v1:0`
Measured 2026-10-30. Gate: PASSED (11/11 checks).
All data is synthetic. Numbers show agent behaviour on labelled scenarios, not real-world outcomes.

---

## Project structure

```
D:\NalamNest\
  agent/
    app.py            main pipeline (safety → sessions → graph → enforce)
    safety.py         SafetyGate hook + all hardcoded safety phrases and handoff text
    tools.py          @tool functions + commit helpers
    interventions.py  ConfirmGate — interactive confirmation before writes
    plan.py           CareResponse + Critique Pydantic models
    score.py          deterministic scorer for ss measure
    baseline.py       one-prompt baseline agent (what NalamNest must beat)
    data/
      care_data.json  synthetic demo data (appointments, documents, tasks, guidance)
      sessions/       per-patient session files (git-ignored)
  cases.jsonl         30 human-labelled evaluation cases
  IDEA.md             project idea and rubric scores
  DESIGN.md           architecture and block choices
  FAILURES.md         log of failures found and fixed
  results/            written by ss measure and ss video (git-ignored except MEASURE.md)
  .kiro/
    hooks/            Kiro agent hooks (cases check, safety code change reminders)
    steering/         hackathon rules and method guide
```

---

## Limits (stated plainly)

- All data is synthetic. Results show what the agent does on labelled demo scenarios, not real-world caregiving outcomes.
- Tamil text from the model may be inaccurate. Safety text (handoff messages, 108 reference) is hardcoded and must be reviewed by a Tamil-fluent person before any real use.
- The safety phrase list is keyword-based. Indirect phrasing may not be caught — add every miss found during `ss measure` to `agent/safety.py`.
- No field deployment or consent study was conducted within the hackathon window.

---

## Licence

Apache-2.0. Built on the [strands-ship power](https://github.com/logesh4v/strands-ship) by Logesh (AWS User Group Madurai).
