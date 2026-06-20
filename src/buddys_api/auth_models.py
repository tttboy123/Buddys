from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class UserPublic(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
    created_at: str


class SessionPublic(BaseModel):
    session_id: str
    user_id: str
    created_at: str


class AuthResult(BaseModel):
    user: UserPublic
    session: SessionPublic
    access_token: str


class AuthResponse(BaseModel):
    user: UserPublic
    access_token: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)
    display_name: str | None = None
    invite_code: str | None = None

    @field_validator("email")
    @classmethod
    def email_must_not_be_blank(cls, value: str) -> str:
        return _require_stripped(value)

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_stripped(value)

    @field_validator("invite_code")
    @classmethod
    def invite_code_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_stripped(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def email_must_not_be_blank(cls, value: str) -> str:
        return _require_stripped(value)


def _require_stripped(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be blank")
    return stripped
