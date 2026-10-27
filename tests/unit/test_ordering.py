from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.shared.clock import store_today
from app.shared.ordering import (
    _format_date_suffix,
    generate_order_number,
    generate_po_number,
    generate_receiving_number,
    generate_refund_number,
    generate_return_number,
    generate_transfer_number,
)


class TestFormatDateSuffix:
    def test_known_date(self):
        d = date(2025, 1, 5)
        assert _format_date_suffix(d) == "20250105"

    def test_end_of_year(self):
        d = date(2025, 12, 31)
        assert _format_date_suffix(d) == "20251231"


class TestGenerateOrderNumber:
    @patch("app.shared.ordering._next_sequence", return_value=1)
    def test_basic_format(self, mock_seq):
        session = MagicMock()
        result = generate_order_number(session, "MBR")
        assert result == f"MBR-{_format_date_suffix(store_today())}-0001"

    @patch("app.shared.ordering._next_sequence", return_value=123)
    def test_padded_sequence(self, mock_seq):
        session = MagicMock()
        result = generate_order_number(session, "NYC")
        assert result == f"NYC-{_format_date_suffix(store_today())}-0123"

    @patch("app.shared.ordering._next_sequence", return_value=9999)
    def test_max_sequence(self, mock_seq):
        session = MagicMock()
        result = generate_order_number(session, "LAX")
        assert result == f"LAX-{_format_date_suffix(store_today())}-9999"


class TestGeneratePONumber:
    @patch("app.shared.ordering._next_sequence", return_value=1)
    def test_format(self, mock_seq):
        session = MagicMock()
        result = generate_po_number(session)
        assert result.startswith("PO-")
        assert result.endswith("-0001")


class TestGenerateOtherNumbers:
    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_receiving(self, mock_seq):
        result = generate_receiving_number(MagicMock())
        assert result == f"REC-{store_today().strftime('%Y%m%d')}-0005"

    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_transfer(self, mock_seq):
        result = generate_transfer_number(MagicMock())
        assert result == f"TRF-{store_today().strftime('%Y%m%d')}-0005"

    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_return(self, mock_seq):
        result = generate_return_number(MagicMock())
        assert result == f"RET-{store_today().strftime('%Y%m%d')}-0005"

    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_refund(self, mock_seq):
        result = generate_refund_number(MagicMock())
        assert result == f"REF-{store_today().strftime('%Y%m%d')}-0005"


class TestDocumentNumbersUseTheStoreDate:
    """10:30 in Bangkok is still the day before in New York and in UTC-4."""

    @staticmethod
    def _at(monkeypatch, text: str) -> None:
        from datetime import datetime, timezone

        from app.shared import clock

        moment = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        monkeypatch.setattr(clock, "_utcnow", lambda: moment)

    def test_order_number_and_sequence_date(self, monkeypatch):
        self._at(monkeypatch, "2026-10-27T03:30:00")
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (7,)
        assert generate_order_number(session, "MBR") == "MBR-20261027-0007"
        assert session.execute.call_args.args[1] == {"doc_type": "ORD-MBR", "doc_date": date(2026, 10, 27)}

    @pytest.mark.parametrize("generate, prefix", [
        (generate_po_number, "PO"), (generate_receiving_number, "REC"),
        (generate_transfer_number, "TRF"), (generate_return_number, "RET"),
        (generate_refund_number, "REF"),
    ])
    def test_other_documents(self, monkeypatch, generate, prefix):
        self._at(monkeypatch, "2026-10-26T17:00:00")  # 00:00 on the 27th in Bangkok
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (1,)
        assert generate(session) == f"{prefix}-20261027-0001"

    def test_day_start_hour(self, monkeypatch):
        from app.config.settings import settings

        monkeypatch.setattr(settings, "STORE_DAY_START_HOUR", 5)
        self._at(monkeypatch, "2026-10-27T21:59:00")  # 04:59 on the 28th in Bangkok
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (1,)
        assert generate_refund_number(session) == "REF-20261027-0001"
