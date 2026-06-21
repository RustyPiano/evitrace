from fastapi import status
from pydantic import BaseModel, Field


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


class SuccessResponse(BaseModel):
    data: object
    message: str = "ok"
