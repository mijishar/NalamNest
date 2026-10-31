"""NalamNest ConfirmGate — interactive confirmation before any write operation.

The agent proposes a task or reminder via propose_task / propose_reminder tools.
This handler intercepts those tool calls, prints the proposal, and asks the user
for an explicit yes/no. Nothing is written without confirmation.

Interactive mode (default — normal use):
  Runs when stdin is a TTY (terminal). Prints the proposal and waits for the
  user to type yes/no. Nothing is saved without an explicit yes.

Non-interactive / batch mode (automatic — ss measure, pipes, threads):
  Detected via sys.stdin.isatty(). When stdin is not a TTY, the gate records
  the proposal as PENDING and denies the write. The agent reports what it
  *would* create. score.py evaluates whether the right proposal was made.
  No bypass of confirmation logic — the write simply does not happen.

Test mode (NALAMNES_TEST_MODE=1):
  For automated evaluation where a specific yes/no answer must be simulated
  per case. Reads the expected answer from test_confirm_response. This is
  the only mode that can produce a confirmed write in a non-interactive run.
  Never set to 1 outside of explicit test infrastructure.
"""
from __future__ import annotations

import os
import sys

from strands.interventions import Deny, InterventionHandler, Proceed

from . import tools as _tools

# Tool names that require confirmation before execution
WRITE_TOOLS = {"propose_task", "propose_reminder"}

# Confirmation words accepted in English and Tamil
YES_WORDS = {"yes", "y", "confirm", "ok", "okay", "sure", "ஆம்", "சரி", "உறுதி"}
NO_WORDS  = {"no", "n", "cancel", "stop", "reject", "வேண்டாம்", "இல்லை", "ரத்து"}


def _is_interactive() -> bool:
    """True only when running in a real terminal where a human can type.

    Returns False when:
    - NALAMNES_BATCH=1 is set (ss measure sets this)
    - NALAMNES_TEST_MODE=1 is set (test mode handles confirmation itself)
    - stdin is not a TTY
    """
    if os.environ.get("NALAMNES_BATCH", "0") == "1":
        return False
    if os.environ.get("NALAMNES_TEST_MODE", "0") == "1":
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _is_test_mode() -> bool:
    return os.environ.get("NALAMNES_TEST_MODE", "0") == "1"


class ConfirmGate(InterventionHandler):
    """Intercepts propose_task and propose_reminder; asks the family to confirm.

    Behaviour by context:
    - Interactive (TTY):   prints proposal, waits for yes/no, commits on yes.
    - Non-interactive:     prints proposal as PENDING, denies write, no stdin read.
    - Test mode:           uses test_confirm_response to simulate user answer.

    Attributes:
        confirmed: list of writes that were approved and committed.
        denied:    list of writes that were rejected by the user.
        pending:   list of writes that were proposed but not acted on
                   (non-interactive batch runs).
    """

    name = "nalamnes-confirm-gate"

    def __init__(self, test_confirm_response: str = "") -> None:
        self._test_response = test_confirm_response
        self.confirmed: list[dict] = []
        self.denied:    list[dict] = []
        self.pending:   list[dict] = []

    def before_tool_call(self, event):  # type: ignore[override]
        tool_name = event.tool_use.get("name", "")
        if tool_name not in WRITE_TOOLS:
            return Proceed()

        args     = event.tool_use.get("input", {})
        proposal = _format_proposal(tool_name, args)
        label    = _action_label(tool_name)

        print(f"\n[confirm] proposed: {proposal}", flush=True)

        # ── Test mode ────────────────────────────────────────────────────────
        if _is_test_mode() and self._test_response:
            answer = self._test_response.strip().lower()
            print(f"[confirm] test-mode response: {answer!r}", flush=True)
            return self._resolve(answer, tool_name, label, args)

        # ── Non-interactive (ss measure, threads, pipes) ──────────────────────
        if not _is_interactive():
            self.pending.append({"tool": tool_name, "args": args})
            print(f"[confirm] non-interactive — {label} proposed, not saved (no terminal)", flush=True)
            return Deny(
                reason=(
                    f"The {label} has been proposed but not confirmed because no terminal "
                    f"is available. Tell the family exactly what would be created: {proposal}. "
                    f"Ask them to confirm when they are ready."
                )
            )

        # ── Interactive (normal use) ──────────────────────────────────────────
        print(
            f"  → Type 'yes' / 'ஆம்' to confirm, or 'no' / 'வேண்டாம்' to cancel: ",
            end="", flush=True,
        )
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "no"

        return self._resolve(answer, tool_name, label, args)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve(self, answer: str, tool_name: str, label: str, args: dict) -> Deny:
        if answer in YES_WORDS:
            saved = _commit(tool_name, args)
            self.confirmed.append({"tool": tool_name, "args": args, "saved": saved})
            print(f"[confirm] approved — saved: {saved}", flush=True)
            return Deny(
                reason=(
                    f"Confirmed and saved by family. Result: {saved}. "
                    f"Tell the family the {label} was saved successfully."
                )
            )
        else:
            self.denied.append({"tool": tool_name, "args": args})
            print("[confirm] denied — nothing saved", flush=True)
            return Deny(
                reason=(
                    f"The family said no. The {label} was NOT saved. "
                    f"Acknowledge this clearly and do not retry."
                )
            )


def _action_label(tool_name: str) -> str:
    return {"propose_task": "task", "propose_reminder": "reminder"}.get(tool_name, "action")


def _format_proposal(tool_name: str, args: dict) -> str:
    if tool_name == "propose_task":
        parts = [f"Task: {args.get('description', '?')}"]
        if args.get("due_date"):
            parts.append(f"due {args['due_date']}")
        if args.get("assigned_to"):
            parts.append(f"assigned to {args['assigned_to']}")
        return " | ".join(parts)
    if tool_name == "propose_reminder":
        parts = [f"Reminder: {args.get('text', '?')}"]
        if args.get("datetime_iso"):
            parts.append(f"at {args['datetime_iso']}")
        return " | ".join(parts)
    return str(args)


def _commit(tool_name: str, args: dict) -> dict:
    if tool_name == "propose_task":
        return _tools.commit_task(
            description=args.get("description", ""),
            due_date=args.get("due_date", ""),
            assigned_to=args.get("assigned_to", ""),
        )
    if tool_name == "propose_reminder":
        return _tools.commit_reminder(
            text=args.get("text", ""),
            datetime_iso=args.get("datetime_iso", ""),
            patient=args.get("patient", "P-DEMO"),
        )
    return {}
