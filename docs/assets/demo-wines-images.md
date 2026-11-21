# ไวน์ตัวอย่าง (DEMO): ที่มาของรูป และการตรวจชื่อ

ใช้กับ `scripts/seed_demo_wines.py` (Phase 50) ทั้ง 24 รายการ ข้อมูลชุดนี้ไม่ใช่สินค้าจริง

## รูป (6 ไฟล์)

- **ที่เก็บ:** `/public/demo-wines/` ใน repo หน้าร้าน ส่วน `image_url` ใน DB เป็น `/demo-wines/<ไฟล์>` (owner Q6)
- **ไฟล์ส่งมอบ:** `~/frontend-handoff/demo-wines/`
- **ตรวจเมื่อ:** 2026-11-22
- **ที่มา:** Wikimedia Commons เฉพาะไฟล์ที่หน้าไฟล์ระบุ `CC0` หรือ `Public domain`
- **ไม่ใช้:** รูปที่สร้างด้วย AI (กรองชื่อและคำอธิบายที่มี DALL·E / AI-generated / Midjourney ออก) และรูปที่เห็นชื่อแบรนด์
- **ขนาด:** ย่อเป็นกว้าง 960px (thumbnail ของ Commons) ยกเว้น `sparkling.jpg` ที่เป็นไฟล์ต้นฉบับ 669×993
- **การตรวจด้วยตา:** เปิดดูทุกรูป และบันทึกผลในคอลัมน์ "ตรวจด้วยตา"
- ถ้าจะเปลี่ยนรูป ต้องบันทึกในตารางนี้ก่อน

| ไฟล์ | ใช้กับ (DEMO-…) | หน้าไฟล์ต้นทาง | ผู้สร้าง | สัญญาอนุญาต | แหล่งเดิม (Credit) | ตรวจด้วยตา | sha256 |
|---|---|---|---|---|---|---|---|
| `red.jpg` | RED-002/004/006/008 | [Red wine in glass.jpg](https://commons.wikimedia.org/wiki/File:Red_wine_in_glass.jpg) | Paolo Neo | Public domain | http://www.public-domain-image.com/public-domain-images-pictures-free-stock-photos/food-and-drink-public-domain-images-pictures/wine-public-domain-images-pictures/red-wine-in-glass.jpg | แก้วไวน์แดงบนพื้นขาว ไม่มีขวด ไม่มีข้อความ | `8e6e1ad755a006dd6de2846b2871be819503f78011aca34cf48abdcb80b418dd` |
| `red-bottle.jpg` | RED-001/003/005/007/009 | [Bottle and glass of red wine.jpg](https://commons.wikimedia.org/wiki/File:Bottle_and_glass_of_red_wine.jpg) | congerdesign | CC0 ([CC0 1.0](http://creativecommons.org/publicdomain/zero/1.0/deed.en)) | https://pixabay.com/en/wine-red-wine-glass-drink-alcohol-541922/ archive copy at the Wayback Machine | ขวดไวน์ + แก้วไวน์แดง ฉลากเป็นแถบสีขาวว่าง ไม่มีตัวอักษรหรือโลโก้ที่อ่านได้ | `7dad6fd319aef76a2dbf42d14960065e215667e539ae911e8c2ef4dfd950da81` |
| `white.jpg` | WHT-001…006 | [Glass of white wine.jpg](https://commons.wikimedia.org/wiki/File:Glass_of_white_wine.jpg) | Jon Sullivan | Public domain | https://www.public-domain-image.com/public-domain-images-pictures-free-stock-photos/food-and-drink-public-domain-images-pictures/wine-public-domain-images-pictures/glass-of-white-wine.jpg | แก้วไวน์ขาวบนโต๊ะ ไม่มีขวด ไม่มีข้อความ | `98fe34adea20db09ac32403ab4cc7c3b4dd503b094e0d315ec7b3a33f8b70ca4` |
| `sparkling.jpg` | SPK-001…004 | [Verre Champagne.jpg](https://commons.wikimedia.org/wiki/File:Verre_Champagne.jpg) | Berndt Fernow | Public domain | Self-photographed | แก้วแชมเปญมีฟอง พื้นหลังเรียบ ไม่มีขวด ไม่มีข้อความ | `e9993dbde2a753a39b830914adfef0c656fe0d57c5816b3f68c59c01cae44530` |
| `rose.jpg` | ROS-001…003 | [Wine Glass, ca. 1900 (CH 68777087).jpg](https://commons.wikimedia.org/wiki/File:Wine_Glass,_ca._1900_(CH_68777087).jpg) | Unknown artist (Cooper Hewitt catalog photo) | Public domain | Catalog Photo | แก้วไวน์แก้วสีชมพู (ภาพวัตถุพิพิธภัณฑ์ Cooper Hewitt ราว ค.ศ. 1900) ไม่มีข้อความ | `f830220e83522d19283df2587b77259ba27fea53694bd056cf836fd25bca8c9c` |
| `dessert.jpg` | DSS-001/002 | [Wine glass with red wine (1).jpg](https://commons.wikimedia.org/wiki/File:Wine_glass_with_red_wine_(1).jpg) | Paolo Neo | Public domain | http://www.public-domain-image.com/public-domain-images-pictures-free-stock-photos/food-and-drink-public-domain-images-pictures/wine-public-domain-images-pictures/wine-glass-with-red-wine.jpg | แก้วเจียระไนใส่ไวน์สีอำพัน พื้นดำ ไม่มีขวด ไม่มีข้อความ | `3e9822b35df2f143edd7bb4cdd4404cdd19d217c9e97984af7039bbced9b37a1` |

- **Public domain:** ใช้ได้โดยไม่ต้องให้เครดิต แต่ให้เครดิตไว้ก็ได้ (หน้าเครดิตของหน้าร้าน)
- **CC0 1.0:** สละสิทธิ์ทั้งหมด
- แก้วสีชมพูใน `rose.jpg` เป็นภาพวัตถุพิพิธภัณฑ์ที่หน้า Commons ระบุว่า Public domain

## ชื่อผู้ผลิต (แต่งขึ้นเอง) และการค้นชื่อซ้ำ

ค้นเว็บ 2026-11-21 ด้วยคำค้น `"<ชื่อ>" wine` (หรือ château / winery / champagne ตามประเภท) และอ่านผลแรก ๆ
ผลที่ยอมรับคือ "ไม่พบผู้ผลิต / แบรนด์ / ไวน์ที่ใช้ชื่อนี้ตรงตัว"
ชื่อแหล่งผลิตและประเทศ (Bordeaux, Mosel, …) เป็นชื่อภูมิศาสตร์ ไม่ใช่ชื่อผู้ผลิต

| ชื่อ | ผล |
|---|---|
| Andelaro Ridge | ไม่พบ (ใกล้สุด: Andeluna ที่ Mendoza ซึ่งเป็นคนละชื่อ) |
| Kestrelmoor | ไม่พบ |
| Château Brumevallon | ไม่พบ |
| Poggio Taventi | ไม่พบ |
| Quillara Estate | ไม่พบ (ใกล้สุด: ไวน์ชื่อ "Quillay") |
| Finca Orvalle | ไม่พบ (ใกล้สุด: Finca Orellana ของ Trapiche) |
| Tenuta Boscaventi | ไม่พบ |
| Bodega Lunacorte | ไม่พบ |
| Domaine Ferrelune | ไม่พบ |
| Tidewren | ไม่พบ |
| Domaine Clairbrisé | ไม่พบ |
| Weingut Sonnhalden | ไม่พบ |
| Casa Velmira | ไม่พบ |
| Brindlecove | ไม่พบ |
| Cantina Lorivane | ไม่พบ |
| Maison Aubrelle | ไม่พบ (ใกล้สุด: Champagne Aubry) |
| Corte Brinavera | ไม่พบ |
| Caves Montserrel | ไม่พบ (ใกล้สุด: Montsarra) |
| Bastide Rosacielle | ไม่พบ |
| Viña Corvalina | ไม่พบผู้ผลิต (ชื่อคล้ายองุ่น Corvina) |
| Petalgrove | ไม่พบ (ใกล้สุด: Pettygrove, Petal & Stem) |
| Château Doréval | ไม่พบ |
| Quinta da Serranelha | ไม่พบ (ใกล้สุด: Quinta da Serradinha) |

**ชื่อที่ถูกตัดออก:**
- **"Tenuta Selvarossa"** ตัดออก เพราะ *Selvarossa* เป็นชื่อไวน์จริง (Salice Salentino Riserva ของ Cantine Due Palme)
- **"Velloro Ridge"** ตัดออก เพราะใกล้กับ *Vellodoro* (Pecorino ของ Umani Ronchi)
- ชื่อในชุด 8 รายการเดิมของ v0.1.24 ไม่ได้นำมาใช้ต่อ ยกเว้นรายการที่อยู่ในตารางนี้
