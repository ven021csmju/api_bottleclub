"""A synthetic transfer slip (PNG) for the staging E2E.

Every name, account and reference is invented; only the order of the lines
and the labels follow the Krungthai and K PLUS layouts the parser knows
(see tests/unit/test_slip_parser_layouts.py). Never put values from a real
slip here.
"""
from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
]


def _font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RuntimeError("no Thai font found (install fonts-tlwg-garuda or fonts-freefont-ttf)")


def thai_date(moment: datetime, short_year: bool = False) -> str:
    year = moment.year + 543
    y = f"{year % 100:02d}" if short_year else str(year)
    return f"{moment.day} {THAI_MONTHS[moment.month - 1]} {y}"


def _lines(bank: str, amount: Decimal, reference: str, moment: datetime) -> list[str]:
    amount_text = f"{amount:,.2f}"
    if bank == "kbank":
        return [
            "โอนเงินสำเร็จ", "K+", f"{thai_date(moment, short_year=True)} {moment:%H:%M} น.",
            "นาย ทดลอง ระบบ", "ธ.กสิกรไทย", "xxx-x-x0000-x",
            "ร้านทดสอบ อีทูอี", "ธ.กสิกรไทย", "xxx-x-x9999-x",
            "จำนวน:", f"{amount_text} บาท", "ค่าธรรมเนียม:", "0.00 บาท",
            "เลขที่รายการ:", reference,
        ]
    return [
        "Krungthai", "กรุงไทย", "โอนเงินสำเร็จ",
        "รหัสอ้างอิง", reference,
        "จาก", "นาย ทดลอง ระบบ", "กรุงไทย", "XXX-X-XX000-0",
        "ไปยัง", "ร้านทดสอบ อีทูอี", "กรุงไทย", "XXX-X-XX999-9",
        "จำนวนเงิน", amount_text, "บาท", "ค่าธรรมเนียม", "0.00 บาท",
        "วันที่ทำรายการ", f"{thai_date(moment)} - {moment:%H:%M}",
    ]


def render_slip(bank: str, amount: Decimal, reference: str, moment: datetime) -> bytes:
    """``moment``: aware, in store time. Returns PNG bytes."""
    from PIL import Image, ImageDraw

    lines = _lines(bank, amount, reference, moment)
    font, big = _font(34), _font(52)
    height = 120 + 70 * len(lines)
    img = Image.new("RGB", (900, height), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    for text in lines:
        f = big if text.replace(",", "").replace(".", "").replace(" บาท", "").isdigit() else font
        draw.text((80, y), text, fill="black", font=f)
        y += 70
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
