# Runbook: Phase 50A (v0.1.25) — catalog สาธารณะ + สินค้า DEMO

เจ้าของเป็นคนรันทุกคำสั่งใน terminal ของตัวเอง **ห้ามรันจนกว่าเจ้าของจะสั่ง**
ต้องมี v0.1.24 (Phase 49, migration 022–025) บน production ก่อน (`phase49-deploy.md`)

| | |
|---|---|
| Migration | `026_products_demo_online.sql` เพิ่ม `products.is_demo`, `products.is_online`, CHECK `ck_products_demo_sku` และ index `ix_products_storefront` · apply ก่อน code |
| Env ใหม่ | `STOREFRONT_CATALOG_ENABLED` **ไม่ต้องตั้งบน production** (ไม่ตั้ง = ปิด = 404 จนกว่าที่ปรึกษากฎหมายจะยืนยัน, owner Q7) · `STOREFRONT_ORGANIZATION_ID` ไม่ต้องตั้ง (องค์กร active เดียว) · `RATE_LIMIT_STOREFRONT_CATALOG` (ค่าเริ่มต้น 120/minute) |
| ข้อมูล | `scripts/seed_demo_wines.py` ใส่ 24 รายการ (`is_demo`) + 24 แถวใน `wine_products` ไม่มีสต็อก ไม่มีหมวด |
| ไม่กระทบ | POS, ออร์เดอร์, สต็อก, จัดซื้อ, โอน, รีวิว, รายงาน ไม่เห็นสินค้า DEMO (ทดสอบใน `tests/integration/test_demo_products_hidden.py`) |

## 1. Backup และ migration

```bash
cd ~/api_bottleclub
sudo scripts/ops/prod_db.sh backup pre-phase50
sudo scripts/ops/prod_db.sh apply migrations/026_products_demo_online.sql
# NOTICE ที่ต้องเห็น: "026: products.is_demo, products.is_online, ck_products_demo_sku; 0 DEMO- row(s) marked"
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -XAt -c "SELECT version FROM schema_migrations WHERE version = '026'"   # 026
```

- ไม่มีตารางใหม่ จึงไม่ต้องรัน grants (role ของ API มี DML บน `products` อยู่แล้ว)
- code v0.1.24 ทำงานบน 026 ได้ เพราะไม่อ่าน column ใหม่ แต่ถ้ามีแถว DEMO อยู่ v0.1.24 จะเห็นเป็นสินค้าธรรมดา (ข้อ 4)

## 2. Code

```bash
sudo bottleclub-deploy v0.1.25 --prepare-only
sudo bottleclub-deploy v0.1.25
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/storefront/products   # 404 (ปิดอยู่ ถูกต้อง)
```

## 3. ไวน์ตัวอย่าง

```bash
# 3.1 dry run: created: 48 (product DEMO-… 24, wine_product DEMO-… 24), แล้ว "dry run: rolled back"
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines'
# 3.2 บันทึกจริง
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --apply'
# 3.3 ตรวจ: products.demo_rows = 24, wine_products.demo_rows = 24
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
  < /home/kittikun/api_bottleclub/scripts/prod_checks/storefront_products.sql
```

- ตรวจด้วยตาบน POS (login แคชเชียร์): catalog ต้องไม่มีชื่อที่ขึ้นต้นด้วย `DEMO`
- เมื่อที่ปรึกษากฎหมายยืนยันแล้ว ให้เปิด catalog โดยเพิ่ม `STOREFRONT_CATALOG_ENABLED=true` ใน `/etc/bottleclub/api.env` (และสำเนา `~/bottleclub-prod/api.env`) แล้ว `sudo systemctl restart fastapi`

## 4. ลบไวน์ตัวอย่าง (บังคับก่อนเปิดร้านออนไลน์จริง หรือก่อนย้อน code)

```bash
# 4.1 dry run: deleted ต้องเป็นเฉพาะ "product DEMO-…" และ "wine_product DEMO-…" (48) และ soft_deleted: 0
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --delete'
# 4.2 ลบจริง
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --delete --apply'
# 4.3 ตรวจ: demo_rows = 0 ทั้งสองตาราง
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
  < /home/kittikun/api_bottleclub/scripts/prod_checks/storefront_products.sql
```

- `--delete` แตะเฉพาะแถวที่ขึ้นต้นด้วย `DEMO-` (และหมวด "ไวน์ตัวอย่าง (DEMO)" ของ v0.1.24 ถ้ามีค้าง)
- ถ้ามีแถว DEMO ถูกอ้างถึงอยู่ ซึ่งไม่ควรเกิดเพราะทุกจุดปฏิเสธ แถวนั้นจะถูกปิดและ soft-delete แทนการลบ

## 5. ย้อนกลับ

| สถานการณ์ | ทำอะไร |
|---|---|
| code ผิดปกติ | **ข้อ 4 ก่อน** (ลบ DEMO) แล้วจึง `sudo bottleclub-deploy v0.1.24` เก็บ 026 ไว้ได้ เพราะ v0.1.24 ไม่อ่าน column ใหม่ |
| ต้องย้อน schema | ย้อน code ก่อน แล้ว `sudo scripts/ops/prod_db.sh apply migrations/026_products_demo_online.rollback.sql` (ค่า `is_online` ที่ตั้งไว้จะหายไป) |
| เปิด catalog แล้วต้องปิดด่วน | ลบ `STOREFRONT_CATALOG_ENABLED` ออกจาก `api.env` แล้ว `sudo systemctl restart fastapi` (route จะกลับไปตอบ 404) |

ซ้อม apply / rollback / apply ซ้ำบน staging แล้ว (2026-11-22, `~/p50-staging/logs/migration-026.log`)
