from __future__ import annotations

import sqlite3
from typing import Literal

from buddys_api.schemas import Buddy, new_id


BuddyOrigin = Literal["auth", "legacy"]


class BuddyStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_buddy(
        self,
        user_id: str,
        name: str = "Home Buddy",
        space_id: str = "home",
        created_via: BuddyOrigin = "auth",
    ) -> Buddy:
        buddy = Buddy(
            buddy_id=new_id("buddy"),
            user_id=user_id,
            name=name,
            space_id=space_id,
            device_id=None,
            autonomy_level="A",
            status="idle",
        )
        return self.save(buddy, created_via=created_via)

    def save(self, buddy: Buddy, created_via: BuddyOrigin = "auth") -> Buddy:
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO buddies (
                    buddy_id, user_id, name, space_id, device_id, autonomy_level, status, created_at, created_via
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    buddy.buddy_id,
                    buddy.user_id,
                    buddy.name,
                    buddy.space_id,
                    buddy.device_id,
                    buddy.autonomy_level,
                    buddy.status,
                    buddy.created_at,
                    created_via,
                ),
            )
        return buddy

    def get(self, buddy_id: str) -> Buddy:
        row = self._fetch_buddy(buddy_id=buddy_id, created_via=None)
        if row is None:
            raise KeyError(f"buddy not found: {buddy_id}")
        return _buddy_from_row(row)

    def get_legacy(self, buddy_id: str) -> Buddy:
        row = self._fetch_buddy(buddy_id=buddy_id, created_via="legacy")
        if row is None:
            raise KeyError(f"buddy not found: {buddy_id}")
        return _buddy_from_row(row)

    def get_for_user(self, buddy_id: str, user_id: str, created_via: BuddyOrigin | None = None) -> Buddy:
        buddy = self._get_for_user(buddy_id=buddy_id, user_id=user_id, created_via=created_via)
        if buddy is None:
            raise KeyError(f"buddy not found: {buddy_id}")
        return buddy

    def list_for_user(self, user_id: str, created_via: BuddyOrigin | None = None) -> list[Buddy]:
        where = "WHERE user_id = ?"
        params: tuple[str, ...] = (user_id,)
        if created_via is not None:
            where += " AND created_via = ?"
            params = (user_id, created_via)
        rows = self.connection.execute(
            """
            SELECT buddy_id, user_id, name, space_id, device_id, autonomy_level, status, created_at
            FROM buddies
            {where}
            ORDER BY created_at, buddy_id
            """.format(where=where),
            params,
        ).fetchall()
        return [_buddy_from_row(row) for row in rows]

    def list_legacy(self) -> list[Buddy]:
        rows = self.connection.execute(
            """
            SELECT buddy_id, user_id, name, space_id, device_id, autonomy_level, status, created_at
            FROM buddies
            WHERE created_via = 'legacy'
            ORDER BY created_at, buddy_id
            """
        ).fetchall()
        return [_buddy_from_row(row) for row in rows]

    def _get_for_user(
        self,
        buddy_id: str,
        user_id: str,
        created_via: BuddyOrigin | None,
    ) -> Buddy | None:
        where = "WHERE buddy_id = ? AND user_id = ?"
        params: tuple[str, ...] = (buddy_id, user_id)
        if created_via is not None:
            where += " AND created_via = ?"
            params = (buddy_id, user_id, created_via)
        row = self.connection.execute(
            """
            SELECT buddy_id, user_id, name, space_id, device_id, autonomy_level, status, created_at
            FROM buddies
            {where}
            """.format(where=where),
            params,
        ).fetchone()
        if row is None:
            return None
        return _buddy_from_row(row)

    def _fetch_buddy(self, buddy_id: str, created_via: BuddyOrigin | None) -> sqlite3.Row | None:
        where = "WHERE buddy_id = ?"
        params: tuple[str, ...] = (buddy_id,)
        if created_via is not None:
            where += " AND created_via = ?"
            params = (buddy_id, created_via)
        return self.connection.execute(
            """
            SELECT buddy_id, user_id, name, space_id, device_id, autonomy_level, status, created_at
            FROM buddies
            {where}
            """.format(where=where),
            params,
        ).fetchone()


def _buddy_from_row(row: sqlite3.Row) -> Buddy:
    return Buddy(
        buddy_id=row["buddy_id"],
        user_id=row["user_id"],
        name=row["name"],
        space_id=row["space_id"],
        device_id=row["device_id"],
        autonomy_level=row["autonomy_level"],
        status=row["status"],
        created_at=row["created_at"],
    )
