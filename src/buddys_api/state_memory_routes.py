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
    StateMemoryShoppingPassCreateRequest,
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


@router.get("/shopping-pass")
def list_state_memory_shopping_pass(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    store = _state_memory_store(fastapi_request)
    return {
        "items": store.list_shopping_pass_items(user_id=current_user.user_id, buddy_id=buddy_id),
        "summary": store.summarize_shopping_pass(user_id=current_user.user_id, buddy_id=buddy_id),
    }


@router.post("/shopping-pass/items", status_code=201)
def create_state_memory_shopping_pass_item(
    buddy_id: str,
    request: StateMemoryShoppingPassCreateRequest,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    store = _state_memory_store(fastapi_request)
    item = store.add_shopping_pass_item(
        user_id=current_user.user_id,
        buddy_id=buddy_id,
        name=request.name,
        source_kind="manual",
        source_summary="Added manually from the shopping pass.",
    )
    revision = _append_shopping_pass_event(
        fastapi_request,
        actor_user_id=current_user.user_id,
        buddy_id=buddy_id,
        event_type="state_memory.shopping_pass_item_added",
        payload_summary={
            "shopping_item_id": item.shopping_item_id,
            "name": item.name,
            "source_kind": item.source_kind,
            "status": item.status,
        },
    )
    return {
        "item": item,
        "summary": store.summarize_shopping_pass(user_id=current_user.user_id, buddy_id=buddy_id),
        "state_revision": revision,
    }


@router.post("/shopping-pass/promote-hint", status_code=201)
def promote_state_memory_hint_to_shopping_pass(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    store = _state_memory_store(fastapi_request)
    hint = store.current_shopping_pass_hint(user_id=current_user.user_id, buddy_id=buddy_id)
    if hint is None:
        raise HTTPException(status_code=409, detail={"code": "shopping_pass_hint_unavailable"})
    item_names = [str(name).strip() for name in (hint.get("basis") or {}).get("item_names", []) if str(name).strip()]
    if not item_names:
        raise HTTPException(status_code=409, detail={"code": "shopping_pass_hint_unavailable"})
    item = store.add_shopping_pass_item(
        user_id=current_user.user_id,
        buddy_id=buddy_id,
        name=item_names[0],
        source_kind="proactive_hint",
        source_summary=str(hint.get("message") or "Promoted current shopping hint."),
    )
    revision = _append_shopping_pass_event(
        fastapi_request,
        actor_user_id=current_user.user_id,
        buddy_id=buddy_id,
        event_type="state_memory.shopping_pass_hint_promoted",
        payload_summary={
            "shopping_item_id": item.shopping_item_id,
            "name": item.name,
            "source_kind": item.source_kind,
        },
    )
    return {
        "item": item,
        "summary": store.summarize_shopping_pass(user_id=current_user.user_id, buddy_id=buddy_id),
        "state_revision": revision,
    }


@router.post("/shopping-pass/promote-latest-query", status_code=201)
def promote_state_memory_latest_query_to_shopping_pass(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    latest_query = _latest_missing_recipe_query(
        fastapi_request,
        user_id=current_user.user_id,
        buddy_id=buddy_id,
    )
    if latest_query is None:
        raise HTTPException(status_code=409, detail={"code": "shopping_pass_latest_query_unavailable"})
    store = _state_memory_store(fastapi_request)
    items = [
        store.add_shopping_pass_item(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            name=name,
            source_kind="missing_for_recipe",
            source_summary=f"Promoted missing recipe items from {latest_query['subject_name']}.",
        )
        for name in latest_query["missing_items"]
    ]
    revision = _append_shopping_pass_event(
        fastapi_request,
        actor_user_id=current_user.user_id,
        buddy_id=buddy_id,
        event_type="state_memory.shopping_pass_latest_query_promoted",
        payload_summary={
            "source_trace_id": latest_query["trace_id"],
            "subject_name": latest_query["subject_name"],
            "item_names": [item.name for item in items],
            "count": len(items),
        },
    )
    return {
        "items": items,
        "summary": store.summarize_shopping_pass(user_id=current_user.user_id, buddy_id=buddy_id),
        "state_revision": revision,
    }


@router.post("/shopping-pass/items/{shopping_item_id}/done")
def mark_state_memory_shopping_pass_item_done(
    buddy_id: str,
    shopping_item_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    _require_auth_buddy(fastapi_request, buddy_id=buddy_id, user_id=current_user.user_id)
    store = _state_memory_store(fastapi_request)
    try:
        item = store.mark_shopping_pass_item_done(
            user_id=current_user.user_id,
            buddy_id=buddy_id,
            shopping_item_id=shopping_item_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "shopping_pass_item_not_found"}) from exc
    revision = _append_shopping_pass_event(
        fastapi_request,
        actor_user_id=current_user.user_id,
        buddy_id=buddy_id,
        event_type="state_memory.shopping_pass_item_done",
        payload_summary={
            "shopping_item_id": item.shopping_item_id,
            "name": item.name,
            "status": item.status,
        },
    )
    return {
        "item": item,
        "summary": store.summarize_shopping_pass(user_id=current_user.user_id, buddy_id=buddy_id),
        "state_revision": revision,
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


def _append_shopping_pass_event(
    request: Request,
    *,
    actor_user_id: str,
    buddy_id: str,
    event_type: str,
    payload_summary: dict[str, object],
) -> int:
    return request.app.state.sync_store.append_event(
        event_type=event_type,
        entity_type="state_memory_shopping_pass",
        entity_id=buddy_id,
        actor_user_id=actor_user_id,
        visibility="auth",
        payload_summary={"buddy_id": buddy_id, **payload_summary},
    ).revision


def _latest_missing_recipe_query(
    request: Request,
    *,
    user_id: str,
    buddy_id: str,
) -> dict[str, object] | None:
    traces = request.app.state.runtime.trace_store.list()
    for trace in reversed(traces):
        if trace.user_id != user_id or trace.buddy_id != buddy_id:
            continue
        if trace.intent.name != "state_memory_query" or trace.proposal.action_type != "reply_only":
            continue
        args = trace.proposal.args or {}
        missing_items = [str(name).strip() for name in args.get("missing_items", []) if str(name).strip()]
        if args.get("answer_type") != "missing_for_recipe" or not missing_items:
            continue
        return {
            "trace_id": trace.trace_id,
            "subject_name": args.get("subject_name") or trace.proposal.summary,
            "missing_items": sorted(dict.fromkeys(missing_items)),
        }
    return None
