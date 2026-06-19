from __future__ import annotations

from buddys_api.state_memory_models import (
    StateMemoryCaptureSource,
    StateMemoryDelta,
    StateMemoryPendingProposal,
    StateMemoryProposalApplyResult,
)
from buddys_api.state_memory_store import StateMemoryStore
from buddys_api.sync_store import SyncStore


class StateMemoryService:
    def __init__(
        self,
        *,
        store: StateMemoryStore,
        sync_store: SyncStore,
        provider: object,
    ) -> None:
        self.store = store
        self.sync_store = sync_store
        self.provider = provider

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

    def _parse_capture(self, *, source: StateMemoryCaptureSource, content: str) -> list[StateMemoryDelta]:
        parse_capture = getattr(self.provider, "parse_state_memory_capture", None)
        if parse_capture is None:
            raise ValueError("state_memory_capture_not_supported")
        deltas = parse_capture(source=source, content=content)
        if not deltas:
            raise ValueError("state_memory_capture_empty")
        return deltas
