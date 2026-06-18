from __future__ import annotations

from buddys_api.schemas import CostEvent, new_id


class CostMeter:
    def __init__(self) -> None:
        self._events: list[CostEvent] = []

    def record_model_call(
        self,
        trace_id: str,
        buddy_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CostEvent:
        event = CostEvent(
            cost_event_id=new_id("cost"),
            trace_id=trace_id,
            buddy_id=buddy_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_cost_usd=0.0,
            tool_cost_usd=0.0,
            log_cost_usd=0.0,
        )
        self._events.append(event)
        return event

    def list(self) -> list[CostEvent]:
        return list(self._events)
