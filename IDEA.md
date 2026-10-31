# IDEA: NalamNest

## One-line pitch
A Tamil-English AI care-coordination assistant that helps families caring for elderly relatives
organise appointments, prepare doctor-visit checklists, track follow-ups, create care tasks,
and summarise health documents — without ever diagnosing, prescribing, or changing doses.

## Focus area
Health

## Who it helps
Families caring for elderly relatives at home. Initial validation with people reachable in our
local community (Tamil Nadu / Tamil-speaking households). The primary user is a family caregiver
(adult child, spouse, or sibling) who coordinates between the elderly person, multiple doctors,
and other family members. They may speak Tamil, English, or mix both in the same message.

## The story (unverified assumption — needs confirmation from real users)
A family member manages their parent's care across three specialists. Appointment dates live in
a WhatsApp thread; medication reminders are sticky notes; the discharge summary from the last
hospital visit is a photo in someone's camera roll. Before the next appointment, no one can
quickly answer: "What did the cardiologist say to follow up on last time?" This assistant
organises that information and produces a one-page doctor-visit checklist before each appointment.

*This story is a plausible composite. It has not been verified by interviews. Treat all
impact claims as assumptions until confirmed by at least five real caregiving families.*

## The decision that must never be wrong
**The safety filter.** The agent must never suggest a diagnosis, recommend starting or stopping
a medication, suggest changing a dose, or interpret a symptom as a specific condition.
Code owns this check — not the model. A hard-coded list of trigger phrases (dose, diagnose,
prescribe, medication change, is it cancer, should I stop, etc.) fires a Strands hook that
cancels the agent and returns a fixed, sourced handoff message directing the family to their
doctor or, for emergencies, to call 108.

## What will be measured
*Unverified assumptions are marked [A].*

| Metric | How measured |
|---|---|
| Safety filter recall | % of safety-trigger cases correctly blocked (target: 100%) |
| Safety filter precision | % of blocked cases that were genuine safety triggers (target: ≥ 95%) |
| Checklist completeness | % of doctor-visit checklist items present and correctly attributed (target: ≥ 90%) |
| Language correctness | Tamil output rendered correctly, not transliteration boxes [A: needs a Tamil reader to verify] |
| Goal success (Strands Evals judge) | Above baseline one-prompt agent |
| Baseline comparison | Agent vs. a single-prompt agent on the same signed cases |

The gate from the hackathon council: 30+ signed cases, 8+ safety-trigger cases, 10+ Tamil cases,
3+ task types (appointment, checklist, document summary), 100% safety-trigger recall,
0 unsafe answers, goal success above baseline, every case signed by a named person.

[A] = unverified assumption. Do not report these as facts in the article or video.

## Languages
Tamil (ta) and English (en), including natural mixed Tamil-English (Tanglish) in a single message.
Fixed safety text (handoff messages, emergency numbers) is hardcoded in both languages and
reviewed by a Tamil-fluent person before submission.

## Scores (honest, pre-build)
| Quarter | Score | Why |
|---|---|---|
| Social impact | 7/10 | Real problem; impact unverified — no field interviews yet |
| Technical execution | 7/10 | Good block fit; web UI is scope risk, keep CLI for submission |
| Communication | 8/10 | Relatable, easy to demo with a checklist output |
| Originality | 6/10 | Not on the examples page; needs a sharp safety gate to lift score |
| Buildable in days left | 7/10 | Agent core feasible; web UI deferred to stretch |

## Argument against (judge's voice)
- "Is the impact measurable in a week? You have no field users yet — this is a plausible story,
  not evidence." → Mitigated by: signed labelled cases from community members, honest [A] markers.
- "Would a plain prompt do as well?" → No, because: the safety filter is hard-coded (the model
  cannot override it), the critic catches incomplete checklists, and sessions remember prior visits.
- "Care coordination tools already exist (Carely, CareZone)." → NalamNest's originality is Tamil
  support, the Strands block composition, and the measured safety gate — not the category.
- "Who could be harmed?" → A family acts on a response that looks like medical advice. Mitigated
  by the hard-stop safety filter and the explicit "I am not a doctor" framing in every answer.

## What is steelmanned
If the safety filter holds on every signed case, and the checklist completeness beats the baseline,
the agent demonstrates a measurable, safety-verified improvement for a real underserved use case
(Tamil-speaking caregiving families who lack access to care-coordination tools in their language).

## What is out of scope this week
- Real appointment calendar integration (Google Calendar, iCal)
- Real health record upload (FHIR, ABDM)
- Web or mobile UI (build CLI/API first; web is a stretch goal)
- Voice interface (Amazon Transcribe ta-IN works for input; Nova Sonic has no Tamil output)
- Multi-family / multi-patient accounts
- Real medication database (use a small curated set of common medications with safety notes)

## Not this week (but worth logging)
- Verified field interviews with caregiving families
- A consented pilot with real families using real data
- ABDM / Ayushman Bharat health record integration
- Pharmacy reminders via SMS

## Next step
Say **"design my agent"** to pick the Strands blocks and write DESIGN.md.
