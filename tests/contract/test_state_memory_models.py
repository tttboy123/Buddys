from pydantic import ValidationError

from buddys_api.state_memory_models import (
    StateMemoryDelta,
    StateMemoryEvidenceItem,
    StateMemoryHistoryEntry,
    StateMemoryItem,
    StateMemoryPendingProposal,
    StateMemoryQueryAnswer,
    StateMemoryQueryRequest,
)


def test_state_memory_records_export_observable_foundation_fields() -> None:
    proposal = StateMemoryPendingProposal(
        proposal_id="proposal_egg",
        user_id="user_1",
        buddy_id="buddy_1",
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
        status="pending",
        created_at="2026-06-19T16:00:00+08:00",
        updated_at="2026-06-19T16:00:00+08:00",
    )
    item = StateMemoryItem(
        item_id="item_egg",
        user_id="user_1",
        buddy_id="buddy_1",
        name="鸡蛋",
        normalized_name="鸡蛋",
        category="ingredient",
        quantity=5,
        unit="个",
        source="voice",
        confidence=0.92,
        status="active",
        captured_at="2026-06-19T16:00:00+08:00",
        last_seen_at="2026-06-19T16:00:00+08:00",
        updated_at="2026-06-19T16:00:00+08:00",
    )
    history = StateMemoryHistoryEntry(
        history_id="history_egg",
        item_id=item.item_id,
        user_id="user_1",
        buddy_id="buddy_1",
        item_name="鸡蛋",
        change_type="observed",
        change_source="voice",
        quantity_before=None,
        quantity_after=5,
        unit_before=None,
        unit_after="个",
        proposal_id=proposal.proposal_id,
        created_at="2026-06-19T16:00:00+08:00",
    )
    evidence_item = StateMemoryEvidenceItem(
        item_id=item.item_id,
        name=item.name,
        quantity=item.quantity,
        unit=item.unit,
        status=item.status,
        source=item.source,
        last_seen_at=item.last_seen_at,
    )
    query_request = StateMemoryQueryRequest(question="有鸡蛋吗")
    query_answer = StateMemoryQueryAnswer(
        answer_type="have_item",
        subject_name="鸡蛋",
        summary="还有鸡蛋。",
        evidence_item_ids=[item.item_id],
        evidence_items=[evidence_item],
        missing_items=[],
        has_item=True,
        trace_id="trace_state_memory_001",
    )

    assert proposal.model_dump()["schema_version"] == "state_memory_pending_proposal.v1"
    assert proposal.deltas[0].operation == "upsert"
    assert item.model_dump()["schema_version"] == "state_memory_item.v1"
    assert item.status == "active"
    assert history.model_dump()["schema_version"] == "state_memory_history.v1"
    assert history.change_source == "voice"
    assert query_request.question == "有鸡蛋吗"
    assert query_answer.evidence_item_ids == ["item_egg"]
    assert query_answer.evidence_items[0].name == "鸡蛋"
    assert query_answer.has_item is True


def test_state_memory_models_reject_blank_names_and_unknown_sources() -> None:
    for factory in [
        lambda: StateMemoryDelta(item_name="", operation="upsert", source="voice"),
        lambda: StateMemoryPendingProposal(
            proposal_id="proposal_1",
            user_id="user_1",
            buddy_id="buddy_1",
            source="email",
            content="invalid",
            deltas=[],
            status="pending",
        ),
        lambda: StateMemoryItem(
            item_id="item_1",
            user_id="user_1",
            buddy_id="buddy_1",
            name="   ",
            normalized_name="egg",
            source="manual",
            status="active",
        ),
        lambda: StateMemoryQueryRequest(question="   "),
        lambda: StateMemoryQueryAnswer(
            answer_type="missing_for_recipe",
            subject_name="红烧肉",
            summary="   ",
            evidence_item_ids=[],
            evidence_items=[],
            missing_items=["生抽"],
            trace_id="trace_state_memory_001",
        ),
    ]:
        try:
            factory()
        except ValidationError:
            continue
        raise AssertionError("expected model validation to fail")
