"""NalamNest structured output models. Every field is scorable by agent/score.py."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TaskItem(BaseModel):
    description: str = Field(description="What needs to be done")
    due_date: str = Field(default="", description="ISO date YYYY-MM-DD or empty")
    assigned_to: str = Field(default="", description="Family member responsible, or empty")


class ReminderItem(BaseModel):
    text: str = Field(description="The reminder message")
    datetime_iso: str = Field(default="", description="ISO datetime or empty")
    patient: str = Field(default="P-DEMO", description="Patient id")


class CareResponse(BaseModel):
    language: Literal["en", "ta"] = Field(description="Language of this response")
    answer: str = Field(description="Direct answer to the family's question, in their language")
    checklist: list[str] = Field(
        default_factory=list,
        description="Ordered checklist items (for doctor-visit prep, document summaries, etc.)"
    )
    tasks_proposed: list[TaskItem] = Field(
        default_factory=list,
        description="Care tasks proposed (awaiting confirmation before saving)"
    )
    reminders_proposed: list[ReminderItem] = Field(
        default_factory=list,
        description="Reminders proposed (awaiting confirmation before saving)"
    )
    escalation: str = Field(
        default="",
        description="When and who to contact for medical questions; always populated"
    )
    citations: list[str] = Field(
        default_factory=list,
        description="Guidance ids from lookup_care_data only"
    )


class Critique(BaseModel):
    ok: bool
    problems: list[str] = Field(default_factory=list)
