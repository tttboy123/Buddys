from __future__ import annotations

from dataclasses import dataclass

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
    pairing_token: str
    idempotency_key: str


class DeviceRegistry:
    def __init__(self) -> None:
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

    def save_device(self, device: Device) -> Device:
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
        self._desired_state_by_device[desired_state.device_id] = desired_state
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

        existing_pair_key = self._pairing_token_index.get(pairing_token)
        if existing_pair_key is not None:
            raise DuplicatePairingError("pairing token has already been used")

        self._invalidate_pairing_tokens_for_device(device.device_id)

        pairing = DevicePairing(
            device=device,
            agent_machine=agent_machine,
            binding=binding,
            pairing_token=pairing_token,
            idempotency_key=idempotency_key,
        )
        self.save_device(device)
        self.save_agent_machine(agent_machine)
        self.save_binding(binding)
        self._pairings_by_idempotency[pair_key] = pairing
        self._pairing_token_index[pairing_token] = pair_key
        return pairing

    def require_device_pairing_token(self, device_id: str, pairing_token: str) -> DevicePairing:
        pair_key = self._pairing_token_index.get(pairing_token)
        if pair_key is None:
            raise KeyError("pairing token not found")
        pairing = self._pairings_by_idempotency[pair_key]
        if pairing.device.device_id != device_id:
            raise KeyError("pairing token does not match device")
        return pairing

    def _invalidate_pairing_tokens_for_device(self, device_id: str) -> None:
        stale_tokens = [
            pairing_token
            for pairing_token, pair_key in self._pairing_token_index.items()
            if self._pairings_by_idempotency[pair_key].device.device_id == device_id
        ]
        for pairing_token in stale_tokens:
            del self._pairing_token_index[pairing_token]
