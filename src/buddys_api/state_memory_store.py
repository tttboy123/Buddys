from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from buddys_api.schemas import new_id, now_iso
from buddys_api.state_memory_models import (
    StateMemoryDelta,
    StateMemoryHistoryEntry,
    StateMemoryItem,
    StateMemoryProposalApplyResult,
    StateMemoryPendingProposal,
    StateMemoryRecipe,
    StateMemoryRecipeIngredient,
    StateMemoryShoppingPassItem,
)

RECENT_CONSUMPTION_WINDOW = timedelta(days=3)


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

    def summarize_buddy_state(self, *, user_id: str, buddy_id: str) -> dict[str, object]:
        items = self.list_items(user_id=user_id, buddy_id=buddy_id)
        pending = self.list_pending_proposals(user_id=user_id, buddy_id=buddy_id)
        history = self.list_history(user_id=user_id, buddy_id=buddy_id)
        recently_consumed_item_ids = {
            entry.item_id
            for entry in history
            if entry.change_type in {"consume", "consumed"}
            and is_recent_consumption_timestamp(entry.created_at)
        }
        return {
            "confirmed_item_count": len(items),
            "pending_proposal_count": len(pending),
            "recently_consumed_count": len(recently_consumed_item_ids),
            "unknown_quantity_count": sum(1 for item in items if item.quantity is None),
            "last_state_change_at": _latest_timestamp(
                [item.updated_at for item in items]
                + [proposal.updated_at for proposal in pending]
                + [entry.created_at for entry in history]
            ),
        }

    def save_pending_proposal(
        self,
        *,
        user_id: str,
        buddy_id: str,
        source: str,
        content: str,
        deltas: list[StateMemoryDelta],
        unrecognized: list[str] | None = None,
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
            unrecognized=unrecognized or [],
            status=status,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.connection:
            self._insert_proposal_locked(proposal)
        return proposal

    def create_recipe(
        self,
        *,
        user_id: str,
        buddy_id: str,
        name: str,
        ingredients: list[str],
    ) -> StateMemoryRecipe:
        timestamp = now_iso()
        recipe = StateMemoryRecipe(
            recipe_id=new_id("state_recipe"),
            user_id=user_id,
            buddy_id=buddy_id,
            name=" ".join(name.strip().split()),
            normalized_name=_normalize_item_name(name),
            ingredients=_recipe_ingredients(ingredients),
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            with self.connection:
                self._insert_recipe_locked(recipe)
        except sqlite3.IntegrityError as exc:
            raise ValueError("recipe_already_exists") from exc
        return recipe

    def list_recipes(self, *, user_id: str, buddy_id: str) -> list[StateMemoryRecipe]:
        rows = self.connection.execute(
            """
            SELECT recipe_id, user_id, buddy_id, name, normalized_name, ingredients_json, created_at, updated_at
            FROM state_memory_recipes
            WHERE user_id = ? AND buddy_id = ?
            ORDER BY normalized_name, recipe_id
            """,
            (user_id, buddy_id),
        ).fetchall()
        return [_recipe_from_row(row) for row in rows]

    def add_shopping_pass_item(
        self,
        *,
        user_id: str,
        buddy_id: str,
        name: str,
        source_kind: str,
        source_summary: str,
    ) -> StateMemoryShoppingPassItem:
        normalized_name = _normalize_item_name(name)
        if not normalized_name:
            raise ValueError("shopping_pass_name_required")
        with self.connection:
            existing = self._find_open_shopping_pass_item_locked(
                user_id=user_id,
                buddy_id=buddy_id,
                normalized_name=normalized_name,
            )
            if existing is not None:
                return existing
            timestamp = now_iso()
            item = StateMemoryShoppingPassItem(
                shopping_item_id=new_id("shopping_item"),
                user_id=user_id,
                buddy_id=buddy_id,
                name=" ".join(name.strip().split()),
                normalized_name=normalized_name,
                status="open",
                source_kind=source_kind,
                source_summary=source_summary,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._insert_shopping_pass_item_locked(item)
            return item

    def list_shopping_pass_items(
        self,
        *,
        user_id: str,
        buddy_id: str,
        include_done: bool = False,
    ) -> list[StateMemoryShoppingPassItem]:
        status_clause = "" if include_done else "AND status = 'open'"
        rows = self.connection.execute(
            f"""
            SELECT shopping_item_id, user_id, buddy_id, name, normalized_name,
                   status, source_kind, source_summary, created_at, updated_at
            FROM state_memory_shopping_pass_items
            WHERE user_id = ? AND buddy_id = ?
            {status_clause}
            ORDER BY created_at, shopping_item_id
            """,
            (user_id, buddy_id),
        ).fetchall()
        return [_shopping_pass_item_from_row(row) for row in rows]

    def mark_shopping_pass_item_done(
        self,
        *,
        user_id: str,
        buddy_id: str,
        shopping_item_id: str,
    ) -> StateMemoryShoppingPassItem:
        item = self._get_owned_shopping_pass_item(
            user_id=user_id,
            buddy_id=buddy_id,
            shopping_item_id=shopping_item_id,
        )
        if item.status == "done":
            return item
        updated = StateMemoryShoppingPassItem(
            shopping_item_id=item.shopping_item_id,
            user_id=item.user_id,
            buddy_id=item.buddy_id,
            name=item.name,
            normalized_name=item.normalized_name,
            status="done",
            source_kind=item.source_kind,
            source_summary=item.source_summary,
            created_at=item.created_at,
            updated_at=now_iso(),
        )
        with self.connection:
            self._update_shopping_pass_item_locked(updated)
        return updated

    def summarize_shopping_pass(self, *, user_id: str, buddy_id: str) -> dict[str, object]:
        items = self.list_shopping_pass_items(user_id=user_id, buddy_id=buddy_id, include_done=True)
        open_items = [item for item in items if item.status == "open"]
        done_items = [item for item in items if item.status == "done"]
        return {
            "open_count": len(open_items),
            "done_count": len(done_items),
            "top_open_names": [item.name for item in open_items[:3]],
            "updated_at": _latest_timestamp([item.updated_at for item in items]),
        }

    def current_shopping_pass_hint(self, *, user_id: str, buddy_id: str) -> dict[str, object] | None:
        items = self.list_items(user_id=user_id, buddy_id=buddy_id)
        history = self.list_history(user_id=user_id, buddy_id=buddy_id)
        recent_consumption = [
            entry
            for entry in history
            if entry.change_type in {"consume", "consumed"} and is_recent_consumption_timestamp(entry.created_at)
        ]
        if recent_consumption:
            recent_consumption.sort(key=lambda entry: (entry.created_at, entry.history_id))
            entry = recent_consumption[-1]
            matching_item = next((item for item in items if item.item_id == entry.item_id), None)
            return {
                "kind": "consumption_inference",
                "message": f"Buddy noticed {entry.item_name} was used recently. Want to review whether it needs a refill?",
                "basis": {
                    "item_ids": [entry.item_id],
                    "item_names": [entry.item_name],
                    "recent_change_type": entry.change_type,
                    "last_seen_at": matching_item.last_seen_at if matching_item is not None else None,
                },
            }

        low_items = [
            item
            for item in items
            if item.status == "active" and item.quantity is not None and item.quantity <= 2
        ]
        if not low_items:
            return None
        low_items.sort(key=lambda item: (item.quantity, item.updated_at, item.name))
        item = low_items[0]
        return {
            "kind": "consumption_inference",
            "message": f"{item.name} might be running low. Add it to the next shopping pass?",
            "basis": {
                "item_ids": [item.item_id],
                "item_names": [item.name],
                "last_seen_at": item.last_seen_at,
            },
        }

    def delete_recipe(self, *, user_id: str, buddy_id: str, recipe_id: str) -> None:
        with self.connection:
            cursor = self.connection.execute(
                """
                DELETE FROM state_memory_recipes
                WHERE recipe_id = ? AND user_id = ? AND buddy_id = ?
                """,
                (recipe_id, user_id, buddy_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"recipe not found: {recipe_id}")

    def get_recipe_by_name(
        self,
        *,
        user_id: str,
        buddy_id: str,
        recipe_name: str,
    ) -> StateMemoryRecipe | None:
        row = self.connection.execute(
            """
            SELECT recipe_id, user_id, buddy_id, name, normalized_name, ingredients_json, created_at, updated_at
            FROM state_memory_recipes
            WHERE user_id = ? AND buddy_id = ? AND normalized_name = ?
            LIMIT 1
            """,
            (user_id, buddy_id, _normalize_item_name(recipe_name)),
        ).fetchone()
        if row is None:
            return None
        return _recipe_from_row(row)

    def find_recipe_for_question(
        self,
        *,
        user_id: str,
        buddy_id: str,
        question: str,
    ) -> StateMemoryRecipe | None:
        normalized_question = _normalize_item_name(question)
        for recipe in self.list_recipes(user_id=user_id, buddy_id=buddy_id):
            if recipe.normalized_name in normalized_question:
                return recipe
        return None

    def list_pending_proposals(self, *, user_id: str, buddy_id: str) -> list[StateMemoryPendingProposal]:
        rows = self.connection.execute(
            """
            SELECT proposal_id, user_id, buddy_id, source, content, deltas_json, unrecognized_json,
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
            return self._update_proposal_locked(proposal, status="rejected", require_pending=True)

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
            updated_proposal = self._update_proposal_locked(
                proposal,
                status="confirmed",
                deltas=deltas,
                require_pending=True,
            )
            for delta in deltas:
                applied = self._apply_delta_locked(proposal=updated_proposal, delta=delta)
                if applied is None:
                    continue
                item, history_entry = applied
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
    ) -> tuple[StateMemoryItem, StateMemoryHistoryEntry] | None:
        current = self._find_item_locked(
            user_id=proposal.user_id,
            buddy_id=proposal.buddy_id,
            normalized_name=_normalize_item_name(delta.item_name),
        )
        if current is None and delta.operation in {"consume", "remove"}:
            return None
        timestamp = now_iso()
        if current is None:
            quantity_after = _quantity_after_for_new_item(delta)
            item = StateMemoryItem(
                item_id=new_id("state_item"),
                user_id=proposal.user_id,
                buddy_id=proposal.buddy_id,
                name=delta.item_name,
                normalized_name=_normalize_item_name(delta.item_name),
                category=delta.category,
                quantity=quantity_after,
                unit=delta.unit,
                source=delta.source,
                confidence=delta.confidence,
                status=_status_after(current_status=None, delta=delta, quantity_after=quantity_after),
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
            SELECT proposal_id, user_id, buddy_id, source, content, deltas_json, unrecognized_json,
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

    def _find_open_shopping_pass_item_locked(
        self,
        *,
        user_id: str,
        buddy_id: str,
        normalized_name: str,
    ) -> StateMemoryShoppingPassItem | None:
        row = self.connection.execute(
            """
            SELECT shopping_item_id, user_id, buddy_id, name, normalized_name,
                   status, source_kind, source_summary, created_at, updated_at
            FROM state_memory_shopping_pass_items
            WHERE user_id = ? AND buddy_id = ? AND normalized_name = ? AND status = 'open'
            LIMIT 1
            """,
            (user_id, buddy_id, normalized_name),
        ).fetchone()
        if row is None:
            return None
        return _shopping_pass_item_from_row(row)

    def _get_owned_shopping_pass_item(
        self,
        *,
        user_id: str,
        buddy_id: str,
        shopping_item_id: str,
    ) -> StateMemoryShoppingPassItem:
        row = self.connection.execute(
            """
            SELECT shopping_item_id, user_id, buddy_id, name, normalized_name,
                   status, source_kind, source_summary, created_at, updated_at
            FROM state_memory_shopping_pass_items
            WHERE shopping_item_id = ? AND user_id = ? AND buddy_id = ?
            """,
            (shopping_item_id, user_id, buddy_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"shopping pass item not found: {shopping_item_id}")
        return _shopping_pass_item_from_row(row)

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
                unrecognized_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                proposal.user_id,
                proposal.buddy_id,
                proposal.source,
                proposal.content,
                _dump_deltas(proposal.deltas),
                _dump_unrecognized(proposal.unrecognized),
                proposal.status,
                proposal.created_at,
                proposal.updated_at,
            ),
        )

    def _insert_recipe_locked(self, recipe: StateMemoryRecipe) -> None:
        self.connection.execute(
            """
            INSERT INTO state_memory_recipes (
                recipe_id, user_id, buddy_id, name, normalized_name, ingredients_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe.recipe_id,
                recipe.user_id,
                recipe.buddy_id,
                recipe.name,
                recipe.normalized_name,
                _dump_recipe_ingredients(recipe.ingredients),
                recipe.created_at,
                recipe.updated_at,
            ),
        )

    def _insert_shopping_pass_item_locked(self, item: StateMemoryShoppingPassItem) -> None:
        self.connection.execute(
            """
            INSERT INTO state_memory_shopping_pass_items (
                shopping_item_id, user_id, buddy_id, name, normalized_name,
                status, source_kind, source_summary, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.shopping_item_id,
                item.user_id,
                item.buddy_id,
                item.name,
                item.normalized_name,
                item.status,
                item.source_kind,
                item.source_summary,
                item.created_at,
                item.updated_at,
            ),
        )

    def _update_shopping_pass_item_locked(self, item: StateMemoryShoppingPassItem) -> None:
        self.connection.execute(
            """
            UPDATE state_memory_shopping_pass_items
            SET name = ?, normalized_name = ?, status = ?, source_kind = ?, source_summary = ?, updated_at = ?
            WHERE shopping_item_id = ? AND user_id = ? AND buddy_id = ?
            """,
            (
                item.name,
                item.normalized_name,
                item.status,
                item.source_kind,
                item.source_summary,
                item.updated_at,
                item.shopping_item_id,
                item.user_id,
                item.buddy_id,
            ),
        )

    def _update_proposal_locked(
        self,
        proposal: StateMemoryPendingProposal,
        *,
        status: str,
        deltas: list[StateMemoryDelta] | None = None,
        require_pending: bool = False,
    ) -> StateMemoryPendingProposal:
        updated = StateMemoryPendingProposal(
            proposal_id=proposal.proposal_id,
            user_id=proposal.user_id,
            buddy_id=proposal.buddy_id,
            source=proposal.source,
            content=proposal.content,
            deltas=deltas or proposal.deltas,
            unrecognized=proposal.unrecognized,
            status=status,
            created_at=proposal.created_at,
            updated_at=now_iso(),
        )
        cursor = self.connection.execute(
            """
            UPDATE state_memory_pending_proposals
            SET deltas_json = ?, unrecognized_json = ?, status = ?, updated_at = ?
            WHERE proposal_id = ? AND user_id = ? AND buddy_id = ?
            """
            + (" AND status = 'pending'" if require_pending else ""),
            (
                _dump_deltas(updated.deltas),
                _dump_unrecognized(updated.unrecognized),
                updated.status,
                updated.updated_at,
                updated.proposal_id,
                updated.user_id,
                updated.buddy_id,
            ),
        )
        if require_pending and cursor.rowcount != 1:
            raise ValueError("proposal_not_pending")
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
        unrecognized=[str(value).strip() for value in json.loads(row["unrecognized_json"] or "[]") if str(value).strip()],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _recipe_from_row(row: sqlite3.Row) -> StateMemoryRecipe:
    return StateMemoryRecipe(
        recipe_id=row["recipe_id"],
        user_id=row["user_id"],
        buddy_id=row["buddy_id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        ingredients=[
            StateMemoryRecipeIngredient.model_validate(ingredient)
            for ingredient in json.loads(row["ingredients_json"])
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _shopping_pass_item_from_row(row: sqlite3.Row) -> StateMemoryShoppingPassItem:
    return StateMemoryShoppingPassItem(
        shopping_item_id=row["shopping_item_id"],
        user_id=row["user_id"],
        buddy_id=row["buddy_id"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        status=row["status"],
        source_kind=row["source_kind"],
        source_summary=row["source_summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dump_deltas(deltas: list[StateMemoryDelta]) -> str:
    return json.dumps([delta.model_dump(mode="json") for delta in deltas], ensure_ascii=False, sort_keys=True)


def _dump_unrecognized(unrecognized: list[str]) -> str:
    return json.dumps(unrecognized, ensure_ascii=False, sort_keys=True)


def _dump_recipe_ingredients(ingredients: list[StateMemoryRecipeIngredient]) -> str:
    return json.dumps([ingredient.model_dump(mode="json") for ingredient in ingredients], ensure_ascii=False, sort_keys=True)


def _normalize_item_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _recipe_ingredients(ingredients: list[str]) -> list[StateMemoryRecipeIngredient]:
    normalized: list[StateMemoryRecipeIngredient] = []
    seen: set[str] = set()
    for ingredient in ingredients:
        name = " ".join(str(ingredient).strip().split())
        if not name:
            continue
        normalized_name = _normalize_item_name(name)
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        normalized.append(StateMemoryRecipeIngredient(name=name, normalized_name=normalized_name))
    if not normalized:
        raise ValueError("recipe_ingredients_required")
    return normalized


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


def _latest_timestamp(timestamps: list[str]) -> str | None:
    return max(timestamps) if timestamps else None


def is_recent_consumption_timestamp(value: str, *, now: datetime | None = None) -> bool:
    reference = now or datetime.now(timezone.utc)
    timestamp = datetime.fromisoformat(value)
    return timestamp >= reference - RECENT_CONSUMPTION_WINDOW
