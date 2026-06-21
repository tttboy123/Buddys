from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from buddys_api.auth_models import UserPublic
from buddys_api.auth_routes import require_current_user
from buddys_api.engagement_metrics_models import EngagementMetricsResponse, RetentionSummaryResponse
from buddys_api.engagement_metrics_store import EngagementMetricsStore


router = APIRouter(prefix="/metrics", tags=["engagement-metrics"])


@router.get("/engagement", response_model=EngagementMetricsResponse)
def get_engagement_metrics(
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> EngagementMetricsResponse:
    return _engagement_metrics_store(fastapi_request).engagement_metrics_for_user(user_id=current_user.user_id)


@router.get("/retention-summary", response_model=RetentionSummaryResponse)
def get_retention_summary(
    fastapi_request: Request,
    current_user: Annotated[UserPublic, Depends(require_current_user)],
) -> RetentionSummaryResponse:
    if current_user.email.lower() not in _founder_metrics_email_allowlist():
        raise HTTPException(status_code=403, detail={"code": "founder_metrics_forbidden"})
    return _engagement_metrics_store(fastapi_request).retention_summary()


def _engagement_metrics_store(request: Request) -> EngagementMetricsStore:
    return request.app.state.engagement_metrics_store


def _founder_metrics_email_allowlist() -> set[str]:
    raw = os.getenv("BUDDYS_FOUNDER_METRICS_EMAIL_ALLOWLIST", "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}
