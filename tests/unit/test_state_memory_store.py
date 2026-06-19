import pytest

from buddys_api.auth_store import AuthStore
from buddys_api.buddy_store import BuddyStore
from buddys_api.db import connect_db, initialize_database
from buddys_api.state_memory_models import StateMemoryDelta
from buddys_api.state_memory_store import StateMemoryStore


def make_store() -> tuple[StateMemoryStore, str, str, str, str]:
    connection = connect_db(":memory:")
    initialize_database(connection)
    auth_store = AuthStore(connection)
    owner = auth_store.register_user(email="owner@example.com", password="correct horse battery staple")
    other = auth_store.register_user(email="other@example.com", password="correct horse battery staple")
    buddy_store = BuddyStore(connection)
    owner_buddy = buddy_store.create_buddy(user_id=owner.user_id, name="Kitchen Buddy", space_id="kitchen")
    other_buddy = buddy_store.create_buddy(user_id=other.user_id, name="Other Buddy", space_id="study")
    return StateMemoryStore(connection), owner.user_id, other.user_id, owner_buddy.buddy_id, other_buddy.buddy_id


def test_store_persists_items_and_history_for_a_buddy() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    item = store.create_item(
        user_id=owner_id,
        buddy_id=buddy_id,
        name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="voice",
        confidence=0.92,
    )
    history = store.append_history(
        user_id=owner_id,
        buddy_id=buddy_id,
        item_id=item.item_id,
        item_name=item.name,
        change_type="observed",
        change_source="voice",
        quantity_before=None,
        quantity_after=5,
        unit_before=None,
        unit_after="个",
    )

    items = store.list_items(user_id=owner_id, buddy_id=buddy_id)
    entries = store.list_history(user_id=owner_id, buddy_id=buddy_id)

    assert [stored.name for stored in items] == ["鸡蛋"]
    assert items[0].normalized_name == "鸡蛋"
    assert entries == [history]
    assert entries[0].quantity_after == 5


def test_store_persists_pending_proposals_and_scopes_queries_to_owner() -> None:
    store, owner_id, other_id, buddy_id, _ = make_store()

    proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="photo",
        content="fridge.jpg",
        deltas=[
            StateMemoryDelta(
                item_name="土豆",
                operation="upsert",
                quantity=1,
                unit="袋",
                confidence=0.81,
                source="photo",
            )
        ],
        unrecognized=["一包面粉"],
    )

    owner_pending = store.list_pending_proposals(user_id=owner_id, buddy_id=buddy_id)
    other_pending = store.list_pending_proposals(user_id=other_id, buddy_id=buddy_id)
    other_items = store.list_items(user_id=other_id, buddy_id=buddy_id)
    other_history = store.list_history(user_id=other_id, buddy_id=buddy_id)

    assert owner_pending == [proposal]
    assert owner_pending[0].status == "pending"
    assert owner_pending[0].unrecognized == ["一包面粉"]
    assert other_pending == []
    assert other_items == []
    assert other_history == []


def test_confirm_proposal_writes_items_and_history_only_after_explicit_apply() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="voice",
        content="我买了五个鸡蛋和一袋土豆",
        deltas=[
            StateMemoryDelta(
                item_name="鸡蛋",
                operation="upsert",
                quantity=5,
                unit="个",
                confidence=0.92,
                source="voice",
            ),
            StateMemoryDelta(
                item_name="土豆",
                operation="upsert",
                quantity=1,
                unit="袋",
                confidence=0.88,
                source="voice",
            ),
        ],
    )

    assert store.list_items(user_id=owner_id, buddy_id=buddy_id) == []
    assert store.list_history(user_id=owner_id, buddy_id=buddy_id) == []

    result = store.confirm_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)

    assert result.applied_delta_count == 2
    assert result.proposal.status == "confirmed"
    assert [item.name for item in result.items] == ["鸡蛋", "土豆"]
    assert [entry.item_name for entry in result.history_entries] == ["鸡蛋", "土豆"]
    assert store.list_pending_proposals(user_id=owner_id, buddy_id=buddy_id) == []


def test_reject_proposal_marks_it_rejected_without_writing_state() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="conversation",
        content="香料用完了",
        deltas=[StateMemoryDelta(item_name="香料", operation="remove", source="conversation")],
    )

    rejected = store.reject_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)

    assert rejected.status == "rejected"
    assert store.list_items(user_id=owner_id, buddy_id=buddy_id) == []
    assert store.list_history(user_id=owner_id, buddy_id=buddy_id) == []
    assert store.list_pending_proposals(user_id=owner_id, buddy_id=buddy_id) == []


def test_correct_proposal_applies_override_deltas_instead_of_original_parse() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="photo",
        content="fridge.jpg",
        deltas=[
            StateMemoryDelta(
                item_name="牛奶",
                operation="upsert",
                quantity=2,
                unit="盒",
                confidence=0.65,
                source="photo",
            )
        ],
    )

    result = store.correct_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        proposal_id=proposal.proposal_id,
        corrected_deltas=[
            StateMemoryDelta(
                item_name="牛奶",
                operation="upsert",
                quantity=1,
                unit="盒",
                confidence=1.0,
                source="manual",
            )
        ],
    )

    assert result.applied_delta_count == 1
    assert result.proposal.status == "confirmed"
    assert result.proposal.deltas[0].quantity == 1
    assert result.items[0].name == "牛奶"
    assert result.items[0].quantity == 1
    assert result.history_entries[0].quantity_after == 1


def test_proposal_lifecycle_is_scoped_to_owner_and_safe_against_double_apply() -> None:
    store, owner_id, other_id, buddy_id, _ = make_store()

    proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="scan",
        content="scan: 可乐 2 瓶",
        deltas=[
            StateMemoryDelta(
                item_name="可乐",
                operation="upsert",
                quantity=2,
                unit="瓶",
                confidence=0.99,
                source="scan",
            )
        ],
    )

    try:
        store.confirm_proposal(user_id=other_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)
    except KeyError:
        pass
    else:
        raise AssertionError("cross-user confirm should not be allowed")

    store.confirm_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)

    try:
        store.confirm_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)
    except ValueError:
        pass
    else:
        raise AssertionError("confirmed proposal should not be applied twice")

    items = store.list_items(user_id=owner_id, buddy_id=buddy_id)
    history = store.list_history(user_id=owner_id, buddy_id=buddy_id)
    assert [(item.name, item.quantity) for item in items] == [("可乐", 2.0)]
    assert [entry.item_name for entry in history] == ["可乐"]


def test_reject_and_correct_raise_when_proposal_is_no_longer_pending() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    reject_proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="conversation",
        content="香料用完了",
        deltas=[StateMemoryDelta(item_name="香料", operation="remove", source="conversation")],
    )
    store.reject_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=reject_proposal.proposal_id)

    with pytest.raises(ValueError, match="proposal_not_pending"):
        store.reject_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=reject_proposal.proposal_id)

    correct_proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="photo",
        content="fridge.jpg",
        deltas=[
            StateMemoryDelta(
                item_name="牛奶",
                operation="upsert",
                quantity=2,
                unit="盒",
                confidence=0.65,
                source="photo",
            )
        ],
    )
    store.correct_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        proposal_id=correct_proposal.proposal_id,
        corrected_deltas=[
            StateMemoryDelta(
                item_name="牛奶",
                operation="upsert",
                quantity=1,
                unit="盒",
                confidence=1.0,
                source="manual",
            )
        ],
    )

    with pytest.raises(ValueError, match="proposal_not_pending"):
        store.correct_proposal(
            user_id=owner_id,
            buddy_id=buddy_id,
            proposal_id=correct_proposal.proposal_id,
            corrected_deltas=[
                StateMemoryDelta(
                    item_name="牛奶",
                    operation="upsert",
                    quantity=3,
                    unit="盒",
                    confidence=1.0,
                    source="manual",
                )
            ],
        )


def test_update_proposal_locked_requires_database_row_to_still_be_pending() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    proposal = store.save_pending_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        source="voice",
        content="我买了五个鸡蛋",
        deltas=[
            StateMemoryDelta(
                item_name="鸡蛋",
                operation="upsert",
                quantity=5,
                unit="个",
                confidence=0.92,
                source="voice",
            )
        ],
    )
    snapshot = store.get_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)

    with store.connection:
        store.connection.execute(
            """
            UPDATE state_memory_pending_proposals
            SET status = 'confirmed'
            WHERE proposal_id = ? AND user_id = ? AND buddy_id = ?
            """,
            (proposal.proposal_id, owner_id, buddy_id),
        )

    with pytest.raises(ValueError, match="proposal_not_pending"):
        with store.connection:
            store._update_proposal_locked(snapshot, status="rejected", require_pending=True)

    persisted = store.get_proposal(user_id=owner_id, buddy_id=buddy_id, proposal_id=proposal.proposal_id)
    assert persisted.status == "confirmed"


def test_consume_or_remove_nonexistent_item_does_not_create_phantom_records() -> None:
    store, owner_id, _, buddy_id, _ = make_store()

    consume_result = store.confirm_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        proposal_id=store.save_pending_proposal(
            user_id=owner_id,
            buddy_id=buddy_id,
            source="voice",
            content="我用了2个鸡蛋",
            deltas=[StateMemoryDelta(item_name="鸡蛋", operation="consume", quantity=2, unit="个", source="voice")],
        ).proposal_id,
    )
    remove_result = store.confirm_proposal(
        user_id=owner_id,
        buddy_id=buddy_id,
        proposal_id=store.save_pending_proposal(
            user_id=owner_id,
            buddy_id=buddy_id,
            source="conversation",
            content="香料用完了",
            deltas=[StateMemoryDelta(item_name="香料", operation="remove", source="conversation")],
        ).proposal_id,
    )

    assert consume_result.applied_delta_count == 0
    assert remove_result.applied_delta_count == 0
    assert store.list_items(user_id=owner_id, buddy_id=buddy_id) == []
    assert store.list_history(user_id=owner_id, buddy_id=buddy_id) == []
