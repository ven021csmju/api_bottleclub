"""OCR client timeouts, MIME handling and the sync slip routes (offline)."""
import inspect
import io
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from PIL import Image


def _image(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format=fmt)
    return buf.getvalue()


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"success": True, "details": [{"text": "SCB", "confidence": 0.9}]}
    return response


class TestOCRClient:
    def test_default_timeouts(self):
        from app.config.settings import Settings

        fields = Settings.model_fields
        assert fields["OCR_SERVICE_TIMEOUT"].default == 20.0
        assert fields["OCR_SERVICE_CONNECT_TIMEOUT"].default == 3.0

    @patch("app.services.ocr_service.httpx.Client")
    def test_extract_text_uses_connect_and_read_timeouts(self, mock_client_cls, monkeypatch):
        from app.services import ocr_service

        monkeypatch.setattr(ocr_service.settings, "OCR_SERVICE_TIMEOUT", 20.0)
        monkeypatch.setattr(ocr_service.settings, "OCR_SERVICE_CONNECT_TIMEOUT", 3.0)
        mock_client_cls.return_value.__enter__.return_value.post.return_value = _ok_response()

        ocr_service.OCRService.extract_text(_image("PNG"), mime_type="image/png")

        timeout = mock_client_cls.call_args.kwargs["timeout"]
        assert timeout == httpx.Timeout(20.0, connect=3.0)
        assert (timeout.connect, timeout.read) == (3.0, 20.0)

    @patch("app.services.ocr_service.httpx.Client")
    def test_extract_text_sends_detected_type_and_name(self, mock_client_cls):
        from app.services.ocr_service import OCRService

        post = mock_client_cls.return_value.__enter__.return_value.post
        post.return_value = _ok_response()
        data = _image("WEBP")

        OCRService.extract_text(data, mime_type="image/webp")

        assert post.call_args.kwargs["files"] == {"file": ("slip.webp", data, "image/webp")}

    @patch("app.services.ocr_service.httpx.Client")
    def test_extract_text_refuses_unknown_type(self, mock_client_cls):
        from app.services.ocr_service import OCRService

        result = OCRService.extract_text(_image("PNG"), mime_type="image/gif")

        assert result.success is False
        mock_client_cls.assert_not_called()

    @patch("app.services.ocr_service.httpx.Client")
    def test_health_uses_short_timeout(self, mock_client_cls):
        from app.services.ocr_service import OCRService

        OCRService.health()

        timeout = mock_client_cls.call_args.kwargs["timeout"]
        assert (timeout.connect, timeout.read) == (3.0, 3.0)


class TestUnsupportedImage:
    def test_gif_named_jpg_is_415_before_any_record(self, monkeypatch):
        from app.domains.slip_verify import router
        from app.domains.slip_verify import service as slip_svc

        order = SimpleNamespace(status="pending", grand_total=Decimal("100.00"), amount_paid=Decimal("0"))
        attempts = []
        monkeypatch.setattr(slip_svc.SlipVerifyRepository, "find_pending_order", staticmethod(lambda *a, **k: order))
        monkeypatch.setattr(slip_svc.SlipVerifyRepository, "create_attempt", staticmethod(lambda db, **k: attempts.append(k)))
        create = MagicMock()
        monkeypatch.setattr(slip_svc.SlipVerifyRepository, "create_verification", create)
        extract = MagicMock()
        monkeypatch.setattr(slip_svc.OCRService, "extract_text", extract)

        # The client claims slip.jpg / image/jpeg; the service only sees bytes.
        result = slip_svc.SlipVerifyService.verify_slip(
            MagicMock(), user=SimpleNamespace(id=1, organization_id=1), order_id=7, file_bytes=_image("GIF")
        )

        assert result["status"] == "unsupported_media_type"
        assert router._HTTP_STATUS[result["status"]] == 415
        assert attempts[0]["http_status"] == 415
        create.assert_not_called()
        extract.assert_not_called()


class TestSlipRoutesRunInThreadpool:
    def test_upload_routes_are_sync(self):
        from app.domains.slip_verify import router

        for fn in (router.upload_slip, router.check_slip, router._process_slip):
            assert not inspect.iscoroutinefunction(fn), fn.__name__


class TestAutoVerifyFlag:
    def test_slip_auto_verify_defaults_to_false(self):
        from app.config.settings import Settings

        assert Settings.model_fields["SLIP_AUTO_VERIFY"].default is False

    def test_flag_reads_from_environment(self, monkeypatch):
        from app.config.settings import Settings

        monkeypatch.setenv("SLIP_AUTO_VERIFY", "true")
        assert Settings().SLIP_AUTO_VERIFY is True
        monkeypatch.setenv("SLIP_AUTO_VERIFY", "false")
        assert Settings().SLIP_AUTO_VERIFY is False
