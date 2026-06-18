from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field, HttpUrl, field_validator

from buddys_api.device_models import (
    AgentMachine,
    BuddyRuntimeBinding,
    Device,
    DeviceDesiredState,
    DeviceEvent,
    DeviceHeartbeat,
    DeviceState,
    NonEmptyStr,
    UptimeSeconds,
    WifiRssi,
    validate_device_event_payload,
)
from buddys_api.device_store import DeviceRegistry, DuplicatePairingError
from buddys_api.runtime import BuddysRuntime
from buddys_api.schemas import Buddy


router = APIRouter(prefix="/devices", tags=["devices"])


class PairAgentMachineRequest(BaseModel):
    agent_machine_id: NonEmptyStr
    owner_user_id: NonEmptyStr
    machine_type: NonEmptyStr
    endpoint: HttpUrl
    public_key: NonEmptyStr
    runtime_version: NonEmptyStr


class PairDeviceRequest(BaseModel):
    buddy_id: NonEmptyStr
    space_id: NonEmptyStr
    public_key: NonEmptyStr
    firmware_version: NonEmptyStr
    pairing_token: NonEmptyStr
    agent_machine: PairAgentMachineRequest
    idempotency_key: NonEmptyStr


class DeviceHeartbeatRequest(BaseModel):
    firmware_version: NonEmptyStr
    wifi_rssi: WifiRssi
    uptime_seconds: UptimeSeconds
    current_state: DeviceState
    idempotency_key: NonEmptyStr


class DeviceEventRequest(BaseModel):
    event_type: Literal["approve", "reject", "ack", "manual_done"]
    idempotency_key: NonEmptyStr
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def payload_must_not_include_sensitive_or_action_keys(cls, payload: dict[str, object]) -> dict[str, object]:
        return validate_device_event_payload(payload)


DeviceIdPath = Annotated[str, Path(min_length=1)]


@router.post("/{device_id}/pair", status_code=201)
def pair_device(device_id: DeviceIdPath, request: PairDeviceRequest, fastapi_request: Request) -> dict[str, object]:
    device_id = _validate_path_id(device_id, "device_id")
    runtime = _runtime(fastapi_request)
    device_store = _device_store(fastapi_request)
    buddy = _require_buddy(runtime, request.buddy_id)
    if request.agent_machine.owner_user_id != buddy.user_id:
        raise HTTPException(status_code=403, detail={"code": "agent_machine_owner_mismatch"})

    device = Device(
        device_id=device_id,
        buddy_id=request.buddy_id,
        space_id=request.space_id,
        public_key=request.public_key,
        pairing_state="paired",
        firmware_version=request.firmware_version,
    )
    agent_machine = AgentMachine(
        agent_machine_id=request.agent_machine.agent_machine_id,
        owner_user_id=request.agent_machine.owner_user_id,
        machine_type=request.agent_machine.machine_type,
        endpoint=request.agent_machine.endpoint,
        public_key=request.agent_machine.public_key,
        runtime_version=request.agent_machine.runtime_version,
        status="online",
    )
    binding = BuddyRuntimeBinding(
        buddy_id=request.buddy_id,
        agent_machine_id=request.agent_machine.agent_machine_id,
        role="primary",
        authority_epoch=1,
        state_revision=0,
    )

    try:
        pairing = device_store.pair_device(
            device=device,
            agent_machine=agent_machine,
            binding=binding,
            pairing_token=request.pairing_token,
            idempotency_key=request.idempotency_key,
        )
    except DuplicatePairingError as exc:
        raise HTTPException(status_code=409, detail={"code": "pairing_token_already_used"}) from exc

    return {"device": pairing.device, "agent_machine": pairing.agent_machine, "binding": pairing.binding}


@router.post("/{device_id}/heartbeat")
def device_heartbeat(device_id: DeviceIdPath, request: DeviceHeartbeatRequest, fastapi_request: Request) -> DeviceHeartbeat:
    device_id = _validate_path_id(device_id, "device_id")
    device_store = _device_store(fastapi_request)
    _require_device(device_store, device_id)
    heartbeat = DeviceHeartbeat(
        device_id=device_id,
        firmware_version=request.firmware_version,
        wifi_rssi=request.wifi_rssi,
        uptime_seconds=request.uptime_seconds,
        current_state=request.current_state,
        idempotency_key=request.idempotency_key,
    )
    return device_store.save_heartbeat(heartbeat)


@router.get("/{device_id}/desired-state")
def get_device_desired_state(device_id: DeviceIdPath, fastapi_request: Request) -> DeviceDesiredState:
    device_id = _validate_path_id(device_id, "device_id")
    device_store = _device_store(fastapi_request)
    _require_device(device_store, device_id)
    return device_store.get_desired_state(device_id)


@router.post("/{device_id}/events", status_code=201)
def submit_device_event(device_id: DeviceIdPath, request: DeviceEventRequest, fastapi_request: Request) -> DeviceEvent:
    device_id = _validate_path_id(device_id, "device_id")
    device_store = _device_store(fastapi_request)
    _require_device(device_store, device_id)
    event = DeviceEvent(
        device_id=device_id,
        event_type=request.event_type,
        idempotency_key=request.idempotency_key,
        payload=request.payload,
    )
    return device_store.append_event(event)


@router.get("/{device_id}/ota/check")
def check_device_ota(device_id: DeviceIdPath, fastapi_request: Request) -> dict[str, object]:
    device_id = _validate_path_id(device_id, "device_id")
    device = _require_device(_device_store(fastapi_request), device_id)
    return {
        "device_id": device_id,
        "update_available": False,
        "current_version": device.firmware_version,
        "target_version": None,
    }


def _runtime(request: Request) -> BuddysRuntime:
    return request.app.state.runtime


def _device_store(request: Request) -> DeviceRegistry:
    return request.app.state.device_store


def _require_buddy(runtime: BuddysRuntime, buddy_id: str) -> Buddy:
    try:
        return runtime._get_buddy(buddy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "buddy_not_found"}) from exc


def _require_device(device_store: DeviceRegistry, device_id: str) -> Device:
    try:
        return device_store.get_device(device_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "device_not_found"}) from exc


def _validate_path_id(value: str, field_name: str) -> str:
    if not value.strip():
        raise HTTPException(status_code=422, detail={"code": f"{field_name}_required"})
    return value
