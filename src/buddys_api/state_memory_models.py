from __future__ import annotations

import base64
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from buddys_api.schemas import now_iso


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CaptureContentStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
OptionalCaptureContentStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
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


class StateMemoryRecipeIngredient(BaseModel):
    name: NonEmptyStr
    normalized_name: NonEmptyStr


class StateMemoryRecipe(BaseModel):
    schema_version: Literal["state_memory_recipe.v1"] = "state_memory_recipe.v1"
    recipe_id: NonEmptyStr
    user_id: NonEmptyStr
    buddy_id: NonEmptyStr
    name: NonEmptyStr
    normalized_name: NonEmptyStr
    ingredients: list[StateMemoryRecipeIngredient] = Field(default_factory=list, min_length=1)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class StateMemoryRecipeCreateRequest(BaseModel):
    name: NonEmptyStr
    ingredients: list[str] = Field(default_factory=list, min_length=1)

    @model_validator(mode="after")
    def normalize_recipe_fields(self) -> "StateMemoryRecipeCreateRequest":
        normalized_name = _normalize_memory_text(self.name)
        ingredient_names = _normalize_recipe_ingredient_names(self.ingredients)
        if not normalized_name:
            raise ValueError("recipe_name_required")
        if not ingredient_names:
            raise ValueError("recipe_ingredients_required")
        self.name = normalized_name
        self.ingredients = ingredient_names
        return self


class StateMemoryCaptureRequest(BaseModel):
    content: OptionalCaptureContentStr | None = None
    image_base64: str | None = None
    image_media_type: str | None = None

    @model_validator(mode="after")
    def validate_image_fields(self) -> "StateMemoryCaptureRequest":
        if (self.image_base64 is None) != (self.image_media_type is None):
            raise ValueError("image_payload_incomplete")
        if self.image_media_type is not None and self.image_media_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise ValueError("image_media_type_not_supported")
        if self.image_base64 is not None:
            try:
                base64.b64decode(self.image_base64, validate=True)
            except Exception as exc:
                raise ValueError("image_base64_invalid") from exc
        return self


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


def _normalize_memory_text(value: str) -> str:
    return " ".join(value.strip().split())


def _normalize_recipe_ingredient_names(ingredients: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for ingredient in ingredients:
        name = _normalize_memory_text(str(ingredient))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(name)
    return normalized
