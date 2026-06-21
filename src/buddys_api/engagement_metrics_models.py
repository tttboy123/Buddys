from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from buddys_api.schemas import now_iso


EngagementEventType = Literal[
    "capture_submitted",
    "proposal_confirmed",
    "proposal_corrected",
    "query_answered",
]


class EngagementEvent(BaseModel):
    event_id: str
    user_id: str
    buddy_id: str
    event_type: EngagementEventType
    capture_source: str | None = None
    answer_type: str | None = None
    created_at: str = Field(default_factory=now_iso)


class EngagementMetricsResponse(BaseModel):
    activation: dict[str, bool]
    capture_by_source: dict[str, int]
    query_by_answer_type: dict[str, int]
    event_count: int


class RetentionSummaryResponse(BaseModel):
    d1_active_users: int
    d3_active_users: int
    d7_active_users: int
    activated_users: int
    capture_by_source: dict[str, int]
