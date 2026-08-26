import hashlib
import io
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_IMAGE_PIXELS = 20_000_000


@dataclass
class ImageMetadata:
    sha256: str
    perceptual_hash: str | None
    mime_type: str
    file_size: int
    width: int
    height: int
    storage_key: str


class ImageService:
    @staticmethod
    def validate_image(file_bytes: bytes, filename: str, content_type: str) -> str | None:
        if len(file_bytes) > MAX_FILE_SIZE:
            return f"File too large: {len(file_bytes)} bytes (max {MAX_FILE_SIZE})"

        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"Unsupported file extension: {ext}"

        if content_type and content_type not in ALLOWED_MIME_TYPES:
            return f"Unsupported MIME type: {content_type}"

        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
        except Exception:
            return "Invalid or corrupted image file"

        try:
            img = Image.open(io.BytesIO(file_bytes))
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                return f"Image too large: {width}x{height} pixels"
        except Exception:
            return "Cannot read image dimensions"

        return None

    @staticmethod
    def compute_sha256(file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    @staticmethod
    def compute_perceptual_hash(file_bytes: bytes) -> str | None:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(file_bytes))
            img = img.convert("L").resize((16, 16), Image.LANCZOS)
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            bits = "".join("1" if p > avg else "0" for p in pixels)
            hex_str = hex(int(bits, 2))[2:].zfill(64)
            return hex_str
        except Exception as e:
            logger.warning("Failed to compute perceptual hash: %s", e)
            return None

    @staticmethod
    def generate_storage_key(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        unique_id = uuid.uuid4().hex
        return f"slip-uploads/{unique_id}{ext}"

    @staticmethod
    def get_image_dimensions(file_bytes: bytes) -> tuple[int, int]:
        try:
            img = Image.open(io.BytesIO(file_bytes))
            return img.size
        except Exception:
            return (0, 0)
