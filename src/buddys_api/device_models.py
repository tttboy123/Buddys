from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, field_validator

from buddys_api.schemas import now_iso


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
WifiRssi = Annotated[int, Field(ge=-127, le=0)]
UptimeSeconds = Annotated[int, Field(ge=0)]

DENIED_PAYLOAD_KEY_PARTS = (
    "secret",
    "token",
    "api_key",
    "password",
    "provider_key",
    "adapter_token",
    "tool_args",
    "action",
)


DeviceState = Literal[
    "idle",
    "thinking",
    "asking_confirmation",
    "executing",
    "success",
    "manual_required",
    "error",
]


class DeviceStateMemoryItemSummary(BaseModel):
    name: NonEmptyStr
    quantity: float | None = None
    unit: str | None = None


class DeviceStateMemoryProjection(BaseModel):
    confirmed_items: list[DeviceStateMemoryItemSummary] = Field(default_factory=list)
    pending_proposal_count: int = Field(ge=0, default=0)


class DeviceProactiveHint(BaseModel):
    kind: Literal["consumption_inference"]
    message: NonEmptyStr
    item_names: list[NonEmptyStr] = Field(default_factory=list)


class DeviceRecentActivityEntry(BaseModel):
    kind: Literal["capture_confirmed", "proposal_waiting", "query_answered"]
    summary: NonEmptyStr
    created_at: NonEmptyStr


class DeviceShoppingPassProjection(BaseModel):
    open_count: int = Field(ge=0, default=0)
    top_open_names: list[NonEmptyStr] = Field(default_factory=list)


class Device(BaseModel):
    schema_version: Literal["device.v1"] = "device.v1"
    device_id: NonEmptyStr
    buddy_id: NonEmptyStr
    space_id: NonEmptyStr
    public_key: NonEmptyStr
    pairing_state: Literal["unpaired", "pairing", "paired", "revoked"] = "unpaired"
    firmware_version: NonEmptyStr | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class AgentMachine(BaseModel):
    schema_version: Literal["agent_machine.v1"] = "agent_machine.v1"
    agent_machine_id: NonEmptyStr
    owner_user_id: NonEmptyStr
    machine_type: NonEmptyStr
    endpoint: HttpUrl
    public_key: NonEmptyStr
    runtime_version: NonEmptyStr
    status: Literal["online", "offline", "degraded"] = "offline"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class BuddyRuntimeBinding(BaseModel):
    schema_version: Literal["buddy_runtime_binding.v1"] = "buddy_runtime_binding.v1"
    buddy_id: NonEmptyStr
    agent_machine_id: NonEmptyStr
    role: Literal["primary", "standby"] = "primary"
    authority_epoch: int = 1
    state_revision: int = 0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DeviceHeartbeat(BaseModel):
    schema_version: Literal["device_heartbeat.v1"] = "device_heartbeat.v1"
    device_id: NonEmptyStr
    firmware_version: NonEmptyStr
    wifi_rssi: WifiRssi
    uptime_seconds: UptimeSeconds
    current_state: DeviceState
    idempotency_key: NonEmptyStr
    created_at: str = Field(default_factory=now_iso)


class DeviceDesiredState(BaseModel):
    schema_version: Literal["device_desired_state.v1"] = "device_desired_state.v1"
    device_id: NonEmptyStr
    state: DeviceState
    revision: int = 0
    display_text: str | None = None
    manual_required: bool = False
    user_instruction: str | None = None
    source_trace_id: str | None = None
    idempotency_key: str | None = None
    state_memory: DeviceStateMemoryProjection | None = None
    shopping_pass: DeviceShoppingPassProjection | None = None
    proactive_hint: DeviceProactiveHint | None = None
    recent_activity: list[DeviceRecentActivityEntry] = Field(default_factory=list)
    updated_at: str = Field(default_factory=now_iso)


class DeviceEvent(BaseModel):
    schema_version: Literal["device_event.v1"] = "device_event.v1"
    device_id: NonEmptyStr
    event_type: Literal["approve", "reject", "ack", "manual_done"]
    idempotency_key: NonEmptyStr
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)

    @field_validator("payload")
    @classmethod
    def payload_must_not_include_sensitive_or_action_keys(cls, payload: dict[str, Any]) -> dict[str, Any]:
        return validate_device_event_payload(payload)


class SyncOutboxEvent(BaseModel):
    schema_version: Literal["sync_outbox_event.v1"] = "sync_outbox_event.v1"
    outbox_event_id: NonEmptyStr
    aggregate_type: Literal["device", "agent_machine", "binding"]
    aggregate_id: NonEmptyStr
    sequence: int
    event_type: NonEmptyStr
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr
    created_at: str = Field(default_factory=now_iso)
    synced_at: str | None = None


def validate_device_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _reject_denied_payload_keys(payload)
    return payload


def _reject_denied_payload_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).lower()
            if any(denied in normalized_key for denied in DENIED_PAYLOAD_KEY_PARTS):
                raise ValueError(f"device event payload key is not allowed: {key}")
            _reject_denied_payload_keys(nested_value)
    elif isinstance(value, list):
        for item in value:
            _reject_denied_payload_keys(item)
