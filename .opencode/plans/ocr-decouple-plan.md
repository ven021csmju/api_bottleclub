# Plan: แยก OCR ออกจาก FastAPI API (โปรเจกต์ `api`) — ใช้ HTTP client เรียก OCR Service

## สถานะปัจจุบัน (สำรวจแล้ว)
- `Backend/ocr` = standalone OCR Service (FastAPI + PaddleOCR, venv `Batman`). มี:
  - `POST /ocr` (multipart, field `file`) → success `{"success":true,"text","confidence","details":[{"text","confidence"}]}`; error 4xx/5xx `{"success":false,"error":"..."}`
  - `GET /health` → `{"status":"ok"}`
- `api/app/services/` **ถูกลบออกจาก disk** (ยังมีใน git HEAD) แต่ `app/domains/slip_verify/service.py` + `tests/unit/test_slip_verify.py` ยัง import `app.services.*` → API รันไม่ได้ตอนนี้
- `requirements.txt` (api) ยังมี `paddleocr`, `paddlepaddle` (เส้น 17-18) → ต้องลบ
- `.env` (api) ยังไม่มี `OCR_SERVICE_URL`/`OCR_SERVICE_TIMEOUT`
- `httpx` มีอยู่แล้วใน requirements (line 13)

## สิ่งที่ทำ (แก้เฉพาะใน `Backend/api`)

### 1. ตั้ง Config (`app/config/settings.py`)
เพิ่มใน `Settings`:
```python
OCR_SERVICE_URL: str = "http://127.0.0.1:9000"
OCR_SERVICE_TIMEOUT: int = 60
```

### 2. `.env` และ `.env.example` (api)
เพิ่ม:
```env
OCR_SERVICE_URL=http://127.0.0.1:9000
OCR_SERVICE_TIMEOUT=60
```
- `.env` ถูก gitignore แล้ว (verify line ".env") และไม่ได้ track → ไม่ commit secrets

### 3. เขียน `app/services/ocr_service.py` ใหม่เป็น HTTP client (ไม่มี PaddleOCR)
- คง interface `OCRService.extract_text(image_bytes) -> OCRResult` ไว้ (เหมือนเดิม) เพราะ `slip_verify/service.py` ใช้ `ocr_result.success/.texts/.confidences/.error`
- `OCRResult` dataclass เดิม: `texts, confidences, fields, success, error`
- ใช้ `httpx.Client(timeout=settings.OCR_SERVICE_TIMEOUT)` ส่ง `POST {OCR_SERVICE_URL}/ocr` (multipart, field `file`)
- map response: success → `texts`/`confidences` จาก `details`
- จัดการ error ให้ return `OCRResult(success=False, error=...)` เสมอ (ไม่ crash API):
  - connection error → "OCR service unavailable"
  - timeout → "OCR service timeout"
  - 4xx/5xx / `success:false` → error จาก response
  - invalid JSON → "Invalid OCR response"
  - ว่าง/no text → "No text detected in image"
  - ไฟล์ใหญ่เกิน (10MB guard) → success=False
- เพิ่ม `OCRService.health() -> bool` เรียก `GET {OCR_SERVICE_URL}/health` (utility, ไม่ทำให้ startup ล้มเหลว)
- Log เหมาะสม ไม่ log รูป/secret

### 4. Restore service files ที่จำเป็นจาก git HEAD (ไม่แก้ business logic)
กลับมาใช้งานที่ `app/services/`:
- `__init__.py`
- `slip_parser.py` (คืนจาก HEAD ตามเดิม — pure logic)
- `image_service.py` (คืนจาก HEAD ตามเดิม — ใช้ PIL ซึ่งใช้งานจริงใน API จึงเก็บ Pillow ไว้)
- `fraud_detection.py` (คืนจาก HEAD ตามเดิม — pure logic)
- `duplicate_check.py` (คืนจาก HEAD **แต่แก้ import** `from app.models import ...` → `from database.models import PaymentVerification, VerificationAttempt` เพราะ models ย้ายไป `database.models` แล้ว; ตัว runtime ไม่ใช้ แต่ test import เป็น)

### 5. `requirements.txt` (api)
- ลบ `paddleocr>=3.7.0`, `paddlepaddle>=3.3.0`
- เก็บ `httpx`, `Pillow` (ใช้จริงใน `image_service.py` และ tests)

### 6. Tests (`tests/unit/test_slip_verify.py`)
- แก้เฉพาะ `TestOCRService` ให้ mock `httpx.Client`/การ POST แทนการ mock `_get_ocr` (PaddleOCR)
- ไม่แตะ `TestImageValidation`, `TestImageHashing`, `TestSlipParser`, `TestFraudDetection`
- `TestDuplicateCheck` import `app.services.duplicate_check` → จะผ่านเพราะ restore แล้ว

### 7. ไม่แตะ
- `Backend/ocr` (OCR Service ดำเนินการเอง / รันแยกข้างนอก)
- `Backend/database`
- `slip_verify/service.py` (interface ยังเหมือนเดิม), JWT, auth, payment, business logic อื่น

## ตรวจสอบ
- `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` เริ่มได้ ไม่มี `ModuleNotFoundError: No module named 'paddleocr'`
- `python -c "from app.config.settings import settings; print(settings.OCR_SERVICE_URL, settings.OCR_SERVICE_TIMEOUT)"`
- `python -m pytest tests/unit/test_slip_verify.py -q` (OCR-related tests mock HTTP)
- OCR Service แยก: `uvicorn app.main:app --port 9000` ที่ `Backend/ocr` (รันข้างนอก)

## ไฟล์ที่จะแก้/สร้าง
- `app/services/ocr_service.py` (เขียนใหม่)
- `app/services/{__init__,slip_parser,image_service,fraud_detection,duplicate_check}.py` (restore จาก HEAD)
- `app/config/settings.py` (เพิ่ม 2 ตัวแปร)
- `requirements.txt` (ลบ paddle*)
- `.env`, `.env.example` (เพิ่ม OCR_SERVICE_*)
- `tests/unit/test_slip_verify.py` (แก้ TestOCRService เท่านั้น)
