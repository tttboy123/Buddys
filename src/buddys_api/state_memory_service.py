from __future__ import annotations

import os
import re

from buddys_api.buddy_store import BuddyStore
from buddys_api.cost_meter import CostMeter
from buddys_api.engagement_metrics_store import EngagementMetricsStore
from buddys_api.provider_models import (
    MINIMAX_OPENAI_BASE_URL,
    SYSTEM_DEFAULT_MODEL_ENV_VAR,
    SYSTEM_DEFAULT_MODEL_NAME,
    SYSTEM_DEFAULT_PROVIDER_ENV_VAR,
    SYSTEM_DEFAULT_PROVIDER_ID,
    SYSTEM_DEFAULT_TOKEN_PLAN_ENV_VAR,
)
from buddys_api.provider_store import ProviderStore
from buddys_api.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
    ParsedStateMemoryCapture,
    ProviderConfigurationError,
    ProviderUsage,
    StateMemoryProviderError,
    StateMemoryQueryUnderstanding,
)
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
from buddys_api.token_plan import TokenPlanLimitExceeded, UsageStore
from buddys_api.trace_store import TraceStore


_RECIPE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "红烧肉": ("五花肉", "生抽", "老抽", "八角", "冰糖"),
}

_EQUIVALENT_ITEM_NAME_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"番茄", "西红柿"}),
    frozenset({"土豆", "马铃薯"}),
)

_GENERIC_ITEM_NAME_EXPANSIONS: dict[str, frozenset[str]] = {
    "猪肉": frozenset({"猪肉", "五花肉", "瘦肉", "里脊肉", "梅花肉"}),
}

_COMMON_ITEM_PREFIX_MODIFIERS: tuple[str, ...] = (
    "无糖",
    "低脂",
    "全脂",
    "脱脂",
    "原味",
    "纯",
    "鲜",
)

_QUANTITY_NUMBER_PATTERN = r"(?:\d+(?:\.\d+)?|半|几|零|〇|一|二|两|俩|仨|三|四|五|六|七|八|九|十|百)"
_QUANTITY_UNIT_PATTERN = (
    r"(?:个|盒|瓶|包|袋|斤|公斤|千克|克|kg|g|升|l|ml|毫升|支|杯|罐|片|块|根|只|双|桶|听|张|盘|份|箱|颗|条|瓣|把)"
)
_ITEM_PREFIX_MODIFIER_PATTERN = rf"(?:{'|'.join(sorted(_COMMON_ITEM_PREFIX_MODIFIERS, key=len, reverse=True))})?"


class StateMemoryService:
    def __init__(
        self,
        *,
        store: StateMemoryStore,
        sync_store: SyncStore,
        provider: object,
        trace_store: TraceStore,
        cost_meter: CostMeter,
        buddy_store: BuddyStore | None = None,
        provider_store: ProviderStore | None = None,
        usage_store: UsageStore | None = None,
        provider_factory: object | None = None,
        engagement_metrics_store: EngagementMetricsStore | None = None,
    ) -> None:
        self.store = store
        self.sync_store = sync_store
        self.provider = provider
        self.trace_store = trace_store
        self.cost_meter = cost_meter
        self.buddy_store = buddy_store
        self.provider_store = provider_store
        self.usage_store = usage_store
        self.provider_factory = provider_factory
        self.engagement_metrics_store = engagement_metrics_store

    def create_capture_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        source: StateMemoryCaptureSource,
        content: str,
        image_base64: str | None = None,
        image_media_type: str | None = None,
    ) -> tuple[StateMemoryPendingProposal, int]:
        provider = self._provider_for_user(user_id)
        normalized_content = _normalized_capture_content(source=source, content=content)
        self._ensure_preflight_capacity(
            user_id=user_id,
            provider=provider,
            text=normalized_content,
            image_base64=image_base64,
        )
        space_id, device_id = self._capture_trace_context(user_id=user_id, buddy_id=buddy_id)
        try:
            deltas, unrecognized, usage = self._parse_capture(
                provider=provider,
                source=source,
                content=normalized_content,
                image_base64=image_base64,
                image_media_type=image_media_type,
            )
        except StateMemoryProviderError as exc:
            self._record_provider_failure(
                user_id=user_id,
                buddy_id=buddy_id,
                space_id=space_id,
                device_id=device_id,
                provider=provider,
                usage=exc.usage,
                intent_name="state_memory_capture",
                summary=normalized_content,
                failure_code=exc.code,
            )
            raise
        try:
            self._ensure_actual_capture_capacity(user_id=user_id, usage=usage)
        except TokenPlanLimitExceeded:
            self._record_provider_failure(
                user_id=user_id,
                buddy_id=buddy_id,
                space_id=space_id,
                device_id=device_id,
                provider=provider,
                usage=usage,
                intent_name="state_memory_capture",
                summary=normalized_content,
                failure_code="token_plan_limit_exceeded",
            )
            raise
        proposal = self.store.save_pending_proposal(
            user_id=user_id,
            buddy_id=buddy_id,
            source=source,
            content=normalized_content,
            deltas=_sanitize_capture_deltas(source=source, content=normalized_content, deltas=deltas),
            unrecognized=unrecognized,
        )
        trace_id = self._record_capture_trace(
            user_id=user_id,
            buddy_id=buddy_id,
            proposal=proposal,
            content=normalized_content,
            space_id=space_id,
            device_id=device_id,
            provider=provider,
            usage=usage,
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
                "trace_id": trace_id,
                "source": source,
                "delta_count": len(proposal.deltas),
                "item_names": [delta.item_name for delta in proposal.deltas],
            },
        )
        self._record_engagement_event(
            user_id=user_id,
            buddy_id=buddy_id,
            event_type="capture_submitted",
            capture_source=str(source),
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
        self._record_engagement_event(
            user_id=user_id,
            buddy_id=buddy_id,
            event_type="proposal_confirmed",
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
        self._record_engagement_event(
            user_id=user_id,
            buddy_id=buddy_id,
            event_type="proposal_corrected",
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
        provider = self._provider_for_user(user_id)
        self._ensure_preflight_capacity(user_id=user_id, provider=provider, text=question)
        if hasattr(provider, "understand_state_memory_query"):
            understanding = None
            try:
                understanding = provider.understand_state_memory_query(question=question)
                self._ensure_actual_capture_capacity(user_id=user_id, usage=understanding.usage)
                answer = self._build_answer_from_understanding(understanding=understanding, items=items)
            except StateMemoryProviderError as exc:
                self._record_provider_failure(
                    user_id=user_id,
                    buddy_id=buddy_id,
                    space_id=space_id,
                    device_id=device_id,
                    provider=provider,
                    usage=exc.usage or (understanding.usage if understanding is not None else None),
                    intent_name="state_memory_query",
                    summary=question,
                    failure_code=exc.code,
                )
                raise
            except TokenPlanLimitExceeded:
                self._record_provider_failure(
                    user_id=user_id,
                    buddy_id=buddy_id,
                    space_id=space_id,
                    device_id=device_id,
                    provider=provider,
                    usage=understanding.usage if understanding is not None else None,
                    intent_name="state_memory_query",
                    summary=question,
                    failure_code="token_plan_limit_exceeded",
                )
                raise
        else:
            understanding = None
            recipe_name, required_items = _match_recipe_question(question)
            if recipe_name is not None:
                answer = _build_missing_for_recipe_answer(
                    subject_name=recipe_name,
                    required_items=list(required_items),
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
            provider=provider,
            usage=understanding.usage if understanding is not None else None,
        )
        self._record_engagement_event(
            user_id=user_id,
            buddy_id=buddy_id,
            event_type="query_answered",
            answer_type=answer.answer_type,
        )
        payload = answer.model_dump(mode="json")
        payload["trace_id"] = trace_id
        return StateMemoryQueryAnswer.model_validate(payload)

    def _record_engagement_event(
        self,
        *,
        user_id: str,
        buddy_id: str,
        event_type: str,
        capture_source: str | None = None,
        answer_type: str | None = None,
    ) -> None:
        if self.engagement_metrics_store is None:
            return
        self.engagement_metrics_store.record_event(
            user_id=user_id,
            buddy_id=buddy_id,
            event_type=event_type,
            capture_source=capture_source,
            answer_type=answer_type,
        )

    def _parse_capture(
        self,
        *,
        provider: object,
        source: StateMemoryCaptureSource,
        content: str,
        image_base64: str | None = None,
        image_media_type: str | None = None,
    ) -> tuple[list[StateMemoryDelta], list[str], ProviderUsage | None]:
        parse_capture = getattr(provider, "parse_state_memory_capture", None)
        if parse_capture is None:
            raise ValueError("state_memory_capture_not_supported")
        if image_base64 is not None or image_media_type is not None:
            parsed = parse_capture(
                source=source,
                content=content,
                image_base64=image_base64,
                image_media_type=image_media_type,
            )
        else:
            parsed = parse_capture(source=source, content=content)
        if isinstance(parsed, ParsedStateMemoryCapture):
            deltas = parsed.deltas
            unrecognized = parsed.unrecognized
            usage = parsed.usage
        elif isinstance(parsed, tuple):
            deltas, unrecognized = parsed
            usage = None
        else:
            deltas = parsed
            unrecognized = []
            usage = None
        if not deltas and not unrecognized:
            raise ValueError("state_memory_capture_empty")
        return deltas, unrecognized, usage

    def _record_query_trace(
        self,
        *,
        user_id: str,
        buddy_id: str,
        space_id: str,
        device_id: str | None,
        question: str,
        answer: StateMemoryQueryAnswer,
        provider: object,
        usage: ProviderUsage | None,
    ) -> str:
        trace_id = new_id("trace")
        provider_name = getattr(provider, "provider", "state_memory")
        model_name = getattr(provider, "model", "state_memory-query-v0")
        if usage is None:
            input_tokens = len(question)
            output_tokens = len(answer.summary)
            estimated = True
        else:
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            estimated = usage.estimated
        if self.usage_store is not None:
            self.usage_store.record_usage(
                user_id=user_id,
                trace_id=trace_id,
                buddy_id=buddy_id,
                provider_id=provider_name,
                model_id=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated=estimated,
                source="state_memory_query",
                enforce_hard_limit=False,
            )
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

    def _provider_for_user(self, user_id: str) -> object:
        if self.provider_store is None:
            return self.provider
        real_configs = [
            config for config in self.provider_store.list_configs(user_id) if config.provider_type == "openai_compatible"
        ]
        if not real_configs:
            default_config = _system_default_provider_config()
            if default_config is None:
                return self.provider
            if callable(self.provider_factory):
                return self.provider_factory(default_config)
            return OpenAICompatibleProvider(
                provider_id=default_config.provider_id,
                base_url=default_config.base_url or MINIMAX_OPENAI_BASE_URL,
                api_key_env_var=default_config.api_key_env_var or SYSTEM_DEFAULT_PROVIDER_ENV_VAR,
                model=default_config.default_model,
            )
        if len(real_configs) > 1:
            raise ProviderConfigurationError("provider_selection_ambiguous")
        config = real_configs[0]
        if not config.configured:
            raise ProviderConfigurationError("provider_not_configured")
        if callable(self.provider_factory):
            return self.provider_factory(config)
        return OpenAICompatibleProvider(
            provider_id=config.provider_id,
            base_url=config.base_url or MINIMAX_OPENAI_BASE_URL,
            api_key_env_var=config.api_key_env_var or "OPENAI_API_KEY",
            model=config.default_model,
        )

    def _ensure_preflight_capacity(
        self,
        *,
        user_id: str,
        provider: object,
        text: str,
        image_base64: str | None = None,
    ) -> None:
        if self.usage_store is None:
            return
        if not getattr(provider, "requires_preflight_hard_limit", False):
            return
        attempted_tokens = (
            max(len(text.strip()), 1)
            + max(getattr(provider, "preflight_token_reserve", 0), 0)
            + _estimated_image_preflight_tokens(image_base64)
        )
        self.usage_store.ensure_within_hard_limit(user_id=user_id, attempted_tokens=attempted_tokens)

    def _ensure_actual_capture_capacity(self, *, user_id: str, usage: ProviderUsage | None) -> None:
        if self.usage_store is None or usage is None:
            return
        self.usage_store.ensure_within_hard_limit(
            user_id=user_id,
            attempted_tokens=usage.input_tokens + usage.output_tokens,
        )

    def _capture_trace_context(self, *, user_id: str, buddy_id: str) -> tuple[str, str | None]:
        if self.buddy_store is None:
            return "auth_space", None
        buddy = self.buddy_store.get_for_user(buddy_id=buddy_id, user_id=user_id, created_via="auth")
        return buddy.space_id, buddy.device_id

    def _record_capture_trace(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal: StateMemoryPendingProposal,
        content: str,
        space_id: str,
        device_id: str | None,
        provider: object,
        usage: ProviderUsage | None,
    ) -> str:
        trace_id = new_id("trace")
        provider_name = getattr(provider, "provider", "state_memory")
        model_name = getattr(provider, "model", "state_memory-capture-v0")
        if usage is None:
            input_tokens = len(content)
            output_tokens = max(len(proposal.deltas), 1)
            estimated = True
        else:
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            estimated = usage.estimated
        if self.usage_store is not None:
            self.usage_store.record_usage(
                user_id=user_id,
                trace_id=trace_id,
                buddy_id=buddy_id,
                provider_id=provider_name,
                model_id=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated=estimated,
                source="state_memory_capture",
                enforce_hard_limit=False,
            )
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
                name="state_memory_capture",
                summary=content,
                confidence=1.0,
                source="user_text",
            ),
            proposal=ActionProposal(
                proposal_id=proposal.proposal_id,
                trace_id=trace_id,
                buddy_id=buddy_id,
                action_type="memory_proposal",
                summary=f"Captured {len(proposal.deltas)} state-memory deltas.",
                requires_confirmation=True,
                tool_id=None,
                action=None,
                args={
                    "source": proposal.source,
                    "content": proposal.content,
                    "delta_count": len(proposal.deltas),
                    "item_names": [delta.item_name for delta in proposal.deltas],
                    "unrecognized": proposal.unrecognized,
                },
                risk_level="none",
            ),
            permission_decision=PermissionDecision(
                policy_result="not_required",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="State-memory capture creates a proposal and requires explicit confirmation before state changes.",
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

    def _build_answer_from_understanding(
        self,
        *,
        understanding: StateMemoryQueryUnderstanding,
        items: list[StateMemoryItem],
    ) -> StateMemoryQueryAnswer:
        if understanding.answer_type == "missing_for_recipe":
            subject_name = (understanding.subject_name or "").strip()
            if not subject_name or not understanding.required_items:
                raise StateMemoryProviderError("model_response_invalid")
            return _build_missing_for_recipe_answer(
                subject_name=subject_name,
                required_items=understanding.required_items,
                items=items,
            )
        if understanding.answer_type == "have_item":
            subject_name = (understanding.subject_name or "").strip()
            if not subject_name:
                raise StateMemoryProviderError("model_response_invalid")
            return _build_have_item_answer(item_name=subject_name, items=items)
        raise StateMemoryProviderError("state_memory_query_unsupported")

    def _record_provider_failure(
        self,
        *,
        user_id: str,
        buddy_id: str,
        space_id: str,
        device_id: str | None,
        provider: object,
        usage: ProviderUsage | None,
        intent_name: str,
        summary: str,
        failure_code: str,
    ) -> None:
        if failure_code in {"provider_not_configured", "provider_selection_ambiguous"}:
            return
        trace_id = new_id("trace")
        provider_name = getattr(provider, "provider", "state_memory")
        model_name = getattr(provider, "model", f"{intent_name}-v0")
        cost_refs: list[str] = []
        model_usage = None
        if usage is not None:
            if self.usage_store is not None:
                self.usage_store.record_usage(
                    user_id=user_id,
                    trace_id=trace_id,
                    buddy_id=buddy_id,
                    provider_id=provider_name,
                    model_id=model_name,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    estimated=usage.estimated,
                    source=intent_name,
                    enforce_hard_limit=False,
                )
            cost_event = self.cost_meter.record_model_call(
                trace_id=trace_id,
                buddy_id=buddy_id,
                provider=provider_name,
                model=model_name,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
            cost_refs = [cost_event.cost_event_id]
            model_usage = ModelUsage(
                provider=provider_name,
                model=model_name,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                latency_ms=0,
            )
        trace = ActionTrace(
            trace_id=trace_id,
            user_id=user_id,
            buddy_id=buddy_id,
            space_id=space_id,
            device_id=device_id,
            turn_id=new_id("turn"),
            intent=Intent(
                name=intent_name,
                summary=summary,
                confidence=1.0,
                source="user_text",
            ),
            proposal=None,
            permission_decision=PermissionDecision(
                policy_result="not_required",
                confirmation_result="not_requested",
                decided_by="policy",
                reason="State-memory model call failed before a user-visible proposal or answer could be produced.",
            ),
            model_usage=model_usage,
            cost_refs=cost_refs,
            failure_class=failure_code,
        )
        self.trace_store.save(trace)


def _build_have_item_answer(*, item_name: str, items: list[StateMemoryItem]) -> StateMemoryQueryAnswer:
    matching_items = [item for item in items if _item_matches_requested_name(item_name=item_name, candidate_name=item.name)]
    evidence_source = [item for item in matching_items if _item_is_available(item)] or matching_items
    has_item = any(_item_is_available(item) for item in matching_items)
    all_available_quantities_unknown = bool(evidence_source) and all(item.quantity is None for item in evidence_source)
    return StateMemoryQueryAnswer(
        answer_type="have_item",
        subject_name=item_name,
        summary=(
            f"还有{item_name}，但数量未输入。"
            if has_item and all_available_quantities_unknown
            else (f"还有{item_name}。" if has_item else f"现在没有{item_name}。")
        ),
        evidence_item_ids=[item.item_id for item in evidence_source],
        evidence_items=[_evidence_item(item) for item in evidence_source],
        missing_items=[] if has_item else [item_name],
        has_item=has_item,
        trace_id="trace_pending",
    )


def _build_missing_for_recipe_answer(
    *,
    subject_name: str,
    required_items: list[str] | tuple[str, ...],
    items: list[StateMemoryItem],
) -> StateMemoryQueryAnswer:
    available_items = [
        item
        for item in items
        if _item_is_available(item)
        and any(_item_matches_requested_name(item_name=required_name, candidate_name=item.name) for required_name in required_items)
    ]
    missing_items = [
        name
        for name in required_items
        if not any(
            _item_is_available(item) and _item_matches_requested_name(item_name=name, candidate_name=item.name)
            for item in items
        )
    ]
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


def _sanitize_capture_deltas(
    *,
    source: StateMemoryCaptureSource,
    content: str,
    deltas: list[StateMemoryDelta],
) -> list[StateMemoryDelta]:
    if source == "photo":
        return deltas
    sanitized: list[StateMemoryDelta] = []
    for delta in deltas:
        if delta.operation == "upsert" and not _content_supports_quantity(content=content, item_name=delta.item_name):
            sanitized.append(delta.model_copy(update={"quantity": None, "unit": None}))
            continue
        sanitized.append(delta)
    return sanitized


def _content_supports_quantity(*, content: str, item_name: str) -> bool:
    normalized_item_name = _normalize_item_name(item_name)
    if not normalized_item_name:
        return False
    quantity_with_unit_pattern = rf"{_QUANTITY_NUMBER_PATTERN}\s*{_QUANTITY_UNIT_PATTERN}"
    quantity_without_unit_pattern = rf"{_QUANTITY_NUMBER_PATTERN}"
    for candidate_name in sorted(_quantity_evidence_name_forms(item_name), key=len, reverse=True):
        item_pattern = re.escape(candidate_name)
        before_item_with_unit = rf"{quantity_with_unit_pattern}\s*{_ITEM_PREFIX_MODIFIER_PATTERN}{item_pattern}"
        after_item_with_unit = rf"{item_pattern}\s*{quantity_with_unit_pattern}"
        before_item_without_unit = rf"{quantity_without_unit_pattern}\s*{item_pattern}"
        after_item_without_unit = rf"{item_pattern}\s*{quantity_without_unit_pattern}"
        if re.search(before_item_with_unit, content, flags=re.IGNORECASE) is not None:
            return True
        if re.search(after_item_with_unit, content, flags=re.IGNORECASE) is not None:
            return True
        if re.search(before_item_without_unit, content, flags=re.IGNORECASE) is not None:
            return True
        if re.search(after_item_without_unit, content, flags=re.IGNORECASE) is not None:
            return True
    return False


def _normalize_item_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _item_matches_requested_name(*, item_name: str, candidate_name: str) -> bool:
    return bool(_candidate_name_forms(candidate_name) & _requested_name_forms(item_name))


def _candidate_name_forms(candidate_name: str) -> set[str]:
    normalized = _normalize_item_name(candidate_name)
    if not normalized:
        return set()
    forms = {normalized}
    for prefix in _COMMON_ITEM_PREFIX_MODIFIERS:
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            forms.add(normalized[len(prefix) :])
    return forms


def _quantity_evidence_name_forms(item_name: str) -> set[str]:
    normalized = _normalize_item_name(item_name)
    if not normalized:
        return set()
    forms = set()
    forms.update(_candidate_name_forms(item_name))
    forms.update(_requested_name_forms(item_name))
    for generic_name, members in _GENERIC_ITEM_NAME_EXPANSIONS.items():
        if normalized == generic_name or normalized in members:
            forms.add(generic_name)
            forms.update(members)
    return forms


def _requested_name_forms(item_name: str) -> set[str]:
    normalized = _normalize_item_name(item_name)
    forms = {normalized}
    for group in _EQUIVALENT_ITEM_NAME_GROUPS:
        if normalized in group:
            forms.update(group)
    forms.update(_GENERIC_ITEM_NAME_EXPANSIONS.get(normalized, ()))
    return forms


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


def _normalized_capture_content(*, source: StateMemoryCaptureSource, content: str) -> str:
    stripped = content.strip()
    if stripped:
        return stripped
    if source == "photo":
        return "photo capture"
    return stripped


def _estimated_image_preflight_tokens(image_base64: str | None) -> int:
    if not image_base64:
        return 0
    # MiniMax image token usage varies with asset size and content. For preflight we
    # conservatively reserve against the uploaded payload itself so near-limit users
    # are blocked before a real vision request leaves the process.
    return max((len(image_base64.strip()) + 3) // 4, 1)


def _system_default_provider_config():
    from buddys_api.provider_models import ProviderConfigPublic

    api_key_env_var = None
    if os.getenv(SYSTEM_DEFAULT_PROVIDER_ENV_VAR, "").strip():
        api_key_env_var = SYSTEM_DEFAULT_PROVIDER_ENV_VAR
    elif os.getenv(SYSTEM_DEFAULT_TOKEN_PLAN_ENV_VAR, "").strip():
        api_key_env_var = SYSTEM_DEFAULT_TOKEN_PLAN_ENV_VAR
    if api_key_env_var is None:
        return None
    return ProviderConfigPublic(
        provider_id=SYSTEM_DEFAULT_PROVIDER_ID,
        display_name="System-managed MiniMax default",
        provider_type="openai_compatible",
        base_url=MINIMAX_OPENAI_BASE_URL,
        api_key_env_var=api_key_env_var,
        default_model=os.getenv(SYSTEM_DEFAULT_MODEL_ENV_VAR, "").strip() or SYSTEM_DEFAULT_MODEL_NAME,
        configured=True,
        created_at="system",
        updated_at="system",
    )
