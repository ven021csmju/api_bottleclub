from datetime import date
from unittest.mock import MagicMock, patch

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
        assert result == f"MBR-{_format_date_suffix(date.today())}-0001"

    @patch("app.shared.ordering._next_sequence", return_value=123)
    def test_padded_sequence(self, mock_seq):
        session = MagicMock()
        result = generate_order_number(session, "NYC")
        assert result == f"NYC-{_format_date_suffix(date.today())}-0123"

    @patch("app.shared.ordering._next_sequence", return_value=9999)
    def test_max_sequence(self, mock_seq):
        session = MagicMock()
        result = generate_order_number(session, "LAX")
        assert result == f"LAX-{_format_date_suffix(date.today())}-9999"


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
        assert result == f"REC-{date.today().strftime('%Y%m%d')}-0005"

    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_transfer(self, mock_seq):
        result = generate_transfer_number(MagicMock())
        assert result == f"TRF-{date.today().strftime('%Y%m%d')}-0005"

    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_return(self, mock_seq):
        result = generate_return_number(MagicMock())
        assert result == f"RET-{date.today().strftime('%Y%m%d')}-0005"

    @patch("app.shared.ordering._next_sequence", return_value=5)
    def test_refund(self, mock_seq):
        result = generate_refund_number(MagicMock())
        assert result == f"REF-{date.today().strftime('%Y%m%d')}-0005"
