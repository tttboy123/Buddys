from __future__ import annotations

import json
import sqlite3

from buddys_api.schemas import new_id, now_iso
from buddys_api.state_memory_models import (
    StateMemoryDelta,
    StateMemoryHistoryEntry,
    StateMemoryItem,
    StateMemoryProposalApplyResult,
    StateMemoryPendingProposal,
)


class StateMemoryStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_item(
        self,
        *,
        user_id: str,
        buddy_id: str,
        name: str,
        source: str,
        category: str | None = None,
        quantity: float | None = None,
        unit: str | None = None,
        confidence: float | None = None,
        status: str = "active",
    ) -> StateMemoryItem:
        timestamp = now_iso()
        item = StateMemoryItem(
            item_id=new_id("state_item"),
            user_id=user_id,
            buddy_id=buddy_id,
            name=name,
            normalized_name=_normalize_item_name(name),
            category=category,
            quantity=quantity,
            unit=unit,
            source=source,
            confidence=confidence,
            status=status,
            captured_at=timestamp,
            last_seen_at=timestamp,
            updated_at=timestamp,
        )
        with self.connection:
            self._insert_item_locked(item)
        return item

    def list_items(self, *, user_id: str, buddy_id: str) -> list[StateMemoryItem]:
        rows = self.connection.execute(
            """
            SELECT item_id, user_id, buddy_id, name, normalized_name, category,
                   quantity, unit, source, confidence, status,
                   captured_at, last_seen_at, updated_at
            FROM state_memory_items
            WHERE user_id = ? AND buddy_id = ?
            ORDER BY normalized_name, item_id
            """,
            (user_id, buddy_id),
        ).fetchall()
        return [_item_from_row(row) for row in rows]

    def append_history(
        self,
        *,
        user_id: str,
        buddy_id: str,
        item_id: str,
        item_name: str,
        change_type: str,
        change_source: str,
        quantity_before: float | None,
        quantity_after: float | None,
        unit_before: str | None,
        unit_after: str | None,
        proposal_id: str | None = None,
    ) -> StateMemoryHistoryEntry:
        entry = StateMemoryHistoryEntry(
            history_id=new_id("state_history"),
            item_id=item_id,
            user_id=user_id,
            buddy_id=buddy_id,
            item_name=item_name,
            change_type=change_type,
            change_source=change_source,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            unit_before=unit_before,
            unit_after=unit_after,
            proposal_id=proposal_id,
            created_at=now_iso(),
        )
        with self.connection:
            self._insert_history_locked(entry)
        return entry

    def list_history(self, *, user_id: str, buddy_id: str) -> list[StateMemoryHistoryEntry]:
        rows = self.connection.execute(
            """
            SELECT history_id, item_id, user_id, buddy_id, item_name,
                   change_type, change_source, quantity_before, quantity_after,
                   unit_before, unit_after, proposal_id, created_at
            FROM state_memory_history
            WHERE user_id = ? AND buddy_id = ?
            ORDER BY created_at, history_id
            """,
            (user_id, buddy_id),
        ).fetchall()
        return [_history_from_row(row) for row in rows]

    def save_pending_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        source: str,
        content: str,
        deltas: list[StateMemoryDelta],
        status: str = "pending",
    ) -> StateMemoryPendingProposal:
        timestamp = now_iso()
        proposal = StateMemoryPendingProposal(
            proposal_id=new_id("state_proposal"),
            user_id=user_id,
            buddy_id=buddy_id,
            source=source,
            content=content,
            deltas=deltas,
            status=status,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.connection:
            self._insert_proposal_locked(proposal)
        return proposal

    def list_pending_proposals(self, *, user_id: str, buddy_id: str) -> list[StateMemoryPendingProposal]:
        rows = self.connection.execute(
            """
            SELECT proposal_id, user_id, buddy_id, source, content, deltas_json,
                   status, created_at, updated_at
            FROM state_memory_pending_proposals
            WHERE user_id = ? AND buddy_id = ? AND status = 'pending'
            ORDER BY created_at, proposal_id
            """,
            (user_id, buddy_id),
        ).fetchall()
        return [_proposal_from_row(row) for row in rows]

    def confirm_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
    ) -> StateMemoryProposalApplyResult:
        proposal = self._get_owned_proposal(user_id=user_id, buddy_id=buddy_id, proposal_id=proposal_id)
        self._require_pending(proposal)
        return self._apply_proposal(proposal=proposal, deltas=proposal.deltas)

    def reject_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
    ) -> StateMemoryPendingProposal:
        proposal = self._get_owned_proposal(user_id=user_id, buddy_id=buddy_id, proposal_id=proposal_id)
        self._require_pending(proposal)
        with self.connection:
            return self._update_proposal_locked(proposal, status="rejected")

    def correct_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
        corrected_deltas: list[StateMemoryDelta],
    ) -> StateMemoryProposalApplyResult:
        proposal = self._get_owned_proposal(user_id=user_id, buddy_id=buddy_id, proposal_id=proposal_id)
        self._require_pending(proposal)
        return self._apply_proposal(proposal=proposal, deltas=corrected_deltas)

    def get_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
    ) -> StateMemoryPendingProposal:
        return self._get_owned_proposal(user_id=user_id, buddy_id=buddy_id, proposal_id=proposal_id)

    def _apply_proposal(
        self,
        *,
        proposal: StateMemoryPendingProposal,
        deltas: list[StateMemoryDelta],
    ) -> StateMemoryProposalApplyResult:
        applied_items: list[StateMemoryItem] = []
        history_entries: list[StateMemoryHistoryEntry] = []
        with self.connection:
            updated_proposal = self._update_proposal_locked(proposal, status="confirmed", deltas=deltas)
            for delta in deltas:
                item, history_entry = self._apply_delta_locked(proposal=updated_proposal, delta=delta)
                applied_items.append(item)
                history_entries.append(history_entry)
        return StateMemoryProposalApplyResult(
            proposal=updated_proposal,
            items=applied_items,
            history_entries=history_entries,
            applied_delta_count=len(applied_items),
        )

    def _apply_delta_locked(
        self,
        *,
        proposal: StateMemoryPendingProposal,
        delta: StateMemoryDelta,
    ) -> tuple[StateMemoryItem, StateMemoryHistoryEntry]:
        current = self._find_item_locked(
            user_id=proposal.user_id,
            buddy_id=proposal.buddy_id,
            normalized_name=_normalize_item_name(delta.item_name),
        )
        timestamp = now_iso()
        if current is None:
            item = StateMemoryItem(
                item_id=new_id("state_item"),
                user_id=proposal.user_id,
                buddy_id=proposal.buddy_id,
                name=delta.item_name,
                normalized_name=_normalize_item_name(delta.item_name),
                category=delta.category,
                quantity=_quantity_after_for_new_item(delta),
                unit=delta.unit,
                source=delta.source,
                confidence=delta.confidence,
                status=_status_after(current_status=None, delta=delta, quantity_after=_quantity_after_for_new_item(delta)),
                captured_at=timestamp,
                last_seen_at=timestamp,
                updated_at=timestamp,
            )
            self._insert_item_locked(item)
            history_entry = self._build_history_entry(
                item=item,
                delta=delta,
                proposal_id=proposal.proposal_id,
                quantity_before=None,
                unit_before=None,
            )
            self._insert_history_locked(history_entry)
            return item, history_entry

        quantity_after = _quantity_after_for_existing_item(current=current, delta=delta)
        updated_item = StateMemoryItem(
            item_id=current.item_id,
            user_id=current.user_id,
            buddy_id=current.buddy_id,
            name=delta.item_name,
            normalized_name=current.normalized_name,
            category=delta.category or current.category,
            quantity=quantity_after,
            unit=delta.unit or current.unit,
            source=delta.source,
            confidence=delta.confidence if delta.confidence is not None else current.confidence,
            status=_status_after(current_status=current.status, delta=delta, quantity_after=quantity_after),
            captured_at=current.captured_at,
            last_seen_at=timestamp,
            updated_at=timestamp,
        )
        self._update_item_locked(updated_item)
        history_entry = self._build_history_entry(
            item=updated_item,
            delta=delta,
            proposal_id=proposal.proposal_id,
            quantity_before=current.quantity,
            unit_before=current.unit,
        )
        self._insert_history_locked(history_entry)
        return updated_item, history_entry

    def _build_history_entry(
        self,
        *,
        item: StateMemoryItem,
        delta: StateMemoryDelta,
        proposal_id: str,
        quantity_before: float | None,
        unit_before: str | None,
    ) -> StateMemoryHistoryEntry:
        return StateMemoryHistoryEntry(
            history_id=new_id("state_history"),
            item_id=item.item_id,
            user_id=item.user_id,
            buddy_id=item.buddy_id,
            item_name=item.name,
            change_type=delta.operation,
            change_source=delta.source,
            quantity_before=quantity_before,
            quantity_after=item.quantity,
            unit_before=unit_before,
            unit_after=item.unit,
            proposal_id=proposal_id,
            created_at=now_iso(),
        )

    def _get_owned_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        proposal_id: str,
    ) -> StateMemoryPendingProposal:
        row = self.connection.execute(
            """
            SELECT proposal_id, user_id, buddy_id, source, content, deltas_json,
                   status, created_at, updated_at
            FROM state_memory_pending_proposals
            WHERE proposal_id = ? AND user_id = ? AND buddy_id = ?
            """,
            (proposal_id, user_id, buddy_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        return _proposal_from_row(row)

    def _require_pending(self, proposal: StateMemoryPendingProposal) -> None:
        if proposal.status != "pending":
            raise ValueError("proposal_not_pending")

    def _find_item_locked(self, *, user_id: str, buddy_id: str, normalized_name: str) -> StateMemoryItem | None:
        row = self.connection.execute(
            """
            SELECT item_id, user_id, buddy_id, name, normalized_name, category,
                   quantity, unit, source, confidence, status,
                   captured_at, last_seen_at, updated_at
            FROM state_memory_items
            WHERE user_id = ? AND buddy_id = ? AND normalized_name = ?
            ORDER BY updated_at DESC, item_id DESC
            LIMIT 1
            """,
            (user_id, buddy_id, normalized_name),
        ).fetchone()
        if row is None:
            return None
        return _item_from_row(row)

    def _insert_item_locked(self, item: StateMemoryItem) -> None:
        self.connection.execute(
            """
            INSERT INTO state_memory_items (
                item_id, user_id, buddy_id, name, normalized_name, category,
                quantity, unit, source, confidence, status,
                captured_at, last_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.item_id,
                item.user_id,
                item.buddy_id,
                item.name,
                item.normalized_name,
                item.category,
                item.quantity,
                item.unit,
                item.source,
                item.confidence,
                item.status,
                item.captured_at,
                item.last_seen_at,
                item.updated_at,
            ),
        )

    def _update_item_locked(self, item: StateMemoryItem) -> None:
        self.connection.execute(
            """
            UPDATE state_memory_items
            SET name = ?, category = ?, quantity = ?, unit = ?, source = ?,
                confidence = ?, status = ?, last_seen_at = ?, updated_at = ?
            WHERE item_id = ? AND user_id = ? AND buddy_id = ?
            """,
            (
                item.name,
                item.category,
                item.quantity,
                item.unit,
                item.source,
                item.confidence,
                item.status,
                item.last_seen_at,
                item.updated_at,
                item.item_id,
                item.user_id,
                item.buddy_id,
            ),
        )

    def _insert_history_locked(self, entry: StateMemoryHistoryEntry) -> None:
        self.connection.execute(
            """
            INSERT INTO state_memory_history (
                history_id, item_id, user_id, buddy_id, item_name,
                change_type, change_source, quantity_before, quantity_after,
                unit_before, unit_after, proposal_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.history_id,
                entry.item_id,
                entry.user_id,
                entry.buddy_id,
                entry.item_name,
                entry.change_type,
                entry.change_source,
                entry.quantity_before,
                entry.quantity_after,
                entry.unit_before,
                entry.unit_after,
                entry.proposal_id,
                entry.created_at,
            ),
        )

    def _insert_proposal_locked(self, proposal: StateMemoryPendingProposal) -> None:
        self.connection.execute(
            """
            INSERT INTO state_memory_pending_proposals (
                proposal_id, user_id, buddy_id, source, content, deltas_json,
                status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                proposal.user_id,
                proposal.buddy_id,
                proposal.source,
                proposal.content,
                _dump_deltas(proposal.deltas),
                proposal.status,
                proposal.created_at,
                proposal.updated_at,
            ),
        )

    def _update_proposal_locked(
        self,
        proposal: StateMemoryPendingProposal,
        *,
        status: str,
        deltas: list[StateMemoryDelta] | None = None,
    ) -> StateMemoryPendingProposal:
        updated = StateMemoryPendingProposal(
            proposal_id=proposal.proposal_id,
            user_id=proposal.user_id,
            buddy_id=proposal.buddy_id,
            source=proposal.source,
            content=proposal.content,
            deltas=deltas or proposal.deltas,
            status=status,
            created_at=proposal.created_at,
            updated_at=now_iso(),
        )
        self.connection.execute(
            """
            UPDATE state_memory_pending_proposals
            SET deltas_json = ?, status = ?, updated_at = ?
            WHERE proposal_id = ? AND user_id = ? AND buddy_id = ?
            """,
            (
                _dump_deltas(updated.deltas),
                updated.status,
                updated.updated_at,
                updated.proposal_id,
                updated.user_id,
                updated.buddy_id,
            ),
        )
        return updated


def _item_from_row(row: sqlite3.Row) -> StateMemoryItem:
    return StateMemoryItem(
        item_id=row["item_id"],
        user_id=row["user_id"],
        buddy_id=row["buddy_id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        category=row["category"],
        quantity=row["quantity"],
        unit=row["unit"],
        source=row["source"],
        confidence=row["confidence"],
        status=row["status"],
        captured_at=row["captured_at"],
        last_seen_at=row["last_seen_at"],
        updated_at=row["updated_at"],
    )


def _history_from_row(row: sqlite3.Row) -> StateMemoryHistoryEntry:
    return StateMemoryHistoryEntry(
        history_id=row["history_id"],
        item_id=row["item_id"],
        user_id=row["user_id"],
        buddy_id=row["buddy_id"],
        item_name=row["item_name"],
        change_type=row["change_type"],
        change_source=row["change_source"],
        quantity_before=row["quantity_before"],
        quantity_after=row["quantity_after"],
        unit_before=row["unit_before"],
        unit_after=row["unit_after"],
        proposal_id=row["proposal_id"],
        created_at=row["created_at"],
    )


def _proposal_from_row(row: sqlite3.Row) -> StateMemoryPendingProposal:
    return StateMemoryPendingProposal(
        proposal_id=row["proposal_id"],
        user_id=row["user_id"],
        buddy_id=row["buddy_id"],
        source=row["source"],
        content=row["content"],
        deltas=[StateMemoryDelta.model_validate(delta) for delta in json.loads(row["deltas_json"])],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dump_deltas(deltas: list[StateMemoryDelta]) -> str:
    return json.dumps([delta.model_dump(mode="json") for delta in deltas], ensure_ascii=False, sort_keys=True)


def _normalize_item_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _quantity_after_for_new_item(delta: StateMemoryDelta) -> float | None:
    if delta.operation == "upsert":
        return delta.quantity
    if delta.operation in {"consume", "remove"}:
        return 0.0
    return delta.quantity


def _quantity_after_for_existing_item(current: StateMemoryItem, delta: StateMemoryDelta) -> float | None:
    if delta.operation == "upsert":
        return delta.quantity
    if delta.operation == "remove":
        return 0.0
    current_quantity = current.quantity or 0.0
    consumed_quantity = delta.quantity or current_quantity
    return max(current_quantity - consumed_quantity, 0.0)


def _status_after(
    *,
    current_status: str | None,
    delta: StateMemoryDelta,
    quantity_after: float | None,
) -> str:
    if delta.operation == "remove":
        return "removed"
    if delta.operation == "consume" and quantity_after is not None and quantity_after <= 0:
        return "consumed"
    if current_status == "removed" and delta.operation == "upsert":
        return "active"
    return "active"
