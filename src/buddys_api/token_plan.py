from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from buddys_api.schemas import new_id, now_iso


class TokenPlan(BaseModel):
    plan_id: str
    display_name: str
    monthly_token_limit: int | None
    hard_limit: bool = True
    byok: bool = False


class UsageLedgerEntry(BaseModel):
    usage_event_id: str
    user_id: str
    trace_id: str | None
    buddy_id: str | None
    provider_id: str
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str
    usage_month: str
    created_at: str


class UsageSummary(BaseModel):
    user_id: str
    plan_id: str
    plan_display_name: str
    monthly_token_limit: int | None
    hard_limit: bool
    byok: bool
    usage_month: str
    used_tokens: int
    remaining_tokens: int | None
    over_limit: bool
    provider_usage: dict[str, dict[str, int]] = Field(default_factory=dict)
    model_usage: dict[str, dict[str, int]] = Field(default_factory=dict)


class TokenPlanLimitExceeded(ValueError):
    def __init__(self, summary: UsageSummary, attempted_tokens: int) -> None:
        super().__init__("token plan limit exceeded")
        self.summary = summary
        self.attempted_tokens = attempted_tokens


DEFAULT_PLANS: tuple[TokenPlan, ...] = (
    TokenPlan(plan_id="free", display_name="Free", monthly_token_limit=100_000, hard_limit=True),
    TokenPlan(plan_id="basic", display_name="Basic", monthly_token_limit=1_000_000, hard_limit=True),
    TokenPlan(plan_id="plus", display_name="Plus", monthly_token_limit=5_000_000, hard_limit=True),
    TokenPlan(plan_id="pro", display_name="Pro", monthly_token_limit=20_000_000, hard_limit=True),
    TokenPlan(plan_id="byok", display_name="BYOK", monthly_token_limit=None, hard_limit=False, byok=True),
)


def plan_catalog() -> dict[str, TokenPlan]:
    return {plan.plan_id: plan for plan in DEFAULT_PLANS}


def available_plans() -> list[dict[str, object]]:
    return [plan.model_dump(mode="json") for plan in DEFAULT_PLANS]


class UsageStore:
    def __init__(self, connection: sqlite3.Connection, plans: dict[str, TokenPlan] | None = None) -> None:
        self.connection = connection
        self.plans = plans or plan_catalog()

    def set_user_plan(self, user_id: str, plan_id: str) -> None:
        if plan_id not in self.plans:
            raise ValueError(f"unknown token plan: {plan_id}")
        timestamp = now_iso()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO token_plan_assignments (user_id, plan_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    updated_at = excluded.updated_at
                """,
                (user_id, plan_id, timestamp, timestamp),
            )

    def usage_summary(self, user_id: str, usage_month: str | None = None) -> UsageSummary:
        month = usage_month or current_usage_month()
        plan = self._plan_for_user(user_id)
        row = self.connection.execute(
            """
            SELECT COALESCE(SUM(total_tokens), 0) AS used_tokens
            FROM usage_ledger
            WHERE user_id = ? AND usage_month = ?
            """,
            (user_id, month),
        ).fetchone()
        used_tokens = int(row["used_tokens"])
        remaining_tokens = None
        over_limit = False
        if plan.monthly_token_limit is not None:
            remaining_tokens = max(plan.monthly_token_limit - used_tokens, 0)
            over_limit = used_tokens >= plan.monthly_token_limit
        return UsageSummary(
            user_id=user_id,
            plan_id=plan.plan_id,
            plan_display_name=plan.display_name,
            monthly_token_limit=plan.monthly_token_limit,
            hard_limit=plan.hard_limit,
            byok=plan.byok,
            usage_month=month,
            used_tokens=used_tokens,
            remaining_tokens=remaining_tokens,
            over_limit=over_limit,
            provider_usage=self._usage_by_field(user_id=user_id, usage_month=month, field="provider_id"),
            model_usage=self._usage_by_field(user_id=user_id, usage_month=month, field="model_id"),
        )

    def record_usage(
        self,
        *,
        user_id: str,
        trace_id: str | None,
        buddy_id: str | None,
        provider_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        source: str,
    ) -> UsageLedgerEntry:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        total_tokens = input_tokens + output_tokens
        month = current_usage_month()
        summary = self.usage_summary(user_id, usage_month=month)
        if (
            summary.hard_limit
            and summary.monthly_token_limit is not None
            and summary.used_tokens + total_tokens > summary.monthly_token_limit
        ):
            raise TokenPlanLimitExceeded(summary=summary, attempted_tokens=total_tokens)

        entry = UsageLedgerEntry(
            usage_event_id=new_id("usage"),
            user_id=user_id,
            trace_id=trace_id,
            buddy_id=buddy_id,
            provider_id=provider_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            source=source,
            usage_month=month,
            created_at=now_iso(),
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO usage_ledger (
                    usage_event_id, user_id, trace_id, buddy_id, provider_id, model_id,
                    input_tokens, output_tokens, total_tokens, source, usage_month, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.usage_event_id,
                    entry.user_id,
                    entry.trace_id,
                    entry.buddy_id,
                    entry.provider_id,
                    entry.model_id,
                    entry.input_tokens,
                    entry.output_tokens,
                    entry.total_tokens,
                    entry.source,
                    entry.usage_month,
                    entry.created_at,
                ),
            )
        return entry

    def list_usage(self, user_id: str, usage_month: str | None = None) -> list[UsageLedgerEntry]:
        month = usage_month or current_usage_month()
        rows = self.connection.execute(
            """
            SELECT usage_event_id, user_id, trace_id, buddy_id, provider_id, model_id,
                   input_tokens, output_tokens, total_tokens, source, usage_month, created_at
            FROM usage_ledger
            WHERE user_id = ? AND usage_month = ?
            ORDER BY created_at, usage_event_id
            """,
            (user_id, month),
        ).fetchall()
        return [_entry_from_row(row) for row in rows]

    def _plan_for_user(self, user_id: str) -> TokenPlan:
        row = self.connection.execute(
            "SELECT plan_id FROM token_plan_assignments WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        plan_id = row["plan_id"] if row is not None else "free"
        return self.plans.get(plan_id, self.plans["free"])

    def _usage_by_field(self, *, user_id: str, usage_month: str, field: str) -> dict[str, dict[str, int]]:
        if field not in {"provider_id", "model_id"}:
            raise ValueError(f"unsupported usage summary field: {field}")
        rows = self.connection.execute(
            f"""
            SELECT {field} AS usage_key, COUNT(*) AS event_count, COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM usage_ledger
            WHERE user_id = ? AND usage_month = ?
            GROUP BY {field}
            ORDER BY {field}
            """,
            (user_id, usage_month),
        ).fetchall()
        return {
            row["usage_key"]: {"event_count": int(row["event_count"]), "total_tokens": int(row["total_tokens"])}
            for row in rows
        }


def current_usage_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _entry_from_row(row: sqlite3.Row) -> UsageLedgerEntry:
    return UsageLedgerEntry(
        usage_event_id=row["usage_event_id"],
        user_id=row["user_id"],
        trace_id=row["trace_id"],
        buddy_id=row["buddy_id"],
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        total_tokens=row["total_tokens"],
        source=row["source"],
        usage_month=row["usage_month"],
        created_at=row["created_at"],
    )
