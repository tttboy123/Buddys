from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request

from buddys_api.auth_store import AuthStore
from buddys_api.sync_models import SyncEventsResponse, SyncSnapshot
from buddys_api.sync_store import SyncStore, build_snapshot


router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/snapshot", response_model=SyncSnapshot)
def sync_snapshot(
    fastapi_request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    user_id = _optional_user_id(fastapi_request, authorization)
    runtime = fastapi_request.app.state.runtime
    return build_snapshot(
        sync_store=_sync_store(fastapi_request),
        buddy_store=fastapi_request.app.state.buddy_store,
        device_store=fastapi_request.app.state.device_store,
        traces=runtime.trace_store.list(),
        cost_events=runtime.cost_meter.list(),
        user_id=user_id,
        usage_store=getattr(fastapi_request.app.state, "usage_store", None),
        agent_store=getattr(fastapi_request.app.state, "agent_store", None),
    )


@router.get("/events", response_model=SyncEventsResponse)
def sync_events(
    fastapi_request: Request,
    since_revision: Annotated[int, Query(ge=0)] = 0,
    authorization: Annotated[str | None, Header()] = None,
) -> SyncEventsResponse:
    user_id = _optional_user_id(fastapi_request, authorization)
    store = _sync_store(fastapi_request)
    return SyncEventsResponse(
        state_revision=store.visible_state_revision(user_id),
        events=store.list_events(since_revision=since_revision, user_id=user_id),
    )


def _sync_store(request: Request) -> SyncStore:
    return request.app.state.sync_store


def _optional_user_id(request: Request, authorization: str | None) -> str | None:
    if authorization is None:
        return None
    token = _bearer_token(authorization)
    user = _auth_store(request).authenticate_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_token"})
    return user.user_id


def _auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    return token.strip()
