from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from buddys_api.auth_models import UserPublic
from buddys_api.auth_routes import require_current_user
from buddys_api.buddy_store import BuddyStore
from buddys_api.state_memory_store import StateMemoryStore


router = APIRouter(prefix="/me/buddies/{buddy_id}/state-memory", tags=["state-memory"])


@router.get("/items")
def list_state_memory_items(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, list[object]]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    return {
        "items": _state_memory_store(fastapi_request).list_items(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
        )
    }


@router.get("/history")
def list_state_memory_history(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, list[object]]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    return {
        "history": _state_memory_store(fastapi_request).list_history(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
        )
    }


@router.get("/pending-proposals")
def list_state_memory_pending_proposals(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, list[object]]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    return {
        "pending_proposals": _state_memory_store(fastapi_request).list_pending_proposals(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
        )
    }


def _require_auth_buddy(request: Request, *, buddy_id: str, user_id: str) -> None:
    try:
        _buddy_store(request).get_for_user(buddy_id=buddy_id, user_id=user_id, created_via="auth")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "buddy_not_found"}) from exc


def _state_memory_store(request: Request) -> StateMemoryStore:
    return request.app.state.state_memory_store


def _buddy_store(request: Request) -> BuddyStore:
    return request.app.state.buddy_store
