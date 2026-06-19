from __future__ import annotations

import json
import sqlite3

from buddys_api.schemas import new_id, now_iso
from buddys_api.state_memory_models import (
    StateMemoryDelta,
    StateMemoryHistoryEntry,
    StateMemoryItem,
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
