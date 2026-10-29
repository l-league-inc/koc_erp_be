from typing import Any, Optional

from django.conf import settings
from django.db.models import QuerySet
from ninja import Schema
from ninja.pagination import PageNumberPagination
from pydantic import Field


class CustomPageNumberPagination(PageNumberPagination):
    items_attribute = "data"

    class Input(Schema):
        page: int = Field(1, ge=1)
        page_size: int | str = Field(settings.PAGINATION_PER_PAGE)

    class Output(Schema):
        count: int
        totalCnt: int
        pageCnt: int
        curPage: int
        nextPage: Optional[int]
        previousPage: Optional[int]

    def __init__(
        self, page_size: int = settings.PAGINATION_PER_PAGE, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.page_size = page_size

    def paginate_queryset(
        self, queryset: QuerySet, pagination: Input, **params: Any
    ) -> dict:
        self.page_size = pagination.page_size
        if self.page_size == "all":
            return {
                "data": queryset,
                "count": len(queryset),
                "totalCnt": len(queryset),
                "pageCnt": 1,
                "curPage": 1,
                "nextPage": None,
                "previousPage": None,
            }
        else:
            self.page_size = int(self.page_size)
        offset = (pagination.page - 1) * self.page_size
        paginated_items = list(queryset[offset : offset + self.page_size])
        totalCnt = self._items_count(queryset)
        pageCnt = (totalCnt + self.page_size - 1) // self.page_size
        next_page, previous_page = None, None
        if pagination.page > 1:
            previous_page = pagination.page - 1
        if offset + self.page_size < totalCnt:
            next_page = pagination.page + 1
        return {
            "data": paginated_items,
            "count": len(paginated_items),
            "totalCnt": totalCnt,
            "pageCnt": pageCnt,
            "curPage": pagination.page,
            "nextPage": next_page,
            "previousPage": previous_page,
        }

    async def apaginate_queryset(
        self, queryset: QuerySet, pagination: Input, **params: Any
    ) -> dict:
        self.page_size = pagination.page_size
        if self.page_size == "all":
            if isinstance(queryset, QuerySet):
                data = [obj async for obj in queryset]
            else:
                data = queryset
            total = len(data)
            return {
                "data": data,
                "count": total,
                "totalCnt": total,
                "pageCnt": 1,
                "curPage": 1,
                "nextPage": None,
                "previousPage": None,
            }
        else:
            self.page_size = int(self.page_size)
        offset = (pagination.page - 1) * self.page_size
        if isinstance(queryset, QuerySet):
            chunk = queryset[offset : offset + self.page_size]
            # 이미 평가된 QuerySet은 슬라이스가 list를 반환함 (Django)
            if hasattr(chunk, "__aiter__"):
                paginated_items = [obj async for obj in chunk]
            else:
                paginated_items = list(chunk)
        else:
            paginated_items = list(queryset[offset : offset + self.page_size])
        totalCnt = await self._aitems_count(queryset)
        pageCnt = (totalCnt + self.page_size - 1) // self.page_size
        next_page, previous_page = None, None
        if pagination.page > 1:
            previous_page = pagination.page - 1
        if offset + self.page_size < totalCnt:
            next_page = pagination.page + 1
        return {
            "data": paginated_items,
            "count": len(paginated_items),
            "totalCnt": totalCnt,
            "pageCnt": pageCnt,
            "curPage": pagination.page,
            "nextPage": next_page,
            "previousPage": previous_page,
        }

    async def _aitems_count(self, queryset: QuerySet) -> int:
        try:
            return await queryset.acount()
        except AttributeError:
            return len(queryset)
