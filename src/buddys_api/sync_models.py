from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from buddys_api.schemas import now_iso


SyncVisibility = Literal["legacy", "auth"]


class SyncEvent(BaseModel):
    revision: int
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor_user_id: str | None = None
    visibility: SyncVisibility
    payload_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


class SyncEventsResponse(BaseModel):
    state_revision: int
    events: list[SyncEvent]


class SyncSnapshot(BaseModel):
    state_revision: int
    buddies: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    agent_machines: list[dict[str, Any]]
    bindings: list[dict[str, Any]]
    latest_heartbeats: dict[str, dict[str, Any]]
    desired_states: dict[str, dict[str, Any]]
    device_events: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    cost_summary: dict[str, Any]
    plan_usage: dict[str, Any] = Field(default_factory=dict)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    state_memory: dict[str, Any] = Field(default_factory=dict)
