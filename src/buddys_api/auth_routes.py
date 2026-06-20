from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from buddys_api.auth_models import AuthResponse, LoginRequest, RegisterRequest, UserPublic
from buddys_api.auth_store import AuthStore, DuplicateEmailError, InvalidCredentialsError
from buddys_api.buddy_store import BuddyStore
from buddys_api.schemas import Buddy


router = APIRouter(tags=["auth"])


class CreateMyBuddyRequest(BaseModel):
    name: str = Field(default="Home Buddy", min_length=1)
    space_id: str = Field(default="home", min_length=1)


@router.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(request: RegisterRequest, fastapi_request: Request) -> AuthResponse:
    store = _auth_store(fastapi_request)
    _require_valid_invite_code(request.invite_code)
    try:
        user = store.register_user(
            email=request.email,
            password=request.password,
            display_name=request.display_name,
        )
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail={"code": "email_already_registered"}) from exc
    auth_result = store.issue_session(user)
    return AuthResponse(user=auth_result.user, access_token=auth_result.access_token)


@router.post("/auth/login", response_model=AuthResponse)
def login(request: LoginRequest, fastapi_request: Request) -> AuthResponse:
    try:
        auth_result = _auth_store(fastapi_request).login(email=request.email, password=request.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials"}) from exc
    return AuthResponse(user=auth_result.user, access_token=auth_result.access_token)


@router.get("/auth/me", response_model=UserPublic)
def me(current_user: Annotated[UserPublic, Depends(require_current_user)]) -> UserPublic:
    return current_user


@router.post("/auth/logout", status_code=204)
def logout(
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    del current_user
    _auth_store(fastapi_request).logout(_bearer_token(authorization))
    return Response(status_code=204)


@router.post("/me/buddies", response_model=Buddy, status_code=201)
def create_my_buddy(
    request: CreateMyBuddyRequest,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> Buddy:
    buddy = _buddy_store(fastapi_request).create_buddy(
        user_id=current_user.user_id,
        name=request.name,
        space_id=request.space_id,
        created_via="auth",
    )
    fastapi_request.app.state.sync_store.append_event(
        event_type="buddy.created",
        entity_type="buddy",
        entity_id=buddy.buddy_id,
        actor_user_id=current_user.user_id,
        visibility="auth",
        payload_summary={"buddy_id": buddy.buddy_id, "user_id": current_user.user_id, "space_id": buddy.space_id},
    )
    return buddy


@router.get("/me/buddies")
def list_my_buddies(
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, list[Buddy]]:
    return {"buddies": _buddy_store(fastapi_request).list_for_user(current_user.user_id, created_via="auth")}


@router.get("/me/buddies/{buddy_id}", response_model=Buddy)
def get_my_buddy(
    buddy_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> Buddy:
    try:
        return _buddy_store(fastapi_request).get_for_user(
            buddy_id=buddy_id,
            user_id=current_user.user_id,
            created_via="auth",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "buddy_not_found"}) from exc


def require_current_user(
    fastapi_request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> UserPublic:
    token = _bearer_token(authorization)
    user = _auth_store(fastapi_request).authenticate_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_token"})
    return user


def _auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def _buddy_store(request: Request) -> BuddyStore:
    return request.app.state.buddy_store


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    return token.strip()


def _require_valid_invite_code(invite_code: str | None) -> None:
    required_code = os.getenv("BUDDYS_INVITE_CODE", "").strip()
    if not required_code:
        return
    if invite_code is None:
        raise HTTPException(status_code=403, detail={"code": "invite_required"})
    if invite_code != required_code:
        raise HTTPException(status_code=403, detail={"code": "invite_invalid"})
