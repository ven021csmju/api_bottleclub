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
