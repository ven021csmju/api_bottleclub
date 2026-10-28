import logging
from dataclasses import dataclass, field

import httpx

from app.config.settings import settings
from app.services.image_service import MIME_EXTENSIONS

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
HEALTH_TIMEOUT = httpx.Timeout(3.0)


def _request_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        settings.OCR_SERVICE_TIMEOUT, connect=settings.OCR_SERVICE_CONNECT_TIMEOUT
    )


@dataclass
class OCRField:
    raw: str
    confidence: float


@dataclass
class OCRResult:
    texts: list[str] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    fields: list[OCRField] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    http_status: int | None = None
    #: The OCR service could not be asked (down, timed out, 5xx): the slip may
    #: be fine, staff check it by hand. False when the service read the image
    #: and found nothing usable.
    unavailable: bool = False


class OCRService:
    MAX_FILE_SIZE = 10 * 1024 * 1024

    @staticmethod
    def extract_text(image_bytes: bytes, *, mime_type: str) -> OCRResult:
        """Send the slip to the OCR service.

        ``mime_type`` is the type detected from the image bytes
        (:meth:`ImageService.validate_image`); the file is sent as
        ``slip.<ext>`` with that type.
        """
        if not image_bytes:
            return OCRResult(success=False, error="No image data provided")

        if len(image_bytes) > OCRService.MAX_FILE_SIZE:
            return OCRResult(
                success=False,
                error=f"Image too large: {len(image_bytes)} bytes (max {OCRService.MAX_FILE_SIZE})",
            )

        ext = MIME_EXTENSIONS.get(mime_type)
        if ext is None:
            return OCRResult(success=False, error=f"Unsupported MIME type: {mime_type}")

        url = settings.OCR_SERVICE_URL.rstrip("/") + "/ocr"
        logger.info("Sending image to OCR service at %s", url)

        try:
            with httpx.Client(timeout=_request_timeout()) as client:
                files = {"file": (f"slip{ext}", image_bytes, mime_type)}
                response = client.post(url, files=files)
        except httpx.TimeoutException:
            logger.error("OCR service timeout")
            return OCRResult(success=False, error="OCR service timeout", unavailable=True)
        except httpx.HTTPError as exc:
            logger.error("OCR service unavailable: %s", exc)
            return OCRResult(success=False, error="OCR service unavailable", unavailable=True)

        return OCRService._handle_response(response)

    @staticmethod
    def _handle_response(response: httpx.Response) -> OCRResult:
        logger.info("OCR service response received: status=%s", response.status_code)

        try:
            data = response.json()
        except ValueError:
            logger.error("OCR service returned invalid JSON")
            return OCRResult(
                success=False,
                error="Invalid OCR response",
                http_status=response.status_code,
                unavailable=True,
            )

        if response.status_code >= 400 or not data.get("success"):
            message = (
                data.get("error")
                or data.get("message")
                or f"OCR error (HTTP {response.status_code})"
            )
            return OCRResult(
                success=False,
                error=message,
                http_status=response.status_code,
                # 5xx: the service is down or still loading its engine (503),
                # not a verdict on the image.
                unavailable=response.status_code >= 500,
            )

        details = data.get("details") or []
        texts = [d.get("text") for d in details if d.get("text")]
        confidences = [d.get("confidence", 0.0) for d in details if d.get("text")]

        if not texts:
            return OCRResult(
                success=False,
                error="No text detected in image",
                http_status=response.status_code,
            )

        return OCRResult(
            texts=texts,
            confidences=confidences,
            fields=[
                OCRField(raw=text, confidence=conf)
                for text, conf in zip(texts, confidences)
            ],
            success=True,
            http_status=response.status_code,
        )

    @staticmethod
    def health() -> bool:
        url = settings.OCR_SERVICE_URL.rstrip("/") + "/health"
        try:
            with httpx.Client(timeout=HEALTH_TIMEOUT) as client:
                response = client.get(url)
                return response.status_code == 200 and response.json().get("status") == "ok"
        except Exception as exc:
            logger.warning("OCR service health check failed: %s", exc)
            return False
