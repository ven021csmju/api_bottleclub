import re
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal, InvalidOperation


@dataclass
class FieldConfidence:
    value: str | Decimal | float | None
    confidence: float


@dataclass
class ParsedSlip:
    bank: FieldConfidence | None = None
    amount: FieldConfidence | None = None
    reference: FieldConfidence | None = None
    date: FieldConfidence | None = None
    time: FieldConfidence | None = None
    sender_name: FieldConfidence | None = None
    receiver_name: FieldConfidence | None = None
    sender_account: FieldConfidence | None = None
    receiver_account: FieldConfidence | None = None
    fee: FieldConfidence | None = None
    status_text: FieldConfidence | None = None
    all_texts: list[str] = field(default_factory=list)
    all_confidences: list[float] = field(default_factory=list)

    @property
    def avg_confidence(self) -> float:
        if not self.all_confidences:
            return 0.0
        return sum(self.all_confidences) / len(self.all_confidences)


BANK_PATTERNS: list[tuple[str, list[str], list[str]]] = [
    ("Krungthai", ["Krungthai", "กรุงไทย"], ["Krungthai"]),
    ("KBank", ["KBank", "กสิกร", "KASIKORN"], ["KBank"]),
    ("SCB", ["SCB", "ไทยพาณิชย์", "Siam Commercial"], ["SCB"]),
    ("Bangkok", ["Bangkok", "กรุงเทพ", "BBL"], ["Bangkok Bank"]),
    ("Thanachart", ["Thanachart", "ธนชาต"], ["Thanachart"]),
    ("TMB", ["TMB", "ทหารไทย"], ["TMB"]),
    ("UOB", ["UOB"], ["UOB"]),
    ("CIMB", ["CIMB"], ["CIMB"]),
    ("BAY", ["BAY", "กรุงศรี", "Ayudhya"], ["BAY"]),
]


def parse_slip(texts: list[str], confidences: list[float]) -> ParsedSlip:
    slip = ParsedSlip(all_texts=texts, all_confidences=confidences)
    full_text = " ".join(texts)

    slip.bank = _extract_bank(texts, confidences)
    slip.amount = _extract_amount(texts, confidences)
    slip.reference = _extract_reference(texts, confidences, full_text)
    slip.date = _extract_date(texts, confidences)
    slip.time = _extract_time(texts, confidences)
    slip.sender_name = _extract_sender(texts, confidences)
    slip.receiver_name = _extract_receiver(texts, confidences)
    slip.sender_account = _extract_account(texts, confidences, "from_sender")
    slip.receiver_account = _extract_account(texts, confidences, "to_receiver")
    slip.fee = _extract_fee(texts, confidences)
    slip.status_text = _extract_status(texts, confidences)

    return slip


def _find_best_match(
    texts: list[str], confidences: list[float], patterns: list[str]
) -> tuple[str, float] | None:
    for i, text in enumerate(texts):
        for pattern in patterns:
            if pattern.lower() in text.lower():
                conf = confidences[i] if i < len(confidences) else 0.0
                return (text.strip(), conf)
    return None


def _extract_bank(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for bank_name, patterns, _ in BANK_PATTERNS:
        match = _find_best_match(texts, confidences, patterns)
        if match:
            return FieldConfidence(value=bank_name, confidence=match[1])
    return None


def _extract_amount(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if "จำนวนเงิน" in text or "Amount" in text.lower():
            for j in range(i - 1, max(i - 4, -1), -1):
                match = re.search(r"(\d+[\.,]\d{2})", texts[j])
                if match:
                    try:
                        val = Decimal(match.group(1).replace(",", ""))
                        conf = confidences[j] if j < len(confidences) else 0.0
                        return FieldConfidence(value=val, confidence=conf)
                    except InvalidOperation:
                        continue

    amounts: list[tuple[Decimal, float]] = []
    for i, text in enumerate(texts):
        match = re.search(r"^\s*(\d+[\.,]\d{2})\s*$", text.strip())
        if match:
            try:
                val = Decimal(match.group(1).replace(",", ""))
                conf = confidences[i] if i < len(confidences) else 0.0
                amounts.append((val, conf))
            except InvalidOperation:
                continue

    if amounts:
        best = max(amounts, key=lambda x: x[0])
        return FieldConfidence(value=best[0], confidence=best[1])

    return None


def _extract_reference(
    texts: list[str], confidences: list[float], full_text: str
) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        match = re.search(r"(?:รหัสอ้างอิง|Reference|Ref|Transaction\s*ID)\s*[:\s]*(\S+)", text, re.IGNORECASE)
        if match:
            conf = confidences[i] if i < len(confidences) else 0.0
            return FieldConfidence(value=match.group(1), confidence=conf)

    for i, text in enumerate(texts):
        match = re.search(r"\b([A-Fa-f0-9]{8,})\b", text)
        if match:
            conf = confidences[i] if i < len(confidences) else 0.0
            return FieldConfidence(value=match.group(1), confidence=conf)

    return None


def _extract_date(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    thai_months = {
        "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
        "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
        "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    }

    for i, text in enumerate(texts):
        match = re.search(r"(\d{1,2})\s*(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s*(\d{4})", text)
        if match:
            day = int(match.group(1))
            month = thai_months.get(match.group(2))
            year = int(match.group(3))
            if year > 2500:
                year -= 543
            try:
                d = date(year, month, day)
                conf = confidences[i] if i < len(confidences) else 0.0
                return FieldConfidence(value=d, confidence=conf)
            except (ValueError, TypeError):
                continue

    for i, text in enumerate(texts):
        match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
        if match:
            try:
                d = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                conf = confidences[i] if i < len(confidences) else 0.0
                return FieldConfidence(value=d, confidence=conf)
            except (ValueError, TypeError):
                continue

    return None


def _extract_time(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
        if match:
            try:
                h, m = int(match.group(1)), int(match.group(2))
                s = int(match.group(3)) if match.group(3) else 0
                t = time(h, m, s)
                conf = confidences[i] if i < len(confidences) else 0.0
                return FieldConfidence(value=t, confidence=conf)
            except (ValueError, TypeError):
                continue
    return None


def _extract_sender(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if re.search(r"(?:จาก|From|ผู้ส่ง)", text, re.IGNORECASE):
            for j in range(i + 1, min(i + 4, len(texts))):
                candidate = texts[j].strip()
                if candidate and not re.match(r"^[\d\s\-\*\.]+$", candidate) and len(candidate) > 1:
                    conf = confidences[j] if j < len(confidences) else 0.0
                    return FieldConfidence(value=candidate, confidence=conf)
    return None


def _extract_receiver(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if re.search(r"(?:ไปยัง|ถึง|To|ผู้รับ|Recipient)", text, re.IGNORECASE):
            for j in range(i + 1, min(i + 4, len(texts))):
                candidate = texts[j].strip()
                if candidate and not re.match(r"^[\d\s\-\*\.]+$", candidate) and len(candidate) > 1:
                    conf = confidences[j] if j < len(confidences) else 0.0
                    return FieldConfidence(value=candidate, confidence=conf)
    return None


def _extract_account(texts: list[str], confidences: list[float], direction: str) -> FieldConfidence | None:
    patterns_to_try = {
        "from_sender": [r"(?:from|จาก).*?(\d[\d\-\s]{8,})", r"(?:Account|บัญชี)\s*[:\s]*(\d[\d\-\s]{8,})"],
        "to_receiver": [r"(?:to|ถึง|ไปยัง).*?(\d[\d\-\s]{8,})", r"(?:Account|บัญชี)\s*[:\s]*(\d[\d\-\s]{8,})"],
    }

    for i, text in enumerate(texts):
        for pattern in patterns_to_try.get(direction, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                conf = confidences[i] if i < len(confidences) else 0.0
                return FieldConfidence(value=match.group(1).strip(), confidence=conf)
    return None


def _extract_fee(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if re.search(r"(?:ค่าธรรมเนียม|Fee|Service\s*charge)", text, re.IGNORECASE):
            for j in range(i + 1, min(i + 3, len(texts))):
                match = re.search(r"(\d+[\.,]\d{2})", texts[j])
                if match:
                    try:
                        val = Decimal(match.group(1).replace(",", ""))
                        conf = confidences[j] if j < len(confidences) else 0.0
                        return FieldConfidence(value=val, confidence=conf)
                    except InvalidOperation:
                        continue

    for i, text in enumerate(texts):
        if re.search(r"ค่าธรรมเนียม|Fee", text, re.IGNORECASE):
            match = re.search(r"(\d+[\.,]\d{2})", text)
            if match:
                try:
                    val = Decimal(match.group(1).replace(",", ""))
                    conf = confidences[i] if i < len(confidences) else 0.0
                    return FieldConfidence(value=val, confidence=conf)
                except InvalidOperation:
                    continue
    return None


def _extract_status(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if re.search(r"(?:สำเร็จ|Success|Complete|Successful)", text, re.IGNORECASE):
            conf = confidences[i] if i < len(confidences) else 0.0
            return FieldConfidence(value="success", confidence=conf)
        if re.search(r"(?:ล้มเหลว|Fail|Failed|Error|Unsuccessful)", text, re.IGNORECASE):
            conf = confidences[i] if i < len(confidences) else 0.0
            return FieldConfidence(value="failed", confidence=conf)
    return None
