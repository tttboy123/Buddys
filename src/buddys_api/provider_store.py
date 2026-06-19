from __future__ import annotations

import os
import sqlite3

from buddys_api.provider_models import ProviderConfigPublic, ProviderConfigRequest, ProviderTestResult
from buddys_api.schemas import now_iso


class ProviderConfigNotFound(KeyError):
    pass


class ProviderStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert_config(self, user_id: str, request: ProviderConfigRequest) -> ProviderConfigPublic:
        existing = self._row(user_id=user_id, provider_id=request.provider_id)
        created_at = existing["created_at"] if existing is not None else now_iso()
        updated_at = now_iso()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO provider_configs (
                    user_id, provider_id, display_name, provider_type, base_url,
                    api_key_env_var, default_model, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    provider_type = excluded.provider_type,
                    base_url = excluded.base_url,
                    api_key_env_var = excluded.api_key_env_var,
                    default_model = excluded.default_model,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    request.provider_id,
                    request.display_name,
                    request.provider_type,
                    request.base_url,
                    request.api_key_env_var,
                    request.default_model,
                    created_at,
                    updated_at,
                ),
            )
        return self.get_config(user_id=user_id, provider_id=request.provider_id)

    def list_configs(self, user_id: str) -> list[ProviderConfigPublic]:
        rows = self.connection.execute(
            """
            SELECT provider_id, display_name, provider_type, base_url, api_key_env_var,
                   default_model, created_at, updated_at
            FROM provider_configs
            WHERE user_id = ?
            ORDER BY provider_id
            """,
            (user_id,),
        ).fetchall()
        return [_config_from_row(row) for row in rows]

    def get_config(self, user_id: str, provider_id: str) -> ProviderConfigPublic:
        row = self._row(user_id=user_id, provider_id=provider_id)
        if row is None:
            raise ProviderConfigNotFound(provider_id)
        return _config_from_row(row)

    def test_config(self, user_id: str, provider_id: str) -> ProviderTestResult:
        config = self.get_config(user_id=user_id, provider_id=provider_id)
        configured = _is_configured(config)
        return ProviderTestResult(
            provider_id=config.provider_id,
            status="configured" if configured else "unconfigured",
            api_key_env_var=config.api_key_env_var,
            external_network_called=False,
        )

    def _row(self, *, user_id: str, provider_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT provider_id, display_name, provider_type, base_url, api_key_env_var,
                   default_model, created_at, updated_at
            FROM provider_configs
            WHERE user_id = ? AND provider_id = ?
            """,
            (user_id, provider_id),
        ).fetchone()


def _is_configured(config: ProviderConfigPublic) -> bool:
    if config.provider_type == "mock":
        return True
    if config.api_key_env_var is None:
        return False
    return bool(os.getenv(config.api_key_env_var, "").strip())


def _config_from_row(row: sqlite3.Row) -> ProviderConfigPublic:
    return ProviderConfigPublic(
        provider_id=row["provider_id"],
        display_name=row["display_name"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        api_key_env_var=row["api_key_env_var"],
        default_model=row["default_model"],
        configured=_is_configured(
            ProviderConfigPublic(
                provider_id=row["provider_id"],
                display_name=row["display_name"],
                provider_type=row["provider_type"],
                base_url=row["base_url"],
                api_key_env_var=row["api_key_env_var"],
                default_model=row["default_model"],
                configured=False,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
