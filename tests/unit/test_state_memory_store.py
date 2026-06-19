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
    )

    owner_pending = store.list_pending_proposals(user_id=owner_id, buddy_id=buddy_id)
    other_pending = store.list_pending_proposals(user_id=other_id, buddy_id=buddy_id)
    other_items = store.list_items(user_id=other_id, buddy_id=buddy_id)
    other_history = store.list_history(user_id=other_id, buddy_id=buddy_id)

    assert owner_pending == [proposal]
    assert owner_pending[0].status == "pending"
    assert other_pending == []
    assert other_items == []
    assert other_history == []
