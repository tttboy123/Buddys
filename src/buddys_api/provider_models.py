from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ProviderType = Literal["mock", "openai_compatible"]
MINIMAX_OPENAI_BASE_URL = "https://api.minimaxi.com/v1"
SYSTEM_DEFAULT_PROVIDER_ID = "system-minimax-default"
SYSTEM_DEFAULT_PROVIDER_ENV_VAR = "BUDDYS_DEFAULT_OPENAI_API_KEY"
SYSTEM_DEFAULT_TOKEN_PLAN_ENV_VAR = "BUDDYS_DEFAULT_TOKEN_PLAN_KEY"
SYSTEM_DEFAULT_MODEL_ENV_VAR = "BUDDYS_DEFAULT_MODEL"
SYSTEM_DEFAULT_MODEL_NAME = "MiniMax-M3"


class ProviderCatalogItem(BaseModel):
    provider_type: ProviderType
    display_name: str
    requires_api_key_env_var: bool
    external_calls_enabled: bool = False


class ProviderConfigRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_type: ProviderType
    base_url: str | None = None
    api_key_env_var: str | None = None
    default_model: str = Field(min_length=1)

    @field_validator("provider_id", "display_name", "default_model")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("base_url", "api_key_env_var")
    @classmethod
    def optional_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("api_key_env_var")
    @classmethod
    def api_key_env_var_must_be_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError("api_key_env_var must be an environment variable name")
        return value

    @model_validator(mode="after")
    def openai_compatible_must_use_official_minimax_contract(self) -> "ProviderConfigRequest":
        if self.provider_type != "openai_compatible":
            return self
        if self.api_key_env_var is None:
            raise ValueError("openai_compatible providers must reference an env var")
        if self.base_url is not None and self.base_url.rstrip("/") != MINIMAX_OPENAI_BASE_URL:
            raise ValueError("openai_compatible providers must use the MiniMax official base URL")
        return self


class ProviderConfigPublic(BaseModel):
    provider_id: str
    display_name: str
    provider_type: ProviderType
    base_url: str | None
    api_key_env_var: str | None
    default_model: str
    configured: bool
    created_at: str
    updated_at: str


class ProviderTestResult(BaseModel):
    provider_id: str
    status: Literal["configured", "unconfigured"]
    api_key_env_var: str | None
    external_network_called: bool = False


PROVIDER_CATALOG: tuple[ProviderCatalogItem, ...] = (
    ProviderCatalogItem(
        provider_type="mock",
        display_name="Mock deterministic provider",
        requires_api_key_env_var=False,
    ),
    ProviderCatalogItem(
        provider_type="openai_compatible",
        display_name="OpenAI-compatible HTTP provider",
        requires_api_key_env_var=True,
    ),
)
