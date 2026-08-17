from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session


def _next_sequence(db: Session, doc_type: str, doc_date: date | None = None) -> int:
    if doc_date is None:
        doc_date = date.today()
    result = db.execute(
        text("""
            INSERT INTO document_sequences (doc_type, sequence_date, last_number)
            VALUES (:doc_type, :doc_date, 1)
            ON CONFLICT (doc_type, sequence_date)
            DO UPDATE SET last_number = document_sequences.last_number + 1
            RETURNING last_number
        """),
        {"doc_type": doc_type, "doc_date": doc_date},
    )
    row = result.fetchone()
    return row[0]  # type: ignore[index]


def _format_date_suffix(d: date) -> str:
    return d.strftime("%Y%m%d")


def generate_order_number(db: Session, branch_code: str) -> str:
    today = date.today()
    seq = _next_sequence(db, f"ORD-{branch_code}", today)
    return f"{branch_code}-{_format_date_suffix(today)}-{seq:04d}"


def generate_po_number(db: Session) -> str:
    today = date.today()
    seq = _next_sequence(db, "PO", today)
    return f"PO-{_format_date_suffix(today)}-{seq:04d}"


def generate_receiving_number(db: Session) -> str:
    today = date.today()
    seq = _next_sequence(db, "REC", today)
    return f"REC-{_format_date_suffix(today)}-{seq:04d}"


def generate_transfer_number(db: Session) -> str:
    today = date.today()
    seq = _next_sequence(db, "TRF", today)
    return f"TRF-{_format_date_suffix(today)}-{seq:04d}"


def generate_return_number(db: Session) -> str:
    today = date.today()
    seq = _next_sequence(db, "RET", today)
    return f"RET-{_format_date_suffix(today)}-{seq:04d}"


def generate_refund_number(db: Session) -> str:
    today = date.today()
    seq = _next_sequence(db, "REF", today)
    return f"REF-{_format_date_suffix(today)}-{seq:04d}"
