# Runbook: ไวน์ตัวอย่าง (DEMO) บน production สำหรับหน้าร้าน

เจ้าของเป็นคนรันทุกคำสั่งในเอกสารนี้ใน terminal ของตัวเอง ห้ามรันจนกว่าเจ้าของจะสั่ง

| | |
|---|---|
| script | `scripts/seed_demo_wines.py` (มีตั้งแต่ v0.1.24) ตั้งค่าเริ่มต้นเป็น dry run คือ rollback ทุกครั้ง ถ้าจะบันทึกจริงต้องใส่ `--apply` |
| บน production ใช้ | **`--wine-only`** ใส่แค่ 8 แถวในตาราง `wine_products` ไม่สร้าง category และไม่สร้าง `products` |
| ป้ายสินค้าตัวอย่าง | `code` ขึ้นต้นด้วย `DEMO-` (ชื่อขึ้นต้นด้วย `DEMO ` ด้วย) หน้าร้านต้องแสดงป้าย "สินค้าตัวอย่าง" เมื่อ `code.startsWith("DEMO-")` |
| ต้องมีก่อน | production ต้องเป็น v0.1.24 แล้ว (`docs/runbooks/phase49-deploy.md`) |
| ลบออก | **ต้องลบก่อนเปิดร้านออนไลน์จริง** (ข้อ 3) |

## 1. ทำไมใช้ `--wine-only` บน production

- POS (`GET /catalog/products`), การสร้างออร์เดอร์, สต็อก และรายงานทุกตัว อ่านจากตาราง `products` ทั้งหมด
  ถ้าไม่มีแถว DEMO ใน `products` แคชเชียร์ก็จะไม่เห็นและขายไม่ได้ และจะไม่มีตัวเลขในรายงานยอดขายหรือรายงานสต็อก
- `wine_products` ถูกอ่านผ่าน `GET /wine-products/` และ `/wine-products/{id}` เท่านั้น ซึ่งเป็น route สาธารณะที่ไม่ต้อง login
- ถ้ารันแบบเต็ม (ไม่ใส่ `--wine-only`) จะได้ `products` ที่ active 8 ตัวในหมวด "ไวน์ตัวอย่าง (DEMO)":
  - **โผล่ใน catalog ของ POS** เพราะ list ไม่ได้กรอง DEMO ออก
  - **ขายได้**
  - **โผล่ในรายงานสต็อก** (`/reports/inventory` ที่ไม่ใส่ `branch_id`)
  - ถ้ามีคนขายไป ก็จะเข้ารายงานยอดขายด้วย
  - ถ้าไม่แก้ code ก็กันเรื่องเหล่านี้ไม่ได้ **บน production จึงห้ามรันแบบเต็ม**
- สิ่งที่ยังขาด: ทั้ง v0.1.24 และ `--wine-only` **ยังไม่มีราคาและคำอธิบายภาษาไทยให้หน้าร้านอ่านได้แบบสาธารณะ**
  - `wine_products` ไม่มีคอลัมน์ราคา
  - ราคาอยู่ใน `products` ซึ่งอ่านได้เฉพาะพนักงานที่ login แล้ว และ service key ก็ไม่มี scope ของ catalog
  - ถ้าต้องการ ต้องเพิ่ม route catalog สาธารณะของหน้าร้านใน phase ถัดไป

## 2. ใส่ไวน์ตัวอย่าง

```bash
# 2.1 dry run: ต้องได้ created: 8 (wine_product DEMO-...) และ "dry run: rolled back"
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --wine-only'
# 2.2 บันทึกจริง
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --wine-only --apply'
# 2.3 ตรวจ: ต้องได้ 8 และ products.demo_rows ต้องเป็น 0
curl -s 'http://127.0.0.1:8000/api/v1/wine-products/?search=DEMO&per_page=50' | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["total"])'
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
  < /home/kittikun/api_bottleclub/scripts/prod_checks/storefront_products.sql
```

- ถ้ารันซ้ำ จะไม่สร้างแถวซ้ำ แถว DEMO ที่ถูกแก้ไขจะถูกคืนเป็นค่าตั้งต้นของ script
- ถ้าเจอ `permission denied for table wine_products` แปลว่า role ของ API ไม่มี INSERT/UPDATE/DELETE บนตารางนี้ ให้หยุดแล้วแจ้ง backend

## 3. ลบออกก่อนเปิดร้านจริง (บังคับ)

ทำก่อนเปิดหน้าร้านให้ลูกค้าจริง หรือก่อนนำเข้าข้อมูลไวน์จริง

```bash
# 3.1 dry run: deleted ต้องมีเฉพาะ "wine_product DEMO-..." ทั้ง 8 แถว (ถ้ามี products DEMO ค้างจากการรันแบบเต็ม จะอยู่ในรายการนี้ด้วย)
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --delete'
# 3.2 ลบจริง
sudo -u bottleclub bash -c 'set -euo pipefail; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.seed_demo_wines --delete --apply'
# 3.3 ตรวจ: wine_products.demo_rows = 0 และ products.demo_rows = 0
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
  < /home/kittikun/api_bottleclub/scripts/prod_checks/storefront_products.sql
```

- `--delete` ลบเฉพาะแถวที่ `code` หรือ `sku` ขึ้นต้นด้วย `DEMO-` เท่านั้น ข้อมูลจริงไม่ถูกแตะ
  - ถ้าเคยมี product DEMO ถูกใช้ในออร์เดอร์หรือสต็อก (ซึ่งไม่ควรเกิดถ้าใช้ `--wine-only`) product นั้นจะถูกปิดและ soft-delete แทนการลบ
- ห้ามใช้ `--delete` คู่กับ `--wine-only` script จะไม่ยอมรัน เพราะ `--delete` ลบ DEMO ทุกแถวอยู่แล้ว
- หลังลบเสร็จ ให้หน้าร้านเอาโหมดสินค้าตัวอย่างออก (หรือปล่อยไว้ก็ได้ เพราะจะไม่มี `DEMO-` แล้ว)
