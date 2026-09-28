# FastAPI + PostgreSQL Backend

โปรเจกต์ REST API แบบง่าย สร้างด้วย FastAPI, SQLAlchemy, Alembic และ PostgreSQL  
พร้อม Deploy บน Ubuntu Server ได้ทันที

---

## Tech Stack

| Layer      | Technology          |
|------------|---------------------|
| API        | FastAPI             |
| Server     | Uvicorn             |
| ORM        | SQLAlchemy 2        |
| Migration  | Alembic             |
| Database   | PostgreSQL          |
| Config     | python-dotenv (.env)|

---

## โครงสร้างโปรเจกต์

```
project/
├── app/
│   ├── __init__.py
│   ├── main.py          ← FastAPI app + root endpoint
│   ├── database.py      ← SQLAlchemy engine & session
│   ├── models.py        ← ORM models (User)
│   ├── schemas.py       ← Pydantic schemas
│   └── routers/
│       └── users.py     ← CRUD endpoints /users
├── alembic/
│   ├── env.py           ← Alembic migration environment
│   ├── script.py.mako
│   └── versions/        ← Migration files
├── alembic.ini
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## วิธีติดตั้งและรัน (Ubuntu Server)

### 1. ติดตั้ง Python 3.11+

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 --version
```

### 2. Clone และเข้าไปในโฟลเดอร์โปรเจกต์

```bash
git clone <your-repo-url>
cd project
```

### 3. สร้าง Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. ติดตั้ง Dependencies

```bash
pip install -r requirements.txt
```

### 5. สร้าง PostgreSQL Database

```bash
sudo apt install -y postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql

# สร้าง database
sudo -u postgres psql -c "CREATE DATABASE mydatabase;"
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'password';"
```

### 6. ตั้งค่า Environment

```bash
cp .env.example .env
nano .env
```

แก้ไขค่าใน `.env` ให้ตรงกับ PostgreSQL ของคุณ:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/mydatabase
```

### 7. รัน Alembic Migration

สร้าง migration file (ครั้งแรก):

```bash
alembic revision --autogenerate -m "create users table"
```

Apply migration เพื่อสร้างตารางใน database:

```bash
alembic upgrade head
```

### 8. Start FastAPI

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

สำหรับ production ให้รันแบบ background:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 &
```

### 9. ทดสอบ API

เปิด Swagger UI ที่:

```
http://<your-server-ip>:8000/docs
```

หรือทดสอบผ่าน curl:

```bash
# Health check
curl http://localhost:8000/

# ดึง users ทั้งหมด
curl http://localhost:8000/users/

# สร้าง user ใหม่
curl -X POST http://localhost:8000/users/ \
  -H "Content-Type: application/json" \
  -d '{"name": "John", "email": "john@example.com"}'

# ดึง user ตาม id
curl http://localhost:8000/users/1

# อัปเดต user
curl -X PUT http://localhost:8000/users/1 \
  -H "Content-Type: application/json" \
  -d '{"name": "John Doe"}'

# ลบ user
curl -X DELETE http://localhost:8000/users/1
```

---

## API Endpoints

| Method | Path           | Description           |
|--------|----------------|-----------------------|
| GET    | /              | Health check          |
| GET    | /users/        | ดึง User ทั้งหมด      |
| GET    | /users/{id}    | ดึง User ตาม ID       |
| POST   | /users/        | สร้าง User ใหม่       |
| PUT    | /users/{id}    | อัปเดต User ตาม ID   |
| DELETE | /users/{id}    | ลบ User ตาม ID        |

### Request Body (POST/PUT)

```json
{
  "name": "John",
  "email": "john@example.com"
}
```

### Response

```json
{
  "id": 1,
  "name": "John",
  "email": "john@example.com",
  "created_at": "2026-08-08T10:00:00"
}
```

---

## Alembic Commands

```bash
# สร้าง migration ใหม่จาก model ที่เปลี่ยนแปลง
alembic revision --autogenerate -m "describe your change"

# Apply migration ล่าสุด
alembic upgrade head

# ดู migration history
alembic history

# Rollback 1 step
alembic downgrade -1
```

---

## MongoDB Log Service Integration

ระบบบันทึก Log (user activity / search / system events) จะเก็บใน MongoDB ที่อยู่บนเครื่อง Ubuntu เดียวกับ
PostgreSQL แต่ไม่เปิด port 27017 ให้ Internet ภายนอก เข้าถึงผ่าน **SSH Tunnel** เท่านั้น

### 1. เปิด SSH Tunnel ไปยัง MongoDB

```bash
ssh -L 27017:localhost:27017 kittikun@192.168.1.146
```

เปิดไว้ทิ้งไว้ (อย่าปิด) แล้วรัน API ตามปกติ ระยะเวลา tunnel พัง/เสถียรภาพ ระบบจะพยายามเชื่อมต่อใหม่เอง
โดยอัตโนมัติ และ **จะไม่มีผลต่อ business API** (เข้าใช้งานได้ตามปกติแม้ MongoDB ติดต่อไม่ได้)

### 2. ตั้งค่า Environment

เพิ่มใน `.env` (ดูตัวอย่างใน `.env.example`):

```env
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=system_logs
MONGODB_CONNECTION_TIMEOUT_MS=2000
MONGODB_SERVER_SELECTION_TIMEOUT_MS=1500
MONGODB_MAX_POOL_SIZE=10
MONGODB_MIN_POOL_SIZE=1
MONGODB_RETRY_COOLDOWN_SECONDS=15
MONGODB_USER_LOGS_TTL_DAYS=90
MONGODB_SEARCH_LOGS_TTL_DAYS=90
MONGODB_SYSTEM_EVENTS_TTL_DAYS=180
```

### 3. Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check ปกติ (PostgreSQL) — ยังคง `{"status": "healthy"}` เสมอ |
| GET | `/health/mongodb` | สถานะการเชื่อมต่อ MongoDB (`connected`/`disconnected`) |

### 4. Collections และ TTL

| Collection | เนื้อหา | TTL |
|------------|---------|-----|
| `user_logs` | activity ของ user รวมถึง `action=login` | 90 วัน |
| `search_logs` | ประวัติค้นหา | 90 วัน |
| `system_events` | เหตุการณ์ภายในระบบ | 180 วัน |

ทุก collection มี index `created_at` แบบ TTL และ index สำหรับ filter (user_id, action, query,
event_type, severity, request_id)

### 5. ข้อควรระวัง

- ต้องเปิด SSH tunnel ก่อนจึงจะบันทึก log ได้ หากไม่ได้เปิด ระบบจะข้ามไปเงียบ ๆ (fail-silent)
  โดยมี cooldown retry ตาม `MONGODB_RETRY_COOLDOWN_SECONDS`
- Server ที่ใช้รัน MongoDB 4.4 (CPU ไม่รองรับ AVX) — อย่าอัปเกรดเป็น MongoDB 5.0+ บนเครื่องนี้
```
