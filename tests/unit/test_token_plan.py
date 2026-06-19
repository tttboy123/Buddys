import pytest

from buddys_api.db import connect_db, initialize_database
from buddys_api.token_plan import (
    TokenPlanLimitExceeded,
    UsageStore,
    available_plans,
    plan_catalog,
)


def test_plan_catalog_includes_default_free_and_byok_without_key_storage() -> None:
    plans = plan_catalog()

    assert "free" in plans
    assert plans["free"].monthly_token_limit > 0
    assert plans["free"].hard_limit is True
    assert plans["byok"].byok is True
    assert plans["byok"].monthly_token_limit is None
    assert "api_key" not in str(available_plans()).lower()


def test_usage_ledger_records_monthly_totals_and_remaining_allowance() -> None:
    connection = connect_db(":memory:")
    initialize_database(connection)
    store = UsageStore(connection)

    first = store.record_usage(
        user_id="user_demo",
        trace_id="trace_001",
        buddy_id="buddy_home",
        provider_id="mock_deterministic",
        model_id="mock-home-v0",
        input_tokens=12,
        output_tokens=8,
        source="legacy_message",
    )
    second = store.record_usage(
        user_id="user_demo",
        trace_id="trace_002",
        buddy_id="buddy_home",
        provider_id="mock_deterministic",
        model_id="mock-home-v0",
        input_tokens=5,
        output_tokens=7,
        source="legacy_message",
    )

    summary = store.usage_summary("user_demo")
    assert first.total_tokens == 20
    assert second.total_tokens == 12
    assert summary.used_tokens == 32
    assert summary.remaining_tokens == summary.monthly_token_limit - 32
    assert summary.provider_usage["mock_deterministic"]["total_tokens"] == 32
    assert summary.model_usage["mock-home-v0"]["total_tokens"] == 32


def test_hard_limit_rejects_before_recording_over_limit_usage() -> None:
    connection = connect_db(":memory:")
    initialize_database(connection)
    store = UsageStore(connection)
    limit = store.usage_summary("user_demo").monthly_token_limit
    assert limit is not None

    store.record_usage(
        user_id="user_demo",
        trace_id="trace_at_limit",
        buddy_id="buddy_home",
        provider_id="mock_deterministic",
        model_id="mock-home-v0",
        input_tokens=limit,
        output_tokens=0,
        source="test_seed",
    )

    with pytest.raises(TokenPlanLimitExceeded):
        store.record_usage(
            user_id="user_demo",
            trace_id="trace_over_limit",
            buddy_id="buddy_home",
            provider_id="mock_deterministic",
            model_id="mock-home-v0",
            input_tokens=1,
            output_tokens=0,
            source="legacy_message",
        )

    summary = store.usage_summary("user_demo")
    assert summary.used_tokens == limit
    assert [entry.trace_id for entry in store.list_usage("user_demo")] == ["trace_at_limit"]
