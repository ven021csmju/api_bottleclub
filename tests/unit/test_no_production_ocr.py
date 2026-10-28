"""Tests never reach the OCR service (Phase 40): its default URL is the
production one on this machine (127.0.0.1:9000)."""
from unittest.mock import patch

from app.config.settings import settings


def test_the_ocr_url_points_at_a_closed_port():
    assert settings.OCR_SERVICE_URL == "http://127.0.0.1:1"


@patch("app.services.ocr_service.httpx.Client")
def test_an_unfaked_call_goes_there(mock_client_cls):
    from app.services.ocr_service import OCRService

    OCRService.health()
    assert mock_client_cls.return_value.__enter__.return_value.get.call_args.args[0] == "http://127.0.0.1:1/health"
