# Method: how a Workshop-to-Ship agent is built

The workshop ends at multi-agent swarms. Judges score originality as "how far the project extends beyond the lessons", so a strong entry adds, on top of whatever Strands blocks it uses:

1. **Code owns the facts that must never be wrong.** Thresholds, amounts, emergency numbers and safety text live in plain Python (a `@tool`, a hook, or Strands Decider above a calibrated threshold). The model reads them and cannot change them; code puts them back if it tries.
2. **A hard stop when someone is in danger.** A Strands hook or intervention stops the agents and sends fixed text. No model writes that answer.
3. **A check the model cannot skip.** A critic in a graph, an intervention, or Decider, with a fail-closed fallback.
4. **Measured against a baseline on human-labelled cases.** `ss measure` runs the agent and a one-prompt agent on the same signed cases and blocks submission unless the agent is safe on every case and better than the baseline.

The worked example `kit/examples/heatsafe` does all four. `ss blocks` lists the 14 runnable Strands blocks; the ship-design skill's catalogue says when each one earns its place.

## Rules for the builder (and for Kiro)
- The idea is the builder's own (IDEA.md); the design names its blocks and what each does (DESIGN.md).
- Report only numbers in `results/MEASURE.md` / `results/FACTS.md`. Never type a number into the article or video by hand.
- Never edit `results/` by hand. Never sign off cases for someone else: `ss cases approve --by` takes the reviewer's real name.
- After any change to safety code or `agent/data/`, re-run `ss measure`.
- Every source needs a URL and the date someone read it. Every place (clinic, shelter, water point) needs a person who checked it and a date.
- Never paste AWS keys or the Decider key into chat or files. Credentials come from `aws configure` / `aws sso login` / environment variables in your own terminal.
- Keep the repo private until 28 Oct 2026; the agent must not be published before the window.
- When a case fails, log it in `FAILURES.md` (what broke, how you found it, what you changed, the re-measured number).
