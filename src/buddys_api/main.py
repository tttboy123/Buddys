from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.agent_routes import router as agent_router
from buddys_api.agent_store import AgentStore
from buddys_api.auth_models import UserPublic
from buddys_api.auth_routes import router as auth_router
from buddys_api.auth_store import AuthStore
from buddys_api.buddy_store import BuddyStore
from buddys_api.cost_meter import CostMeter
from buddys_api.db import connect_db, initialize_database
from buddys_api.device_routes import router as device_router
from buddys_api.device_store import DeviceRegistry
from buddys_api.engagement_metrics_routes import router as engagement_metrics_router
from buddys_api.engagement_metrics_store import EngagementMetricsStore
from buddys_api.provider_routes import router as provider_router
from buddys_api.provider_store import ProviderStore
from buddys_api.runtime import BuddysRuntime
from buddys_api.schemas import ActionTrace, Buddy, CostEvent
from buddys_api.state_memory_routes import router as state_memory_router
from buddys_api.state_memory_service import StateMemoryService
from buddys_api.state_memory_store import StateMemoryStore
from buddys_api.sync_routes import router as sync_router
from buddys_api.sync_store import SyncStore
from buddys_api.token_plan import TokenPlanLimitExceeded, UsageStore
from buddys_api.trace_store import TraceStore


STATIC_DIR = Path(__file__).resolve().parent / "static"
CONSOLE_TEMPLATE = Path(__file__).resolve().parent / "console_template.html"


class CreateBuddyRequest(BaseModel):
    user_id: str


class SendMessageRequest(BaseModel):
    user_id: str
    message: str
    provider_id: str | None = None
    model_id: str | None = None


class ConfirmProposalRequest(BaseModel):
    approved: bool | None = None
    decision: Literal["approved", "rejected"] | None = None

    def is_approved(self) -> bool:
        if self.approved is not None:
            return self.approved
        if self.decision is not None:
            return self.decision == "approved"
        raise ValueError("confirmation decision is required")


def create_app(
    runtime: BuddysRuntime | None = None,
    device_store: DeviceRegistry | None = None,
    db_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Buddys Runtime API")
    connection = connect_db(_db_path(db_path))
    initialize_database(connection)
    app.state.db = connection
    app.state.auth_store = AuthStore(connection)
    app.state.buddy_store = BuddyStore(connection)
    app.state.sync_store = SyncStore(connection)
    app.state.provider_store = ProviderStore(connection)
    app.state.usage_store = UsageStore(connection)
    app.state.agent_store = AgentStore(connection)
    app.state.state_memory_store = StateMemoryStore(connection)
    app.state.engagement_metrics_store = EngagementMetricsStore(connection)
    app.state.runtime = runtime or _runtime_from_env(connection=connection, buddy_store=app.state.buddy_store)
    if runtime is not None and runtime.buddy_store is None:
        runtime.buddy_store = app.state.buddy_store
    if app.state.runtime.usage_store is None:
        app.state.runtime.usage_store = app.state.usage_store
    app.state.device_store = device_store or DeviceRegistry()
    app.state.state_memory_service = StateMemoryService(
        store=app.state.state_memory_store,
        sync_store=app.state.sync_store,
        provider=app.state.runtime.provider,
        trace_store=app.state.runtime.trace_store,
        cost_meter=app.state.runtime.cost_meter,
        buddy_store=app.state.buddy_store,
        provider_store=app.state.provider_store,
        usage_store=app.state.usage_store,
        engagement_metrics_store=app.state.engagement_metrics_store,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(auth_router)
    app.include_router(device_router)
    app.include_router(sync_router)
    app.include_router(provider_router)
    app.include_router(agent_router)
    app.include_router(engagement_metrics_router)
    app.include_router(state_memory_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/console", response_class=HTMLResponse)
    def console() -> str:
        bootstrap = {"inviteRequired": bool(os.getenv("BUDDYS_INVITE_CODE", "").strip())}
        return CONSOLE_TEMPLATE.read_text(encoding="utf-8").replace(
            "__BUDDYS_BOOTSTRAP__",
            json.dumps(bootstrap),
        )

    @app.get("/favicon.ico", status_code=204)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.post("/buddies", status_code=201)
    def create_buddy(request: CreateBuddyRequest) -> Buddy:
        buddy = app.state.runtime.create_home_buddy(user_id=request.user_id)
        app.state.sync_store.append_event(
            event_type="buddy.created",
            entity_type="buddy",
            entity_id=buddy.buddy_id,
            actor_user_id=buddy.user_id,
            visibility="legacy",
            payload_summary={"buddy_id": buddy.buddy_id, "user_id": buddy.user_id, "space_id": buddy.space_id},
        )
        return buddy

    @app.get("/buddies/{buddy_id}")
    def get_buddy(buddy_id: str) -> Buddy:
        try:
            return app.state.runtime._get_legacy_buddy(buddy_id)
        except KeyError as exc:
            raise _not_found("buddy_not_found") from exc

    @app.post("/buddies/{buddy_id}/messages")
    def send_message(buddy_id: str, request: SendMessageRequest) -> dict[str, object]:
        try:
            proposal = app.state.runtime.submit_legacy_message(
                buddy_id=buddy_id,
                user_id=request.user_id,
                text=request.message,
            )
        except KeyError as exc:
            raise _not_found("buddy_not_found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"code": "buddy_access_denied"}) from exc
        except TokenPlanLimitExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "token_plan_limit_exceeded",
                    "plan_id": exc.summary.plan_id,
                    "used_tokens": exc.summary.used_tokens,
                    "monthly_token_limit": exc.summary.monthly_token_limit,
                    "attempted_tokens": exc.attempted_tokens,
                    "usage_scope": "legacy_demo",
                },
            ) from exc

        trace = app.state.runtime.trace_store.get(proposal.trace_id)
        sync_event = app.state.sync_store.append_event(
            event_type="message.proposal_created",
            entity_type="trace",
            entity_id=trace.trace_id,
            actor_user_id=trace.user_id,
            visibility="legacy",
            payload_summary={
                "trace_id": trace.trace_id,
                "buddy_id": trace.buddy_id,
                "proposal_id": proposal.proposal_id,
                "requires_confirmation": proposal.requires_confirmation,
                "cost_event_ids": trace.cost_refs,
                "message_length": len(request.message),
            },
        )
        return {
            "trace_id": proposal.trace_id,
            "assistant_message": _assistant_message(proposal.summary, proposal.requires_confirmation),
            "proposal_id": proposal.proposal_id,
            "requires_confirmation": proposal.requires_confirmation,
            "cost_event_ids": trace.cost_refs,
            "state_revision": sync_event.revision,
            "usage_scope": "legacy_demo",
            "usage_todo": "auth message route will attach usage to the authenticated user in a later phase",
        }

    @app.post("/proposals/{proposal_id}/confirm")
    def confirm_proposal(proposal_id: str, request: ConfirmProposalRequest) -> dict[str, object]:
        try:
            approved = request.is_approved()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "confirmation_decision_required"}) from exc

        try:
            trace = app.state.runtime.confirm_proposal(proposal_id=proposal_id, approved=approved)
        except KeyError as exc:
            raise _not_found("proposal_not_found") from exc

        sync_event = app.state.sync_store.append_event(
            event_type="proposal.confirmed",
            entity_type="trace",
            entity_id=trace.trace_id,
            actor_user_id=trace.user_id,
            visibility="legacy",
            payload_summary={
                "trace_id": trace.trace_id,
                "proposal_id": proposal_id,
                "buddy_id": trace.buddy_id,
                "approved": approved,
                "tool_result_status": trace.tool_result.status if trace.tool_result else None,
            },
        )
        return {
            "proposal_id": proposal_id,
            "trace_id": trace.trace_id,
            "permission_decision": trace.permission_decision,
            "tool_result": trace.tool_result,
            "state_revision": sync_event.revision,
        }

    @app.get("/traces/{trace_id}")
    def get_trace(
        trace_id: str,
        fastapi_request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> ActionTrace:
        try:
            trace = app.state.runtime.trace_store.get(trace_id)
        except KeyError as exc:
            raise _not_found("trace_not_found") from exc
        current_user = _optional_current_user(fastapi_request, authorization)
        if not _can_view_trace(fastapi_request, trace=trace, current_user=current_user):
            raise _not_found("trace_not_found")
        return trace

    @app.get("/cost-events")
    def list_cost_events(
        fastapi_request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, list[CostEvent]]:
        current_user = _optional_current_user(fastapi_request, authorization)
        visible_events = [
            event
            for event in app.state.runtime.cost_meter.list()
            if _can_view_cost_event(fastapi_request, event=event, current_user=current_user)
        ]
        return {"cost_events": visible_events}

    return app


def _assistant_message(summary: str, requires_confirmation: bool) -> str:
    if requires_confirmation:
        return f"{summary}。需要确认后执行。"
    return summary


def _not_found(code: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code})


def _optional_current_user(request: Request, authorization: str | None) -> UserPublic | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    user = request.app.state.auth_store.authenticate_token(token.strip())
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_token"})
    return user


def _can_view_trace(request: Request, *, trace: ActionTrace, current_user: UserPublic | None) -> bool:
    origin = _buddy_origin(request, trace.buddy_id)
    if origin is None:
        return False
    if origin != "auth":
        return True
    return current_user is not None and current_user.user_id == trace.user_id


def _can_view_cost_event(request: Request, *, event: CostEvent, current_user: UserPublic | None) -> bool:
    try:
        buddy = request.app.state.buddy_store.get(event.buddy_id)
    except KeyError:
        return False
    origin = _buddy_origin(request, event.buddy_id)
    if origin is None:
        return False
    if origin != "auth":
        return True
    return current_user is not None and current_user.user_id == buddy.user_id


def _buddy_origin(request: Request, buddy_id: str) -> str | None:
    try:
        return request.app.state.buddy_store.origin_for_buddy(buddy_id)
    except KeyError:
        return None


def _db_path(db_path: str | Path | None) -> str | Path:
    if db_path is not None:
        return db_path
    return os.getenv("BUDDYS_DB_PATH", ":memory:")


def _runtime_from_env(
    connection,
    buddy_store: BuddyStore | None = None,
) -> BuddysRuntime:
    can_control_devices = os.getenv("BUDDYS_MOCK_CAN_CONTROL_DEVICES", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    return BuddysRuntime(
        adapter=MockHomeAdapter(can_control_devices=can_control_devices),
        trace_store=TraceStore(connection),
        cost_meter=CostMeter(connection),
        buddy_store=buddy_store,
    )


app = create_app()
