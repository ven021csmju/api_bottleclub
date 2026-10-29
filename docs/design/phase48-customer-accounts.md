# Phase 48 — บัญชีลูกค้า (สมัครด้วยอีเมล): ข้อเสนอออกแบบ

สถานะ: **แบบอนุมัติแล้ว 2026-10-30** (ยังไม่มีโค้ด/migration) · ฐาน: v0.1.21 (`5bc08f85d8e1`)

## การตัดสินใจของเจ้าของ (2026-10-30) — ใช้แทนข้อเสนอเดิมทุกที่ที่ขัดกัน

| # | การตัดสินใจ | ผลต่อแบบ |
|---|---|---|
| D1 | **ไม่มีอีเมลการตลาด และไม่มี consent การตลาด** (ม.32 พ.ร.บ.ควบคุมเครื่องดื่มแอลกอฮอล์) — ส่งเฉพาะอีเมลระบบ | `customer_consents.kind` มีแค่ `terms` / `privacy`; ไม่มี `marketing_opt_in` ใน register; template อีเมลมีแค่ `verify_email`, `reset_password`, `account_exists`, `email_changed`, `account_deleted` |
| D2 | **ลบบัญชี → แต้มเป็น 0** โดยแสดงยอดแต้มที่จะหายและให้ลูกค้ายืนยันก่อน | ledger: `loyalty_transactions` แถว `transaction_type = 'adjustment'`, `points = -<คงเหลือ>`, `reference_type = 'account_deleted'`, `reference_id = customer_account_id`; `POST /customer/me/delete` ต้องส่ง `confirm_points_forfeit: <จำนวนแต้มที่เห็น>` ตรงกับยอดปัจจุบัน ไม่งั้น 409 `POINTS_CHANGED` |
| D3 | **ช่วงผ่อนผัน refresh ซ้อนอยู่ใน 48a** | ข้อ 4 + 6 |
| D4 | **SES เป็นหลัก, Resend สำรอง** — เปลี่ยน provider ได้ผ่าน outbox (`EMAIL_PROVIDER`) | ข้อ 3 |
| D5 | ก่อน 48a มี **Phase 48-0** ตรวจ/แก้ IP ที่ rate limit ใช้หลัง cloudflared | ข้อ 5.6, 6 |

> ⚠️ **อ่านข้อ 5.1 ก่อน**: ประกาศสำนักนายกรัฐมนตรี พ.ศ. 2563 **ห้ามขายเครื่องดื่มแอลกอฮอล์ทางอิเล็กทรอนิกส์**
> (มีผล 7 ธ.ค. 2563, ยกเว้นการซื้อขาย**และชำระเงินที่ร้าน**) — ไม่พบข่าวว่ายกเลิก. บัญชีลูกค้าทำได้
> แต่ "สั่งซื้อออนไลน์" ต้องให้ที่ปรึกษากฎหมายยืนยันรูปแบบก่อน (เช่น จองออนไลน์ → จ่ายและรับที่ร้าน).

## 0. สิ่งที่พบในโค้ดปัจจุบัน (เกี่ยวกับการออกแบบ)

| เรื่อง | ที่ไหน | ผลต่อ Phase 48 |
|---|---|---|
| ทุกอย่างของลูกค้าผูกกับ `customers.id` (แต้ม, ที่อยู่, รีวิว, `orders.customer_id`) | `app/db/models.py:737`, `:777`, `:1706`, `:1736`, `:836` | บัญชีลูกค้า = ตัว login ที่ชี้ไป `customers` 1 แถว (ไม่สร้างตารางลูกค้าซ้ำ) |
| `customers` มี unique index `(organization_id, phone)` | `models.py:760` | สมัครด้วยเบอร์ที่ลูกค้าหน้าร้านใช้อยู่ = ชน index — **และ** ถ้าผูกอัตโนมัติด้วยเบอร์ = คนอื่นอ้างแต้มของเขาได้ → ข้อ 1.3 |
| token พนักงาน: ไม่มี `aud`, `type: "access"`, `sub` = `users.id` | `app/shared/security.py:37`, `app/middleware/auth.py:28` | ถ้าใช้ key เดียวกัน `sub` ของลูกค้าจะไปตรงกับ `users.id` ของพนักงาน |
| python-jose: `decode` **ไม่ส่ง** `audience` แล้ว token มี `aud` → ปฏิเสธ (`Invalid audience`) — แต่ **ส่ง** `audience=` แล้ว token **ไม่มี** `aud` → **ผ่าน** | ทดลองกับ python-jose 3.3.0 ใน venv ของ repo | ฝั่งลูกค้าต้องใช้ key แยก **และ** `options={"require_aud": True}` (ข้อ 2.1) |
| `GET /auth/google/callback` สร้างบัญชี **ในตาราง `users` ของพนักงาน** (ไม่มี role) | `app/domains/auth/service.py:355` | บัญชีลักษณะลูกค้าอยู่ปนกับพนักงานแล้ว → ย้าย/ปิดใน 48c |
| `POST /auth/register` สร้าง `users` ไม่มี role; ปิดใน prod (`REGISTRATION_ENABLED` unset → false) | `app/domains/auth/router.py` | ต้องปิดต่อไป (มี test อยู่แล้ว) — ลบ route ใน 48c |
| `orders.user_id` NOT NULL (พนักงานที่เปิดบิล) | `models.py:839` | ออร์เดอร์ที่ลูกค้าสร้างเองต้องแก้ (นอก Phase 48 — ข้อ 5) |
| rate limit: slowapi key = `request.client.host`, เก็บใน memory, uvicorn `--workers 1` | `app/middleware/rate_limit.py`, `fastapi.service` | ต่อ IP ใช้ได้ (แต่รีเซ็ตเมื่อ restart); **ต่อบัญชี** ต้องเก็บใน DB |
| prod อยู่หลัง **Cloudflare Tunnel** (`cloudflared` → 127.0.0.1:8000) และ NS ของ wayneven.uk เป็น Cloudflare | `ps`, `dig NS` | IP จริงของลูกค้าต้องอ่านจาก `CF-Connecting-IP` (ข้อ 5.6); Turnstile/DNS อยู่ที่ Cloudflare ที่เดียว |
| wayneven.uk **ยังไม่มี** SPF / MX / DMARC | `dig TXT/MX/_dmarc` | เริ่มจากศูนย์ — ไม่ต้องรวมกับ record เดิม |

---

## 1. Schema

### 1.1 ภาพรวม

```
customers (เดิม: โปรไฟล์ + แต้ม; ลูกค้าหน้าร้านมีแค่แถวนี้)
   ▲ 1:1 (customer_id UNIQUE)
customer_accounts (ใหม่: login ของลูกค้า — ไม่เกี่ยวกับ users ของพนักงาน)
   ├─< customer_identities      (ใหม่: Google / LINE ภายหลัง)
   ├─< customer_consents        (ใหม่: ประวัติ consent แบบ append-only)
   ├─< customer_email_tokens    (ใหม่: ยืนยันอีเมล / ลืมรหัส / เปลี่ยนอีเมล)
   ├─< customer_refresh_tokens  (ใหม่: เหมือน refresh_tokens + family_id ของ Phase 45)
   └─< customer_auth_events     (ใหม่: rate limit ต่อบัญชี + ประวัติ login)
email_outbox (ใหม่: คิวอีเมล ส่งโดย worker — ไม่ส่งใน request)
users (พนักงาน) ── age_verified_by ──> customer_accounts
```

**ตัดสินใจ:** ตาราง identity ชื่อ `customer_identities` (เจ้าของเรียก `user_identities`) — เพราะ `users` ในระบบนี้คือ
**พนักงาน**; ชื่อ `user_identities` จะทำให้คนอ่านเข้าใจว่าผูกกับพนักงาน. โครงสร้างตรงตามที่ต้องการ (หลาย provider ต่อบัญชี).

### 1.2 ตารางใหม่ (migration 022 — ใน 48a)

**`customer_accounts`**

| column | type | หมายเหตุ |
|---|---|---|
| `id` | bigint PK | |
| `organization_id` | bigint FK organizations NOT NULL | |
| `customer_id` | bigint FK customers **UNIQUE** NOT NULL, `ON DELETE RESTRICT` | โปรไฟล์/แต้ม |
| `email` | varchar(255) NULL | เก็บแบบ lower-case; NULL หลังลบบัญชี |
| `email_verified_at` | timestamptz NULL | NULL = ยังสั่งซื้อไม่ได้ |
| `password_hash` | varchar(255) NULL | NULL = บัญชีที่ login ด้วย Google/LINE อย่างเดียว (48c) |
| `password_changed_at` | timestamptz NULL | token ที่ออกก่อนนี้ใช้ไม่ได้ (เหมือนพนักงาน) |
| `phone_pending` | varchar(50) NULL | เบอร์ที่กรอกตอนสมัคร — ยังไม่ใส่ใน `customers.phone` (ข้อ 1.3) |
| `status` | varchar(20) NOT NULL | `active` / `locked` / `deleted` |
| `age_verified_at` | timestamptz NULL | พนักงานตรวจบัตรแล้ว |
| `age_verified_by` | bigint FK **users** NULL | พนักงานที่ตรวจ — **ไม่เก็บเลข/รูปบัตร** |
| `age_verified_branch_id` | bigint FK branches NULL | ตรวจที่สาขาไหน |
| `last_login_at`, `created_at`, `updated_at` | timestamptz | |
| `deleted_at` | timestamptz NULL | เวลาที่ anonymize |

ข้อจำกัด: `UNIQUE (organization_id, email) WHERE email IS NOT NULL`; `CHECK (status IN ('active','locked','deleted'))`;
`CHECK (status <> 'deleted' OR email IS NULL)`; `CHECK ((age_verified_at IS NULL) = (age_verified_by IS NULL))`.
วันเกิดเก็บที่ `customers.date_of_birth` เดิม (มีอยู่แล้ว) — บังคับกรอกตอนสมัครที่ API (ไม่แก้ NOT NULL ของตารางเดิม เพราะลูกค้าหน้าร้านไม่มี).

**`customer_identities`** (สร้างใน 48a ให้ schema พร้อม, ใช้จริงใน 48c)

| column | หมายเหตุ |
|---|---|
| `id`, `customer_account_id` FK `ON DELETE CASCADE` | |
| `provider` varchar(20) | `google` / `line` |
| `provider_subject` varchar(255) | `sub` ของ provider (ไม่ใช่อีเมล — อีเมลเปลี่ยนได้) |
| `email_at_link` varchar(255) NULL | อีเมลจาก provider ตอนผูก (ข้อมูลประกอบ) |
| `linked_at`, `last_used_at` | |

`UNIQUE (provider, provider_subject)` — 1 บัญชี provider ผูกได้บัญชีลูกค้าเดียว; `UNIQUE (customer_account_id, provider)`.
**กฎ 48c:** ผูกได้เฉพาะตอน login ด้วยรหัสผ่านอยู่แล้ว (หรือยืนยันผ่านอีเมล) — **ห้าม**ผูกอัตโนมัติด้วยอีเมลที่ตรงกัน.

**`customer_consents`** (append-only: ถอน = แถวใหม่ `granted = false`)

| column | หมายเหตุ |
|---|---|
| `id`, `customer_account_id` FK | |
| `kind` varchar(20) | `terms` / `privacy` (ไม่มี marketing: D1) — `CHECK (kind IN ('terms','privacy'))` |
| `version` varchar(20) | เวอร์ชันเอกสารที่ยอมรับ (เช่น `2026-11-01`) |
| `granted` boolean | |
| `granted_at` timestamptz, `ip` varchar(45), `user_agent` text | หลักฐานตาม PDPA |

เวอร์ชันปัจจุบันของ terms/privacy อยู่ในตาราง `settings` เดิม (`customer.terms_version`, `customer.privacy_version`):
เปลี่ยนเวอร์ชัน → ลูกค้าที่ยังไม่ยอมรับเวอร์ชันใหม่ได้ 403 `CONSENT_VERSION_OUTDATED` ที่ route สั่งซื้อจนกว่าจะยอมรับ.

**`customer_email_tokens`**

| column | หมายเหตุ |
|---|---|
| `id`, `customer_account_id` FK `ON DELETE CASCADE` | |
| `purpose` | `verify_email` / `reset_password` / `change_email` |
| `token_hash` varchar(64) UNIQUE | sha256 ของ token สุ่ม 32 byte — ไม่เก็บ token จริง |
| `new_email` NULL | สำหรับ `change_email` |
| `expires_at` | verify 24 ชม., reset 30 นาที, change 24 ชม. |
| `used_at` NULL, `created_at`, `request_ip` | ใช้ได้ครั้งเดียว; ออก token ใหม่ = token เก่า purpose เดียวกันใช้ไม่ได้ |

**`customer_refresh_tokens`**: โครงเดียวกับ `refresh_tokens` (รวม `family_id`, row lock, reuse → revoke family ของ Phase 45)
แต่ FK `customer_account_id` — แยกตารางเพื่อไม่ให้ token สองระบบปนกันแม้ใน DB.

**`customer_auth_events`** (rate limit ต่อบัญชี + ประวัติ)

| column | หมายเหตุ |
|---|---|
| `id`, `occurred_at` | |
| `kind` | `login_failed` / `login_ok` / `register` / `forgot` / `email_sent` / `reset` |
| `email_hash` varchar(64) | sha256(lower(email) + pepper) — **นับได้แม้อีเมลไม่มีบัญชี** (ไม่ให้รู้ว่ามีบัญชีหรือไม่) |
| `customer_account_id` NULL, `ip` varchar(45) | |

index `(email_hash, kind, occurred_at)`, `(ip, kind, occurred_at)`; ลบแถวเก่ากว่า 90 วันด้วย job.

**`email_outbox`**

| column | หมายเหตุ |
|---|---|
| `id`, `to_email`, `template` (`verify_email`, `reset_password`, `account_exists`, `email_changed`, …), `payload` jsonb | payload มีลิงก์ที่มี token → **ล้าง payload หลังส่งสำเร็จ** |
| `status` (`pending`/`sent`/`failed`), `attempts`, `next_attempt_at`, `sent_at`, `provider_message_id`, `last_error` | |

ส่งโดย worker แยก (systemd service, poll ทุก 5 วินาที, `SELECT … FOR UPDATE SKIP LOCKED`). เหตุผล: (1) เวลาตอบของ
register/forgot เท่ากันไม่ว่าจะมีบัญชีหรือไม่ (2) provider ล่ม ≠ สมัครไม่ได้ (3) retry ได้.

### 1.3 ความสัมพันธ์กับ `customers` เดิม (ลูกค้าหน้าร้าน/แต้มสะสม)

| สถานการณ์ | พฤติกรรมที่เสนอ |
|---|---|
| สมัครใหม่ | สร้าง `customers` แถวใหม่ (ชื่อ, อีเมล, วันเกิด; **`phone` = NULL**) + `customer_accounts` (`phone_pending` = เบอร์ที่กรอก). ไม่ชน unique index ของเบอร์ และไม่แตะลูกค้าหน้าร้าน |
| ลูกค้าหน้าร้านมีแต้มอยู่แล้ว (เบอร์เดียวกัน) | **ไม่ผูกอัตโนมัติ** (เบอร์ไม่ได้ยืนยัน = ใครก็กรอกเบอร์คนอื่นได้). ผูกที่เคาน์เตอร์: พนักงานค้นบัญชี → เห็นว่า `phone_pending` ตรงกับลูกค้าหน้าร้าน → ตรวจบัตร (ครั้งเดียวกับยืนยันอายุ) → `POST /customers/{id}/link-account` ย้าย `customer_accounts.customer_id` ไปแถวเดิม (มีแต้ม/ประวัติ) และปิดแถวใหม่ที่ว่าง (ทำได้เฉพาะแถวใหม่ที่ยังไม่มีออร์เดอร์/แต้ม; ไม่งั้น 409 `CUSTOMER_MERGE_NEEDED` → ทำมือ) |
| ไม่มีลูกค้าหน้าร้านเดิม | พนักงานยืนยันที่เคาน์เตอร์ → ย้าย `phone_pending` ไป `customers.phone` (ถ้าชน → 409 เหมือนบรรทัดบน) |
| POS ค้นลูกค้าด้วยเบอร์ (เหมือนเดิม) | เจอเฉพาะ `customers.phone` (ที่ยืนยันแล้ว) — ไม่ค้น `phone_pending` เพื่อสะสมแต้ม |

---

## 2. Endpoint และ error code

### 2.1 แยก token ลูกค้ากับพนักงาน

| | พนักงาน (เดิม) | ลูกค้า (ใหม่) |
|---|---|---|
| key | `JWT_SECRET_KEY` | **`CUSTOMER_JWT_SECRET_KEY`** (อีกค่า, ≥ 32 ตัว, API ไม่ start ถ้าเท่ากับของพนักงาน) |
| claims | `type: access`, ไม่มี `aud` | `type: customer_access`, `aud: bottleclub-customer`, `sub: <customer_account_id>`, `ev` (อีเมลยืนยันแล้ว) |
| decode | เดิม (jose ปฏิเสธ token ที่มี `aud` อยู่แล้ว) + key ต่างกัน → signature ไม่ผ่าน | `audience="bottleclub-customer"`, `options={"require_aud": True}`, ตรวจ `type` |
| dependency | `get_authenticated_user` (`users`) | `get_customer_account` (`customer_accounts`) — คนละฟังก์ชัน, route ลูกค้า**ไม่**ใช้ dependency ของพนักงานเลย |

test ที่ต้องมี: token ลูกค้า → ทุก route พนักงาน 401; token พนักงาน (และ token ที่ไม่มี `aud`) → ทุก route `/customer/*` 401;
token ลูกค้าเซ็นด้วย key พนักงาน → 401; `POST /auth/register` ยัง 403 `REGISTRATION_DISABLED` ใน production/staging.

### 2.2 ลูกค้า — `/api/v1/customer/auth/*` (48a)

| method & path | body | ผลสำเร็จ | หมายเหตุ |
|---|---|---|---|
| `POST /customer/auth/register` | `email, password, first_name, last_name, phone, date_of_birth, terms_version, privacy_version, turnstile_token` | **202** `{"detail": "ถ้าใช้อีเมลนี้สมัครได้ เราได้ส่งลิงก์ยืนยันไปแล้ว"}` | **ตอบเหมือนกันเสมอ**: อีเมลมีบัญชีแล้ว → ไม่สร้าง, ส่งอีเมล `account_exists` ("มีคนพยายามสมัครด้วยอีเมลนี้ — login หรือรีเซ็ตรหัส") ไปที่อีเมลนั้นแทน. ตรวจรูปแบบ/อายุ/consent **ก่อน**ดูว่ามีบัญชี (error พวกนี้ไม่บอกอะไรเรื่องการมีบัญชี). hash รหัสผ่านทั้งสองทาง (เวลาเท่ากัน) |
| `POST /customer/auth/verify-email` | `token` | 200 `{email_verified: true}` | token ใช้ครั้งเดียว |
| `POST /customer/auth/resend-verification` | `email, turnstile_token` | 202 (ข้อความเดียวกันเสมอ) | |
| `POST /customer/auth/login` | `email, password, turnstile_token` | 200 token (โหมด body หรือ cookie — ข้อ 4) | อีเมลยังไม่ยืนยัน → **login ได้** (`email_verified: false`) แต่สั่งซื้อไม่ได้ |
| `POST /customer/auth/refresh` | — / `refresh_token` | 200 | กลไก Phase 45 ทั้งหมด |
| `POST /customer/auth/logout` | — / `refresh_token` | 204 | |
| `POST /customer/auth/forgot-password` | `email, turnstile_token` | 202 (ข้อความเดียวกันเสมอ) | ไม่มีบัญชี → ไม่ส่งอะไร (หรือส่ง "ไม่มีบัญชีด้วยอีเมลนี้" — **ไม่แนะนำ**: เป็นช่องให้ส่งอีเมลหาใครก็ได้) |
| `POST /customer/auth/reset-password` | `token, new_password` | 204 | revoke refresh token ทุกตัว, `password_changed_at` |

### 2.3 ลูกค้า — `/api/v1/customer/me*` (48b)

| method & path | หมายเหตุ |
|---|---|
| `GET /customer/me` | โปรไฟล์ + `email_verified`, `age_verified` (true/false เท่านั้น), แต้มคงเหลือ, consent ล่าสุด |
| `PATCH /customer/me` | ชื่อ, เบอร์ (→ `phone_pending` ใหม่, ต้องยืนยันที่เคาน์เตอร์อีกครั้ง); วันเกิด **แก้เองไม่ได้** หลังพนักงานยืนยันอายุแล้ว |
| `POST /customer/me/change-password` | `current_password, new_password` |
| `POST /customer/me/change-email` | `new_email, password` → 202, ส่งลิงก์ไปอีเมลใหม่ + แจ้งอีเมลเดิม |
| `GET /customer/me/consents`, `POST /customer/me/consents` | ยอมรับ terms/privacy เวอร์ชันใหม่ (ไม่มี marketing: D1) |
| `GET /customer/me/export` | ข้อมูลของฉัน (PDPA ม.30–31): โปรไฟล์, consent, ออร์เดอร์, แต้ม — JSON |
| `GET /customer/me/delete-preview` | แต้มที่จะหาย + ออร์เดอร์ค้าง (ให้หน้า shop แสดงก่อนยืนยัน: D2) |
| `POST /customer/me/delete` | `password` (หรือ re-auth ผ่านอีเมลถ้าไม่มีรหัส) + `confirm_points_forfeit` → 202; anonymize ทันที (ข้อ 2.5) |

### 2.4 พนักงาน (route เดิมฝั่งพนักงาน, permission ใหม่)

| method & path | permission | หมายเหตุ |
|---|---|---|
| `GET /customer-accounts/?email=&phone=` | `customers.read` (สาขา) | ค้นบัญชีที่เคาน์เตอร์ (ค้น `phone_pending` ได้ที่นี่) |
| `POST /customer-accounts/{id}/age-verification` | **`customers.verify_age`** (ใหม่, ระดับสาขา: Branch Admin + POS) | body `{"document": "id_card" \| "passport" \| "driving_licence"}` — **ไม่มีช่องเลข/รูป**; บันทึก `age_verified_at/by/branch` + audit log `CUSTOMER.AGE_VERIFIED`; วันเกิดในบัตรไม่ตรงกับที่กรอก → พนักงานแก้วันเกิดได้ใน body เดียวกัน (audit) — ถ้าอายุ < 20 → 422 `UNDERAGE` และล็อกบัญชี |
| `POST /customers/{id}/link-account` | `customers.update` + `customers.verify_age` | ข้อ 1.3 |

### 2.5 ลบบัญชี (anonymize)

| ข้อมูล | ทำอย่างไร |
|---|---|
| `customer_accounts` | `email`, `password_hash`, `phone_pending` → NULL; `status = deleted`, `deleted_at = now`; คง `age_verified_at/by` (หลักฐานการขาย) |
| `customers` | `first_name = "ลูกค้าที่ลบบัญชี"`, `last_name/phone/email/date_of_birth` → NULL, `deleted_at` |
| `customer_identities`, `customer_email_tokens`, `customer_refresh_tokens` | ลบ |
| `customer_addresses` | ลบ (FK เดิม CASCADE แต่เราไม่ลบแถว customers → ลบเอง) |
| `reviews` | คงข้อความ, ชื่อผู้รีวิวแสดงเป็นชื่อ anonymize |
| `orders`, `payments`, `loyalty_transactions` | **คงไว้** (บัญชี/ภาษี: กฎหมายบัญชี/ประมวลรัษฎากรให้เก็บหลักฐาน) — ผูกกับ `customers` ที่ anonymize แล้ว |
| แต้มคงเหลือ | **ตัดเป็น 0** (D2): `adjustment`, `reference_type = 'account_deleted'`; ในทรานแซกชันเดียวกับ anonymize |
| `customer_consents` | คงไว้ (หลักฐาน consent) — ผูก id ที่ anonymize แล้ว |
| ออร์เดอร์ที่ยังไม่จบ | 409 `ACCOUNT_HAS_OPEN_ORDERS` — ยกเลิก/รับของก่อน |

อีเมลเดิมสมัครใหม่ได้หลังลบ (unique เฉพาะ `email IS NOT NULL`).

### 2.6 Error code

| HTTP | code | เมื่อไร |
|---|---|---|
| 422 | `VALIDATION_ERROR` | รูปแบบ body ผิด |
| 422 | `UNDERAGE` | อายุ < 20 ปีเต็ม คำนวณจาก `date_of_birth` กับ **วันที่ปัจจุบันเวลา Asia/Bangkok ที่ server** (เกิด 29 ก.พ. → ครบปีวันที่ 1 มี.ค. ในปีไม่อธิกสุรทิน) |
| 422 | `CONSENT_REQUIRED` | ไม่ยอมรับ terms/privacy, หรือเวอร์ชันที่ส่งไม่ใช่ปัจจุบัน |
| 422 | `WEAK_PASSWORD` | < 12 ตัว / > 72 byte / เท่ากับอีเมล (เหมือนพนักงาน) |
| 403 | `TURNSTILE_FAILED` | token ไม่ผ่าน / ใช้ซ้ำ / hostname หรือ action ไม่ตรง |
| 503 | `TURNSTILE_UNAVAILABLE` | ตรวจกับ Cloudflare ไม่ได้ (fail closed) |
| 429 | `RATE_LIMIT_EXCEEDED` | ต่อ IP หรือต่ออีเมล + `Retry-After` |
| 401 | `INVALID_CREDENTIALS` | อีเมลไม่มี **หรือ** รหัสผิด (ข้อความเดียวกัน) |
| 401 | `UNAUTHORIZED` | ไม่มี/ผิด token, token ผิดฝั่ง (ไม่บอกว่าเป็น token พนักงาน) |
| 401 | `TOKEN_REVOKED`, `REFRESH_TOKEN_MISSING`, `REFRESH_TOKEN_REUSED`; 403 `CSRF_REJECTED` | เหมือน Phase 45 |
| 400 | `EMAIL_TOKEN_INVALID` | ลิงก์ยืนยัน/รีเซ็ตผิด หมดอายุ หรือใช้แล้ว (ข้อความเดียวกันทุกกรณี) |
| 403 | `EMAIL_NOT_VERIFIED` | สั่งซื้อก่อนยืนยันอีเมล |
| 403 | `CONSENT_VERSION_OUTDATED` | terms/privacy มีเวอร์ชันใหม่ที่ยังไม่ยอมรับ |
| 403 | `ACCOUNT_LOCKED` | พนักงานพบว่าอายุไม่ถึง / ผู้ดูแลล็อก (ตอบ**หลัง**รหัสถูกเท่านั้น) |
| 409 | `ACCOUNT_HAS_OPEN_ORDERS` | ลบบัญชีขณะมีออร์เดอร์ค้าง |
| 409 | `POINTS_CHANGED` | ลบบัญชี: `confirm_points_forfeit` ไม่ตรงกับแต้มปัจจุบัน (แต้มเปลี่ยนหลังลูกค้าเห็น) → แสดงใหม่แล้วยืนยันอีกครั้ง |
| 409 | `AGE_VERIFICATION_REQUIRED` | ส่งมอบออร์เดอร์ของบัญชีที่ยังไม่ตรวจบัตร (route ส่งมอบ — phase สั่งซื้อ) |
| 409 | `CUSTOMER_MERGE_NEEDED` | ผูกบัญชีกับลูกค้าหน้าร้านไม่ได้อัตโนมัติ |
| 422 | `PASSWORD_REUSED` | รหัสใหม่เท่ารหัสเดิม |

### 2.7 Turnstile และ rate limit

- **Turnstile** (register / login / forgot / resend-verification): server `POST https://challenges.cloudflare.com/turnstile/v0/siteverify`
  ด้วย `secret`, `response`, `remoteip` (IP จริง ข้อ 5.6); ผ่านเมื่อ `success` **และ** `hostname ∈ CUSTOMER_TURNSTILE_HOSTNAMES`
  (`shop.wayneven.uk`) **และ** `action` ตรงกับ route; timeout 5 วินาที → 503 (fail closed). ตรวจ Turnstile **ก่อน** อย่างอื่นทุกอย่าง.
  staging/test ใช้ test key ของ Cloudflare (ผ่านเสมอ / ไม่ผ่านเสมอ) — ไม่ต้องต่อเน็ตใน integration test (mock).
- **Rate limit ต่อ IP** (slowapi เดิม, key = IP จริง): register 5/ชม., login 20/นาที, forgot 5/ชม., verify-email 30/ชม.
- **Rate limit ต่อบัญชี** (นับใน `customer_auth_events` ตาม `email_hash` — นับเหมือนกันแม้ไม่มีบัญชี):
  login ผิด 5 ครั้ง/15 นาที → 429 15 นาที; อีเมลยืนยัน/รีเซ็ต/account_exists **ไม่เกิน 3 ฉบับ/ชม. และ 10/วัน ต่อที่อยู่**
  (กันใช้ระบบเราส่งอีเมลรบกวนคนอื่น); เกิน → ยังตอบ 202 เหมือนเดิมแต่ไม่ส่ง (ไม่บอกผ่าน response).

---

## 3. บริการส่งอีเมล

ราคาจากแหล่งรวมราคา (ต.ค. 2026) — **ต้องเช็คหน้าราคาทางการอีกครั้งก่อนสมัคร**.

| | Amazon SES (ap-southeast-1 สิงคโปร์) | Resend | Cloudflare Email Service |
|---|---|---|---|
| ราคา | ~$0.10 / 1,000 ฉบับ (บัญชีใหม่อาจเริ่มที่แผน Essentials ~$0.16/1,000; เปลี่ยนเป็น à la carte ได้); ฟรี 3,000/เดือน ใน 12 เดือนแรก | ฟรี 3,000/เดือน **แต่ไม่เกิน 100/วัน** (เกิน = ส่งไม่ออก); Pro $20/เดือน 50,000 ฉบับ | ต้องมี Workers Paid $5/เดือน (รวม 3,000 ฉบับ) แล้ว ~$0.35/1,000 |
| ปริมาณที่คาด (ยืนยัน+รีเซ็ต < 3,000/เดือน) | ≈ $0 – $0.5/เดือน | $0 (ถ้าไม่เกิน 100/วัน) – $20 | $5/เดือน |
| ตั้งค่า DNS บน wayneven.uk (Cloudflare) | DKIM: 3 CNAME `<token>._domainkey` (**DNS only**, ห้ามเปิด proxy); custom MAIL FROM `mail.wayneven.uk`: MX + TXT `v=spf1 include:amazonses.com ~all`; DMARC TXT `_dmarc` | DKIM TXT `resend._domainkey`; MX + SPF TXT บน subdomain ส่ง (`send.wayneven.uk`); DMARC | ตั้งให้อัตโนมัติ (DNS อยู่ Cloudflare อยู่แล้ว) |
| ความยาก | ปานกลาง: บัญชี AWS + IAM user ที่ส่งได้อย่างเดียว, ยืนยันโดเมน, **ขอออกจาก sandbox** (กรอกฟอร์ม ~1 วัน; ระหว่างนั้นส่งได้เฉพาะอีเมลที่ยืนยันแล้ว 200/วัน) | ง่าย: API key + 2–3 DNS record | ง่ายสุดถ้าใช้ Workers; จาก Python ต้องผ่าน REST API |
| ความเสี่ยง | ต้องดูแล bounce/complaint ไม่ให้เกินเกณฑ์ (มี suppression list ระดับบัญชีให้) | free tier จำกัดรายวัน — วันเปิดตัวสมัคร > 100 คน = อีเมลยืนยันตกหล่น | **public beta ตั้งแต่ เม.ย. 2026**: ราคา/ข้อจำกัดอาจเปลี่ยน (เช่น 50 ผู้รับ/ฉบับ) |

**แนะนำ: Amazon SES (ap-southeast-1)** — ถูกที่สุดในทุกปริมาณ ไม่มีเพดานรายวัน ใช้มานานและ deliverability ดี; ความยากเป็นงานตั้งค่าครั้งเดียว.
โค้ดเขียนผ่าน interface `EmailSender` (SES / Resend / console-for-staging) + `email_outbox` → เปลี่ยน provider ได้ด้วย env.
**สำรอง (D4):** Resend — ใช้เมื่อ AWS ไม่ให้ออกจาก sandbox หรือ SES มีปัญหา (แผน Pro ถ้าเกิน 100/วัน); สลับด้วย `EMAIL_PROVIDER=resend`
แล้ว restart worker — แถว `pending`/`failed` ใน `email_outbox` ส่งต่อด้วย provider ใหม่โดยไม่ต้องแก้อะไร. ไม่มีอีเมลการตลาด (D1).

DNS ที่ต้องเพิ่มเพราะ wayneven.uk ยังไม่มีอะไรเลย (ทำครั้งเดียว ใน Cloudflare):
1. DKIM 3 CNAME จาก SES (DNS only)
2. `mail.wayneven.uk` MX `10 feedback-smtp.ap-southeast-1.amazonses.com` + TXT `v=spf1 include:amazonses.com ~all`
3. `_dmarc.wayneven.uk` TXT `v=DMARC1; p=none; rua=mailto:<กล่องของเจ้าของ>` → ดูรายงาน 2–4 สัปดาห์ → `p=quarantine`
4. (ถ้าโดเมนหลักไม่ส่งอีเมลเลย) `wayneven.uk` TXT `v=spf1 -all` ได้ เพราะ SES ใช้ MAIL FROM ของ subdomain

ผู้ส่ง: `no-reply@wayneven.uk` (ไม่รับตอบ — ใส่ช่องทางติดต่อร้านในเนื้อหา). Gmail/Yahoo บังคับ SPF+DKIM+DMARC กับผู้ส่งจำนวนมากแล้ว:
ทำครบตั้งแต่แรก. secret ของ SES อยู่ `/etc/bottleclub/secrets.env` (`AWS_SES_ACCESS_KEY_ID/SECRET`) — IAM policy `ses:SendEmail` เฉพาะ identity `wayneven.uk`.

---

## 4. โหมด cookie ของลูกค้า (shop.wayneven.uk)

**ใช้กลไก Phase 45 ได้** (shop.wayneven.uk กับ api.wayneven.uk เป็น same-site; `SameSite=Strict` + ตรวจ `Origin` + `X-Auth-Mode: cookie`
+ rotation + family + cookie ต่อ origin) — แต่**แยกทุกชิ้นจากของพนักงาน**:

| | พนักงาน (Phase 45) | ลูกค้า |
|---|---|---|
| ชื่อ cookie | `__Host-bc_refresh_<id>` | **`__Host-bc_cust_refresh_<id>`** (prefix ต่างกัน → ไม่มีทางอ่านสลับกัน) |
| ตาราง | `refresh_tokens` | `customer_refresh_tokens` |
| รายการ origin | `AUTH_COOKIE_ORIGINS` (pos, admin) | **`CUSTOMER_AUTH_COOKIE_ORIGINS`** (`https://shop.wayneven.uk`) — ต้องอยู่ใน `CORS_ORIGINS`; **ห้ามซ้ำกับ** `AUTH_COOKIE_ORIGINS` (API ไม่ start) |
| route | `/auth/refresh`, `/auth/logout` | `/customer/auth/refresh`, `/customer/auth/logout` |
| อายุ refresh | 7 วัน | เสนอ 30 วัน (`CUSTOMER_REFRESH_TOKEN_EXPIRE_DAYS`) |

ข้อสังเกต:
- `__Host-` บังคับ `Path=/` → browser ส่ง cookie ลูกค้าไปกับทุก request ไป api.wayneven.uk (รวม route พนักงาน) — **ไม่มีผล** เพราะ route พนักงานไม่อ่านชื่อนี้ (และ token ลูกค้า access ใช้กับพนักงานไม่ได้อยู่แล้ว).
- refactor `app/domains/auth/cookie.py` ให้รับ "ชุดค่า" (prefix, origins) แทนค่าคงที่ — ใช้ร่วมสองฝั่ง, test ของพนักงานต้องผ่านเหมือนเดิม.
- ลูกค้าเปิดหลายแท็บ/มือถือเน็ตหลุดบ่อยกว่าพนักงาน → **ช่วงผ่อนผัน refresh ซ้อนทำใน 48a (D3)**: token ที่ถูก rotate ไปไม่เกิน
  `REFRESH_REUSE_GRACE_SECONDS` (เสนอ 10 วินาที) แล้วถูกใช้อีกครั้ง → ตอบ token ตัวถัดไปของสายเดิม (ไม่ revoke family);
  ต้องเพิ่ม `rotated_at` + `replaced_by_id` ใน `customer_refresh_tokens` (และ migration เดียวกันเพิ่มใน `refresh_tokens` ของพนักงาน).
  เกินช่วงนั้น = reuse ตาม Phase 45.
- local dev ของทีม shop: `http://localhost:<port>` ได้ cookie `bc_cust_refresh_<id>` แบบ Phase 45.

---

## 5. ความเสี่ยง

| # | ความเสี่ยง | ระดับ | ทางลด |
|---|---|---|---|
| 5.1 | **กฎหมาย: ห้ามขายเครื่องดื่มแอลกอฮอล์ทางอิเล็กทรอนิกส์** (ประกาศสำนักนายกฯ 2563, โทษจำคุก ≤ 6 เดือน/ปรับ ≤ 10,000 บาท; ยกเว้นซื้อขาย**และชำระเงินที่ร้าน**); และ **ม.32 พ.ร.บ.ควบคุมเครื่องดื่มแอลกอฮอล์** (โฆษณา) — อีเมลการตลาดเรื่องสินค้าแอลกอฮอล์อาจผิดแม้ลูกค้ายินยอม | **สูง** | ให้ที่ปรึกษากฎหมายยืนยันก่อน phase สั่งซื้อ. บัญชีลูกค้า (48a–b) ทำได้โดยไม่ขายออนไลน์: ดูแต้ม, ประวัติ, จองแล้ว**จ่ายและรับที่ร้าน**. **ไม่มีอีเมล/consent การตลาด (D1)**; เนื้อหาอีเมลระบบห้ามมีสินค้า/โปรโมชัน |
| 5.2 | PDPA: วันเกิด/เบอร์/อีเมลเป็นข้อมูลส่วนบุคคล — ต้องมีประกาศความเป็นส่วนตัว, ขอบเขตการใช้, ระยะเก็บ, สิทธิ์เข้าถึง/ลบ/โอนย้าย, แจ้งเหตุรั่วไหลภายใน 72 ชม. | สูง | consent แยก + เวอร์ชัน (ข้อ 1.2), export/ลบ (48b), ไม่เก็บเลข/รูปบัตร, log ไม่มี PII (เหมือนกฎ slip PII เดิม), backup ที่มีข้อมูลลูกค้าต้องเข้ารหัส |
| 5.3 | ยึดแต้ม/บัญชีลูกค้าหน้าร้านด้วยการกรอกเบอร์คนอื่น | สูง | ไม่ผูกด้วยเบอร์อัตโนมัติ — ผูกที่เคาน์เตอร์หลังตรวจบัตร (ข้อ 1.3) |
| 5.4 | token สลับฝั่ง: jose ยอม token ที่ไม่มี `aud` เมื่อส่ง `audience=` | สูง | key แยก + `require_aud` + `type` + test สองทิศ (ข้อ 2.1) |
| 5.5 | รู้ว่าอีเมลไหนมีบัญชี (enumeration) จากข้อความ/เวลาตอบ/rate limit | กลาง | ตอบ 202 ข้อความเดียว, hash รหัสทั้งสองทาง, ส่งอีเมลผ่าน outbox, นับ limit ตาม `email_hash` เหมือนกันทุกอีเมล |
| 5.6 | IP จริงหลัง Cloudflare Tunnel. **ตรวจแล้ว 2026-10-30** (โค้ด + journal 14 วัน): uvicorn 0.30.6 `--proxy-headers --forwarded-allow-ips 127.0.0.1` แทน IP ด้วย X-Forwarded-For ตัวขวาสุดที่ไม่ใช่ 127.0.0.1; request ผ่าน tunnel ทั้ง 228 มี XFF (port `:0`) เป็น IP สาธารณะจริง, ไม่มี `127.0.0.1:0` เลย → **ปัจจุบันไม่ได้นับเป็น IP เดียว**. ที่เหลือ: พึ่งรูปแบบ XFF ของ Cloudflare, process ใดก็ได้บนเครื่องปลอม XFF ได้, ไม่มี test ล็อกพฤติกรรม | กลาง | **Phase 48-0** (ข้อ 6) |
| 5.7 | อีเมลเข้า spam (โดเมนยังไม่มี SPF/DMARC) | กลาง | ข้อ 3: DKIM+SPF+DMARC ก่อนเปิด, เริ่ม `p=none` |
| 5.8 | วันเกิดที่กรอกเป็นแค่คำแถลง | กลาง | ตัวควบคุมจริง = ตรวจบัตรตอนรับของ; route ส่งมอบตอบ 409 `AGE_VERIFICATION_REQUIRED` ถ้ายังไม่ตรวจ (พนักงานข้ามไม่ได้) |
| 5.9 | บัญชีลักษณะลูกค้าในตาราง `users` ของพนักงานจาก Google login เดิม | กลาง | ตรวจจำนวนใน prod (SQL ข้างล่าง); 48c ย้ายไป `customer_identities` แล้วปิด path เดิม |
| 5.10 | Turnstile ล่ม → สมัคร/login ไม่ได้ (fail closed) | ต่ำ | ข้อความชัดเจน; ทางเลือก: login ยอม fail-open เฉพาะเมื่อไม่มี failed login ล่าสุดของอีเมลนั้น (ตัดสินใจภายหลัง) |
| 5.11 | ลบบัญชี vs หนี้แต้ม/หลักฐานบัญชี | ต่ำ | **ตัดสินแล้ว (D2)**: คงออร์เดอร์, แต้มเป็น 0 หลังลูกค้าเห็นยอดและยืนยัน, ledger `account_deleted` |
| 5.12 | worker อีเมลอีกตัวบน laptop prod | ต่ำ | systemd service แยก, Restart=on-failure, ดู `email_outbox.status = failed` ใน check ประจำวัน |

SQL ตรวจ prod: **`scripts/prod_checks/google_staff_accounts.sql`** (อ่านอย่างเดียว, `bottleclub_ro` + GRANT ระดับคอลัมน์ที่ไม่ใช่ข้อมูลส่วนตัว — คำสั่ง GRANT อยู่หัวไฟล์; แสดงแค่จำนวน).

---

## 6. แบ่ง phase ย่อย (48-0 + 3)

| phase | ขอบเขต | ส่งมอบ / เงื่อนไขเริ่ม |
|---|---|---|
| **48-0 — IP จริงสำหรับ rate limit (ก่อน 48a, D5)** | key ของ limiter (และ `login_attempts.ip_address`) = `CF-Connecting-IP` **เฉพาะเมื่อ peer = 127.0.0.1** (cloudflared) และค่าเป็น IP ที่ถูกรูปแบบ; ไม่งั้น `request.client.host` (ผลของ uvicorn เดิม). test: peer ภายนอกส่ง `CF-Connecting-IP` ปลอม → ไม่เชื่อ; 2 IP ผ่าน tunnel → bucket แยก; ไม่มี header → พฤติกรรมเดิม | เล็ก ไม่มี migration; ฐานเดียวกับที่ลูกค้า (48a) จะใช้ |
| **48a — บัญชีและการเข้าสู่ระบบ** | migration 022 (ทุกตารางข้อ 1.2), key/claim แยก + test สองทิศ, register / verify-email / resend / login / refresh / logout / forgot / reset, consent (terms+privacy; ไม่มี marketing: D1), Turnstile, rate limit ต่อ IP (IP จริงหลัง tunnel) + ต่ออีเมล, `email_outbox` + worker + SES (สำรอง Resend; staging: console sender), cookie โหมดลูกค้า + **ช่วงผ่อนผัน refresh ซ้อน (D3, ทั้งลูกค้าและพนักงาน)** | เริ่มได้เมื่อ: เจ้าของสมัคร AWS SES + DNS (ข้อ 3), ได้ Turnstile site/secret key, ร่าง terms/privacy เวอร์ชันแรก. env ใหม่: `CUSTOMER_JWT_SECRET_KEY`, `CUSTOMER_AUTH_COOKIE_ORIGINS`, `CUSTOMER_TURNSTILE_SECRET_KEY`, `CUSTOMER_TURNSTILE_HOSTNAMES`, `EMAIL_PROVIDER`, `AWS_SES_*`, `CUSTOMER_EMAIL_PEPPER` |
| **48b — โปรไฟล์, PDPA, ฝั่งเคาน์เตอร์** | `/customer/me*` (แก้ไข, เปลี่ยนรหัส/อีเมล, consent, export, **ลบ/anonymize**), ฝั่งพนักงาน: ค้นบัญชี, **ยืนยันอายุ** (`customers.verify_age`), **ผูกกับลูกค้าหน้าร้าน**; FRONTEND_GUIDE สำหรับ shop + POS | หลัง 48a |
| **48c — Google / LINE** | `customer_identities` ใช้จริง: login/ผูก Google และ LINE เข้าบัญชีเดิม (ผูกเฉพาะตอน login อยู่), ย้ายบัญชี role-less เดิมออกจาก `users`, ปิด `GET /auth/google*` ฝั่งพนักงาน + ลบ `POST /auth/register` | หลัง 48b; ผล SQL ข้อ 5.9 |

**นอก Phase 48** (phase สั่งซื้อ หลังกฎหมายยืนยันข้อ 5.1): route สร้างออร์เดอร์ของลูกค้า (`orders.user_id` NULL ได้เมื่อ
`order_source <> 'pos'` + CHECK), ตรวจ `EMAIL_NOT_VERIFIED` / `CONSENT_VERSION_OUTDATED`, ส่งมอบที่ร้านพร้อม `AGE_VERIFICATION_REQUIRED`.

## แหล่งอ้างอิง (ราคาและกฎหมาย; ตรวจซ้ำกับหน้าทางการก่อนใช้)

- Amazon SES: [campaignhq](https://blog.campaignhq.co/amazon-ses-pricing-2026/), [mailblast](https://www.mailblast.io/blog/ses/amazon-ses-pricing), [saaspricepulse](https://www.saaspricepulse.com/tools/amazon-ses)
- Resend: [sendfox](https://sendfox.com/compare/resend-pricing), [transactionalemailservices](https://www.transactionalemailservices.com/pricing/resend), [superdupr](https://superdupr.com/blog/resend-pricing)
- Cloudflare Email Service: [flowmails](https://flowmails.net/blog/cloudflare-workers-email-cost), [sequenzy](https://www.sequenzy.com/versus/cloudflare-email-vs-amazon-ses)
- Postmark (ไม่เข้ารอบ: แพงกว่าในปริมาณนี้, ~$15/เดือน 10,000 ฉบับ): [saaspricepulse](https://www.saaspricepulse.com/tools/postmark)
- ประกาศห้ามขายเครื่องดื่มแอลกอฮอล์ทางอิเล็กทรอนิกส์ 2563: [ประกาศ (กรมควบคุมโรค)](https://ddc.moph.go.th/uploads/files/12120210405134539.PDF), [The Standard](https://thestandard.co/announcement-of-a-ban-on-online-alcohol-beer-sales-for-the-next-90-days/), [กรุงเทพธุรกิจ](https://www.bangkokbiznews.com/news/detail/911027)
