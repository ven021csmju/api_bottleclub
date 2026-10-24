"""SHOP_RECEIVER_NAMES and how the slip's receiver name is compared (offline)."""
from decimal import Decimal

import pytest

from app.config.settings import Settings
from app.domains.slip_verify.service import decide_status
from app.services.fraud_detection import FraudDetectionService, _name_matches, normalize_name


def _assess(receiver_name, names):
    return FraudDetectionService.assess(
        ocr_amount=Decimal("100.00"), expected_amount=Decimal("100.00"), ocr_reference="REF0001",
        sender_name="นาย สมมติ ท", receiver_name=receiver_name, expected_receiver_names=names,
    )


class TestSetting:
    def test_default_is_empty(self):
        assert Settings.model_fields["SHOP_RECEIVER_NAMES"].default == ""
        assert Settings(SHOP_RECEIVER_NAMES="").shop_receiver_names == []

    def test_comma_separated(self):
        names = Settings(SHOP_RECEIVER_NAMES=" บจก. ร้านทดสอบ , ,TEST SHOP ").shop_receiver_names
        assert names == ["บจก. ร้านทดสอบ", "TEST SHOP"]


class TestNameMatching:
    def test_normalize(self):
        assert normalize_name(" นาย สมชาย  ใจดี ") == "สมชายใจดี"
        assert normalize_name("น.ส. ตัวอย่าง ท***") == "ตัวอย่างท"
        assert normalize_name("บริษัท ร้านทดสอบ จำกัด (มหาชน)") == "ร้านทดสอบ"
        assert normalize_name("Mr. Test SHOP Co., Ltd.") == "testshop"

    @pytest.mark.parametrize(
        "expected, on_slip",
        [
            ("บจก. ร้านทดสอบ สมมติ", "บริษัท ร้านทดสอบ สมมติ จำกัด"),  # company form
            ("สมชาย ใจดี", "นาย สมชาย ใจดี"),  # title
            ("นาย สมชาย ใจดี", "นาย สมชาย ใ"),  # K PLUS: surname initial
            ("สมชาย ใจดี", "สมชาย ใ***"),  # Paotang: masked surname
            ("Test Shop", "TEST SHOP (THAILAND)"),  # case, branch suffix
            ("ร้านทดสอบ", "ร้านทดสอบ (สาขา ตัวอย่าง)"),
        ],
    )
    def test_matches(self, expected, on_slip):
        assert _name_matches(expected, on_slip)

    @pytest.mark.parametrize(
        "expected, on_slip",
        [
            ("สมชาย ใจดี", "สมหญิง ใจดี"),
            ("สมชาย ใจดี", "ส***"),  # too short to tell
            ("สมชาย ใจดี", "นาย สม"),
            ("ร้านทดสอบ", "ร้านอื่น"),
            ("สมชาย ใจดี", "***"),
        ],
    )
    def test_does_not_match(self, expected, on_slip):
        assert not _name_matches(expected, on_slip)


class TestFraudCheck:
    def test_other_receiver_is_receiver_mismatch(self):
        assessment = _assess("นาย คนอื่น ตัวอย่าง", ["ร้านทดสอบ", "สมชาย ใจดี"])
        assert assessment.has_signal("receiver_mismatch")
        status = decide_status(
            assessment, amount=Decimal("100.00"), reference_found=True,
            grand_total=Decimal("100.00"), reference_duplicate=False,
        )
        assert status == "receiver_mismatch"

    def test_any_configured_name_matches(self):
        assert not _assess("นาย สมชาย ใ", ["ร้านทดสอบ", "สมชาย ใจดี"]).has_signal("receiver_mismatch")

    def test_no_names_configured_means_no_check(self):
        assert not _assess("นาย คนอื่น ตัวอย่าง", []).has_signal("receiver_mismatch")

    def test_unread_receiver_is_review_not_mismatch(self):
        assessment = _assess(None, ["ร้านทดสอบ"])
        assert not assessment.has_signal("receiver_mismatch")
        assert assessment.has_signal("missing_receiver")
