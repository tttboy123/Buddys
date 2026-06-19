from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import ValidationError

from buddys_api.agent_models import AgentCreateRequest, AgentHeartbeatRequest, AgentRecord
from buddys_api.agent_store import AgentNotFoundError, AgentStore, is_denied_agent_key
from buddys_api.auth_models import UserPublic
from buddys_api.auth_routes import require_current_user


router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentRecord, status_code=201)
def create_agent(
    payload: dict[str, Any],
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> AgentRecord:
    _reject_top_level_secret_fields(payload)
    try:
        request = AgentCreateRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_agent"}) from exc

    agent = _agent_store(fastapi_request).create_agent(user_id=current_user.user_id, request=request)
    fastapi_request.app.state.sync_store.append_event(
        event_type="agent.created",
        entity_type="agent",
        entity_id=agent.agent_id,
        actor_user_id=current_user.user_id,
        visibility="auth",
        payload_summary={
            "agent_id": agent.agent_id,
            "role": agent.role,
            "status": agent.status,
            "version": agent.version,
        },
    )
    return agent


@router.get("")
def list_agents(
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, list[AgentRecord]]:
    return {"agents": _agent_store(fastapi_request).list_for_user(current_user.user_id)}


@router.get("/{agent_id}", response_model=AgentRecord)
def get_agent(
    agent_id: Annotated[str, Path(min_length=1)],
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> AgentRecord:
    try:
        return _agent_store(fastapi_request).get_for_user(user_id=current_user.user_id, agent_id=agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found"}) from exc


@router.post("/{agent_id}/heartbeat", response_model=AgentRecord)
def heartbeat_agent(
    agent_id: Annotated[str, Path(min_length=1)],
    payload: dict[str, Any],
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> AgentRecord:
    _reject_top_level_secret_fields(payload)
    try:
        request = AgentHeartbeatRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_agent_heartbeat"}) from exc

    try:
        agent = _agent_store(fastapi_request).heartbeat(
            user_id=current_user.user_id,
            agent_id=agent_id,
            request=request,
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found"}) from exc

    fastapi_request.app.state.sync_store.append_event(
        event_type="agent.heartbeat",
        entity_type="agent",
        entity_id=agent.agent_id,
        actor_user_id=current_user.user_id,
        visibility="auth",
        payload_summary={
            "agent_id": agent.agent_id,
            "role": agent.role,
            "status": agent.status,
            "version": agent.version,
            "last_seen": agent.last_seen,
        },
    )
    return agent


def _agent_store(request: Request) -> AgentStore:
    return request.app.state.agent_store


def _reject_top_level_secret_fields(payload: dict[str, Any]) -> None:
    rejected = sorted(key for key in payload if is_denied_agent_key(key))
    if rejected:
        raise HTTPException(
            status_code=422,
            detail={"code": "raw_secret_fields_rejected", "fields": rejected},
        )
