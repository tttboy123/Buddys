from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from buddys_api.schemas import now_iso


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CaptureContentStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
StateMemorySource = Literal["voice", "photo", "scan", "conversation", "inference", "manual"]
StateMemoryCaptureSource = Literal["voice", "photo", "scan", "conversation", "inference"]
StateMemoryOperation = Literal["upsert", "consume", "remove"]
StateMemoryProposalStatus = Literal["pending", "confirmed", "rejected"]
StateMemoryItemStatus = Literal["active", "consumed", "removed"]


class StateMemoryDelta(BaseModel):
    item_name: NonEmptyStr
    operation: StateMemoryOperation
    quantity: float | None = Field(default=None, ge=0)
    unit: NonEmptyStr | None = None
    category: NonEmptyStr | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: StateMemorySource


class StateMemoryPendingProposal(BaseModel):
    schema_version: Literal["state_memory_pending_proposal.v1"] = "state_memory_pending_proposal.v1"
    proposal_id: NonEmptyStr
    user_id: NonEmptyStr
    buddy_id: NonEmptyStr
    source: StateMemorySource
    content: CaptureContentStr
    deltas: list[StateMemoryDelta] = Field(default_factory=list)
    unrecognized: list[NonEmptyStr] = Field(default_factory=list)
    status: StateMemoryProposalStatus = "pending"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class StateMemoryItem(BaseModel):
    schema_version: Literal["state_memory_item.v1"] = "state_memory_item.v1"
    item_id: NonEmptyStr
    user_id: NonEmptyStr
    buddy_id: NonEmptyStr
    name: NonEmptyStr
    normalized_name: NonEmptyStr
    category: NonEmptyStr | None = None
    quantity: float | None = Field(default=None, ge=0)
    unit: NonEmptyStr | None = None
    source: StateMemorySource
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: StateMemoryItemStatus = "active"
    captured_at: str = Field(default_factory=now_iso)
    last_seen_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class StateMemoryHistoryEntry(BaseModel):
    schema_version: Literal["state_memory_history.v1"] = "state_memory_history.v1"
    history_id: NonEmptyStr
    item_id: NonEmptyStr
    user_id: NonEmptyStr
    buddy_id: NonEmptyStr
    item_name: NonEmptyStr
    change_type: NonEmptyStr
    change_source: StateMemorySource
    quantity_before: float | None = None
    quantity_after: float | None = None
    unit_before: NonEmptyStr | None = None
    unit_after: NonEmptyStr | None = None
    proposal_id: str | None = None
    created_at: str = Field(default_factory=now_iso)


class StateMemoryCaptureRequest(BaseModel):
    content: CaptureContentStr


class StateMemoryProposalCorrectionRequest(BaseModel):
    deltas: list[StateMemoryDelta] = Field(default_factory=list, min_length=1)


class StateMemoryProposalApplyResult(BaseModel):
    proposal: StateMemoryPendingProposal
    items: list[StateMemoryItem] = Field(default_factory=list)
    history_entries: list[StateMemoryHistoryEntry] = Field(default_factory=list)
    applied_delta_count: int = 0


class StateMemoryEvidenceItem(BaseModel):
    item_id: NonEmptyStr
    name: NonEmptyStr
    quantity: float | None = Field(default=None, ge=0)
    unit: NonEmptyStr | None = None
    status: StateMemoryItemStatus
    source: StateMemorySource
    last_seen_at: str


class StateMemoryQueryRequest(BaseModel):
    question: NonEmptyStr


class StateMemoryQueryAnswer(BaseModel):
    answer_type: Literal["have_item", "missing_for_recipe"]
    subject_name: NonEmptyStr
    summary: NonEmptyStr
    evidence_item_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_items: list[StateMemoryEvidenceItem] = Field(default_factory=list)
    missing_items: list[NonEmptyStr] = Field(default_factory=list)
    has_item: bool | None = None
    trace_id: NonEmptyStr
