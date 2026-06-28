"""Benchmark helper for TraceStore list-path query behavior."""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta

from buddys_api.db import connect_db, initialize_database
from buddys_api.schemas import ActionProposal, ActionTrace, Intent, PermissionDecision
from buddys_api.trace_store import TraceStore


RECORD_COUNT = 50_000
BUDDY_COUNT = 20
SAMPLES = 20
LIMIT = 200
TARGET_BUDDY = "buddy_10"


if __name__ == "__main__":
    start = datetime(2026, 6, 28)
    connection = connect_db(":memory:")
    initialize_database(connection)
    store = TraceStore(connection)

    for i in range(RECORD_COUNT):
        buddy_id = f"buddy_{i % BUDDY_COUNT:02d}"
        ts = (start + timedelta(seconds=i)).isoformat() + "+00:00"
        store.save(
            ActionTrace(
                trace_id=f"trace_{i:06d}",
                user_id="user_demo",
                buddy_id=buddy_id,
                space_id="space_home",
                device_id="device_1",
                turn_id=f"turn_{i:06d}",
                created_at=ts,
                updated_at=ts,
                intent=Intent(name="state_memory_query", summary="benchmark"),
                proposal=ActionProposal(
                    proposal_id=f"proposal_{i:06d}",
                    trace_id=f"trace_{i:06d}",
                    buddy_id=buddy_id,
                    action_type="reply_only",
                    summary="missing item", 
                    requires_confirmation=False,
                    tool_id="mock_home.light",
                    action="noop",
                    args={"answer_type": "missing_for_recipe", "missing_items": ["鸡蛋"]},
                ),
                permission_decision=PermissionDecision(
                    policy_result="allow",
                    confirmation_result="not_requested",
                    decided_by="policy",
                    reason="benchmark",
                ),
            )
        )

    sample_times = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        rows = store.list(buddy_id=TARGET_BUDDY, reverse=True, limit=LIMIT)
        duration = time.perf_counter() - started
        sample_times.append(duration)
        if not rows:
            raise RuntimeError("benchmark produced empty result")

    med = statistics.median(sample_times)
    p95 = statistics.quantiles(sample_times, n=20)[18]

    print(f"records={RECORD_COUNT}")
    print(f"buddy={TARGET_BUDDY}")
    print(f"samples={SAMPLES}")
    print(f"median_sec={med:.6f}")
    print(f"p95_sec={p95:.6f}")
    print(f"min_sec={min(sample_times):.6f}")
    print(f"max_sec={max(sample_times):.6f}")
