from typing import Any, Generic, Sequence, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Query as SAQuery, Session

T = TypeVar("T")


class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> None:
        self.page = page
        self.per_page = per_page
        self.offset = (page - 1) * per_page


class PaginationResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    pages: int


def paginate(
    db: Session,
    query: SAQuery[T],
    page: int = 1,
    per_page: int = 20,
) -> tuple[Sequence[T], int, int, int]:
    total_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(total_query) or 0

    items = db.scalars(query.offset((page - 1) * per_page).limit(per_page)).all()
    pages = (total + per_page - 1) // per_page if total else 0

    return items, total, page, pages
