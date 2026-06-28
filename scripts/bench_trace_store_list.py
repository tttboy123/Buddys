"""Benchmark helper for TraceStore list-path query behavior."""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta
import argparse

from buddys_api.db import connect_db, initialize_database
from buddys_api.schemas import ActionProposal, ActionTrace, Intent, PermissionDecision
from buddys_api.trace_store import TraceStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark TraceStore list-path query performance.")
    parser.add_argument("--record-count", type=int, default=50_000)
    parser.add_argument("--buddy-count", type=int, default=20)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--target-buddy", default="buddy_10")
    return parser.parse_args()


def run_benchmark(
    record_count: int,
    buddy_count: int,
    samples: int,
    limit: int,
    target_buddy: str,
) -> dict[str, float | int | str]:
    start = datetime(2026, 6, 28)
    connection = connect_db(":memory:")
    initialize_database(connection)
    store = TraceStore(connection)

    for i in range(record_count):
        buddy_id = f"buddy_{i % buddy_count:02d}"
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
    for _ in range(samples):
        started = time.perf_counter()
        rows = store.list(buddy_id=target_buddy, reverse=True, limit=limit)
        duration = time.perf_counter() - started
        sample_times.append(duration)
        if not rows:
            raise RuntimeError("benchmark produced empty result")

    med = statistics.median(sample_times)
    p95 = statistics.quantiles(sample_times, n=20)[18]

    return {
        "records": record_count,
        "buddy": target_buddy,
        "samples": samples,
        "limit": limit,
        "buddy_count": buddy_count,
        "median_sec": med,
        "p95_sec": p95,
        "min_sec": min(sample_times),
        "max_sec": max(sample_times),
    }


def main() -> None:
    args = parse_args()
    results = run_benchmark(
        record_count=args.record_count,
        buddy_count=args.buddy_count,
        samples=args.samples,
        limit=args.limit,
        target_buddy=args.target_buddy,
    )

    print(f"records={results['records']}")
    print(f"buddy_count={results['buddy_count']}")
    print(f"buddy={results['buddy']}")
    print(f"limit={results['limit']}")
    print(f"samples={results['samples']}")
    print(f"median_sec={results['median_sec']:.6f}")
    print(f"p95_sec={results['p95_sec']:.6f}")
    print(f"min_sec={results['min_sec']:.6f}")
    print(f"max_sec={results['max_sec']:.6f}")


if __name__ == "__main__":
    main()
