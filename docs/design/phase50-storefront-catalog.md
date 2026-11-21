# Phase 50 — catalog สาธารณะของหน้าร้าน (A) + checkout ฝั่งลูกค้า (B): ข้อเสนอออกแบบ

สถานะ: **ข้อเสนอ ยังไม่มีโค้ด** (2026-11-21) · ฐาน: v0.1.24 (`2fd969b`)

## การตัดสินใจของเจ้าของ (2026-11-21)

- ร้านยังไม่มีข้อมูลสินค้าจริง: หน้าร้านบน production ใช้สินค้า DEMO
- สินค้า DEMO ต้องไม่ขึ้นทุกจุดฝั่งพนักงาน (POS, การสร้างออร์เดอร์, สต็อก, รายงาน) และต้องขายผ่าน POS ไม่ได้
- หน้าร้านแสดงสินค้า DEMO พร้อมราคา คำอธิบาย และ `is_demo: true` เพื่อแสดงป้าย "สินค้าตัวอย่าง"
- B (checkout) อยู่หลัง flag ที่ปิดไว้

## 0. สิ่งที่พบในโค้ด v0.1.24

- `products` (ราคา, คำอธิบายไทย, `image_url`) อ่านได้เฉพาะพนักงานที่ login (`/catalog/*`) ส่วน service key ไม่มี scope ของ catalog
- `wine_products` (ประเภท, ประเทศ, แหล่ง, แอลกอฮอล์, รูป) อ่านได้สาธารณะผ่าน `GET /wine-products/` แต่ไม่มีราคาและไม่มีสถานะ active
  สองตารางเชื่อมกันด้วยข้อตกลง `wine_products.code = products.sku` เท่านั้น
- ตอนนี้ไม่มีจุดไหนในโค้ดรู้จัก DEMO นอกจาก `scripts/seed_demo_wines.py` ซึ่งดูจาก prefix ของ sku/code
- `GET /catalog/products` ไม่ได้กรอง `is_active` เป็นค่าเริ่มต้น การสร้างออร์เดอร์รับเฉพาะ `is_active` และยังไม่ถูกลบ
  รายงานสต็อกแสดงสินค้าที่ยังไม่ถูกลบทุกตัว
- branch `feat/demo-wines-prod` (`dbae296`, ยังไม่ merge) มี `--wine-only` ไว้ใช้ชั่วคราว ถ้าข้อเสนอนี้ผ่าน
  `--wine-only` ไม่จำเป็นอีกต่อไป (ข้อ A4)

## A. Catalog สาธารณะ

### A1. Migration `026_products_is_demo.sql`

```sql
BEGIN;
ALTER TABLE products ADD COLUMN IF NOT EXISTS is_demo boolean NOT NULL DEFAULT false;
UPDATE products SET is_demo = true WHERE sku LIKE 'DEMO-%' AND NOT is_demo;
-- invariant (คำถาม Q2): sku DEMO- <=> is_demo
ALTER TABLE products ADD CONSTRAINT ck_products_demo_sku CHECK (is_demo = (sku LIKE 'DEMO-%'));
CREATE INDEX IF NOT EXISTS ix_products_storefront ON products (organization_id)
    WHERE is_demo AND is_active AND deleted_at IS NULL;
INSERT INTO schema_migrations (version, note) VALUES ('026', 'products.is_demo');
COMMIT;
```
ตามรูปแบบของ 025: มี `DO` block ตรวจว่ามี `schema_migrations` แล้ว, ยังไม่เคย apply 026 และ apply 025 แล้ว

- **rollback** `026_products_is_demo.rollback.sql`: drop constraint, index และ column
  แถว DEMO- ยังอยู่ และ code v0.1.24 จะเห็นเป็นสินค้าธรรมดา จึงต้องรัน `--delete --apply` ก่อนย้อน
- `ADD COLUMN ... DEFAULT false` ใน PostgreSQL 11 ขึ้นไปไม่ rewrite ตาราง ส่วน `UPDATE` บน production กระทบ 0 แถว (ยังไม่มี DEMO)
- grants: ไม่มีตารางใหม่ role ของ API มี DML บน `products` อยู่แล้ว
- API ของพนักงานตั้ง `is_demo` ไม่ได้ และ `sku` ที่ขึ้นต้นด้วย `DEMO-` จาก `POST/PUT /catalog/products` จะได้ 422 `DEMO_SKU_RESERVED`
  สินค้า DEMO จึงเกิดได้จาก `seed_demo_wines.py` ทางเดียว

### A2. ทุก query ฝั่งพนักงานที่อ่าน `products` (ไล่จาก v0.1.24)

ใช้ helper เดียว `staff_products()` คือ `Product.is_demo.is_(False)` ใส่ทุกจุดในตารางนี้ แล้วเพิ่ม test ที่ไล่ทุก route ของพนักงานด้วยสินค้า DEMO (A4)

| # | ไฟล์ : ฟังก์ชัน | ใช้ที่ | ทำอะไร |
|---|---|---|---|
| 1 | `db/repositories/catalog/catalog_repository.py:82` `list_products` | `GET /catalog/products` (catalog ของ POS, ค้นด้วย barcode, หน้า Admin) | กรองออก |
| 2 | `catalog_repository.py:133` `get_product` ← `catalog/service.py:174` `get_product` | `GET /catalog/products/{id}` | 404 |
| 3 | `catalog/service.py:231` `update_product`, `:270` `delete_product` | `PUT` / `DELETE /catalog/products/{id}` | 404 (DEMO แก้ได้ผ่าน seed เท่านั้น) |
| 4 | `catalog_repository.py:125` `list_product_costs` | `GET /catalog/products/costs` | กรองออก |
| 5 | `catalog_repository.py:137/147` `find_by_sku` / `find_by_barcode` | ค้นตรงตัว | กรองออก |
| 6 | `catalog_repository.py:157/170` `find_sku_conflict` / `find_barcode_conflict` | กัน sku/barcode ซ้ำ | **ไม่กรอง** (ต้องกันซ้ำกับ DEMO ด้วย) |
| 7 | `catalog_repository.py:60` `count_category_products` | กันลบหมวดที่มีสินค้า | **ไม่กรอง** |
| 8 | `catalog/service.py:386/426` link supplier ↔ product, `catalog_repository.py:253` `list_supplier_products` | `/catalog/suppliers/{id}/products` | link → 404, list → กรองออก |
| 9 | `db/repositories/orders/order_repository.py:22` `get_products_by_ids` ← `orders/service.py:178` | `POST /orders/` (POS) | **ปฏิเสธทั้งออร์เดอร์** 422 `DEMO_PRODUCT_NOT_FOR_SALE` (ไม่ใช่ "not found") |
| 10 | `order_repository.py:37` `get_product` ← `orders/service.py:563` (ยกเลิกออร์เดอร์, คืนสต็อก) | cancel | ไม่ต้องกรอง (ไม่มีออร์เดอร์ DEMO) แต่ใส่ assert ใน test |
| 11 | `order_repository.py:43` `get_stations_for_products` | KDS | ไม่ต้องกรอง (ตาม #9) |
| 12 | `db/repositories/inventory/inventory_repository.py:17` `get_org_product` ← `inventory/service.py:26` `_org_branch_product` | balance / adjust / lots / movements ของสินค้าตัวเดียว | 404 |
| 13 | `inventory_repository.py:102` `list_balances` | `GET /inventory/...` | กรองออก |
| 14 | `inventory_repository.py:146` `list_lots`, `:162` `list_movements` | lot / movement | กรองออก |
| 15 | `inventory_repository.py:203` `list_low_stock` | สต็อกต่ำ | กรองออก |
| 16 | `inventory_repository.py:27/67` `apply_adjustment` / `add_on_hand` | ปรับสต็อก | ไม่ถึง (กันที่ #12) |
| 17 | `db/repositories/purchases/purchase_repository.py:33` `get_product` ← `purchases/service.py:133/170` | สร้าง / รับ PO | 422 `DEMO_PRODUCT_NOT_FOR_SALE` |
| 18 | `transfers/service.py:32` `create_transfer` (ตอนนี้ไม่ตรวจ product เลย) | โอนสต็อก | เพิ่มการตรวจ → 422 |
| 19 | `returns/service.py:44` `create_return` | คืนสินค้า | ไม่ถึง (ไม่มีออร์เดอร์ DEMO) ใส่ assert ใน test |
| 20 | `db/repositories/reports/report_repository.py:104` `sold_lines` | daily-summary, sales, financial, top_products | กรองออก (กันไว้อีกชั้นแม้ #9 กันแล้ว) |
| 21 | `report_repository.py:196` `inventory_report` | `/reports/inventory` | กรองออก (`total_products` ไม่นับ DEMO) |
| 22 | `db/repositories/reviews/review_repository.py:9/39/52` ← `reviews/service.py:14`, `reviews/router.py:82` | รีวิว (พนักงาน) | รีวิวใหม่ของ DEMO → 404, list → กรองออก |
| 23 | `scripts/import_master_data.py` (ผ่าน API) | นำเข้า CSV | ได้ผลตาม #3/#6 (sku DEMO- → 422) |

รายงานที่คิดจากตาราง `orders` / `payments` อย่างเดียว (กะ, X-report, financial ส่วน payment) ไม่อ่าน `products`
จึงไม่มีตัวเลขของ DEMO ตราบที่ #9 กันไว้ ส่วน `GET /wine-products/` ไม่เปลี่ยน (ดู A3)

### A3. Route catalog สาธารณะ (ไม่ต้อง login)

```
GET /storefront/products   ?page=&per_page=(≤50)&type=red|white|sparkling|rose&country=&search=&sort=price|-price|name
GET /storefront/products/{id}
→ 200 { "id", "sku", "name", "description", "price": "1590.00", "image_url", "is_demo": true,
        "wine": { "type", "country", "region", "alcohol", "volume" } | null }
```

- **แสดงเฉพาะ** `is_demo AND is_active AND deleted_at IS NULL AND selling_price > 0` ในองค์กรของ `STOREFRONT_ORGANIZATION_ID`
  (ว่าง = องค์กร active เดียว) `wine` ได้จากการ left join `wine_products` ด้วย `code = sku`
- **สินค้าจริงที่ค้างอยู่ใน `products` (ไม่ใช่ DEMO) จะไม่ขึ้นหน้าร้าน** จนกว่า phase ถัดไปจะเพิ่มวิธีเลือกสินค้าที่ขายออนไลน์ (คำถาม Q1)
- ไม่ส่ง `cost_price`, สต็อก, `barcode`, `station` หรือ `organization_id`
- rate limit 120/นาที ต่อ IP มี `Cache-Control: public, max-age=60`
- ไม่ log คำค้น (ต่างจาก `/wine-products` ที่ส่ง event)
- ส่วน `GET /wine-products/` คงไว้ตามเดิม (ไม่เปลี่ยน contract) หน้าร้านควรใช้ route ใหม่แทน

### A4. Seed แบบเต็มบน production + test

- `seed_demo_wines.py` (ไม่ใส่ `--wine-only`) ตั้ง `is_demo = true` และ `track_inventory = false` (ไม่มีสต็อกให้หลุด)
  `--delete` ทำงานเหมือนเดิม และ `--wine-only` ถูกยกเลิก (คำถาม Q4)
- integration test ใหม่ ใช้ฐานที่มีสินค้าจริง 1 ตัวและ DEMO ครบชุด:
  - `GET /catalog/products` (ทั้งแบบมีและไม่มี `search=<barcode/sku ของ DEMO>`) ต้องไม่มี DEMO
  - `GET /catalog/products/{demo_id}` ได้ 404 และ `/catalog/products/costs` ไม่มี DEMO
  - `POST /orders/` ที่มีบรรทัด DEMO ได้ 422 `DEMO_PRODUCT_NOT_FOR_SALE` และไม่มีแถวใน orders / stock เกิดขึ้น
  - ออร์เดอร์ของสินค้าจริงยังใช้ได้ตามปกติ
  - inventory (balance, adjust, lots, movements, low-stock), PO, transfer: DEMO ได้ 404/422 หรือไม่อยู่ในรายการ
  - `/reports/daily-summary`, `sales`, `financial`, `inventory`: ตัวเลขเท่ากับฐานที่ไม่มี DEMO
  - `POST/PUT /catalog/products` ที่ใช้ sku `DEMO-…` ได้ 422 `DEMO_SKU_RESERVED`
  - `GET /storefront/products` เห็นเฉพาะ DEMO พร้อม `is_demo: true` ส่วนสินค้าจริงไม่ขึ้น
  - test เทียบรายการ route: ทุก route ใน `app.routes` ที่มี `product` ใน path หรืออ่าน `Product` ต้องอยู่ใน
    allow-list ของ test นี้ ถ้าเพิ่ม route ใหม่แล้วไม่อัปเดต test จะตก
- staging: รัน seed แบบเต็มใน `reset_staging.sh` แล้วเพิ่มตัวอย่างใน `capture_examples.py`
  ขั้น E2E ต้องยืนยันว่า catalog ของ POS ยังมี 20 รายการ

### A5. ขยาย seed เป็น 24 รายการ (ไม่บังคับ: Q5)

- ชื่อแต่งขึ้นเองทั้งหมด (ขึ้นต้นด้วย `DEMO `) ไม่ใช้ชื่อแบรนด์ โรงไวน์ หรือ château จริง
  ชื่อแหล่ง/ประเทศใช้ชื่อภูมิศาสตร์ (เช่น Bordeaux) ได้ แต่ไม่ใช้คำที่เป็นชื่อการค้าจดทะเบียน
  ก่อน commit ต้องค้นชื่อทุกตัวว่าไม่ซ้ำผู้ผลิตจริง และบันทึกการตรวจไว้
- ผสม: แดง 9, ขาว 6, สปาร์กลิง 4, โรเซ่ 3, ของหวาน 2 ราคา 590–30,000 บาท มีคำอธิบายไทยทุกตัว
- รูป: รูปทั่วไป (ขวด/แก้วที่ไม่เห็นฉลาก หรือเห็นฉลากว่าง) จาก CC0 / Unsplash License / Pexels License
  บันทึกใน `docs/assets/demo-wines-images.md` ครบทุกรูป: ไฟล์, URL ต้นทาง, ผู้ถ่าย, สัญญาอนุญาต (พร้อมลิงก์), วันที่ตรวจ, sha256
  และหมายเหตุว่า "ไม่เห็นฉลากแบรนด์" ที่ตรวจด้วยตาแล้ว
  ห้ามใช้รูปที่สร้างจาก AI ซึ่งเลียนแบบฉลากจริง ที่เก็บรูปรอคำตอบ Q6

## B. Checkout ฝั่งลูกค้า (หลัง flag ปิด)

> ใน repo **ยังไม่มี**เอกสารออกแบบ B ฉบับก่อน ที่มีคือ phase48 ข้อ 5.1 และข้อ "นอก Phase 48"
> ส่วนนี้จึงเป็นโครงจากข้อจำกัดเดิม ถ้ามีฉบับอื่นอยู่ ให้แจ้ง path แล้วผมจะใช้ฉบับนั้นแทน

- **กฎหมาย (phase48 ข้อ 5.1):** ห้ามขายเครื่องดื่มแอลกอฮอล์ทางอิเล็กทรอนิกส์ ยกเว้น**ซื้อและชำระเงินที่ร้าน**
  B จึงเป็นแค่ "จองออนไลน์ จ่ายและรับที่ร้าน" ไม่มีการจ่ายเงินออนไลน์ ต้องให้ที่ปรึกษากฎหมายยืนยันก่อนเปิด flag
- flag `CUSTOMER_CHECKOUT_ENABLED=false` (ค่าเริ่มต้น และบน production) ถ้าปิด route ของ B ทุกตัวตอบ 404
- `POST /customer/reservations` (token ลูกค้า, `Idempotency-Key`) `{branch_id, items:[{product_id, quantity}], pickup_note?}`
  - สร้างออร์เดอร์ `order_source = 'online'`, `status = 'reserved'` ไม่ตัดสต็อกและไม่จ่ายเงิน มีอายุจอง (เช่น 48 ชม.)
  - **สินค้า DEMO ได้ 422 `DEMO_PRODUCT_NOT_FOR_SALE`** (บน production ที่มีแต่ DEMO จึงจองอะไรไม่ได้เลย) ทดสอบบน staging ด้วยสินค้าจริงตัวอย่าง
- POS: แคชเชียร์เปิดออร์เดอร์ที่จองไว้ ตรวจอายุ/บัตร (`customer_accounts.age_verified_*`) แล้วรับเงินผ่าน checkout เดิม ตัดสต็อกตอนนั้น
- `GET /customer/reservations`, `POST /customer/reservations/{id}/cancel` ใช้แค่ว่าการจองหมดอายุแล้วยกเลิกเอง
- ข้อจำกัดเดิมที่ต้องเปลี่ยน: ตอนนี้ `POST /orders/` รับเฉพาะ POS (`order_source` อื่นได้ 422) B จะใช้ route ของตัวเอง ไม่ไปเปิด route เดิม

## C. แบ่งงานและ deploy

1. **50A-1**: migration 026 + กรองทุกจุดใน A2 + `DEMO_SKU_RESERVED` + test A4 → v0.1.25
   deploy: backup → 026 → code (ย้อน code ได้: v0.1.24 ไม่อ่าน `is_demo` แต่จะเห็น DEMO เป็นสินค้าธรรมดา จึงต้องลบ DEMO ก่อนย้อน)
2. **50A-2**: `/storefront/products` + seed แบบเต็ม (+ 24 รายการ ถ้า Q5 = ใช่) + handoff
3. **50B**: หลัง flag ปิด รอกฎหมายยืนยัน

## คำถามให้เจ้าของตัดสินใจ

- **Q1** สินค้าจริงในอนาคต: เพิ่ม `products.is_online` (เลือกได้ทีละตัวว่าขึ้นหน้าร้านไหม) ใน phase ถัดไป
  หรือให้หน้าร้านแสดงสินค้าจริงที่ active และมีราคาทุกตัว (เสนอ: `is_online` ค่าเริ่มต้น false)
- **Q2** CHECK `is_demo = (sku LIKE 'DEMO-%')`: ผูกสองค่านี้ไว้ถาวร (เสนอ: ใช่ เพราะ flag กับ prefix จะไม่มีทางขัดกัน)
- **Q3** Admin ควรเห็นหรือแก้ DEMO ในหน้าหลังบ้านไหม (เสนอ: ไม่ แก้ได้ผ่าน seed อย่างเดียว ซึ่งเป็นตามข้อ 2 ของคำสั่ง)
- **Q4** ยกเลิก `--wine-only` และ branch `feat/demo-wines-prod` แล้วรวมเข้า Phase 50 (เสนอ: ใช่)
  เพราะถ้าใช้ `--wine-only` ไปก่อน หน้าร้านจะไม่มีราคาอยู่ดี
- **Q5** ขยายเป็น 24 รายการไหม หรือใช้ 8 รายการเดิม
- **Q6** รูปเก็บที่ไหน: (ก) ใน repo หน้าร้าน (Vercel `/public`) แล้ว `image_url` เป็น path สัมพัทธ์
  (ข) ให้ API เสิร์ฟ static (ค) object storage/CDN (เสนอ: ก ไม่เพิ่มภาระให้ laptop production)
- **Q7** กฎหมาย: แสดงไวน์พร้อมราคาบนเว็บสาธารณะ (แม้เป็น DEMO) อาจเข้าข่ายโฆษณาตาม ม.32 พ.ร.บ.ควบคุมเครื่องดื่มแอลกอฮอล์
  ต้องให้ที่ปรึกษากฎหมายดูก่อนเปิดหน้า catalog บน production หรือไม่ (เสนอ: ต้องดู ส่วน staging เปิดได้)
- **Q8** `STOREFRONT_ORGANIZATION_ID`: ปล่อยว่าง (องค์กร active เดียว แบบ LINE) ใช่ไหม
