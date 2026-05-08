from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class StatusResponse(BaseModel):
    success: bool
    message: str


class ErrorResponse(BaseModel):
    error: str
    status_code: int
