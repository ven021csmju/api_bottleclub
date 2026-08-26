import hashlib
import io
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def _create_test_image(
    text: str = "test",
    width: int = 400,
    height: int = 200,
    format: str = "JPEG",
) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    try:
        draw.text((10, 10), text, fill="black")
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def _create_blank_image(width: int = 400, height: int = 200) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestImageValidation:
    def test_valid_jpeg(self):
        from app.services.image_service import ImageService
        img_bytes = _create_blank_image()
        result = ImageService.validate_image(img_bytes, "test.jpg", "image/jpeg")
        assert result is None

    def test_valid_png(self):
        from app.services.image_service import ImageService
        img = Image.new("RGB", (100, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = ImageService.validate_image(buf.getvalue(), "test.png", "image/png")
        assert result is None

    def test_oversized_file(self):
        from app.services.image_service import ImageService, MAX_FILE_SIZE
        large_bytes = b"\x00" * (MAX_FILE_SIZE + 1)
        result = ImageService.validate_image(large_bytes, "test.jpg", "image/jpeg")
        assert result is not None
        assert "too large" in result.lower()

    def test_unsupported_extension(self):
        from app.services.image_service import ImageService
        result = ImageService.validate_image(b"fake", "test.exe", "application/x-executable")
        assert result is not None
        assert "extension" in result.lower() or "unsupported" in result.lower()

    def test_invalid_image_content(self):
        from app.services.image_service import ImageService
        result = ImageService.validate_image(b"not an image", "test.jpg", "image/jpeg")
        assert result is not None

    def test_corrupted_image(self):
        from app.services.image_service import ImageService
        result = ImageService.validate_image(b"\xff\xd8\xff\xe0\x00\x10JFIF", "test.jpg", "image/jpeg")
        assert result is not None


class TestImageHashing:
    def test_sha256_deterministic(self):
        from app.services.image_service import ImageService
        data = b"test data for hashing"
        h1 = ImageService.compute_sha256(data)
        h2 = ImageService.compute_sha256(data)
        assert h1 == h2
        assert len(h1) == 64

    def test_sha256_different_for_different_data(self):
        from app.services.image_service import ImageService
        h1 = ImageService.compute_sha256(b"data1")
        h2 = ImageService.compute_sha256(b"data2")
        assert h1 != h2

    def test_perceptual_hash(self):
        from app.services.image_service import ImageService
        img_bytes = _create_blank_image()
        phash = ImageService.compute_perceptual_hash(img_bytes)
        assert phash is not None
        assert len(phash) == 64

    def test_perceptual_hash_similar_images(self):
        from app.services.image_service import ImageService
        img1 = _create_blank_image(400, 200)
        img2 = _create_blank_image(400, 200)
        ph1 = ImageService.compute_perceptual_hash(img1)
        ph2 = ImageService.compute_perceptual_hash(img2)
        assert ph1 == ph2

    def test_storage_key_format(self):
        from app.services.image_service import ImageService
        key = ImageService.generate_storage_key("test.jpg")
        assert key.startswith("slip-uploads/")
        assert key.endswith(".jpg")


class TestOCRService:
    @patch("app.services.ocr_service._get_ocr")
    def test_extract_text_success(self, mock_get_ocr):
        from app.services.ocr_service import OCRService

        mock_ocr = MagicMock()
        mock_ocr.predict.return_value = [
            {
                "rec_texts": ["Krungthai", "200.00", "ABC123"],
                "rec_scores": [0.99, 0.98, 0.97],
            }
        ]
        mock_get_ocr.return_value = mock_ocr

        img_bytes = _create_blank_image()
        result = OCRService.extract_text(img_bytes)

        assert result.success is True
        assert len(result.texts) == 3
        assert result.texts[0] == "Krungthai"
        assert result.confidences[0] == 0.99

    def test_extract_text_invalid_image(self):
        from app.services.ocr_service import OCRService
        result = OCRService.extract_text(b"not an image")
        assert result.success is False
        assert result.error is not None

    def test_extract_text_oversized_image(self):
        from app.services.ocr_service import OCRService
        oversized_bytes = b"\xff\xd8" + b"\x00" * (20 * 1024 * 1024 + 1)
        result = OCRService.extract_text(oversized_bytes)
        assert result.success is False


class TestSlipParser:
    def test_parse_basic_slip(self):
        from app.services.slip_parser import parse_slip
        texts = [
            "Krungthai", "กรุงไทย", "โอนเงินสำเร็จ",
            "รหัสอ้างอิง ABC123XYZ", "200.00", "บาท",
            "จำนวนเงิน", "0.00", "ค่าธรรมเนียม",
            "26 ส.ค. 2569 - 10:19",
        ]
        confidences = [0.99] * len(texts)

        parsed = parse_slip(texts, confidences)

        assert parsed.bank is not None
        assert parsed.bank.value == "Krungthai"
        assert parsed.amount is not None
        assert parsed.amount.value == Decimal("200.00")
        assert parsed.reference is not None
        assert parsed.reference.value == "ABC123XYZ"
        assert parsed.status_text is not None
        assert parsed.status_text.value == "success"

    def test_parse_empty_texts(self):
        from app.services.slip_parser import parse_slip
        parsed = parse_slip([], [])
        assert parsed.bank is None
        assert parsed.amount is None
        assert parsed.reference is None

    def test_parse_kbank_slip(self):
        from app.services.slip_parser import parse_slip
        texts = ["KBank", "กสิกรไทย", "สำเร็จ", "REF987654", "1500.50"]
        confidences = [0.95, 0.94, 0.98, 0.96, 0.99]
        parsed = parse_slip(texts, confidences)
        assert parsed.bank is not None
        assert parsed.bank.value == "KBank"

    def test_parse_scb_slip(self):
        from app.services.slip_parser import parse_slip
        texts = ["SCB", "ไทยพาณิชย์", "SUCCESS", "TXN-ABC-123", "500.00"]
        confidences = [0.97, 0.96, 0.99, 0.95, 0.98]
        parsed = parse_slip(texts, confidences)
        assert parsed.bank is not None
        assert parsed.bank.value == "SCB"


class TestFraudDetection:
    def test_low_risk(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.95,
            amount_confidence=0.99,
            reference_confidence=0.98,
            ocr_amount=Decimal("200.00"),
            expected_amount=Decimal("200.00"),
            ocr_reference="ABC123",
            reference_duplicate=False,
            image_duplicate=False,
            sender_name="John Doe",
            receiver_name="Jane Smith",
            ocr_date=datetime.now(timezone.utc),
        )
        assert assessment.level == "verified"
        assert assessment.total_score < 0.20

    def test_amount_mismatch_high_risk(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.95,
            amount_confidence=0.99,
            reference_confidence=0.98,
            ocr_amount=Decimal("100.00"),
            expected_amount=Decimal("500.00"),
            ocr_reference="ABC123",
            reference_duplicate=False,
            image_duplicate=False,
            sender_name="John Doe",
            receiver_name="Jane Smith",
            ocr_date=datetime.now(timezone.utc),
        )
        assert assessment.total_score >= 0.20

    def test_duplicate_reference_rejected(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.95,
            amount_confidence=0.99,
            reference_confidence=0.98,
            ocr_amount=Decimal("200.00"),
            expected_amount=Decimal("200.00"),
            ocr_reference="ABC123",
            reference_duplicate=True,
            image_duplicate=False,
        )
        assert assessment.level == "rejected"
        assert assessment.total_score >= 0.50

    def test_duplicate_image_rejected(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.95,
            amount_confidence=0.99,
            reference_confidence=0.98,
            ocr_amount=Decimal("200.00"),
            expected_amount=Decimal("200.00"),
            ocr_reference="ABC123",
            reference_duplicate=False,
            image_duplicate=True,
            sender_name="John Doe",
            receiver_name="Jane Smith",
            ocr_date=datetime.now(timezone.utc),
        )
        assert assessment.level == "rejected"

    def test_low_ocr_confidence_review(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.70,
            amount_confidence=0.50,
            reference_confidence=0.95,
            ocr_amount=Decimal("200.00"),
            expected_amount=Decimal("200.00"),
            ocr_reference="ABC123",
            reference_duplicate=False,
            image_duplicate=False,
            sender_name="John Doe",
            receiver_name="Jane Smith",
            ocr_date=datetime.now(timezone.utc),
        )
        assert assessment.level == "review"

    def test_missing_reference_high_risk(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.95,
            amount_confidence=0.99,
            reference_confidence=0.0,
            ocr_amount=Decimal("200.00"),
            expected_amount=Decimal("200.00"),
            ocr_reference=None,
            reference_duplicate=False,
            image_duplicate=False,
            sender_name="John",
            receiver_name="Jane",
            ocr_date=datetime.now(timezone.utc),
        )
        assert assessment.total_score >= 0.50

    def test_score_capped_at_one(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timezone
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.10,
            amount_confidence=0.10,
            reference_confidence=0.10,
            ocr_amount=Decimal("100.00"),
            expected_amount=Decimal("500.00"),
            ocr_reference=None,
            reference_duplicate=True,
            image_duplicate=True,
            sender_name="John",
            receiver_name="Jane",
            ocr_date=datetime.now(timezone.utc),
        )
        assert assessment.total_score <= 1.0

    def test_old_transaction_increases_risk(self):
        from app.services.fraud_detection import FraudDetectionService
        from datetime import datetime, timedelta, timezone
        old_date = datetime.now(timezone.utc) - timedelta(days=30)
        assessment = FraudDetectionService.assess(
            ocr_avg_confidence=0.95,
            amount_confidence=0.99,
            reference_confidence=0.98,
            ocr_amount=Decimal("200.00"),
            expected_amount=Decimal("200.00"),
            ocr_reference="ABC123",
            reference_duplicate=False,
            image_duplicate=False,
            sender_name="John",
            receiver_name="Jane",
            ocr_date=old_date,
        )
        signal_names = [s.name for s in assessment.signals]
        assert "old_transaction" in signal_names


class TestDuplicateCheck:
    def test_check_reference_returns_none_for_new(self):
        from app.services.duplicate_check import DuplicateCheckService
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        result = DuplicateCheckService.check_reference(mock_db, "NEWREF123")
        assert result is None

    def test_check_image_hash_returns_none_for_new(self):
        from app.services.duplicate_check import DuplicateCheckService
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        result = DuplicateCheckService.check_image_hash(mock_db, "abc123", 1)
        assert result is None
