from unittest.mock import MagicMock

from sqlalchemy import column, select

from app.shared.pagination import PaginationParams, paginate


class TestPaginationParams:
    def test_defaults(self):
        params = PaginationParams(page=1, per_page=20)
        assert params.page == 1
        assert params.per_page == 20
        assert params.offset == 0

    def test_offset_calculation(self):
        params = PaginationParams(page=3, per_page=10)
        assert params.offset == 20

    def test_first_page_offset(self):
        params = PaginationParams(page=1, per_page=50)
        assert params.offset == 0


class TestPaginate:
    def _make_mock_session(self, total: int):
        session = MagicMock()
        session.scalar.return_value = total
        session.scalars.return_value.all.return_value = [f"item_{i}" for i in range(min(total, 10))]
        return session

    def _make_query(self):
        return select(column("id"))

    def test_returns_tuple_of_four(self):
        session = self._make_mock_session(total=0)
        result = paginate(session, self._make_query(), page=1, per_page=20)
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_pages_zero_when_no_items(self):
        session = self._make_mock_session(total=0)
        _, total, page, pages = paginate(session, self._make_query(), page=1, per_page=20)
        assert total == 0
        assert pages == 0

    def test_pages_calculation(self):
        session = self._make_mock_session(total=45)
        _, total, _, pages = paginate(session, self._make_query(), page=1, per_page=20)
        assert total == 45
        assert pages == 3  # ceil(45/20)

    def test_pages_exact_multiple(self):
        session = self._make_mock_session(total=40)
        _, _, _, pages = paginate(session, self._make_query(), page=1, per_page=20)
        assert pages == 2
