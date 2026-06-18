from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from buddys_api.adapters.mock_home import MockHomeAdapter
from buddys_api.device_routes import router as device_router
from buddys_api.device_store import DeviceRegistry
from buddys_api.runtime import BuddysRuntime
from buddys_api.schemas import ActionTrace, Buddy, CostEvent


STATIC_DIR = Path(__file__).resolve().parent / "static"


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


def create_app(runtime: BuddysRuntime | None = None, device_store: DeviceRegistry | None = None) -> FastAPI:
    app = FastAPI(title="Buddys Runtime API")
    app.state.runtime = runtime or _runtime_from_env()
    app.state.device_store = device_store or DeviceRegistry()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(device_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/console", response_class=HTMLResponse)
    def console() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/favicon.ico", status_code=204)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.post("/buddies", status_code=201)
    def create_buddy(request: CreateBuddyRequest) -> Buddy:
        return app.state.runtime.create_home_buddy(user_id=request.user_id)

    @app.get("/buddies/{buddy_id}")
    def get_buddy(buddy_id: str) -> Buddy:
        try:
            return app.state.runtime._get_buddy(buddy_id)
        except KeyError as exc:
            raise _not_found("buddy_not_found") from exc

    @app.post("/buddies/{buddy_id}/messages")
    def send_message(buddy_id: str, request: SendMessageRequest) -> dict[str, object]:
        try:
            proposal = app.state.runtime.submit_message(
                buddy_id=buddy_id,
                user_id=request.user_id,
                text=request.message,
            )
        except KeyError as exc:
            raise _not_found("buddy_not_found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"code": "buddy_access_denied"}) from exc

        trace = app.state.runtime.trace_store.get(proposal.trace_id)
        return {
            "trace_id": proposal.trace_id,
            "assistant_message": _assistant_message(proposal.summary, proposal.requires_confirmation),
            "proposal_id": proposal.proposal_id,
            "requires_confirmation": proposal.requires_confirmation,
            "cost_event_ids": trace.cost_refs,
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

        return {
            "proposal_id": proposal_id,
            "trace_id": trace.trace_id,
            "permission_decision": trace.permission_decision,
            "tool_result": trace.tool_result,
        }

    @app.get("/traces/{trace_id}")
    def get_trace(trace_id: str) -> ActionTrace:
        try:
            return app.state.runtime.trace_store.get(trace_id)
        except KeyError as exc:
            raise _not_found("trace_not_found") from exc

    @app.get("/cost-events")
    def list_cost_events() -> dict[str, list[CostEvent]]:
        return {"cost_events": app.state.runtime.cost_meter.list()}

    return app


def _assistant_message(summary: str, requires_confirmation: bool) -> str:
    if requires_confirmation:
        return f"{summary}。需要确认后执行。"
    return summary


def _not_found(code: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code})


def _runtime_from_env() -> BuddysRuntime:
    can_control_devices = os.getenv("BUDDYS_MOCK_CAN_CONTROL_DEVICES", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    return BuddysRuntime(adapter=MockHomeAdapter(can_control_devices=can_control_devices))


app = create_app()
