"""Slip parser on the line layouts the OCR returns for real slips (offline).

Every name, account and number below is made up; only the order of the
lines and the labels follow the Krungthai, K PLUS and Paotang slips.
"""
from datetime import date, time
from decimal import Decimal

import pytest

from app.services.slip_parser import parse_amount, parse_slip


def _parse(lines):
    """``lines``: text, or (text, confidence) for OCR noise."""
    texts = [line[0] if isinstance(line, tuple) else line for line in lines]
    confidences = [line[1] if isinstance(line, tuple) else 0.97 for line in lines]
    return parse_slip(texts, confidences)


# Krungthai: amount above "จำนวนเงิน", reference on the line after the label
# and not hex.
KRUNGTHAI_AMOUNT_ABOVE = [
    "Krungthai", "กรุงไทย", "โอนเงินสำเร็จ",
    "รหัสอ้างอิง", "P123456789012345678901234",
    "จาก", "นาย สมมติ ทดสอบ", "* **", "กรุงไทย", "XXX-X-XX123-4",
    "ไปยัง", "นาย ตัวอย่าง สมมุติ", "กรุงไทย", "XXX-X-XX567-8",
    "1,250.00", "จำนวนเงิน", "บาท", "ค่าธรรมเนียม", "0.00 บาท",
    "วันที่ทำรายการ", "3 ม.ค. 2570 - 08:15",
]

# Krungthai: amount below "จำนวนเงิน", an icon read as one letter between
# the reference label and its value.
KRUNGTHAI_AMOUNT_BELOW = [
    "Krungthai", "กรุงไทย", "โอนเงินสำเร็จ",
    "รหัสอ้างอิง", ("ก", 0.24), "A00000000000000001111",
    "จาก", "นายสมมติ ท", "***", "กรุงไทย", "XXX-x-XX999-0",
    "ไปยัง", "TEST SHOP (THAILAND)", "(000000000000000)", "ร้านค้าทดสอบ",
    "00000000000000000", "12", "ร้านค้าตัวอย่างสมมุติ", "TESTSHOP",
    "จำนวนเงิน", "12,345.67", ") บาท", "ค่าธรรมเนียม", "0.00 บาท",
    "วันที่ทำรายการ", "14 ก.พ. 2570 - 21:40",
]

# K PLUS paying a shop: no จาก/ไปยัง, receiver split over lines, amount
# below "จำนวน:", reference below "เลขที่รายการ:" after the QR caption,
# two-digit Buddhist year.
KBANK_SHOP = [
    "โอนเงินสำเร็จ", "K+", "5 มี.ค. 70 10:20 น.",
    "นาย สมมติ ท", "ธ.กสิกรไทย", ("√", 0.57), "xxx-x-x1234-x",
    "ร้านทดสอบ (สาขา", ("A", 0.29), "ตัวอย่าง)", "0000000000000000000", "TESTMERCHANT",
    "จำนวน:", "1,250.00 บาท", ("AA", 0.59), "ค่าธรรมเนียม:", "0.00 บาท",
    "เลขที่รายการ:", "สแกน", "015293123456ABC01234", "ตรวจสอบสลิป",
]

# K PLUS to a person at the same bank.
KBANK_PERSON = [
    "โอนเงินสำเร็จ", "K+", "9 เม.ย.70 23:58 น.",
    "นาย สมมติ ท", "ธ.กสิกรไทย", ("A", 0.15), "XXX-X-X1234-X",
    "น.ส. ตัวอย่าง ทดสอบ", "ธ.กสิกรไทย", "xxx-x-x5678-x",
    "จำนวน:", "321.00บาท", "ค่าธรรมเนียม:", "0.00 บาท",
    "เลขที่รายการ:", "015294000000BOR01234",
]

# Paotang top-up: whole-baht amount, reference on the label line.
PAOTANG_TOPUP = [
    "เติมเงินสำเร็จ", "รหัสอ้างอิง 123456789", "1 พ.ค. 2570 07:07 น.",
    "นาย สมมติ ทดสอบ", "ออมทรัพย์:*** * **999 0", "สมมติ ทดสอบ", "G",
    "G-Wallet ID: 000 ******** 0000", "จำนวนเงิน", "7 บาท",
]

# Paotang payment: the app itself cuts the reference short; amount above
# "จำนวนเงินที่ชำระ" with a discount line before it.
PAOTANG_PAYMENT = [
    ("aa", 0.41), "แอปทดสอบ", "ทดสอบ", "ทำรายการสำเร็จ",
    "รหัสอ้างอิง 1234567890ab12cd3ef4abc123f..", "2 มิ.ย. 2570 12:00 น.",
    "สมมติ ท***", "G", "G-Wallet ID: **** ******* 0000", ("A", 0.2),
    "ร้านทดสอบสมมุติ", "หมวดทดสอบ/", "80 บาท", "-35 บาท", "สิทธิทดสอบ", "45 บาท",
    "จำนวนเงินที่ชำระ",
]


class TestAmount:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("1,250.00", Decimal("1250.00")),
            ("12,345.67", Decimal("12345.67")),
            ("1,234,567.89 บาท", Decimal("1234567.89")),
            ("99.99บาท", Decimal("99.99")),
            ("9 บาท", Decimal("9.00")),
            ("1,500 บาท", Decimal("1500.00")),
            ("200.00", Decimal("200.00")),
        ],
    )
    def test_parses(self, text, expected):
        assert parse_amount(text) == expected

    @pytest.mark.parametrize("text", ["9", "-35 บาท", "1,25", "12.5", "XXX-X-XX123-4", "000 ******** 0000"])
    def test_rejects(self, text):
        assert parse_amount(text) is None

    def test_thousands_on_a_slip_is_not_read_as_125(self):
        slip = _parse(["Krungthai", "1,250.00", "บาท", "จำนวนเงิน"])
        assert slip.amount.value == Decimal("1250.00")


class TestKrungthai:
    def test_amount_above_label_reference_on_next_line(self):
        slip = _parse(KRUNGTHAI_AMOUNT_ABOVE)
        assert slip.bank.value == "Krungthai"
        assert slip.amount.value == Decimal("1250.00")
        assert slip.reference.value == "P123456789012345678901234"
        assert slip.sender_name.value == "นาย สมมติ ทดสอบ"
        assert slip.receiver_name.value == "นาย ตัวอย่าง สมมุติ"
        assert slip.sender_account.value == "XXX-X-XX123-4"
        assert slip.receiver_account.value == "XXX-X-XX567-8"
        assert slip.fee.value == Decimal("0.00")
        assert slip.date.value == date(2027, 1, 3)
        assert slip.time.value == time(8, 15)

    def test_amount_below_label_noise_before_reference(self):
        slip = _parse(KRUNGTHAI_AMOUNT_BELOW)
        assert slip.amount.value == Decimal("12345.67")
        assert slip.reference.value == "A00000000000000001111"
        assert slip.sender_name.value == "นายสมมติ ท"
        assert slip.receiver_name.value == "TEST SHOP (THAILAND)"
        assert slip.date.value == date(2027, 2, 14)


class TestKBank:
    def test_shop_payment(self):
        slip = _parse(KBANK_SHOP)
        assert slip.bank.value == "KBank"
        assert slip.amount.value == Decimal("1250.00")
        assert slip.reference.value == "015293123456ABC01234"
        assert slip.sender_name.value == "นาย สมมติ ท"
        assert slip.receiver_name.value == "ร้านทดสอบ (สาขา ตัวอย่าง)"
        assert slip.sender_account.value == "xxx-x-x1234-x"
        assert slip.fee.value == Decimal("0.00")
        assert slip.date.value == date(2027, 3, 5)  # "70" = 2570 BE
        assert slip.time.value == time(10, 20)

    def test_person_transfer(self):
        slip = _parse(KBANK_PERSON)
        assert slip.amount.value == Decimal("321.00")
        assert slip.reference.value == "015294000000BOR01234"
        assert slip.sender_name.value == "นาย สมมติ ท"
        assert slip.receiver_name.value == "น.ส. ตัวอย่าง ทดสอบ"
        assert slip.sender_account.value == "XXX-X-X1234-X"
        assert slip.receiver_account.value == "xxx-x-x5678-x"
        assert slip.date.value == date(2027, 4, 9)

    def test_receiver_bank_does_not_change_the_issuer(self):
        lines = [line for line in KBANK_PERSON if line != "ธ.กสิกรไทย"]
        lines.insert(8, "ธ.กรุงไทย")
        assert _parse(lines).bank.value == "KBank"


class TestPaotang:
    def test_whole_baht_top_up(self):
        slip = _parse(PAOTANG_TOPUP)
        assert slip.amount.value == Decimal("7.00")
        assert slip.reference.value == "123456789"
        assert slip.sender_name.value == "นาย สมมติ ทดสอบ"
        assert slip.receiver_name.value == "สมมติ ทดสอบ"

    def test_cut_reference_is_none_amount_is_the_paid_total(self):
        slip = _parse(PAOTANG_PAYMENT)
        assert slip.reference is None
        assert slip.amount.value == Decimal("45.00")


class TestReferenceOnlyNextToLabel:
    def test_hex_code_without_label_is_not_a_reference(self):
        slip = _parse(["SCB", "โอนเงินสำเร็จ", "ABCDEF1234567890", "500.00"])
        assert slip.reference is None

    def test_kbank_code_elsewhere_is_not_taken(self):
        lines = [line for line in KBANK_SHOP if line not in ("เลขที่รายการ:", "015293123456ABC01234")]
        slip = _parse(lines)
        assert slip.reference is None

    def test_label_without_value_is_none(self):
        slip = _parse(["Krungthai", "รหัสอ้างอิง", "จาก", "นาย สมมติ ทดสอบ", "DEADBEEF0001"])
        assert slip.reference is None

    @pytest.mark.parametrize(
        "line, expected",
        [
            ("รหัสอ้างอิง ABC123XYZ", "ABC123XYZ"),
            ("เลขที่รายการ: 015293123456ABC01234", "015293123456ABC01234"),
            ("Ref No. 2026090112345", "2026090112345"),
            ("Transaction ID: TXN-2026-0001", "TXN-2026-0001"),
        ],
    )
    def test_same_line_values(self, line, expected):
        assert _parse([line]).reference.value == expected
