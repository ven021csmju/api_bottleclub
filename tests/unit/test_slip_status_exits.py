"""Every verification status other than verified has a way out (offline)."""
import re

from app.db.models import PaymentVerification
from app.db.repositories.slip_verify.slip_verify_repository import RESENDABLE_STATUSES
from app.domains.slip_verify.service import APPROVABLE_STATUSES, REJECTABLE_STATUSES


def _check_statuses() -> set[str]:
    (constraint,) = [
        c for c in PaymentVerification.__table__.constraints if c.name == "ck_verification_status"
    ]
    return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))


def test_every_non_verified_status_has_an_exit():
    statuses = _check_statuses()
    assert "verified" in statuses and len(statuses) == 11
    stuck = {
        s for s in statuses - {"verified"}
        if s not in APPROVABLE_STATUSES and s not in REJECTABLE_STATUSES and s not in RESENDABLE_STATUSES
    }
    assert stuck == set()


def test_exit_table():
    assert APPROVABLE_STATUSES == {"pending", "review", "ocr_failed", "amount_mismatch", "receiver_mismatch"}
    # Duplicates can only be rejected, which frees the image for a resend.
    for status in ("duplicate_reference", "duplicate_image"):
        assert status in REJECTABLE_STATUSES
        assert status not in APPROVABLE_STATUSES
    assert "verified" not in REJECTABLE_STATUSES | APPROVABLE_STATUSES
    assert set(RESENDABLE_STATUSES) == {"rejected", "ocr_failed"}
    assert (APPROVABLE_STATUSES | REJECTABLE_STATUSES | set(RESENDABLE_STATUSES)) <= _check_statuses()
