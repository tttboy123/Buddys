from __future__ import annotations

from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.buddy_store import BuddyStore
from buddys_api.cost_meter import CostMeter
from buddys_api.policy import PermissionPolicy
from buddys_api.providers.mock_provider import MockProvider
from buddys_api.schemas import (
    ActionProposal,
    ActionTrace,
    Buddy,
    Intent,
    ModelUsage,
    ToolCall,
    new_id,
    now_iso,
)
from buddys_api.token_plan import UsageStore
from buddys_api.trace_store import TraceStore


class BuddysRuntime:
    def __init__(
        self,
        provider: MockProvider | None = None,
        adapter: MockHomeAdapter | None = None,
        policy: PermissionPolicy | None = None,
        trace_store: TraceStore | None = None,
        cost_meter: CostMeter | None = None,
        buddy_store: BuddyStore | None = None,
        usage_store: UsageStore | None = None,
    ) -> None:
        self.provider = provider or MockProvider()
        self.adapter = adapter or MockHomeAdapter()
        self.policy = policy or PermissionPolicy()
        self.trace_store = trace_store or TraceStore()
        self.cost_meter = cost_meter or CostMeter()
        self.buddy_store = buddy_store
        self.usage_store = usage_store
        self._buddies: dict[str, Buddy] = {}
        self._proposals: dict[str, ActionProposal] = {}

    def create_home_buddy(self, user_id: str, created_via: str = "legacy") -> Buddy:
        if self.buddy_store is not None:
            buddy = self.buddy_store.create_buddy(user_id=user_id, created_via=created_via)
            self._buddies[buddy.buddy_id] = buddy
            return buddy

        buddy = Buddy(
            buddy_id=new_id("buddy"),
            user_id=user_id,
            name="Home Buddy",
            space_id="home",
            device_id=None,
            autonomy_level="A",
            status="idle",
        )
        self._buddies[buddy.buddy_id] = buddy
        return buddy

    def submit_message(self, buddy_id: str, user_id: str, text: str) -> ActionProposal:
        buddy = self._get_buddy(buddy_id)
        return self._submit_message_for_buddy(buddy=buddy, user_id=user_id, text=text)

    def submit_legacy_message(self, buddy_id: str, user_id: str, text: str) -> ActionProposal:
        buddy = self._get_legacy_buddy(buddy_id)
        return self._submit_message_for_buddy(buddy=buddy, user_id=user_id, text=text)

    def _submit_message_for_buddy(self, buddy: Buddy, user_id: str, text: str) -> ActionProposal:
        if buddy.user_id != user_id:
            raise PermissionError(f"user cannot access buddy: {buddy.buddy_id}")

        trace_id = new_id("trace")
        turn_id = new_id("turn")
        plan = self.provider.plan(text=text, buddy_id=buddy.buddy_id, trace_id=trace_id)
        proposal = plan.proposal
        decision = self.policy.evaluate(proposal, user_confirmation=None)
        input_tokens = len(text)
        output_tokens = len(proposal.summary)
        if self.usage_store is not None:
            self.usage_store.record_usage(
                user_id=user_id,
                trace_id=trace_id,
                buddy_id=buddy.buddy_id,
                provider_id=self.provider.provider,
                model_id=self.provider.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                source="legacy_message",
            )
        cost_event = self.cost_meter.record_model_call(
            trace_id=trace_id,
            buddy_id=buddy.buddy_id,
            provider=self.provider.provider,
            model=self.provider.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        trace = ActionTrace(
            trace_id=trace_id,
            user_id=user_id,
            buddy_id=buddy.buddy_id,
            space_id=buddy.space_id,
            device_id=buddy.device_id,
            turn_id=turn_id,
            intent=Intent(name=plan.intent_name, summary=text, confidence=1.0, source="user_text"),
            proposal=proposal,
            permission_decision=decision,
            model_usage=ModelUsage(
                provider=self.provider.provider,
                model=self.provider.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=0,
            ),
            cost_refs=[cost_event.cost_event_id],
        )
        self._proposals[proposal.proposal_id] = proposal
        self.trace_store.save(trace)
        return proposal

    def confirm_proposal(self, proposal_id: str, approved: bool) -> ActionTrace:
        proposal = self._get_proposal(proposal_id)
        trace = self.trace_store.get(proposal.trace_id)
        confirmation = "approved" if approved else "rejected"
        decision = self.policy.evaluate(proposal, user_confirmation=confirmation)

        trace.permission_decision = decision
        trace.updated_at = now_iso()

        if decision.policy_result == "allow":
            tool_call = ToolCall(
                tool_call_id=new_id("tool_call"),
                adapter_id=self.adapter.adapter_id,
                tool_id=proposal.tool_id or "",
                action=proposal.action or "",
                args=proposal.args,
            )
            tool_result = self.adapter.execute(tool_call)
            proposal.executed = tool_result.status == "success"
            trace.tool_call = tool_call
            trace.tool_result = tool_result

        trace.proposal = proposal
        self.trace_store.save(trace)
        return trace

    def _get_buddy(self, buddy_id: str) -> Buddy:
        if self.buddy_store is not None:
            return self.buddy_store.get(buddy_id)
        try:
            return self._buddies[buddy_id]
        except KeyError as exc:
            raise KeyError(f"buddy not found: {buddy_id}") from exc

    def _get_legacy_buddy(self, buddy_id: str) -> Buddy:
        if self.buddy_store is not None:
            return self.buddy_store.get_legacy(buddy_id)
        return self._get_buddy(buddy_id)

    def _get_proposal(self, proposal_id: str) -> ActionProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"proposal not found: {proposal_id}") from exc
