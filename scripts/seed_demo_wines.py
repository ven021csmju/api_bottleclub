"""Demo wines for the storefront (Phase 50): 24 demo products (price, Thai
description, image) and their 24 wine_products rows (type, country, region,
alcohol, volume), on the database of DATABASE_URL (the API's environment),
through the ORM.

    python -m scripts.seed_demo_wines                  # dry run: what would change
    python -m scripts.seed_demo_wines --apply          # create / bring back in line
    python -m scripts.seed_demo_wines --delete --apply # remove the demo data

Every demo product has products.is_demo = true and a sku starting with DEMO-
(026's CHECK ties the two); its wine_products row has the same code. The
storefront catalog (GET /storefront/products) shows them with is_demo=true;
no staff route, order, purchase, transfer, stock movement or report sees or
uses them (app/db/product_scope.py), so the full seed is safe on production.
They track no stock and belong to no category.

Names, producers and labels are invented (each producer name was searched
before use: docs/assets/demo-wines-images.md). image_url is relative
(/demo-wines/<file>.jpg): the storefront serves the files from its own
/public/demo-wines/ (public-domain / CC0 images, sources in the same doc).

Running it again creates nothing twice (looked up by sku / code) and puts
changed demo rows back to the values below. --delete touches DEMO- rows only
(and the empty demo category of earlier versions); a demo product already
used by an order or a stock row cannot be deleted (RESTRICT), so it is
deactivated and soft-deleted instead.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models import Category, Organization, Product, WineProduct  # noqa: E402

PREFIX = "DEMO-"
# Earlier versions (v0.1.24) put the demo products in this category: --delete removes it.
LEGACY_DEMO_CATEGORY = "ไวน์ตัวอย่าง (DEMO)"
IMAGE_DIR = "/demo-wines/"
RED, WHITE, SPARKLING, ROSE, DESSERT = "Red wines", "White wines", "Sparkling wines", "Rosé wines", "Dessert wines"


@dataclass(frozen=True)
class DemoWine:
    sku: str
    name: str
    producer: str  # wine_products.brands (invented)
    kind: str  # wine_products.categories_en
    country: str
    region: str
    alcohol: str
    volume: str
    price: Decimal
    image: str
    description: str


def _w(sku, name, producer, kind, country, region, alcohol, price, image, description, volume="750 ml"):
    return DemoWine(sku, name, producer, kind, country, region, alcohol, volume, Decimal(price), image, description)


# Invented producers (no real winery); prices 590-30,000 baht.
WINES: tuple[DemoWine, ...] = (
    _w("DEMO-RED-001", "DEMO Andelaro Ridge Cabernet Sauvignon 2021", "Andelaro Ridge", RED, "Chile",
       "Central Valley", "13.5", "1590.00", "red-bottle.jpg",
       "ไวน์แดงรสชาติเข้มข้น กลิ่นแบล็กเคอร์แรนต์และพริกไทยดำ แทนนินนุ่ม เข้ากับสเต๊กและอาหารปิ้งย่าง"),
    _w("DEMO-RED-002", "DEMO Kestrelmoor Pinot Noir 2020", "Kestrelmoor", RED, "New Zealand",
       "Central Otago", "13.0", "2890.00", "red.jpg",
       "ไวน์แดงบอดี้เบา กลิ่นเชอร์รีและราสป์เบอร์รี เปรี้ยวสดชื่น ดื่มคู่เป็ดย่างหรือแซลมอนได้ดี"),
    _w("DEMO-RED-003", "DEMO Château Brumevallon Bordeaux Supérieur 2018", "Château Brumevallon", RED, "France",
       "Bordeaux", "14.0", "8900.00", "red-bottle.jpg",
       "ไวน์แดงเบลนด์สไตล์บอร์โดซ์ กลิ่นพลัม ซีดาร์ และวานิลลาจากถังโอ๊ก โครงสร้างดี เก็บบ่มต่อได้อีกหลายปี"),
    _w("DEMO-RED-004", "DEMO Poggio Taventi Barolo Riserva 2015", "Poggio Taventi", RED, "Italy",
       "Piedmont", "14.5", "30000.00", "red.jpg",
       "ไวน์แดงระดับพรีเมียมจากองุ่นเนบบิโอโล กลิ่นกุหลาบแห้ง ทาร์ และเห็ดทรัฟเฟิล แทนนินแน่น เหมาะสำหรับโอกาสพิเศษ"),
    _w("DEMO-RED-005", "DEMO Quillara Estate Shiraz 2019", "Quillara Estate", RED, "Australia",
       "Barossa Valley", "14.5", "2390.00", "red-bottle.jpg",
       "ไวน์แดงชีราซเนื้อแน่น กลิ่นแบล็กเบอร์รี ช็อกโกแลต และเครื่องเทศ เข้ากับเนื้อย่างและบาร์บีคิว"),
    _w("DEMO-RED-006", "DEMO Finca Orvalle Tempranillo Crianza 2019", "Finca Orvalle", RED, "Spain",
       "Rioja", "13.5", "1890.00", "red.jpg",
       "ไวน์แดงเทมปรานิลโยบ่มถังโอ๊ก กลิ่นสตรอว์เบอร์รีสุก หนัง และวานิลลา ดื่มง่าย เข้ากับทาปาสและหมูย่าง"),
    _w("DEMO-RED-007", "DEMO Tenuta Boscaventi Chianti Classico 2020", "Tenuta Boscaventi", RED, "Italy",
       "Tuscany", "13.5", "2490.00", "red-bottle.jpg",
       "ไวน์แดงซานโจเวเซ กลิ่นเชอร์รีเปรี้ยว สมุนไพรแห้ง และใบชา ความเปรี้ยวสดชื่น เข้ากับพาสต้าซอสมะเขือเทศและพิซซ่า"),
    _w("DEMO-RED-008", "DEMO Bodega Lunacorte Malbec 2021", "Bodega Lunacorte", RED, "Argentina",
       "Mendoza", "14.0", "1290.00", "red.jpg",
       "ไวน์แดงมัลเบคสีเข้ม กลิ่นพลัมและไวโอเล็ต เนื้อนุ่มกลมกล่อม คู่หูของสเต๊กเนื้อ"),
    _w("DEMO-RED-009", "DEMO Domaine Ferrelune Côtes du Rhône 2021", "Domaine Ferrelune", RED, "France",
       "Rhône", "14.0", "990.00", "red-bottle.jpg",
       "ไวน์แดงเกรอนาชและซีราห์ กลิ่นราสป์เบอร์รี พริกไทย และสมุนไพรการ์ริก ดื่มสบายทุกวัน"),
    _w("DEMO-WHT-001", "DEMO Tidewren Sauvignon Blanc 2023", "Tidewren", WHITE, "New Zealand",
       "Marlborough", "12.5", "1500.00", "white.jpg",
       "ไวน์ขาวกลิ่นเสาวรส มะนาว และหญ้าตัดใหม่ เปรี้ยวสดชื่น เสิร์ฟเย็นคู่กับอาหารทะเลและยำไทย"),
    _w("DEMO-WHT-002", "DEMO Domaine Clairbrisé Bourgogne Chardonnay 2021", "Domaine Clairbrisé", WHITE, "France",
       "Burgundy", "13.0", "4200.00", "white.jpg",
       "ไวน์ขาวชาร์ดอนเนย์ กลิ่นแอปเปิ้ลเขียว เนย และถั่วอบ เนื้อสัมผัสนุ่มละมุน เข้ากับไก่อบและพาสต้าครีม"),
    _w("DEMO-WHT-003", "DEMO Weingut Sonnhalden Riesling Kabinett 2022", "Weingut Sonnhalden", WHITE, "Germany",
       "Mosel", "9.0", "1790.00", "white.jpg",
       "ไวน์ขาวรีสลิงหวานอ่อนๆ กลิ่นพีช แอปริคอต และดอกไม้ขาว เปรี้ยวสมดุล เข้ากับอาหารไทยรสจัดและแกงเขียวหวาน"),
    _w("DEMO-WHT-004", "DEMO Casa Velmira Albariño 2022", "Casa Velmira", WHITE, "Spain",
       "Rías Baixas", "12.5", "1390.00", "white.jpg",
       "ไวน์ขาวอัลบาริโญ กลิ่นส้มโอ ลูกพีช และกลิ่นอายทะเล สดชื่น เข้ากับหอยนางรมและปลาย่าง"),
    _w("DEMO-WHT-005", "DEMO Brindlecove Chardonnay 2022", "Brindlecove", WHITE, "Australia",
       "Margaret River", "13.5", "1990.00", "white.jpg",
       "ไวน์ขาวชาร์ดอนเนย์สไตล์โลกใหม่ กลิ่นสับปะรด พีช และโอ๊กอ่อนๆ เข้ากับกุ้งย่างเนยกระเทียม"),
    _w("DEMO-WHT-006", "DEMO Cantina Lorivane Pinot Grigio 2023", "Cantina Lorivane", WHITE, "Italy",
       "Veneto", "12.0", "790.00", "white.jpg",
       "ไวน์ขาวปิโนต์กริโจ เบาสบาย กลิ่นลูกแพร์และมะนาว ดื่มเย็นๆ ได้ทุกโอกาส"),
    _w("DEMO-SPK-001", "DEMO Maison Aubrelle Champagne Brut NV", "Maison Aubrelle", SPARKLING, "France",
       "Champagne", "12.0", "12500.00", "sparkling.jpg",
       "แชมเปญสไตล์บรูต ฟองละเอียด กลิ่นขนมปังอบ บริยอช และลูกแพร์ เหมาะสำหรับฉลองหรือเป็นเครื่องดื่มเรียกน้ำย่อย"),
    _w("DEMO-SPK-002", "DEMO Corte Brinavera Prosecco Extra Dry NV", "Corte Brinavera", SPARKLING, "Italy",
       "Veneto", "11.0", "890.00", "sparkling.jpg",
       "สปาร์กลิงไวน์โปรเซคโก ฟองนุ่ม กลิ่นแอปเปิ้ลเขียวและดอกไม้ขาว หวานเล็กน้อย เหมาะกับปาร์ตี้และค็อกเทล"),
    _w("DEMO-SPK-003", "DEMO Caves Montserrel Cava Brut Nature NV", "Caves Montserrel", SPARKLING, "Spain",
       "Penedès", "11.5", "690.00", "sparkling.jpg",
       "สปาร์กลิงไวน์คาวาแบบแห้งสนิท ฟองกระชับ กลิ่นมะนาวและอัลมอนด์ เข้ากับของทอดและทาปาส"),
    _w("DEMO-SPK-004", "DEMO Maison Aubrelle Champagne Rosé NV", "Maison Aubrelle", SPARKLING, "France",
       "Champagne", "12.0", "14900.00", "sparkling.jpg",
       "แชมเปญโรเซ่สีชมพูแซลมอน กลิ่นสตรอว์เบอร์รีป่าและราสป์เบอร์รี ฟองละเอียด สำหรับโอกาสพิเศษ"),
    _w("DEMO-ROS-001", "DEMO Bastide Rosacielle Provence Rosé 2023", "Bastide Rosacielle", ROSE, "France",
       "Provence", "12.5", "1890.00", "rose.jpg",
       "ไวน์โรเซ่สีชมพูอ่อน กลิ่นสตรอว์เบอร์รีและพีช แห้งและสดชื่น ดื่มเย็นๆ คู่สลัดหรืออาหารเมดิเตอร์เรเนียน"),
    _w("DEMO-ROS-002", "DEMO Viña Corvalina Garnacha Rosado 2023", "Viña Corvalina", ROSE, "Spain",
       "Navarra", "13.0", "590.00", "rose.jpg",
       "ไวน์โรเซ่จากองุ่นการ์นาชา กลิ่นแตงโมและเชอร์รี ดื่มง่าย ราคาย่อมเยา เข้ากับอาหารริมทะเล"),
    _w("DEMO-ROS-003", "DEMO Petalgrove Rosé 2023", "Petalgrove", ROSE, "United States",
       "California", "12.5", "1190.00", "rose.jpg",
       "ไวน์โรเซ่สไตล์แคลิฟอร์เนีย กลิ่นกุหลาบ ส้ม และแตงโม สดชื่น เหมาะกับบ่ายวันอากาศร้อน"),
    _w("DEMO-DSS-001", "DEMO Château Doréval Sauternes 2017", "Château Doréval", DESSERT, "France",
       "Sauternes", "13.5", "3900.00", "dessert.jpg",
       "ไวน์หวานซอแตร์น กลิ่นน้ำผึ้ง แอปริคอตแห้ง และหญ้าฝรั่น เข้ากับฟัวกราส์ ชีสบลู และของหวาน",
       volume="375 ml"),
    _w("DEMO-DSS-002", "DEMO Quinta da Serranelha Tawny Port 10 Years", "Quinta da Serranelha", DESSERT, "Portugal",
       "Douro", "20.0", "2290.00", "dessert.jpg",
       "ไวน์ปอร์ตทอว์นีบ่ม 10 ปี กลิ่นคาราเมล ถั่ววอลนัต และผลไม้แห้ง ดื่มหลังอาหารคู่ช็อกโกแลตหรือชีส"),
)


def _organization(db: Session, org_id: int | None) -> Organization:
    query = select(Organization).where(Organization.is_active.is_(True))
    if org_id is not None:
        org = db.scalar(query.where(Organization.id == org_id))
        if org is None:
            raise SystemExit(f"no active organization {org_id}")
        return org
    orgs = db.scalars(query.order_by(Organization.id)).all()
    if len(orgs) != 1:
        raise SystemExit(f"{len(orgs)} active organizations: pass --org-id")
    return orgs[0]


def _product_values(wine: DemoWine) -> dict:
    return {
        "name": wine.name,
        "description": wine.description,
        "selling_price": wine.price,
        "cost_price": (wine.price * Decimal("0.6")).quantize(Decimal("1.00")),
        "unit": "bottle",
        "image_url": IMAGE_DIR + wine.image,
        "is_demo": True,
        "is_online": False,
        "is_active": True,
        "track_inventory": False,
        "has_expiry": False,
        "category_id": None,
        "barcode": None,
        "station": None,
        "deleted_at": None,
    }


def _wine_values(wine: DemoWine) -> dict:
    return {
        "product_name": wine.name,
        "brands": wine.producer,
        "categories_en": wine.kind,
        "origins_en": wine.region,
        "countries_en": wine.country,
        "quantity": wine.volume,
        "alcohol_100g": wine.alcohol,
        "image_url": IMAGE_DIR + wine.image,
    }


def _sync(row, values: dict) -> bool:
    changed = False
    for field, value in values.items():
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    return changed


def seed(db: Session, org_id: int | None = None) -> dict[str, list[str]]:
    """Create the demo rows or put them back in line; nothing twice."""
    org = _organization(db, org_id)
    out: dict[str, list[str]] = {"created": [], "updated": [], "unchanged": []}
    for wine in WINES:
        product = db.scalar(select(Product).where(Product.organization_id == org.id, Product.sku == wine.sku))
        if product is None:
            db.add(Product(organization_id=org.id, sku=wine.sku, **_product_values(wine)))
            out["created"].append(f"product {wine.sku}")
        else:
            out["updated" if _sync(product, _product_values(wine)) else "unchanged"].append(f"product {wine.sku}")

        row = db.scalar(select(WineProduct).where(WineProduct.code == wine.sku))
        if row is None:
            db.add(WineProduct(code=wine.sku, **_wine_values(wine)))
            out["created"].append(f"wine_product {wine.sku}")
        else:
            out["updated" if _sync(row, _wine_values(wine)) else "unchanged"].append(f"wine_product {wine.sku}")
    db.flush()
    # v0.1.24 put its 8 demo wines in a category the POS lists: gone once empty.
    out.setdefault("deleted", []).extend(_drop_legacy_categories(db))
    if not out["deleted"]:
        del out["deleted"]
    return out


def _drop_legacy_categories(db: Session) -> list[str]:
    gone = []
    for category in db.scalars(select(Category).where(Category.name == LEGACY_DEMO_CATEGORY)).all():
        if db.scalar(select(Product.id).where(Product.category_id == category.id).limit(1)) is None:
            db.delete(category)
            gone.append(f"category {LEGACY_DEMO_CATEGORY} (org {category.organization_id})")
    db.flush()
    return gone


def delete_demo(db: Session) -> dict[str, list[str]]:
    """Remove the DEMO- rows of every organization (and the empty legacy demo category)."""
    out: dict[str, list[str]] = {"deleted": [], "soft_deleted": []}
    for row in db.scalars(select(WineProduct).where(WineProduct.code.startswith(PREFIX))).all():
        db.delete(row)
        out["deleted"].append(f"wine_product {row.code}")
    db.flush()

    now = datetime.now(timezone.utc)
    for product in db.scalars(select(Product).where(Product.sku.startswith(PREFIX)).order_by(Product.id)).all():
        try:
            with db.begin_nested():
                db.delete(product)
                db.flush()
            out["deleted"].append(f"product {product.sku}")
        except IntegrityError:
            # Used by an order/stock row (RESTRICT): keep the history, hide the product.
            product.is_active = False
            product.deleted_at = product.deleted_at or now
            db.flush()
            out["soft_deleted"].append(f"product {product.sku}")

    out["deleted"].extend(_drop_legacy_categories(db))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run, rolled back)")
    parser.add_argument("--delete", action="store_true", help="remove the DEMO- data instead of seeding it")
    parser.add_argument("--org-id", type=int, help="organization of the products (default: the sole active one)")
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = delete_demo(db) if args.delete else seed(db, args.org_id)
        for kind, rows in result.items():
            print(f"{kind}: {len(rows)}")
            for row in rows:
                print(f"  {row}")
        if args.apply:
            db.commit()
            print("committed")
        else:
            db.rollback()
            print("dry run: rolled back (add --apply to commit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
