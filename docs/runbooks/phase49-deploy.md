# Phase 49: runbook สำหรับ deploy (storefront: track, LINE Login, service keys)

สถานะ: ร่างสำหรับรอบอนุมัติ merge (2026-11-21) ยังไม่ได้ทำขั้นใดเลย
- ฐาน: `main` = v0.1.23 (`4f5f96271a4d`) ซึ่ง production ใช้อยู่
- branch: `feature/storefront-integration`
- tag ที่เสนอ: **v0.1.24**

เจ้าของเป็นคนรันทุกคำสั่งในเอกสารนี้ใน terminal ของตัวเอง (`sudo` และ `[y/N]` ต้องมี TTY)
- ห้าม echo, วาง หรือส่ง secret เป็น argument
- ห้าม push ขึ้น GitHub

ลำดับ: **merge → tag → staging :8100 → ทดสอบ LINE ด้วย channel จริงบน staging → production**
ทำทีละขั้น ถ้าขั้นไหนตรวจไม่ผ่าน ให้หยุดแล้วทำ "ย้อนกลับ" ของขั้นนั้น

## 0. ต้องรู้ก่อนเริ่ม

| เรื่อง | รายละเอียด |
|---|---|
| Migration | `022` orders.shipping_carrier → `023` customer_accounts / customer_identities / auth_exchange_codes → `024` service_keys → `025` revoke key ที่มี `customers.read` · apply ก่อน code ทุกครั้ง |
| **025 ย้อนไม่ได้** | key ที่ถูก revoke (`revoked_at`) จะไม่กลับมาใช้ได้ rollback ของ 025 ลบแค่แถว `schema_migrations` ต้องสร้าง key ใหม่เท่านั้น |
| **023 ย้อนไม่ได้เมื่อมีบัญชีลูกค้า** | rollback ของ 023 ปฏิเสธเองทันทีที่ `customer_accounts` มีแถวแรก (ลูกค้า LINE คนแรก) หลังจากนั้นถ้าจะย้อน schema **ต้อง restore จาก backup (ข้อ 4.1) เท่านั้น** ซึ่งจะเสียทุกอย่างที่เขียนหลัง backup (ออเดอร์ การชำระเงิน แต้ม) ทางที่ควรใช้คือย้อนเฉพาะ code (ข้อ 4.8) แล้วเก็บ schema ไว้ |
| code เก่ากับ schema ใหม่ | v0.1.23 ไม่อ่านตารางใหม่ ส่วน `orders.shipping_carrier` เป็นคอลัมน์ nullable ไม่มี default ทำให้ INSERT ของ v0.1.23 ยังทำงาน **ข้อนี้มาจากการอ่านโค้ด ยังไม่ได้รันจริง** |
| Firewall | ufw default deny ขาเข้า เปิด 22/tcp, OpenSSH, 51820/udp API ฟังที่ 127.0.0.1:8000 และเข้ามาได้ทาง cloudflared เท่านั้น |
| test ของรอบนี้ | ทำแล้วบน `14/phase22test`: unit 582 (main 538), integration 971 (main 849) migration และขั้น DB ของ runbook นี้ซ้อมด้วย `scripts/ops/prod_db.sh` แล้ว ผลอยู่ที่ `~/p49-staging/rehearse_prod_db.log` |

Script ที่ใช้ (อยู่ใน repo):
- `scripts/ops/prod_db.sh`: `backup <label>`, `apply <file.sql>`, `check <file.sql>`
  - ทำงานในชื่อ `bottleclub_owner` โดยอ่าน `OWNER_PSQL_URL` จาก `/etc/bottleclub/owner.env`
  - ไม่แสดง URL หรือรหัสผ่าน
  - ทำงานกับ `127.0.0.1:5433/bottleclub_prod` เท่านั้น ถ้า `OWNER_PSQL_URL` ใช้ host `localhost` จะได้ `refused: target …` ให้หยุดแล้วแจ้ง อย่าแก้ guard ของ script
- `scripts/ops/phase49_grants.sql`: GRANT ให้ `bottleclub_api` แล้วตรวจว่าได้สิทธิ์ครบ
- `scripts/prod_checks/customer_duplicates.sql`: นับลูกค้าที่ email หรือ phone ซ้ำ ไม่แสดงค่า

## 1. Merge และ tag (repo หลัก `~/api_bottleclub`)

```bash
cd ~/api_bottleclub
git status --short                    # ต้องว่าง
git switch main && git log --oneline -1   # 4f5f962
git merge --no-ff feature/storefront-integration -m "Merge branch 'feature/storefront-integration' (Phase 49): ..."
# test บนต้นทางที่ merge แล้ว (cluster ทดสอบต้อง active: systemctl status postgresql@14-phase22test)
~/p49-staging/run_unit.sh ~/api_bottleclub        # ห้ามมี .env ใน repo (script ปฏิเสธเอง)
~/p49-staging/run_integration.sh ~/api_bottleclub
git tag -a v0.1.24 -m "v0.1.24: Phase 49 storefront (022-025)"
git rev-parse --short=12 v0.1.24      # = <sha12> ที่ใช้ในข้อ 3–4
```

**ตรวจ:** test ผ่านทั้งหมด และ `git log --oneline main -1` เป็น commit merge

**ย้อนกลับ** (ไม่มีอะไรออกนอกเครื่อง):
- ก่อนสร้าง tag: `git reset --hard ORIG_HEAD`
- หลังสร้าง tag แต่ยังไม่ deploy: `git tag -d v0.1.24 && git reset --hard 4f5f962`
- หลัง deploy แล้ว: ห้ามแก้ history ให้ใช้ `git revert -m 1 <merge>` แล้วออก tag ใหม่

## 2. Staging :8100 (แจ้งทีม frontend ก่อน เพราะข้อมูลของทีมจะถูก reset)

staging ใช้ release ของตัวเองใน `~/staging/releases` และห้ามใช้อะไรใต้ `/opt` (ดู `~/staging/README.md`)
requirements.txt ไม่เปลี่ยนตั้งแต่ v0.1.17 จึงใช้ไฟล์ freeze ของ prod ตัวเดิมได้

```bash
TAG=v0.1.24; SHA=$(git -C ~/api_bottleclub rev-parse --short=12 $TAG)
R=~/staging/releases/$SHA
mkdir "$R" && git -C ~/api_bottleclub archive $TAG | tar -x -C "$R"
python3 -m venv "$R/.venv" && "$R/.venv/bin/pip" install -q -r ~/staging/releases/prod-a76c4ef4388b.freeze.txt
cp ~/staging/release.sh ~/staging/release.sh.bak-v0123
sed -i "s|^STAGING_RELEASE=.*|STAGING_RELEASE=\$HOME/staging/releases/$SHA|" ~/staging/release.sh
```

**Secret ของ staging** (ไฟล์ 600 ใน `~/staging/secrets/` ห้าม echo):
```bash
cd ~/staging/secrets && umask 077
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > customer_jwt_key   # ห้ามเท่ากับ JWT_SECRET_KEY
read -rs -p "LINE channel secret (staging channel): " S && printf '%s\n' "$S" > line_client_secret; unset S; echo
```

**Env ที่เพิ่มใน `~/staging/start_api.sh`** (ใน `env -i ...` ต่อจาก `AUTH_COOKIE_ORIGINS`):

| Env | ค่าบน staging |
|---|---|
| `FRONTEND_URLS` | URL ของหน้าที่รับ `?code=` บนเว็บ storefront ที่ใช้ทดสอบ เช่น `http://localhost:3000/auth/line/done` (ต้องตรงทุกตัวอักษร คั่นหลายค่าด้วยจุลภาค) |
| `LINE_CLIENT_ID` | Channel ID ของ channel ที่ใช้ทดสอบ |
| `LINE_CLIENT_SECRET` | `"$(cat $HOME/staging/secrets/line_client_secret)"` |
| `LINE_REDIRECT_URI` | `http://localhost:8100/api/v1/auth/line/callback` (ดูหมายเหตุด้านล่าง) |
| `LINE_DEFAULT_ORGANIZATION_ID` | ว่างไว้ = องค์กร active เดียวของ staging |
| `CUSTOMER_JWT_SECRET_KEY` | `"$(cat $HOME/staging/secrets/customer_jwt_key)"` |
| `CLOUDFLARE_IP_RANGES(_FILE)`, `RATE_LIMIT_*` ใหม่ | ไม่ต้องตั้ง (ใช้ค่าเริ่มต้น) |

ใช้งาน:
```bash
cp ~/staging/start_api.sh ~/staging/start_api.sh.bak-v0123     # ก่อนแก้
~/staging/reset_staging.sh         # create_all + 001–019 และ apply 020–025 ด้วย apply_sql.py (ข้าม .rollback.sql)
systemctl --user restart bottleclub-staging-api
```

**ตรวจ staging** (ชุดสั้น ทุกข้อต้องได้ตามที่เขียน):
```bash
B=http://127.0.0.1:8100/api/v1; J='Content-Type: application/json'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8100/health                                        # 200
curl -s -o /dev/null -w '%{http_code}\n' -H "$J" -d '{"ref":"ORD-NONE","contact":"0899999999"}' $B/orders/track   # 404
curl -s -o /dev/null -w '%{http_code}\n' -H "$J" -d '{"phone":"0812345678"}' $B/customers/lookup                 # 401
curl -s -o /dev/null -w '%{http_code}\n' $B/customer/me                                                      # 401
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "$B/auth/line?return_to=<FRONTEND_URLS>" | cut -c1-60  # 302 https://access.line.me/...
. ~/staging/release.sh; $STAGING_VENV/bin/python -I ~/staging/check_staging.py
```

Service key ให้ทีม frontend (บน staging เท่านั้น):
```bash
. ~/staging/release.sh && . ~/staging/guard_env.sh && cd "$STAGING_RELEASE" && umask 077 && \
env -i PATH=/usr/bin:/bin ENVIRONMENT=development DATABASE_URL="$STAGING_DATABASE_URL" \
  RABBITMQ_URL=amqp://none:none@127.0.0.1:1/ MONGODB_URI=mongodb://127.0.0.1:1/ \
  "$STAGING_VENV/bin/python" -m scripts.service_keys create --name storefront-staging --org-id <org ของ staging> \
  --scope customers.lookup --scope customers.create --scope loyalty.read --out ~/staging/secrets/storefront_service_key
```
(`ENVIRONMENT=development` เพราะ CLI แค่เขียนแถว ส่วน `staging` ต้องมี JWT_SECRET_KEY) ส่งให้ทีมทางช่องทางที่ปลอดภัย ให้ทีมเก็บไว้ใน env ฝั่ง server ของ Next.js เท่านั้น (ไม่ใช่ `NEXT_PUBLIC_*`) และห้ามใส่ใน `~/frontend-handoff`

**ทดสอบ LINE ด้วย channel จริง:**
1. ใน LINE Developers Console ให้ใส่ Callback URL = `LINE_REDIRECT_URI` ข้างบน **ถ้า Console ไม่รับ `http://localhost`** (เอกสาร LINE บอกแค่ว่าแนะนำ HTTPS ไม่ได้บอกชัดว่า localhost ใช้ได้หรือไม่) ให้หยุด ตัวเลือกที่เหลือคือ hostname https สำหรับ staging ผ่าน cloudflared แต่จะทำให้ staging ออกสู่สาธารณะ เจ้าของต้องตัดสินใจก่อน
2. ใช้ browser บนเครื่องนี้ หรือผ่าน SSH tunnel ให้ `localhost:8100` และหน้าเว็บ storefront ชี้มาที่เครื่องนี้ แล้วกดปุ่ม LINE ต้องเห็นตามลำดับ:
   - LINE แสดงหน้าขอสิทธิ์ (profile, openid, email)
   - browser กลับมาที่ `FRONTEND_URLS?code=…`
   - `POST /auth/exchange` ได้ 200
   - `GET /customer/me` ได้ชื่อจริงจาก LINE
3. ตรวจอีเมล: ถ้ายังไม่ได้รับอนุมัติสิทธิ์ Email, `email` ต้องเป็น `null` (ไม่ใช่อีเมลปลอม)
4. กดซ้ำด้วยบัญชี LINE เดิม ต้องได้ลูกค้าคนเดิม (`customer_id` เดิม)
5. กดยกเลิกที่หน้า LINE ต้องกลับมาที่ `?error=line_login_cancelled`

**ย้อนกลับ staging:**
```bash
cp ~/staging/release.sh.bak-v0123 ~/staging/release.sh && cp ~/staging/start_api.sh.bak-v0123 ~/staging/start_api.sh
~/staging/reset_staging.sh && systemctl --user restart bottleclub-staging-api   # สร้าง DB ใหม่จาก v0.1.23 (ข้อมูลตัวอย่าง)
```

## 3. Env ของ production (ตั้งก่อน deploy ใน ข้อ 4.6)

| Env | ไฟล์ | ค่า |
|---|---|---|
| `FRONTEND_URLS` | `/etc/bottleclub/api.env` | URL https ของหน้าที่รับ `?code=` บน storefront จริง ทีม frontend เป็นคนกำหนด path ห้ามมี query, `#` หรือ `*` |
| `LINE_CLIENT_ID` | `api.env` | Channel ID ของ channel production |
| `LINE_REDIRECT_URI` | `api.env` | `https://api.wayneven.uk/api/v1/auth/line/callback` (ใส่ค่าเดียวกันใน Console) |
| `LINE_DEFAULT_ORGANIZATION_ID` | `api.env` | ว่างไว้ = องค์กร active เดียว |
| `LINE_CLIENT_SECRET` | `/etc/bottleclub/secrets.env` | จาก LINE Console |
| `CUSTOMER_JWT_SECRET_KEY` | `secrets.env` | random ≥ 32 ตัว ห้ามเท่ากับ `JWT_SECRET_KEY` ไม่อย่างนั้น API ไม่ start |
| `RATE_LIMIT_*` ใหม่, `CLOUDFLARE_IP_RANGES(_FILE)`, `TRUSTED_PROXY_IPS` | ไม่ต้องตั้ง | production ผ่าน tunnel จึงใช้ `TRUSTED_PROXY_IPS` ค่าเดิม (127.0.0.1,::1) |

ถ้ายังไม่ตั้ง LINE ครบ API ก็ยัง start ได้ โดย `/auth/line` จะตอบ 400 `LINE_NOT_CONFIGURED` ห้ามตั้ง `GOOGLE_*` จนกว่าจะถึง 48c

```bash
sudo cp /etc/bottleclub/api.env /etc/bottleclub/api.env.bak-v0123
sudoedit /etc/bottleclub/api.env          # เพิ่ม 4 บรรทัดแรกของตาราง (ไม่มี quote) แล้วคัดลอกไป ~/bottleclub-prod/api.env
sudo bash -c 'set -euo pipefail; umask 077; f=/etc/bottleclub/secrets.env; cp -p $f $f.bak-v0123
  grep -q "^CUSTOMER_JWT_SECRET_KEY=" $f || printf "CUSTOMER_JWT_SECRET_KEY=%s\n" "$(openssl rand -hex 32)" >> $f
  grep -q "^LINE_CLIENT_SECRET=" $f || { read -rs -p "LINE channel secret (production): " S; echo; printf "LINE_CLIENT_SECRET=%s\n" "$S" >> $f; }'
```

## 4. Production

ทำจาก `~/api_bottleclub` ที่ main = v0.1.24 แล้ว ทุกคำสั่ง `prod_db.sh` ทำงานในชื่อ `bottleclub_owner` ซึ่ง default privileges ของ role นี้ GRANT ตารางใหม่ให้ `bottleclub_api` อยู่แล้ว ข้อ 4.5 ทำซ้ำแบบระบุชัดแล้วตรวจอีกครั้ง

### 4.1 Backup ก่อน migration (ห้ามข้ามขั้นนี้)
```bash
cd ~/api_bottleclub
sudo scripts/ops/prod_db.sh backup pre-phase49
#   prod_db: OK /var/backups/bottleclub/pg/bottleclub_prod-pre-phase49-<stamp>.dump <size>; entries: N, table data: M
sudo /usr/lib/postgresql/16/bin/pg_restore --list /var/backups/bottleclub/pg/bottleclub_prod-pre-phase49-*.dump | grep -c 'TABLE DATA'   # = M
sudo systemctl start bottleclub-backup.service && journalctl -u bottleclub-backup -n 5 --no-pager   # สำเนา off-site (B2) อีกชุด
```
- ไฟล์ dump อยู่นอก repo (`/var/backups/bottleclub/pg`, 0700/0600) และจะเก็บไว้จนกว่าจะเลิกใช้ rollback ของ Phase 49
- `prod_db.sh` เก็บไฟล์ไว้เฉพาะเมื่อ `pg_restore --list` อ่านได้ และใน dump มีข้อมูล `schema_migrations`
- **ตรวจ:** ต้องเห็นบรรทัด `OK` และตัวเลข `table data` สองครั้งต้องตรงกัน ถ้าไม่ตรงให้หยุด

### 4.2 ตรวจข้อมูลซ้ำ (เพื่อทราบ ไม่ได้บล็อกการ deploy)
```bash
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -X -v ON_ERROR_STOP=1 \
  < ~/api_bottleclub/scripts/prod_checks/customer_duplicates.sql
```
ถ้ามีลูกค้าซ้ำ `POST /customers/lookup` จะตอบ 409 `CUSTOMER_AMBIGUOUS` สำหรับคนเหล่านั้น ให้รวมข้อมูลด้วยมือก่อนเปิด storefront

### 4.3 เตรียม release (ยังไม่สลับ)
```bash
sudo bottleclub-deploy v0.1.24 --prepare-only     # git archive + .venv + unit test ของ release
```

### 4.4 Migration 022 → 025 (ก่อน code ทุกครั้ง)
```bash
M=/opt/bottleclub/releases/<sha12>/migrations
for m in 022_order_shipping_carrier 023_customer_line_login 024_service_keys 025_service_key_scope_lookup; do
  sudo ~/api_bottleclub/scripts/ops/prod_db.sh apply $M/$m.sql || break; done
# NOTICE ที่ต้องเห็น: "022: orders.shipping_carrier", "023: customer_accounts, ...", "024: service_keys",
#                     "025: 0 service key(s) with customers.read revoked"
```
แต่ละไฟล์อยู่ใน transaction ของตัวเอง ถ้าไฟล์ไหน error ไฟล์นั้นจะไม่มีผลอะไร และ loop จะหยุดทันที

### 4.5 GRANT และตรวจสิทธิ์ของ `bottleclub_api`
```bash
sudo ~/api_bottleclub/scripts/ops/prod_db.sh apply ~/api_bottleclub/scripts/ops/phase49_grants.sql
# ต้องจบด้วย "phase49_grants: OK, every privilege held" (ถ้ามี false สักบรรทัด จะ ERROR และหยุด)
```
คำสั่งที่ไฟล์นี้รัน (idempotent):
```sql
GRANT SELECT, INSERT, UPDATE, DELETE
    ON customer_accounts, customer_identities, auth_exchange_codes, service_keys TO bottleclub_api;
GRANT USAGE, SELECT
    ON SEQUENCE customer_accounts_id_seq, customer_identities_id_seq, auth_exchange_codes_id_seq,
                service_keys_id_seq TO bottleclub_api;
```

### 4.6 Deploy code
ตั้ง env ตามข้อ 3 ก่อน แล้วรัน:
```bash
sudo bottleclub-deploy v0.1.24
```
- tool จะต้องแสดงว่า "every migration in this release is recorded" ก่อนถาม `[y/N]`
- ถ้า health หรือ DB probe ไม่ผ่าน tool จะสลับกลับ release เดิมเอง

### 4.7 ตรวจว่า deploy สำเร็จ (ชุดสั้น)
```bash
B=http://127.0.0.1:8000/api/v1; J='Content-Type: application/json'
curl -s -w ' %{http_code}\n' http://127.0.0.1:8000/health                                                # {"status":"healthy"} 200
curl -s -o /dev/null -w '%{http_code}\n' -H "$J" -d '{"ref":"ORD-NONE","contact":"0899999999"}' $B/orders/track  # 404
curl -s -o /dev/null -w '%{http_code}\n' -H "$J" -d '{"phone":"0812345678"}' $B/customers/lookup               # 401
curl -s -o /dev/null -w '%{http_code}\n' $B/customer/me                                                    # 401
curl -s -o /dev/null -w '%{http_code}\n' "$B/auth/line?return_to=<FRONTEND_URLS>"                        # 302 (400 ถ้า LINE ยังไม่ตั้ง)
curl -s -o /dev/null -w '%{http_code}\n' https://api.wayneven.uk/health                                    # 200 ผ่าน Cloudflare
~/bottleclub-prod/check_client_ip.sh                                                                       # IP จริงยังใช้ได้หลัง restart
journalctl -u fastapi -n 30 --no-pager | grep -iE 'error|traceback' || echo "no errors"
cd /tmp && sudo -u postgres psql -p 5433 -d bottleclub_prod -XAt -c "SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations WHERE version >= '022'"   # 022,023,024,025
```

Service key ของ storefront production:
```bash
sudo bash -c 'set -euo pipefail; umask 077; set -a; . /etc/bottleclub/secrets.env; . /etc/bottleclub/api.env; set +a
  cd /opt/bottleclub/current && .venv/bin/python -m scripts.service_keys create --name storefront --org-id <org> \
    --scope customers.lookup --scope customers.create --scope loyalty.read --out /root/storefront-service-key.txt'
```
- ใส่ค่าลง env ฝั่ง server ของ Vercel (ไม่ใช่ `NEXT_PUBLIC_*`) แล้ว `sudo shred -u /root/storefront-service-key.txt`
- ตรวจด้วย `POST /customers/lookup` ใส่ key และเบอร์ที่ไม่มีในระบบ ต้องได้ 404
- ถ้าจะยกเลิก key: `... python -m scripts.service_keys revoke --id N`

### 4.8 ย้อนกลับ production

| สถานการณ์ | ทำอะไร |
|---|---|
| code ผิดปกติ (กรณีที่ควรใช้) | `sudo bottleclub-deploy v0.1.23` (release เดิมและ `.venv` ยังอยู่) **เก็บ schema 022–025 ไว้** code เก่าไม่ใช้ตารางและคอลัมน์ใหม่ |
| env ใหม่ทำให้ API ไม่ start | `sudo cp -p /etc/bottleclub/api.env.bak-v0123 /etc/bottleclub/api.env` (และ `secrets.env.bak-v0123`) แล้ว `sudo systemctl restart fastapi` |
| ต้องย้อน schema และ**ยังไม่มี**บัญชีลูกค้า | ย้อน code ก่อน แล้ว `prod_db.sh apply $M/<NNN>.rollback.sql` ตามลำดับ 025 → 024 → 023 → 022 · 025 ไม่คืนสถานะ key ที่ถูก revoke · 024 ลบ key ทั้งหมด · 022 ลบ `shipping_carrier` ที่บันทึกไว้ |
| ต้องย้อน schema หลังมีบัญชีลูกค้า LINE แล้ว | rollback ของ 023 ปฏิเสธ (`customer_accounts has rows`) **ทางเดียวคือ restore ด้านล่าง** ข้อมูลหลัง backup ข้อ 4.1 จะหาย |

Restore จาก `pre-phase49` ให้ restore ลง DB ใหม่ก่อน แล้วค่อยสลับชื่อ DB เก่าจะยังอยู่ให้ตรวจสอบ:
```bash
sudo systemctl stop fastapi
cd /tmp && sudo -u postgres createdb -p 5433 -O bottleclub_owner bottleclub_prod_restore
sudo -u postgres /usr/lib/postgresql/16/bin/pg_restore -p 5433 -d bottleclub_prod_restore --exit-on-error \
  /var/backups/bottleclub/pg/bottleclub_prod-pre-phase49-<stamp>.dump     # dump มี GRANT และ default privileges ไปด้วย
sudo -u postgres psql -p 5433 -d bottleclub_prod_restore -XAt -c "SELECT max(version) FROM schema_migrations"   # 021
sudo -u postgres psql -p 5433 -X -c "ALTER DATABASE bottleclub_prod RENAME TO bottleclub_prod_phase49_failed" \
                                 -c "ALTER DATABASE bottleclub_prod_restore RENAME TO bottleclub_prod"
sudo bottleclub-deploy v0.1.23     # start code เก่าบน DB ที่ restore แล้ว พร้อมตรวจ health
```

## 5. งานแยก (ยังไม่ทำในรอบนี้): ผูก RabbitMQ 25672 และ epmd 4369 ไว้ที่ 127.0.0.1

ufw ป้องกันอยู่แล้ว งานนี้เพิ่มความปลอดภัยอีกชั้น ให้ทำในช่วงเวลาแยกจาก deploy ด้านล่างคือ §1 ของ `~/bottleclub-prod/rabbitmq-setup.md` ซึ่งยังไม่เคยทำ
ระหว่าง restart ระบบ log ของผู้ใช้จะขาดช่วงสั้นๆ แต่ API ยังทำงาน

1. `/etc/rabbitmq/rabbitmq.conf`: คงบรรทัดเดิมไว้ แล้วเพิ่ม
   ```ini
   distribution.listener.interface = 127.0.0.1
   ```
2. `/etc/rabbitmq/rabbitmq-env.conf`: เพิ่ม `ERL_EPMD_ADDRESS=127.0.0.1`
3. epmd เริ่มทำงานผ่าน systemd socket ให้ override:
   ```bash
   sudo systemctl edit epmd.socket
   # [Socket]
   # ListenStream=
   # ListenStream=127.0.0.1:4369
   # BindIPv6Only=default
   ```
4. ใช้งาน:
   ```bash
   sudo cp -p /etc/rabbitmq/rabbitmq.conf /etc/rabbitmq/rabbitmq.conf.bak-p49
   sudo systemctl stop rabbitmq-server
   sudo systemctl daemon-reload && sudo systemctl restart epmd.socket
   sudo pkill -x epmd || true
   sudo systemctl start rabbitmq-server
   sudo ss -ltnp | grep -E ':(5672|25672|4369)\b'      # ทุกบรรทัดต้องเป็น 127.0.0.1 (หรือ [::1])
   sudo rabbitmqctl status | head -5
   systemctl status log-user-bottleclub log-user-bottleclub-worker --no-pager | grep Active
   ```
5. ย้อนกลับ: คืน `rabbitmq.conf.bak-p49`, ลบบรรทัด `ERL_EPMD_ADDRESS`, `sudo systemctl revert epmd.socket` แล้วทำข้อ 4 ซ้ำ
