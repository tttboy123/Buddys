from __future__ import annotations

from buddys_api.schemas import ActionTrace


class TraceStore:
    def __init__(self) -> None:
        self._traces: dict[str, ActionTrace] = {}

    def save(self, trace: ActionTrace) -> ActionTrace:
        self._traces[trace.trace_id] = trace
        return trace

    def get(self, trace_id: str) -> ActionTrace:
        try:
            return self._traces[trace_id]
        except KeyError as exc:
            raise KeyError(f"trace not found: {trace_id}") from exc

    def list(self) -> list[ActionTrace]:
        return list(self._traces.values())
