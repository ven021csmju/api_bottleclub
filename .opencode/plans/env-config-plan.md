# Plan: ปรับปรุง Environment Variables สำหรับโปรเจกต์ `api` เท่านั้น

## สถานะปัจจุบัน (สำรวจแล้ว)
- `Backend/api` มี git repo ของตัวเอง (`.git` อยู่ใน `api/`), `database` เป็น sibling ที่ `Backend/database`
- Configuration ถูก centralized แล้วที่ `app/config/settings.py` (pydantic-settings, `env_file=".env"`)
- `main.py`, `security.py`, `auth.py`, `auth/service.py` อ่าน config ผ่าน `from app.config.settings import settings` แล้ว (ไม่มี `os.getenv` กระจายใน `app/`)
- `requirements.txt` มี `python-dotenv==1.0.1`, `pydantic-settings==2.5.2` แล้ว
- `api/.env` มีอยู่แล้ว (มี secrets จริง แต่อยู่ใน `.gitignore` แล้ว), `api/.env.example` ถูกลบใน working tree แต่ยังถูก track
- `.gitignore` (api) มี `.env` อยู่แล้วบรรทัด 25
- ปัญหา: รัน `uvicorn app.main:app --reload` จาก `api/` เกิด `ModuleNotFoundError: No module named 'database'` เพราะ `database` เป็น sibling ที่ `Backend/database`

## ขั้นตอน (แก้เฉพาะใน `Backend/api`)

### 1. ปรับ `app/config/settings.py` (ไม่สร้าง `app/core/config.py` ใหม่ — รักษา architecture เดิม)
- ใช้ `SettingsConfigDict` + anchor `env_file` ไปที่ `api/.env` แบบ absolute ผ่าน `Path(__file__).resolve().parents[2] / ".env"` (ทำให้อ่าน `api/.env` เสมอ ไม่ว่าจาก CWD ไหน)
- เพิ่ม `ENVIRONMENT: str = "development"`
- เพิ่ม `DATABASE_URL` (ค่า default placeholder ชี้ development DB) — ตัวเชื่อมต่อ DB จริงยังสร้างโดย `database/database.py` ผ่าน `database/config.py` (อ่าน `DATABASE_URL` จาก env)
- เก็บตัวแปรที่มีอยู่แล้ว: `REDIS_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `CORS_ORIGINS`
- หมายเหตุ: `JWT_SECRET_KEY` default เป็น placeholder (ต้อง override ใน `.env` เสมอ — ไม่ hardcode secret จริง)

### 2. เพิ่ม bootstrap sys.path ใน `app/main.py` (บนสุด ก่อน import อื่น)
- คำนวณ `REPO_ROOT = Path(__file__).resolve().parents[2]` (= `Backend/`) และถ้ายังไม่ใน `sys.path` ให้ insert เพิ่ม
- ทำให้ `from database...` resolve ได้เมื่อรันจาก `api/` โดยไม่แก้ไขโค้ด `database` เลย (ตรงตามข้อ 13)
- (กรณีรันจาก `Backend` ด้วย `--app-dir api` ตาม run_dev scripts/Dockerfile ยังทำงานเหมือนเดิม เพราะ `Backend` อยู่ใน path อยู่แล้ว)

### 3. สร้าง `Backend/api/.env.example` (template, ห้าม secret จริง)
ครอบคลุมตัวแปรที่ใช้จริงใน source code:
- `ENVIRONMENT=development`
- `DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:<port>/<db>`
- `REDIS_URL=redis://localhost:6379/0`
- `JWT_SECRET_KEY=<generate-a-long-random-string>`
- `JWT_ALGORITHM=HS256`
- `ACCESS_TOKEN_EXPIRE_MINUTES=15`
- `REFRESH_TOKEN_EXPIRE_DAYS=7`
- `CORS_ORIGINS=["http://localhost:3000"]`
พร้อม comment/ตัวอย่าง — ไม่ใส่ `0217`, `venv0217` หรือ password จริง

### 4. `.gitignore` — ยืนยันแล้วว่า `.env` ถูก ignore อยู่ (บรรทัด 25) ไม่ต้องแก้เพิ่ม
- ตรวจไม่ให้ `.env` ถูก track (ยังไม่มีใน `git ls-files`) และไม่ commit secrets จริง

### 5. Dependency — ไม่ต้องติดตั้งเพิ่ม (`python-dotenv` + `pydantic-settings` มีแล้ว)
- ถ้า environment ยังไม่ได้: `pip install -r requirements.txt`

### 6. รัน/ตรวจสอบ
- รันจาก `Backend/api`: `uvicorn app.main:app --reload`
- ตรวจ health: `http://localhost:8000/health`
- ตรวจว่า `.env` โหลด: `python -c "from app.config.settings import settings; print(settings.ENVIRONMENT, settings.DATABASE_URL, settings.JWT_SECRET_KEY)"`

## ตัวแปรใน `api/.env` (ปัจจุบัน, ทิ้งไว้ตามเดิม)
`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` (do not commit)

## ตัวแปรใน `.env.example`
`ENVIRONMENT`, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `CORS_ORIGINS`

## คำสั่ง
- ติดตั้ง: `pip install -r requirements.txt`
- รัน: `uvicorn app.main:app --reload` (จาก `Backend/api`)
- ตรวจโหลด `.env`: `python -c "from app.config.settings import settings; print(settings.ENVIRONMENT)"`
