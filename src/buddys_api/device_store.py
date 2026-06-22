from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from buddys_api.device_models import (
    AgentMachine,
    BuddyRuntimeBinding,
    Device,
    DeviceDesiredState,
    DeviceEvent,
    DeviceHeartbeat,
)


class DuplicatePairingError(ValueError):
    pass


@dataclass(frozen=True)
class DevicePairing:
    device: Device
    agent_machine: AgentMachine
    binding: BuddyRuntimeBinding
    pairing_token: str | None
    idempotency_key: str


class DeviceRegistry:
    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self._connection = connection
        self._devices: dict[str, Device] = {}
        self._agent_machines: dict[str, AgentMachine] = {}
        self._bindings_by_buddy: dict[str, BuddyRuntimeBinding] = {}
        self._latest_heartbeat_by_device: dict[str, DeviceHeartbeat] = {}
        self._heartbeats_by_idempotency: dict[tuple[str, str], DeviceHeartbeat] = {}
        self._desired_state_by_device: dict[str, DeviceDesiredState] = {}
        self._device_events: list[DeviceEvent] = []
        self._events_by_idempotency: dict[tuple[str, str], DeviceEvent] = {}
        self._pairings_by_idempotency: dict[tuple[str, str], DevicePairing] = {}
        self._pairing_token_index: dict[str, tuple[str, str]] = {}
        self._revoked_pairing_tokens: set[str] = set()
        self._desired_state_lock = threading.Lock()
        if self._connection is not None:
            self._migrate_legacy_pairing_token_storage()
            self._load_from_connection()

    def save_device(self, device: Device) -> Device:
        if self._connection is not None:
            with self._connection:
                self._persist_device(device)
        self._devices[device.device_id] = device
        return device

    def get_device(self, device_id: str) -> Device:
        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise KeyError(f"device not found: {device_id}") from exc

    def list_devices(self) -> list[Device]:
        return list(self._devices.values())

    def save_agent_machine(self, agent_machine: AgentMachine) -> AgentMachine:
        if self._connection is not None:
            with self._connection:
                self._persist_agent_machine(agent_machine)
        self._agent_machines[agent_machine.agent_machine_id] = agent_machine
        return agent_machine

    def get_agent_machine(self, agent_machine_id: str) -> AgentMachine:
        try:
            return self._agent_machines[agent_machine_id]
        except KeyError as exc:
            raise KeyError(f"agent machine not found: {agent_machine_id}") from exc

    def list_agent_machines(self) -> list[AgentMachine]:
        return list(self._agent_machines.values())

    def save_binding(self, binding: BuddyRuntimeBinding) -> BuddyRuntimeBinding:
        if self._connection is not None:
            with self._connection:
                self._persist_binding(binding)
        self._bindings_by_buddy[binding.buddy_id] = binding
        return binding

    def get_binding(self, buddy_id: str) -> BuddyRuntimeBinding:
        try:
            return self._bindings_by_buddy[buddy_id]
        except KeyError as exc:
            raise KeyError(f"binding not found for buddy: {buddy_id}") from exc

    def list_bindings(self) -> list[BuddyRuntimeBinding]:
        return list(self._bindings_by_buddy.values())

    def save_heartbeat(self, heartbeat: DeviceHeartbeat) -> DeviceHeartbeat:
        idempotency_key = (heartbeat.device_id, heartbeat.idempotency_key)
        if idempotency_key in self._heartbeats_by_idempotency:
            return self._heartbeats_by_idempotency[idempotency_key]
        if self._connection is not None:
            with self._connection:
                self._persist_heartbeat(heartbeat)
        self._latest_heartbeat_by_device[heartbeat.device_id] = heartbeat
        self._heartbeats_by_idempotency[idempotency_key] = heartbeat
        return heartbeat

    def get_latest_heartbeat(self, device_id: str) -> DeviceHeartbeat:
        try:
            return self._latest_heartbeat_by_device[device_id]
        except KeyError as exc:
            raise KeyError(f"heartbeat not found for device: {device_id}") from exc

    def list_latest_heartbeats(self) -> list[DeviceHeartbeat]:
        return list(self._latest_heartbeat_by_device.values())

    def set_desired_state(self, desired_state: DeviceDesiredState) -> DeviceDesiredState:
        if self._connection is not None:
            with self._connection:
                self._persist_desired_state(desired_state)
        self._desired_state_by_device[desired_state.device_id] = desired_state
        return desired_state

    def publish_owner_manual_reminder(self, *, device_id: str, reminder_text: str) -> DeviceDesiredState:
        with self._desired_state_lock:
            current_desired_state = self._desired_state_by_device.get(
                device_id,
                DeviceDesiredState(device_id=device_id, state="idle", revision=0),
            )
            desired_state = DeviceDesiredState(
                device_id=device_id,
                state="manual_required",
                revision=current_desired_state.revision + 1,
                display_text=reminder_text,
                manual_required=True,
                user_instruction=reminder_text,
                recent_activity=[],
            )
            if self._connection is not None:
                with self._connection:
                    self._persist_desired_state(desired_state)
            self._desired_state_by_device[device_id] = desired_state
            return desired_state

    def get_desired_state(self, device_id: str) -> DeviceDesiredState:
        return self._desired_state_by_device.get(
            device_id,
            DeviceDesiredState(device_id=device_id, state="idle", revision=0),
        )

    def append_event(self, event: DeviceEvent) -> DeviceEvent:
        idempotency_key = (event.device_id, event.idempotency_key)
        if idempotency_key in self._events_by_idempotency:
            return self._events_by_idempotency[idempotency_key]
        if self._connection is not None:
            with self._connection:
                self._persist_event(event)
        self._device_events.append(event)
        self._events_by_idempotency[idempotency_key] = event
        return event

    def list_events(self, device_id: str) -> list[DeviceEvent]:
        return [event for event in self._device_events if event.device_id == device_id]

    def list_all_events(self) -> list[DeviceEvent]:
        return list(self._device_events)

    def pair_device(
        self,
        device: Device,
        agent_machine: AgentMachine,
        binding: BuddyRuntimeBinding,
        pairing_token: str,
        idempotency_key: str,
    ) -> DevicePairing:
        pair_key = (device.device_id, idempotency_key)
        if pair_key in self._pairings_by_idempotency:
            return self._pairings_by_idempotency[pair_key]

        pairing_token_verifier = _pairing_token_verifier(pairing_token)
        existing_pair_key = self._pairing_token_index.get(pairing_token_verifier)
        if existing_pair_key is not None or pairing_token_verifier in self._revoked_pairing_tokens:
            raise DuplicatePairingError("pairing token has already been used")

        pairing = DevicePairing(
            device=device,
            agent_machine=agent_machine,
            binding=binding,
            pairing_token=pairing_token,
            idempotency_key=idempotency_key,
        )
        stale_pairing_token_verifiers = self._pairing_token_verifiers_for_device(device.device_id)
        if self._connection is not None:
            with self._connection:
                for stale_pairing_token_verifier in stale_pairing_token_verifiers:
                    self._persist_revoked_pairing_token(stale_pairing_token_verifier, device.device_id)
                self._persist_device(device)
                self._persist_agent_machine(agent_machine)
                self._persist_binding(binding)
                self._persist_pairing(pairing, pairing_token_verifier)

        self._invalidate_pairing_tokens_for_device(device.device_id)
        self._devices[device.device_id] = device
        self._agent_machines[agent_machine.agent_machine_id] = agent_machine
        self._bindings_by_buddy[binding.buddy_id] = binding
        self._pairings_by_idempotency[pair_key] = pairing
        self._pairing_token_index[pairing_token_verifier] = pair_key
        return pairing

    def require_device_pairing_token(self, device_id: str, pairing_token: str) -> DevicePairing:
        pair_key = self._pairing_token_index.get(_pairing_token_verifier(pairing_token))
        if pair_key is None:
            raise KeyError("pairing token not found")
        pairing = self._pairings_by_idempotency[pair_key]
        if pairing.device.device_id != device_id:
            raise KeyError("pairing token does not match device")
        return pairing

    def _pairing_token_verifiers_for_device(self, device_id: str) -> list[str]:
        return [
            pairing_token_verifier
            for pairing_token_verifier, pair_key in self._pairing_token_index.items()
            if self._pairings_by_idempotency[pair_key].device.device_id == device_id
        ]

    def _invalidate_pairing_tokens_for_device(self, device_id: str) -> None:
        for pairing_token_verifier in self._pairing_token_verifiers_for_device(device_id):
            del self._pairing_token_index[pairing_token_verifier]
            self._revoked_pairing_tokens.add(pairing_token_verifier)

    def _migrate_legacy_pairing_token_storage(self) -> None:
        legacy_pairings = self._connection.execute(
            """
            SELECT device_id, idempotency_key, pairing_token, payload_json
            FROM device_pairings_runtime
            """
        ).fetchall()
        legacy_revoked = self._connection.execute(
            """
            SELECT pairing_token, device_id, revoked_at
            FROM device_revoked_pairing_tokens_runtime
            """
        ).fetchall()
        legacy_plaintext_pairing_tokens: set[str] = set()
        for row in legacy_pairings:
            payload = json.loads(row["payload_json"])
            payload_pairing_token = payload.get("pairing_token")
            if isinstance(payload_pairing_token, str):
                legacy_plaintext_pairing_tokens.add(payload_pairing_token)
            elif not _looks_like_token_verifier(row["pairing_token"]):
                legacy_plaintext_pairing_tokens.add(row["pairing_token"])

        if not legacy_plaintext_pairing_tokens and not any(
            not _looks_like_token_verifier(row["pairing_token"]) for row in legacy_revoked
        ):
            return

        with self._connection:
            for row in legacy_pairings:
                payload = json.loads(row["payload_json"])
                legacy_pairing_token = payload.pop("pairing_token", None)
                if isinstance(legacy_pairing_token, str):
                    pairing_token_verifier = _pairing_token_verifier(legacy_pairing_token)
                elif row["pairing_token"] in legacy_plaintext_pairing_tokens:
                    pairing_token_verifier = _pairing_token_verifier(row["pairing_token"])
                else:
                    pairing_token_verifier = row["pairing_token"]
                self._connection.execute(
                    """
                    UPDATE device_pairings_runtime
                    SET pairing_token = ?, payload_json = ?
                    WHERE device_id = ? AND idempotency_key = ?
                    """,
                    (
                        pairing_token_verifier,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        row["device_id"],
                        row["idempotency_key"],
                    ),
                )
            for row in legacy_revoked:
                if row["pairing_token"] in legacy_plaintext_pairing_tokens:
                    pairing_token_verifier = _pairing_token_verifier(row["pairing_token"])
                elif not _looks_like_token_verifier(row["pairing_token"]):
                    pairing_token_verifier = _pairing_token_verifier(row["pairing_token"])
                else:
                    continue
                self._connection.execute(
                    """
                    UPDATE device_revoked_pairing_tokens_runtime
                    SET pairing_token = ?
                    WHERE pairing_token = ? AND device_id = ? AND revoked_at = ?
                    """,
                    (
                        pairing_token_verifier,
                        row["pairing_token"],
                        row["device_id"],
                        row["revoked_at"],
                    ),
                )

    def _load_from_connection(self) -> None:
        self._revoked_pairing_tokens = {
            row["pairing_token"]
            for row in self._connection.execute(
                "SELECT pairing_token FROM device_revoked_pairing_tokens_runtime"
            ).fetchall()
        }
        for row in self._connection.execute(
            "SELECT payload_json FROM devices_runtime"
        ).fetchall():
            device = Device.model_validate(json.loads(row["payload_json"]))
            self._devices[device.device_id] = device
        for row in self._connection.execute(
            "SELECT payload_json FROM agent_machines_runtime"
        ).fetchall():
            machine = AgentMachine.model_validate(json.loads(row["payload_json"]))
            self._agent_machines[machine.agent_machine_id] = machine
        for row in self._connection.execute(
            "SELECT payload_json FROM buddy_runtime_bindings"
        ).fetchall():
            binding = BuddyRuntimeBinding.model_validate(json.loads(row["payload_json"]))
            self._bindings_by_buddy[binding.buddy_id] = binding
        for row in self._connection.execute(
            "SELECT pairing_token, payload_json FROM device_pairings_runtime ORDER BY created_at, device_id, idempotency_key"
        ).fetchall():
            pairing = _pairing_from_json(row["payload_json"])
            pair_key = (pairing.device.device_id, pairing.idempotency_key)
            self._pairings_by_idempotency[pair_key] = pairing
            if row["pairing_token"] not in self._revoked_pairing_tokens:
                self._pairing_token_index[row["pairing_token"]] = pair_key
        for row in self._connection.execute(
            "SELECT payload_json FROM device_latest_heartbeats_runtime ORDER BY created_at, device_id, idempotency_key"
        ).fetchall():
            heartbeat = DeviceHeartbeat.model_validate(json.loads(row["payload_json"]))
            idempotency_key = (heartbeat.device_id, heartbeat.idempotency_key)
            self._heartbeats_by_idempotency[idempotency_key] = heartbeat
            self._latest_heartbeat_by_device[heartbeat.device_id] = heartbeat
        for row in self._connection.execute(
            "SELECT payload_json FROM device_desired_states_runtime"
        ).fetchall():
            desired_state = DeviceDesiredState.model_validate(json.loads(row["payload_json"]))
            self._desired_state_by_device[desired_state.device_id] = desired_state
        for row in self._connection.execute(
            "SELECT payload_json FROM device_events_runtime ORDER BY created_at, device_id, idempotency_key"
        ).fetchall():
            event = DeviceEvent.model_validate(json.loads(row["payload_json"]))
            self._device_events.append(event)
            self._events_by_idempotency[(event.device_id, event.idempotency_key)] = event

    def _persist_device(self, device: Device) -> None:
        if self._connection is None:
            return
        payload = _model_json(device)
        self._connection.execute(
            """
            INSERT INTO devices_runtime (device_id, buddy_id, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                buddy_id = excluded.buddy_id,
                payload_json = excluded.payload_json
            """,
            (device.device_id, device.buddy_id, payload),
        )

    def _persist_agent_machine(self, agent_machine: AgentMachine) -> None:
        if self._connection is None:
            return
        payload = _model_json(agent_machine)
        self._connection.execute(
            """
            INSERT INTO agent_machines_runtime (agent_machine_id, owner_user_id, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(agent_machine_id) DO UPDATE SET
                owner_user_id = excluded.owner_user_id,
                payload_json = excluded.payload_json
            """,
            (agent_machine.agent_machine_id, agent_machine.owner_user_id, payload),
        )

    def _persist_binding(self, binding: BuddyRuntimeBinding) -> None:
        if self._connection is None:
            return
        payload = _model_json(binding)
        self._connection.execute(
            """
            INSERT INTO buddy_runtime_bindings (buddy_id, agent_machine_id, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(buddy_id) DO UPDATE SET
                agent_machine_id = excluded.agent_machine_id,
                payload_json = excluded.payload_json
            """,
            (binding.buddy_id, binding.agent_machine_id, payload),
        )

    def _persist_pairing(self, pairing: DevicePairing, pairing_token_verifier: str) -> None:
        if self._connection is None:
            return
        payload = _pairing_json(pairing)
        self._connection.execute(
            """
            INSERT OR REPLACE INTO device_pairings_runtime (
                device_id, idempotency_key, pairing_token, buddy_id, agent_machine_id, created_at, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pairing.device.device_id,
                pairing.idempotency_key,
                pairing_token_verifier,
                pairing.device.buddy_id,
                pairing.agent_machine.agent_machine_id,
                pairing.device.created_at,
                payload,
            ),
        )

    def _persist_heartbeat(self, heartbeat: DeviceHeartbeat) -> None:
        if self._connection is None:
            return
        payload = _model_json(heartbeat)
        self._connection.execute(
            """
            INSERT OR REPLACE INTO device_latest_heartbeats_runtime (
                device_id, idempotency_key, created_at, payload_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                heartbeat.device_id,
                heartbeat.idempotency_key,
                heartbeat.created_at,
                payload,
            ),
        )

    def _persist_desired_state(self, desired_state: DeviceDesiredState) -> None:
        if self._connection is None:
            return
        payload = _model_json(desired_state)
        self._connection.execute(
            """
            INSERT INTO device_desired_states_runtime (device_id, updated_at, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                payload_json = excluded.payload_json
            """,
            (desired_state.device_id, desired_state.updated_at, payload),
        )

    def _persist_event(self, event: DeviceEvent) -> None:
        if self._connection is None:
            return
        payload = _model_json(event)
        self._connection.execute(
            """
            INSERT OR REPLACE INTO device_events_runtime (
                device_id, idempotency_key, created_at, payload_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                event.device_id,
                event.idempotency_key,
                event.created_at,
                payload,
            ),
        )

    def _persist_revoked_pairing_token(self, pairing_token_verifier: str, device_id: str) -> None:
        if self._connection is None:
            return
        self._connection.execute(
            """
            INSERT OR IGNORE INTO device_revoked_pairing_tokens_runtime (
                pairing_token, device_id, revoked_at
            )
            VALUES (?, ?, COALESCE(
                (SELECT created_at FROM device_pairings_runtime WHERE pairing_token = ?),
                CURRENT_TIMESTAMP
            ))
            """,
            (pairing_token_verifier, device_id, pairing_token_verifier),
        )


def _model_json(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def _pairing_json(pairing: DevicePairing) -> str:
    return json.dumps(
        {
            "device": pairing.device.model_dump(mode="json"),
            "agent_machine": pairing.agent_machine.model_dump(mode="json"),
            "binding": pairing.binding.model_dump(mode="json"),
            "idempotency_key": pairing.idempotency_key,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _pairing_from_json(payload_json: str) -> DevicePairing:
    payload = json.loads(payload_json)
    return DevicePairing(
        device=Device.model_validate(payload["device"]),
        agent_machine=AgentMachine.model_validate(payload["agent_machine"]),
        binding=BuddyRuntimeBinding.model_validate(payload["binding"]),
        pairing_token=None,
        idempotency_key=payload["idempotency_key"],
    )


def _pairing_token_verifier(pairing_token: str) -> str:
    return hashlib.sha256(pairing_token.encode("utf-8")).hexdigest()


def _looks_like_token_verifier(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
