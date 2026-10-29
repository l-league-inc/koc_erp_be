from typing import Generic, TypeVar

from ninja import Schema


T = TypeVar("T")


class ObjectResponse(Schema, Generic[T]):
    results: T


class ErrorResponse(Schema):
    detail: str
