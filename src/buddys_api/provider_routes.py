from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from buddys_api.auth_routes import require_current_user
from buddys_api.auth_store import AuthStore
from buddys_api.auth_models import UserPublic
from buddys_api.provider_models import PROVIDER_CATALOG, ProviderConfigRequest
from buddys_api.provider_store import ProviderConfigNotFound, ProviderStore
from buddys_api.token_plan import UsageStore, available_plans


router = APIRouter(tags=["providers"])

SECRET_FIELD_TERMS = ("api_key", "token", "secret", "password", "private_key")
ALLOWED_SECRET_REFERENCE_FIELDS = {"apikeyenvvar"}


@router.get("/plans")
def list_plans() -> dict[str, list[dict[str, object]]]:
    return {"plans": available_plans()}


@router.get("/usage")
def current_usage(
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    return _usage_store(fastapi_request).usage_summary(current_user.user_id).model_dump(mode="json")


@router.get("/providers")
def list_providers(
    fastapi_request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    user = _optional_current_user(fastapi_request, authorization)
    configs = [] if user is None else _provider_store(fastapi_request).list_configs(user.user_id)
    return {
        "catalog": [item.model_dump(mode="json") for item in PROVIDER_CATALOG],
        "configs": [config.model_dump(mode="json") for config in configs],
    }


@router.post("/providers")
def upsert_provider(
    payload: dict[str, Any],
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    rejected_fields = _rejected_secret_fields(payload)
    if rejected_fields:
        raise HTTPException(
            status_code=422,
            detail={"code": "raw_secret_fields_rejected", "fields": rejected_fields},
        )
    try:
        request = ProviderConfigRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_provider_config"}) from exc
    config = _provider_store(fastapi_request).upsert_config(user_id=current_user.user_id, request=request)
    return config.model_dump(mode="json")


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: str,
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> dict[str, object]:
    try:
        result = _provider_store(fastapi_request).test_config(user_id=current_user.user_id, provider_id=provider_id)
    except ProviderConfigNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "provider_not_found"}) from exc
    return result.model_dump(mode="json")


def _provider_store(request: Request) -> ProviderStore:
    return request.app.state.provider_store


def _usage_store(request: Request) -> UsageStore:
    return request.app.state.usage_store


def _optional_current_user(request: Request, authorization: str | None) -> UserPublic | None:
    if authorization is None:
        return None
    token = _bearer_token(authorization)
    user = _auth_store(request).authenticate_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_or_expired_token"})
    return user


def _auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"code": "missing_bearer_token"})
    return token.strip()


def _rejected_secret_fields(payload: dict[str, Any]) -> list[str]:
    rejected: list[str] = []
    for key in payload:
        normalized = _normalize_field_name(key)
        if normalized in ALLOWED_SECRET_REFERENCE_FIELDS:
            continue
        if any(_normalize_field_name(term) in normalized for term in SECRET_FIELD_TERMS):
            rejected.append(key)
    return sorted(rejected)


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())
