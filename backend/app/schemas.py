from fastapi import status
from pydantic import BaseModel, Field, field_validator

from app.constants import ROLE_ADMIN, ROLE_ANALYST


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class UserPublic(BaseModel):
    id: str
    username: str
    role: str


class CurrentUser(UserPublic):
    is_active: bool


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)
    role: str = ROLE_ANALYST

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {ROLE_ANALYST, ROLE_ADMIN}:
            raise ValueError("role must be analyst or admin")
        return value


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = None
    password: str | None = Field(default=None, min_length=1)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is not None and value not in {ROLE_ANALYST, ROLE_ADMIN}:
            raise ValueError("role must be analyst or admin")
        return value


class AdminSkillUpdate(BaseModel):
    enabled: bool


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserPublic


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    objective: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = None
