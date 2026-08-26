import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from paddleocr import PaddleOCR

logger = logging.getLogger(__name__)

MAX_IMAGE_PIXELS = 20_000_000
_ocr_instance: PaddleOCR | None = None


def _get_ocr() -> PaddleOCR:
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = PaddleOCR(lang="th", enable_mkldnn=False, show_log=False)
    return _ocr_instance


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


class OCRService:
    MAX_IMAGE_PIXELS = 20_000_000

    @staticmethod
    def extract_text(image_bytes: bytes) -> OCRResult:
        try:
            from PIL import Image
            import numpy as np

            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size
            if width * height > OCRService.MAX_IMAGE_PIXELS:
                return OCRResult(
                    success=False,
                    error=f"Image too large: {width}x{height} pixels (max {OCRService.MAX_IMAGE_PIXELS})",
                )

            img = img.convert("RGB")
            img_array = np.array(img)
        except Exception as e:
            return OCRResult(success=False, error=f"Invalid image: {e}")

        try:
            ocr = _get_ocr()
            result = ocr.predict(img_array)
        except Exception as e:
            return OCRResult(success=False, error=f"OCR engine error: {e}")

        ocr_result = OCRResult()

        for res in result:
            texts = res.get("rec_texts", [])
            scores = res.get("rec_scores", [])

            ocr_result.texts = texts
            ocr_result.confidences = scores
            ocr_result.fields = [
                OCRField(raw=text, confidence=score)
                for text, score in zip(texts, scores)
            ]

        if not ocr_result.texts:
            ocr_result.success = False
            ocr_result.error = "No text detected in image"

        return ocr_result
