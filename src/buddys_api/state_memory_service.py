from __future__ import annotations

import re

from buddys_api.cost_meter import CostMeter
from buddys_api.schemas import (
    ActionProposal,
    ActionTrace,
    Intent,
    ModelUsage,
    PermissionDecision,
    new_id,
)
from buddys_api.state_memory_models import (
    StateMemoryCaptureSource,
    StateMemoryDelta,
    StateMemoryEvidenceItem,
    StateMemoryPendingProposal,
    StateMemoryProposalApplyResult,
    StateMemoryQueryAnswer,
    StateMemoryItem,
)
from buddys_api.state_memory_store import StateMemoryStore
from buddys_api.sync_store import SyncStore
from buddys_api.trace_store import TraceStore


_RECIPE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "红烧肉": ("五花肉", "生抽", "老抽", "八角", "冰糖"),
}


class StateMemoryService:
    def __init__(
        self,
        *,
        store: StateMemoryStore,
        sync_store: SyncStore,
        provider: object,
        trace_store: TraceStore,
        cost_meter: CostMeter,
    ) -> None:
        self.store = store
        self.sync_store = sync_store
        self.provider = provider
        self.trace_store = trace_store
        self.cost_meter = cost_meter

    def create_capture_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        source: StateMemoryCaptureSource,
        content: str,
    ) -> tuple[StateMemoryPendingProposal, int]:
        deltas = self._parse_capture(source=source, content=content)
        proposal = self.store.save_pending_proposal(
            user_id=user_id,
            buddy_id=buddy_id,
            source=source,
            content=content,
            deltas=deltas,
        )
        sync_event = self.sync_store.append_event(
            event_type="state_memory.proposal_created",
            entity_type="state_memory_proposal",
            entity_id=proposal.proposal_id,
            actor_user_id=user_id,
            visibility="auth",
            payload_summary={
                "buddy_id": buddy_id,
                "proposal_id": proposal.proposal_id,
                "source": source,
                "delta_count": len(proposal.deltas),
                "item_names": [delta.item_name for delta in proposal.deltas],
            },
        )
        return proposal, sync_event.revision

    def confirm_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
    ) -> tuple[StateMemoryProposalApplyResult, int]:
        result = self.store.confirm_proposal(user_id=user_id, buddy_id=buddy_id, proposal_id=proposal_id)
        sync_event = self.sync_store.append_event(
            event_type="state_memory.proposal_confirmed",
            entity_type="state_memory_proposal",
            entity_id=proposal_id,
            actor_user_id=user_id,
            visibility="auth",
            payload_summary={
                "buddy_id": buddy_id,
                "proposal_id": proposal_id,
                "source": result.proposal.source,
                "applied_delta_count": result.applied_delta_count,
                "item_ids": [item.item_id for item in result.items],
            },
        )
        return result, sync_event.revision

    def reject_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
    ) -> tuple[StateMemoryPendingProposal, int]:
        proposal = self.store.reject_proposal(user_id=user_id, buddy_id=buddy_id, proposal_id=proposal_id)
        sync_event = self.sync_store.append_event(
            event_type="state_memory.proposal_rejected",
            entity_type="state_memory_proposal",
            entity_id=proposal_id,
            actor_user_id=user_id,
            visibility="auth",
            payload_summary={
                "buddy_id": buddy_id,
                "proposal_id": proposal_id,
                "source": proposal.source,
                "delta_count": len(proposal.deltas),
            },
        )
        return proposal, sync_event.revision

    def correct_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
        corrected_deltas: list[StateMemoryDelta],
    ) -> tuple[StateMemoryProposalApplyResult, int]:
        result = self.store.correct_proposal(
            user_id=user_id,
            buddy_id=buddy_id,
            proposal_id=proposal_id,
            corrected_deltas=corrected_deltas,
        )
        sync_event = self.sync_store.append_event(
            event_type="state_memory.proposal_corrected",
            entity_type="state_memory_proposal",
            entity_id=proposal_id,
            actor_user_id=user_id,
            visibility="auth",
            payload_summary={
                "buddy_id": buddy_id,
                "proposal_id": proposal_id,
                "source": result.proposal.source,
                "applied_delta_count": result.applied_delta_count,
                "item_ids": [item.item_id for item in result.items],
            },
        )
        return result, sync_event.revision

    def answer_query(
        self,
        *,
        user_id: str,
        buddy_id: str,
        space_id: str,
        device_id: str | None,
        question: str,
    ) -> StateMemoryQueryAnswer:
        items = self.store.list_items(user_id=user_id, buddy_id=buddy_id)
        recipe_name, required_items = _match_recipe_question(question)
        if recipe_name is not None:
            answer = _build_missing_for_recipe_answer(
                subject_name=recipe_name,
                required_items=required_items,
                items=items,
            )
        else:
            item_name = _extract_have_item_name(question)
            if item_name is None:
                raise ValueError("state_memory_query_unsupported")
            answer = _build_have_item_answer(item_name=item_name, items=items)

        trace_id = self._record_query_trace(
            user_id=user_id,
            buddy_id=buddy_id,
            space_id=space_id,
            device_id=device_id,
            question=question,
            answer=answer,
        )
        payload = answer.model_dump(mode="json")
        payload["trace_id"] = trace_id
        return StateMemoryQueryAnswer.model_validate(payload)

    def _parse_capture(self, *, source: StateMemoryCaptureSource, content: str) -> list[StateMemoryDelta]:
        parse_capture = getattr(self.provider, "parse_state_memory_capture", None)
        if parse_capture is None:
            raise ValueError("state_memory_capture_not_supported")
        deltas = parse_capture(source=source, content=content)
        if not deltas:
            raise ValueError("state_memory_capture_empty")
        return deltas

    def _record_query_trace(
        self,
        *,
        user_id: str,
        buddy_id: str,
        space_id: str,
        device_id: str | None,
        question: str,
        answer: StateMemoryQueryAnswer,
    ) -> str:
        trace_id = new_id("trace")
        input_tokens = len(question)
        output_tokens = len(answer.summary)
        provider_name = getattr(self.provider, "provider", "state_memory")
        model_name = getattr(self.provider, "model", "state_memory-query-v0")
        cost_event = self.cost_meter.record_model_call(
            trace_id=trace_id,
            buddy_id=buddy_id,
            provider=provider_name,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        trace = ActionTrace(
            trace_id=trace_id,
            user_id=user_id,
            buddy_id=buddy_id,
            space_id=space_id,
            device_id=device_id,
            turn_id=new_id("turn"),
            intent=Intent(
                name="state_memory_query",
                summary=question,
                confidence=1.0,
                source="user_text",
            ),
            proposal=ActionProposal(
                proposal_id=new_id("proposal"),
                trace_id=trace_id,
                buddy_id=buddy_id,
                action_type="reply_only",
                summary=answer.summary,
                requires_confirmation=False,
                tool_id=None,
                action=None,
                args={
                    "question": question,
                    "answer_type": answer.answer_type,
                    "subject_name": answer.subject_name,
                    "evidence_item_ids": answer.evidence_item_ids,
                    "missing_items": answer.missing_items,
                    "has_item": answer.has_item,
                },
                risk_level="none",
            ),
            permission_decision=PermissionDecision(
                policy_result="not_required",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="Read-only state-memory query.",
            ),
            model_usage=ModelUsage(
                provider=provider_name,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=0,
            ),
            cost_refs=[cost_event.cost_event_id],
        )
        self.trace_store.save(trace)
        return trace_id


def _build_have_item_answer(*, item_name: str, items: list[StateMemoryItem]) -> StateMemoryQueryAnswer:
    normalized_target = _normalize_item_name(item_name)
    matching_items = [item for item in items if item.normalized_name == normalized_target]
    evidence_source = [item for item in matching_items if _item_is_available(item)] or matching_items
    has_item = any(_item_is_available(item) for item in matching_items)
    return StateMemoryQueryAnswer(
        answer_type="have_item",
        subject_name=item_name,
        summary=f"还有{item_name}。" if has_item else f"现在没有{item_name}。",
        evidence_item_ids=[item.item_id for item in evidence_source],
        evidence_items=[_evidence_item(item) for item in evidence_source],
        missing_items=[] if has_item else [item_name],
        has_item=has_item,
        trace_id="trace_pending",
    )


def _build_missing_for_recipe_answer(
    *,
    subject_name: str,
    required_items: tuple[str, ...],
    items: list[StateMemoryItem],
) -> StateMemoryQueryAnswer:
    available_items = [item for item in items if _item_is_available(item)]
    available_names = {_normalize_item_name(item.name) for item in available_items}
    missing_items = [name for name in required_items if _normalize_item_name(name) not in available_names]
    summary = (
        f"做{subject_name}还缺{'、'.join(missing_items)}。"
        if missing_items
        else f"做{subject_name}的材料目前齐了。"
    )
    return StateMemoryQueryAnswer(
        answer_type="missing_for_recipe",
        subject_name=subject_name,
        summary=summary,
        evidence_item_ids=[item.item_id for item in available_items],
        evidence_items=[_evidence_item(item) for item in available_items],
        missing_items=missing_items,
        has_item=None,
        trace_id="trace_pending",
    )


def _evidence_item(item: StateMemoryItem) -> StateMemoryEvidenceItem:
    return StateMemoryEvidenceItem(
        item_id=item.item_id,
        name=item.name,
        quantity=item.quantity,
        unit=item.unit,
        status=item.status,
        source=item.source,
        last_seen_at=item.last_seen_at,
    )


def _item_is_available(item: StateMemoryItem) -> bool:
    if item.status != "active":
        return False
    return item.quantity is None or item.quantity > 0


def _normalize_item_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _match_recipe_question(question: str) -> tuple[str | None, tuple[str, ...]]:
    for recipe_name, required_items in _RECIPE_REQUIREMENTS.items():
        if recipe_name in question:
            return recipe_name, required_items
    return None, ()


def _extract_have_item_name(question: str) -> str | None:
    match = re.search(r"(?:我还有|还有|我有|有)(?P<item>.+?)(?:吗|么|嘛|\?|？)$", question.strip())
    if match is None:
        return None
    item_name = match.group("item").strip()
    if not item_name:
        return None
    return item_name
