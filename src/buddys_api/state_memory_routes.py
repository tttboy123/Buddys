from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from buddys_api.auth_models import UserPublic
from buddys_api.auth_routes import require_current_user
from buddys_api.buddy_store import BuddyStore
from buddys_api.state_memory_models import (
    StateMemoryCaptureRequest,
    StateMemoryCaptureSource,
    StateMemoryProposalCorrectionRequest,
    StateMemoryQueryAnswer,
    StateMemoryQueryRequest,
    StateMemoryRecipeCreateRequest,
)
from buddys_api.state_memory_service import StateMemoryService
from buddys_api.state_memory_store import StateMemoryStore
from buddys_api.token_plan import TokenPlanLimitExceeded
from buddys_api.providers.openai_compatible_provider import StateMemoryProviderError


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


@router.get("/recipes")
def list_state_memory_recipes(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, list[object]]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    return {
        "recipes": _state_memory_store(fastapi_request).list_recipes(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
        )
    }


@router.post("/recipes", status_code=201)
def create_state_memory_recipe(
    buddy_id: str,
    request: StateMemoryRecipeCreateRequest,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    try:
        recipe = _state_memory_store(fastapi_request).create_recipe(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            name=request.name,
            ingredients=request.ingredients,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return {"recipe": recipe}


@router.delete("/recipes/{recipe_id}", status_code=204)
def delete_state_memory_recipe(
    buddy_id: str,
    recipe_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> Response:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    try:
        _state_memory_store(fastapi_request).delete_recipe(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            recipe_id=recipe_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "recipe_not_found"}) from exc
    return Response(status_code=204)


@router.post("/query")
def query_state_memory(
    buddy_id: str,
    request: StateMemoryQueryRequest,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> StateMemoryQueryAnswer:
    buddy = _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    try:
        return _state_memory_service(fastapi_request).answer_query(
            user_id=current_user.user_id,
            buddy_id=buddy.buddy_id,
            space_id=buddy.space_id,
            device_id=buddy.device_id,
            question=request.question,
        )
    except TokenPlanLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "token_plan_limit_exceeded",
                "plan_id": exc.summary.plan_id,
                "used_tokens": exc.summary.used_tokens,
                "monthly_token_limit": exc.summary.monthly_token_limit,
                "attempted_tokens": exc.attempted_tokens,
                "usage_scope": "state_memory",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    except StateMemoryProviderError as exc:
        if exc.code == "state_memory_query_unsupported":
            raise HTTPException(status_code=422, detail={"code": exc.code}) from exc
        raise HTTPException(status_code=503, detail={"code": exc.code, **exc.details}) from exc


@router.post("/captures/{source}", status_code=201)
def create_state_memory_capture_proposal(
    buddy_id: str,
    source: StateMemoryCaptureSource,
    request: StateMemoryCaptureRequest,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    if source == "photo" and request.image_base64 is None:
        raise HTTPException(status_code=422, detail={"code": "photo_capture_image_required"})
    if source != "photo" and not request.content:
        raise HTTPException(status_code=422, detail={"code": "state_memory_capture_content_required"})
    try:
        proposal, revision = _state_memory_service(fastapi_request).create_capture_proposal(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            source=source,
            content=request.content or "",
            image_base64=request.image_base64,
            image_media_type=request.image_media_type,
        )
    except TokenPlanLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "token_plan_limit_exceeded",
                "plan_id": exc.summary.plan_id,
                "used_tokens": exc.summary.used_tokens,
                "monthly_token_limit": exc.summary.monthly_token_limit,
                "attempted_tokens": exc.attempted_tokens,
                "usage_scope": "state_memory",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    except StateMemoryProviderError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, **exc.details}) from exc
    return {
        "proposal": proposal,
        "state_revision": revision,
    }


@router.post("/proposals/{proposal_id}/confirm")
def confirm_state_memory_proposal(
    buddy_id: str,
    proposal_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    try:
        result, revision = _state_memory_service(fastapi_request).confirm_proposal(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            proposal_id=proposal_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "proposal_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return {
        **result.model_dump(mode="json"),
        "state_revision": revision,
    }


@router.post("/proposals/{proposal_id}/reject")
def reject_state_memory_proposal(
    buddy_id: str,
    proposal_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    try:
        proposal, revision = _state_memory_service(fastapi_request).reject_proposal(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            proposal_id=proposal_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "proposal_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return {
        "proposal": proposal,
        "state_revision": revision,
    }


@router.post("/proposals/{proposal_id}/correct")
def correct_state_memory_proposal(
    buddy_id: str,
    proposal_id: str,
    request: StateMemoryProposalCorrectionRequest,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    try:
        result, revision = _state_memory_service(fastapi_request).correct_proposal(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            proposal_id=proposal_id,
            corrected_deltas=request.deltas,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "proposal_not_found"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    return {
        **result.model_dump(mode="json"),
        "state_revision": revision,
    }


def _require_auth_buddy(request: Request, *, buddy_id: str, user_id: str) -> UserPublic | object:
    try:
        return _buddy_store(request).get_for_user(buddy_id=buddy_id, user_id=user_id, created_via="auth")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "buddy_not_found"}) from exc


def _state_memory_store(request: Request) -> StateMemoryStore:
    return request.app.state.state_memory_store


def _state_memory_service(request: Request) -> StateMemoryService:
    return request.app.state.state_memory_service


def _buddy_store(request: Request) -> BuddyStore:
    return request.app.state.buddy_store
