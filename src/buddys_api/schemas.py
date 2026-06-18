from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Buddy(BaseModel):
    buddy_id: str
    user_id: str
    name: str
    space_id: str
    device_id: str | None = None
    autonomy_level: Literal["A", "B", "C"] = "A"
    status: Literal["offline", "idle", "thinking", "asking_confirmation", "executing", "error"] = "idle"
    created_at: str = Field(default_factory=now_iso)


class ChatMessage(BaseModel):
    user_id: str
    text: str
    source: Literal["user_text", "console", "system_test"] = "user_text"


class ActionProposal(BaseModel):
    proposal_id: str
    trace_id: str
    buddy_id: str
    action_type: Literal["reply_only", "tool_call", "memory_proposal", "clarification", "no_action"]
    summary: str
    requires_confirmation: bool
    tool_id: str | None
    action: str | None
    args: dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["none", "low", "medium", "high"] = "none"
    executed: bool = False
    created_at: str = Field(default_factory=now_iso)


class PermissionDecision(BaseModel):
    policy_result: Literal["not_required", "allow", "require_confirmation", "deny"]
    confirmation_result: Literal["not_requested", "approved", "rejected", "expired"]
    decided_by: Literal["policy", "user", "system_test", "operator"]
    reason: str
    policy_version: str = "p0-a-level-v1"


class ToolCall(BaseModel):
    tool_call_id: str
    adapter_id: str
    tool_id: str
    action: str
    args: dict[str, Any]


class ToolResult(BaseModel):
    status: Literal["success", "failure", "skipped"]
    output_summary: str
    error_code: str | None = None
    latency_ms: int | None = None


class Intent(BaseModel):
    name: str
    summary: str
    confidence: float | None = None
    source: Literal["user_text", "user_voice", "console", "device", "system_test"] = "user_text"


class ModelUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int | None = None


class ActionTrace(BaseModel):
    trace_id: str
    user_id: str
    buddy_id: str
    space_id: str
    device_id: str | None
    turn_id: str
    intent: Intent
    proposal: ActionProposal | None
    permission_decision: PermissionDecision
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    model_usage: ModelUsage | None = None
    cost_refs: list[str] = Field(default_factory=list)
    failure_class: str | None = None
    review_status: Literal["unreviewed", "reviewed", "regression_candidate"] = "unreviewed"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @classmethod
    def minimal_pending(
        cls,
        trace_id: str,
        user_id: str,
        buddy_id: str,
        space_id: str,
        device_id: str | None,
        turn_id: str,
        intent_name: str,
        summary: str,
    ) -> "ActionTrace":
        return cls(
            trace_id=trace_id,
            user_id=user_id,
            buddy_id=buddy_id,
            space_id=space_id,
            device_id=device_id,
            turn_id=turn_id,
            intent=Intent(name=intent_name, summary=summary),
            proposal=None,
            permission_decision=PermissionDecision(
                policy_result="not_required",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="No device action proposed yet.",
            ),
        )


class CostEvent(BaseModel):
    cost_event_id: str
    trace_id: str
    buddy_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    model_cost_usd: float
    tool_cost_usd: float
    log_cost_usd: float
    created_at: str = Field(default_factory=now_iso)
