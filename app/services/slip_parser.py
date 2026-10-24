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

#: Amount with optional thousands separators: 99.99, 1,250.00, 12,345.67, 9.
#: Not preceded by a sign, digit or separator (so -35 and 1,25 are not read).
_AMOUNT = r"(?<![\d.,\-])(\d{1,3}(?:,\d{3})+|\d+)(\.\d{2})?(?![\d]|[.,]\d)"
_AMOUNT_RE = re.compile(_AMOUNT)
_BAHT_AFTER_RE = re.compile(r"^\s*(?:บาท|THB|฿)", re.IGNORECASE)

#: Krungthai/K PLUS/Paotang amount labels. The value is on the label line,
#: just above it (Krungthai, Paotang) or just below it (K PLUS, Krungthai).
_AMOUNT_LABEL_RE = re.compile(r"จำนวนเงิน|ยอดเงิน|\bAmount\b", re.IGNORECASE)
_KBANK_AMOUNT_LABEL_RE = re.compile(r"^จำนวน(?!เงิน)\s*:?")

#: Labels a reference value sits next to: on the same line or on one of the
#: next lines. Nothing else on the slip is taken as the reference.
_REFERENCE_LABEL_RE = re.compile(
    r"(?:รหัสอ้างอิง|เลขที่รายการ|เลขที่อ้างอิง|หมายเลขอ้างอิง|\bRef(?:erence)?\b(?:\s*No\.?)?|\bTransaction\s*ID\b)\s*:?",
    re.IGNORECASE,
)
_REFERENCE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{5,}$")

#: Masked account numbers (xxx-x-x1234-x) and account lines such as
#: "ออมทรัพย์: *** * **123 4" or "G-Wallet ID: 000 ******** 0000".
_ACCOUNT_RE = re.compile(r"^[A-Za-z\d]{3}-[A-Za-z\d]-[A-Za-z\d]{5}-[A-Za-z\d]$")
_ACCOUNT_LINE_RE = re.compile(r"ออมทรัพย์|กระแสรายวัน|Wallet\s*ID|บัญชี", re.IGNORECASE)
_BANK_LINE_RE = re.compile(r"^(?:ธ\.|ธนาคาร)")

#: Lines that mark where a field starts; a value search stops at them.
_STOP_LABEL_RE = re.compile(
    r"^(?:จาก|ไปยัง|ผู้รับ|ผู้โอน|ผู้ส่ง|จำนวน|ค่าธรรมเนียม|วันที่|รหัสอ้างอิง|เลขที่รายการ|บันทึกช่วยจำ)"
)

_SENDER_LABEL_RE = re.compile(r"^(?:จาก|ผู้โอน|ผู้ส่ง|From)\b\s*:?\s*(.*)$", re.IGNORECASE)
_RECEIVER_LABEL_RE = re.compile(r"^(?:ไปยัง|ถึง|ผู้รับ|To|Recipient)\b\s*:?\s*(.*)$", re.IGNORECASE)

_THAI_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}
_THAI_DATE_RE = re.compile(
    r"(\d{1,2})\s*(" + "|".join(re.escape(m) for m in _THAI_MONTHS) + r")\s*(\d{4}|\d{2})(?!\d)"
)

#: OCR noise (stray icons read as one letter) is short and low-confidence.
_NOISE_CONFIDENCE = 0.5


def parse_slip(texts: list[str], confidences: list[float]) -> ParsedSlip:
    slip = ParsedSlip(all_texts=texts, all_confidences=confidences)

    slip.bank = _extract_bank(texts, confidences)
    slip.amount = _extract_amount(texts, confidences)
    slip.reference = _extract_reference(texts, confidences)
    slip.date = _extract_date(texts, confidences)
    slip.time = _extract_time(texts, confidences)
    (
        slip.sender_name,
        slip.receiver_name,
        slip.sender_account,
        slip.receiver_account,
    ) = _extract_parties(texts, confidences)
    slip.fee = _extract_fee(texts, confidences)
    slip.status_text = _extract_status(texts, confidences)

    return slip


def _conf(confidences: list[float], i: int) -> float:
    return confidences[i] if i < len(confidences) else 0.0


def _extract_bank(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    # The issuing bank's name is at the top of the slip; the receiver's bank
    # may be another one further down, so the first line that names a bank wins.
    for i, text in enumerate(texts):
        if text.strip() == "K+":
            return FieldConfidence(value="KBank", confidence=_conf(confidences, i))
        for bank_name, patterns, _ in BANK_PATTERNS:
            if any(pattern.lower() in text.lower() for pattern in patterns):
                return FieldConfidence(value=bank_name, confidence=_conf(confidences, i))
    return None


def parse_amount(text: str, *, allow_integer: bool = True) -> Decimal | None:
    """First amount in ``text``: ``1,250.00`` -> 1250.00.

    A whole number (``9 บาท``) counts only when ``บาท``/``THB`` follows it,
    so account fragments and dates are not read as amounts.
    """
    for match in _AMOUNT_RE.finditer(text):
        whole, cents = match.group(1), match.group(2)
        if cents is None and not (allow_integer and _BAHT_AFTER_RE.match(text[match.end():])):
            continue
        try:
            return Decimal(whole.replace(",", "") + (cents or ".00"))
        except InvalidOperation:
            continue
    return None


def _amount_at(texts: list[str], confidences: list[float], i: int) -> FieldConfidence | None:
    if _STOP_LABEL_RE.match(texts[i].strip()) and not _AMOUNT_LABEL_RE.search(texts[i]):
        return None
    value = parse_amount(texts[i])
    return FieldConfidence(value=value, confidence=_conf(confidences, i)) if value is not None else None


def _extract_amount(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        kbank = _KBANK_AMOUNT_LABEL_RE.match(text.strip())
        label = kbank or _AMOUNT_LABEL_RE.search(text)
        if not label:
            continue
        value = parse_amount(text[label.end():])
        if value is not None:
            return FieldConfidence(value=value, confidence=_conf(confidences, i))
        # K PLUS puts the amount below "จำนวน:"; Krungthai and Paotang put it
        # above "จำนวนเงิน", or below it when nothing above is an amount.
        before = [] if kbank else range(i - 1, max(i - 4, -1), -1)
        after = range(i + 1, min(i + 3, len(texts)))
        for j in (*before, *after):
            if j > i and _STOP_LABEL_RE.match(texts[j].strip()):
                break
            found = _amount_at(texts, confidences, j)
            if found:
                return found

    amounts: list[tuple[Decimal, float]] = []
    for i, text in enumerate(texts):
        match = re.fullmatch(r"\s*" + _AMOUNT + r"\s*", text)
        if match and match.group(2):
            amounts.append((Decimal(match.group(1).replace(",", "") + match.group(2)), _conf(confidences, i)))

    if amounts:
        best = max(amounts, key=lambda x: x[0])
        return FieldConfidence(value=best[0], confidence=best[1])

    return None


def _reference_value(candidate: str) -> str | None:
    candidate = candidate.strip()
    if not _REFERENCE_VALUE_RE.match(candidate) or not re.search(r"\d", candidate):
        return None
    if _ACCOUNT_RE.match(candidate):
        return None
    return candidate


def _extract_reference(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    """The value next to a reference label, or None.

    No reference is better than a wrong one: it is the duplicate-slip key.
    """
    for i, text in enumerate(texts):
        label = _REFERENCE_LABEL_RE.search(text)
        if not label:
            continue
        rest = text[label.end():].strip()
        if rest:
            token = rest.split()[0]
            # The app cut the reference short ("1234...abcd..."): unusable.
            if token.endswith(("..", "…")):
                return None
            value = _reference_value(token.rstrip("."))
            if value:
                return FieldConfidence(value=value, confidence=_conf(confidences, i))
        # K PLUS: "เลขที่รายการ:" / "สแกนตรวจสอบสลิป" / value; Krungthai: label / value.
        for j in range(i + 1, min(i + 4, len(texts))):
            if _STOP_LABEL_RE.match(texts[j].strip()):
                break
            value = _reference_value(texts[j])
            if value:
                return FieldConfidence(value=value, confidence=_conf(confidences, j))
    return None


def _extract_date(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        match = _THAI_DATE_RE.search(text)
        if match:
            day = int(match.group(1))
            month = _THAI_MONTHS.get(match.group(2))
            year = int(match.group(3))
            if year < 100:
                year += 2500  # "3 ม.ค. 70": two-digit Buddhist year
            if year > 2400:
                year -= 543
            try:
                d = date(year, month, day)
                return FieldConfidence(value=d, confidence=_conf(confidences, i))
            except (ValueError, TypeError):
                continue

    for i, text in enumerate(texts):
        match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
        if match:
            try:
                d = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                return FieldConfidence(value=d, confidence=_conf(confidences, i))
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
                return FieldConfidence(value=t, confidence=_conf(confidences, i))
            except (ValueError, TypeError):
                continue
    return None


def _is_noise(texts: list[str], confidences: list[float], i: int) -> bool:
    text = texts[i].strip()
    return len(text) <= 2 or (_conf(confidences, i) < _NOISE_CONFIDENCE and len(text) <= 3)


def _is_account(text: str) -> bool:
    text = text.strip()
    if _ACCOUNT_RE.match(text):
        return True
    return bool(_ACCOUNT_LINE_RE.search(text) and re.search(r"\d", text))


def _is_name(texts: list[str], confidences: list[float], i: int) -> bool:
    text = texts[i].strip()
    if _is_noise(texts, confidences, i) or _is_account(text) or _BANK_LINE_RE.match(text):
        return False
    if _STOP_LABEL_RE.match(text) or _THAI_DATE_RE.search(text) or re.search(r"\d{1,2}:\d{2}", text):
        return False
    if re.search(r"สำเร็จ|ทำรายการ|^K\+$", text) or _REFERENCE_LABEL_RE.search(text):
        return False
    letters = re.findall(r"[A-Za-zก-ฮ]", text)
    return len(letters) >= 3 and parse_amount(text) is None


def _name_at(texts: list[str], confidences: list[float], i: int) -> FieldConfidence:
    """Name on line ``i``; a name cut by the OCR after "(" continues below."""
    parts, j = [texts[i].strip()], i
    while " ".join(parts).count("(") > " ".join(parts).count(")") and j + 1 < min(i + 4, len(texts)):
        j += 1
        if _is_noise(texts, confidences, j):
            continue
        parts.append(texts[j].strip())
    return FieldConfidence(value=" ".join(parts), confidence=_conf(confidences, i))


def _account_after(texts: list[str], confidences: list[float], i: int, limit: int = 4) -> FieldConfidence | None:
    for j in range(i + 1, min(i + 1 + limit, len(texts))):
        if _is_account(texts[j]):
            return FieldConfidence(value=texts[j].strip(), confidence=_conf(confidences, j))
        if _STOP_LABEL_RE.match(texts[j].strip()):
            break
    return None


def _party_after_label(
    texts: list[str], confidences: list[float], label_re: re.Pattern
) -> tuple[FieldConfidence | None, FieldConfidence | None]:
    for i, text in enumerate(texts):
        match = label_re.match(text.strip())
        if not match:
            continue
        if match.group(1) and len(match.group(1).strip()) > 1:
            return FieldConfidence(value=match.group(1).strip(), confidence=_conf(confidences, i)), _account_after(texts, confidences, i)
        for j in range(i + 1, min(i + 4, len(texts))):
            if _is_name(texts, confidences, j):
                return _name_at(texts, confidences, j), _account_after(texts, confidences, j)
    return None, None


def _extract_parties(
    texts: list[str], confidences: list[float]
) -> tuple[FieldConfidence | None, FieldConfidence | None, FieldConfidence | None, FieldConfidence | None]:
    """(sender name, receiver name, sender account, receiver account).

    Labelled slips (Krungthai: "จาก" / "ไปยัง") are read from the labels.
    Unlabelled ones (K PLUS, Paotang) by line order: sender name, its bank
    and account lines, then the receiver name.
    """
    sender, sender_account = _party_after_label(texts, confidences, _SENDER_LABEL_RE)
    receiver, receiver_account = _party_after_label(texts, confidences, _RECEIVER_LABEL_RE)
    if sender or receiver:
        return sender, receiver, sender_account, receiver_account

    end = next((i for i, t in enumerate(texts) if _KBANK_AMOUNT_LABEL_RE.match(t.strip()) or _AMOUNT_LABEL_RE.search(t)), len(texts))
    anchors = [i for i in range(end) if _BANK_LINE_RE.match(texts[i].strip()) or _is_account(texts[i])]
    if not anchors:
        return None, None, None, None

    first = anchors[0]
    for j in range(first - 1, max(first - 3, -1), -1):
        if _is_name(texts, confidences, j):
            sender = _name_at(texts, confidences, j)
            break
    sender_account = _account_after(texts, confidences, first - 1)

    # Skip the sender's bank/account block (and icons read as letters).
    k = first
    while k < end and (k in anchors or _is_noise(texts, confidences, k)):
        k += 1
    for j in range(k, end):
        if _is_name(texts, confidences, j):
            receiver = _name_at(texts, confidences, j)
            receiver_account = _account_after(texts, confidences, j)
            break
    return sender, receiver, sender_account, receiver_account


def _extract_fee(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if re.search(r"(?:ค่าธรรมเนียม|Fee|Service\s*charge)", text, re.IGNORECASE):
            value = parse_amount(text)
            if value is not None:
                return FieldConfidence(value=value, confidence=_conf(confidences, i))
            for j in range(i + 1, min(i + 3, len(texts))):
                value = parse_amount(texts[j])
                if value is not None:
                    return FieldConfidence(value=value, confidence=_conf(confidences, j))
    return None


def _extract_status(texts: list[str], confidences: list[float]) -> FieldConfidence | None:
    for i, text in enumerate(texts):
        if re.search(r"(?:สำเร็จ|Success|Complete|Successful)", text, re.IGNORECASE):
            return FieldConfidence(value="success", confidence=_conf(confidences, i))
        if re.search(r"(?:ล้มเหลว|Fail|Failed|Error|Unsuccessful)", text, re.IGNORECASE):
            return FieldConfidence(value="failed", confidence=_conf(confidences, i))
    return None
