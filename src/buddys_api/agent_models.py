from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from buddys_api.schemas import now_iso


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

AgentRole = Literal["runtime", "hardware_simulator", "cost_agent", "verifier", "doc_progress", "adapter"]
AgentStatus = Literal["starting", "online", "degraded", "offline", "error"]


class AgentCreateRequest(BaseModel):
    name: NonEmptyStr
    role: AgentRole
    status: AgentStatus = "starting"
    version: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", "capabilities")
    @classmethod
    def objects_only(cls, value: dict[str, Any]) -> dict[str, Any]:
        return value


class AgentHeartbeatRequest(BaseModel):
    status: AgentStatus
    version: NonEmptyStr | None = None
    capabilities: dict[str, Any] | None = None

    @field_validator("capabilities")
    @classmethod
    def capabilities_object_only(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return value


class AgentRecord(BaseModel):
    schema_version: Literal["agent.v1"] = "agent.v1"
    agent_id: NonEmptyStr
    user_id: NonEmptyStr
    name: NonEmptyStr
    role: AgentRole
    status: AgentStatus
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    last_seen: str | None = None
