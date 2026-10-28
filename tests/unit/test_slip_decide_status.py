"""Verification status from the parsed slip and its fraud score (offline)."""
from datetime import datetime, timezone
from decimal import Decimal

from app.domains.slip_verify.service import decide_status
from app.services.fraud_detection import FraudDetectionService

TOTAL = Decimal("250.00")
NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _assess(**overrides):
    fields = dict(
        ocr_avg_confidence=0.95, amount_confidence=0.95, reference_confidence=0.95,
        ocr_amount=TOTAL, expected_amount=TOTAL, ocr_reference="015293123456ABC01234",
        sender_name="นาย สมมติ ท", receiver_name="ร้านทดสอบ",
        ocr_date=NOW, ocr_time=NOW,
    )
    fields.update(overrides)
    return FraudDetectionService.assess(**fields)


def _status(assessment, *, amount=TOTAL, reference_found=True, duplicate=False):
    return decide_status(
        assessment, amount=amount, reference_found=reference_found,
        due=TOTAL, reference_duplicate=duplicate,
    )


def test_clean_slip_is_verified():
    assert _status(_assess()) == "verified"


def test_no_reference_goes_to_review_not_rejected():
    assessment = _assess(ocr_reference=None, reference_confidence=0.0)
    assert assessment.level == "rejected"  # reference_not_found alone is 0.80
    assert _status(assessment, reference_found=False) == "review"


def test_unreadable_slip_goes_to_review():
    # Paotang payment: no reference, no names read.
    assessment = _assess(
        ocr_reference=None, reference_confidence=0.0, sender_name=None, receiver_name=None,
        ocr_avg_confidence=0.55,
    )
    assert assessment.total_score == 1.0
    assert assessment.evidence_score == 0.0
    assert _status(assessment, reference_found=False) == "review"


def test_no_amount_goes_to_review():
    assessment = _assess(ocr_amount=None, amount_confidence=0.0)
    assert _status(assessment, amount=None) == "review"


def test_evidence_of_a_bad_slip_is_still_rejected():
    assessment = _assess(sender_account="xxx-x-x1234-x", receiver_account="xxx-x-x1234-x")
    assert assessment.evidence_score == 0.6
    assert _status(assessment) == "rejected"


def test_duplicate_and_mismatch_take_precedence():
    assert _status(_assess(), duplicate=True) == "duplicate_reference"
    assert _status(_assess(ocr_amount=TOTAL + 1), amount=TOTAL + 1) == "amount_mismatch"
