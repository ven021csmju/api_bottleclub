from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal


@dataclass
class RiskSignal:
    name: str
    score: float
    description: str


@dataclass
class FraudAssessment:
    total_score: float
    signals: list[RiskSignal] = field(default_factory=list)
    level: str = "verified"

    def __post_init__(self):
        if self.total_score >= 0.50:
            self.level = "rejected"
        elif self.total_score >= 0.20:
            self.level = "review"
        else:
            self.level = "verified"


class FraudDetectionService:
    SIGNAL_VALUES = {
        "low_ocr_confidence": 0.15,
        "very_low_ocr_confidence": 0.30,
        "amount_mismatch": 0.50,
        "amount_significantly_lower": 0.60,
        "amount_significantly_higher": 0.25,
        "reference_not_found": 0.80,
        "reference_duplicate": 1.00,
        "image_hash_duplicate": 1.00,
        "receiver_mismatch": 0.70,
        "sender_is_receiver": 0.60,
        "suspicious_timestamp": 0.30,
        "old_transaction": 0.20,
        "future_transaction": 0.40,
        "weekend_transaction": 0.05,
        "multiple_failed_attempts": 0.40,
        "low_confidence_amount": 0.25,
        "low_confidence_reference": 0.20,
        "missing_sender": 0.30,
        "missing_receiver": 0.30,
        "unusual_round_amount": 0.15,
        "missing_date": 0.20,
        "missing_time": 0.10,
    }

    THRESHOLDS = {
        "verified": 0.20,
        "review": 0.50,
    }

    @classmethod
    def assess(
        cls,
        *,
        ocr_avg_confidence: float = 1.0,
        amount_confidence: float = 1.0,
        reference_confidence: float = 1.0,
        ocr_amount: Decimal | None = None,
        expected_amount: Decimal | None = None,
        ocr_reference: str | None = None,
        reference_duplicate: bool = False,
        image_duplicate: bool = False,
        sender_name: str | None = None,
        receiver_name: str | None = None,
        sender_account: str | None = None,
        receiver_account: str | None = None,
        ocr_date: datetime | None = None,
        ocr_time: datetime | None = None,
        failed_attempts: int = 0,
        expected_receiver_name: str | None = None,
    ) -> FraudAssessment:
        signals: list[RiskSignal] = []
        total = 0.0

        # OCR confidence signals
        if ocr_avg_confidence < 0.6:
            sig = cls.SIGNAL_VALUES["very_low_ocr_confidence"]
            signals.append(RiskSignal("very_low_ocr_confidence", sig, f"Very low OCR confidence: {ocr_avg_confidence:.2f}"))
            total += sig
        elif ocr_avg_confidence < 0.8:
            sig = cls.SIGNAL_VALUES["low_ocr_confidence"]
            signals.append(RiskSignal("low_ocr_confidence", sig, f"Low OCR confidence: {ocr_avg_confidence:.2f}"))
            total += sig

        if amount_confidence < 0.9:
            sig = cls.SIGNAL_VALUES["low_confidence_amount"]
            signals.append(RiskSignal("low_confidence_amount", sig, f"Low amount OCR confidence: {amount_confidence:.2f}"))
            total += sig

        if reference_confidence < 0.9:
            sig = cls.SIGNAL_VALUES["low_confidence_reference"]
            signals.append(RiskSignal("low_confidence_reference", sig, f"Low reference OCR confidence: {reference_confidence:.2f}"))
            total += sig

        # Amount mismatch
        if ocr_amount is not None and expected_amount is not None:
            diff = ocr_amount - expected_amount
            if diff != 0:
                if diff < 0 and abs(diff) > expected_amount * Decimal("0.1"):
                    sig = cls.SIGNAL_VALUES["amount_significantly_lower"]
                    signals.append(RiskSignal("amount_significantly_lower", sig, f"Amount {ocr_amount} significantly lower than expected {expected_amount}"))
                    total += sig
                elif diff > 0:
                    sig = cls.SIGNAL_VALUES["amount_significantly_higher"]
                    signals.append(RiskSignal("amount_significantly_higher", sig, f"Amount {ocr_amount} higher than expected {expected_amount}"))
                    total += sig
                else:
                    sig = cls.SIGNAL_VALUES["amount_mismatch"]
                    signals.append(RiskSignal("amount_mismatch", sig, f"Amount mismatch: {ocr_amount} != {expected_amount}"))
                    total += sig

        # Reference signals
        if ocr_reference is None:
            sig = cls.SIGNAL_VALUES["reference_not_found"]
            signals.append(RiskSignal("reference_not_found", sig, "Reference not found in OCR"))
            total += sig
        elif reference_duplicate:
            sig = cls.SIGNAL_VALUES["reference_duplicate"]
            signals.append(RiskSignal("reference_duplicate", sig, f"Reference already used: {ocr_reference}"))
            total += sig

        # Image duplicate
        if image_duplicate:
            sig = cls.SIGNAL_VALUES["image_hash_duplicate"]
            signals.append(RiskSignal("image_hash_duplicate", sig, "Image hash already exists"))
            total += sig

        # Receiver mismatch
        if expected_receiver_name and receiver_name:
            if not _name_matches(expected_receiver_name, receiver_name):
                sig = cls.SIGNAL_VALUES["receiver_mismatch"]
                signals.append(RiskSignal("receiver_mismatch", sig, f"Receiver mismatch: expected '{expected_receiver_name}', got '{receiver_name}'"))
                total += sig

        if sender_account and receiver_account and sender_account == receiver_account:
            sig = cls.SIGNAL_VALUES["sender_is_receiver"]
            signals.append(RiskSignal("sender_is_receiver", sig, "Sender and receiver account are the same"))
            total += sig

        # Timestamp signals
        now = datetime.now(timezone.utc)
        if ocr_date:
            tx_datetime = datetime.combine(ocr_date, ocr_time or datetime.min.time())
            tx_datetime = tx_datetime.replace(tzinfo=timezone.utc)
            delta = now - tx_datetime
            if delta.days > 7:
                sig = cls.SIGNAL_VALUES["old_transaction"]
                signals.append(RiskSignal("old_transaction", sig, f"Transaction is {delta.days} days old"))
                total += sig
            if delta.days < 0:
                sig = cls.SIGNAL_VALUES["future_transaction"]
                signals.append(RiskSignal("future_transaction", sig, "Transaction date is in the future"))
                total += sig

        # Missing fields
        if sender_name is None:
            sig = cls.SIGNAL_VALUES["missing_sender"]
            signals.append(RiskSignal("missing_sender", sig, "Sender name not found"))
            total += sig

        if receiver_name is None:
            sig = cls.SIGNAL_VALUES["missing_receiver"]
            signals.append(RiskSignal("missing_receiver", sig, "Receiver name not found"))
            total += sig

        if ocr_date is None:
            sig = cls.SIGNAL_VALUES["missing_date"]
            signals.append(RiskSignal("missing_date", sig, "Transaction date not found"))
            total += sig

        # Multiple failed attempts
        if failed_attempts >= 2:
            sig = cls.SIGNAL_VALUES["multiple_failed_attempts"]
            signals.append(RiskSignal("multiple_failed_attempts", sig, f"{failed_attempts} failed verification attempts"))
            total += sig

        # Unusual round amount
        if ocr_amount and ocr_amount >= Decimal("10000") and ocr_amount % 1000 == 0:
            sig = cls.SIGNAL_VALUES["unusual_round_amount"]
            signals.append(RiskSignal("unusual_round_amount", sig, f"Unusually round amount: {ocr_amount}"))
            total += sig

        total = min(total, 1.0)

        return FraudAssessment(total_score=round(total, 2), signals=signals)


def _name_matches(expected: str, actual: str) -> bool:
    expected_norm = expected.lower().strip()
    actual_norm = actual.lower().strip()
    if expected_norm == actual_norm:
        return True
    if expected_norm in actual_norm or actual_norm in expected_norm:
        return True
    return False
