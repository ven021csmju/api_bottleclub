"""Demo wines for the storefront: 8 catalog products (price, Thai description)
and their 8 wine_products rows (GET /wine-products/), on the database of
DATABASE_URL (the API's environment), through the ORM.

    python -m scripts.seed_demo_wines                  # dry run: what would change
    python -m scripts.seed_demo_wines --apply          # create / bring back in line
    python -m scripts.seed_demo_wines --delete --apply # remove the demo data
    python -m scripts.seed_demo_wines --wine-only --apply  # wine_products rows only (production)

Every demo row is marked: products.sku and wine_products.code start with
DEMO-, and the products are in the category DEMO_CATEGORY. 17 rows: the
category, 8 products and their 8 wine_products rows. Running it again
creates nothing twice (looked up by sku / code) and puts changed demo rows
back to the values below. --delete touches DEMO- rows only; a demo product
already used by an order or a stock movement cannot be deleted (RESTRICT),
so it is deactivated and soft-deleted instead.

--wine-only (production, before the shop opens online): the 8 wine_products
rows only, no category and no products. wine_products is read only by the
public GET /wine-products/; the POS catalog, orders, stock and every report
read products, so demo wines never reach a cashier or a sales figure. The
storefront tells them apart by `code` starting with DEMO- (the name starts
with "DEMO " too). --delete removes them as above.
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
DEMO_CATEGORY = "ไวน์ตัวอย่าง (DEMO)"


@dataclass(frozen=True)
class DemoWine:
    sku: str
    name: str
    kind: str  # wine_products.categories_en
    country: str
    region: str
    alcohol: str
    price: Decimal
    description: str


# Invented labels (no real producer); prices 1,500-30,000 baht.
WINES: tuple[DemoWine, ...] = (
    DemoWine("DEMO-RED-001", "DEMO Andes Ridge Cabernet Sauvignon 2021", "Red wines", "Chile", "Central Valley",
             "13.5", Decimal("1590.00"),
             "ไวน์แดงรสชาติเข้มข้น กลิ่นแบล็กเคอร์แรนต์และพริกไทยดำ แทนนินนุ่ม เข้ากับสเต๊กและอาหารปิ้งย่าง"),
    DemoWine("DEMO-RED-002", "DEMO Southern Lakes Pinot Noir 2020", "Red wines", "New Zealand", "Central Otago",
             "13.0", Decimal("2890.00"),
             "ไวน์แดงบอดี้เบา กลิ่นเชอร์รีและราสป์เบอร์รี เปรี้ยวสดชื่น ดื่มคู่เป็ดย่างหรือแซลมอนได้ดี"),
    DemoWine("DEMO-RED-003", "DEMO Château Exemple Bordeaux Supérieur 2018", "Red wines", "France", "Bordeaux",
             "14.0", Decimal("8900.00"),
             "ไวน์แดงเบลนด์สไตล์บอร์โดซ์ กลิ่นพลัม ซีดาร์ และวานิลลาจากถังโอ๊ก โครงสร้างดี เก็บบ่มต่อได้อีกหลายปี"),
    DemoWine("DEMO-RED-004", "DEMO Colline Alte Barolo Riserva 2015", "Red wines", "Italy", "Piedmont",
             "14.5", Decimal("30000.00"),
             "ไวน์แดงระดับพรีเมียมจากองุ่นเนบบิโอโล กลิ่นกุหลาบแห้ง ทาร์ และเห็ดทรัฟเฟิล แทนนินแน่น เหมาะสำหรับโอกาสพิเศษ"),
    DemoWine("DEMO-WHT-001", "DEMO Coastal Bay Sauvignon Blanc 2023", "White wines", "New Zealand", "Marlborough",
             "12.5", Decimal("1500.00"),
             "ไวน์ขาวกลิ่นเสาวรส มะนาว และหญ้าตัดใหม่ เปรี้ยวสดชื่น เสิร์ฟเย็นคู่กับอาหารทะเลและยำไทย"),
    DemoWine("DEMO-WHT-002", "DEMO Domaine Modèle Bourgogne Chardonnay 2021", "White wines", "France", "Burgundy",
             "13.0", Decimal("4200.00"),
             "ไวน์ขาวชาร์ดอนเนย์ กลิ่นแอปเปิ้ลเขียว เนย และถั่วอบ เนื้อสัมผัสนุ่มละมุน เข้ากับไก่อบและพาสต้าครีม"),
    DemoWine("DEMO-SPK-001", "DEMO Maison Essai Champagne Brut NV", "Sparkling wines", "France", "Champagne",
             "12.0", Decimal("12500.00"),
             "แชมเปญสไตล์บรูต ฟองละเอียด กลิ่นขนมปังอบ บริยอช และลูกแพร์ เหมาะสำหรับฉลองหรือเป็นเครื่องดื่มเรียกน้ำย่อย"),
    DemoWine("DEMO-ROS-001", "DEMO Côte Rose Provence Rosé 2023", "Rosé wines", "France", "Provence",
             "12.5", Decimal("1890.00"),
             "ไวน์โรเซ่สีชมพูอ่อน กลิ่นสตรอว์เบอร์รีและพีช แห้งและสดชื่น ดื่มเย็นๆ คู่สลัดหรืออาหารเมดิเตอร์เรเนียน"),
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


def _product_values(wine: DemoWine, category_id: int | None) -> dict:
    return {
        "name": wine.name,
        "description": wine.description,
        "selling_price": wine.price,
        "cost_price": (wine.price * Decimal("0.6")).quantize(Decimal("1.00")),
        "unit": "bottle",
        "is_active": True,
        "track_inventory": True,
        "category_id": category_id,
        "deleted_at": None,
    }


def _wine_values(wine: DemoWine) -> dict:
    return {
        "product_name": wine.name,
        "brands": wine.name.split(" ")[1] + " " + wine.name.split(" ")[2],
        "categories_en": wine.kind,
        "origins_en": wine.region,
        "countries_en": wine.country,
        "quantity": "750 ml",
        "alcohol_100g": wine.alcohol,
    }


def _sync(row, values: dict) -> bool:
    changed = False
    for field, value in values.items():
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    return changed


def seed(db: Session, org_id: int | None = None, *, wine_only: bool = False) -> dict[str, list[str]]:
    """Create the demo rows or put them back in line; nothing twice.
    ``wine_only``: the wine_products rows only (nothing the POS or a report reads)."""
    out: dict[str, list[str]] = {"created": [], "updated": [], "unchanged": []}
    if wine_only:
        for wine in WINES:
            _seed_wine_row(db, wine, out)
        db.flush()
        return out
    org = _organization(db, org_id)

    category = db.scalar(select(Category).where(Category.organization_id == org.id, Category.name == DEMO_CATEGORY))
    if category is None:
        category = Category(organization_id=org.id, name=DEMO_CATEGORY, description="ข้อมูลทดสอบ (DEMO) — ลบได้")
        db.add(category)
        db.flush()
        out["created"].append(f"category {DEMO_CATEGORY}")
    else:
        out["unchanged"].append(f"category {DEMO_CATEGORY}")

    for wine in WINES:
        product = db.scalar(select(Product).where(Product.organization_id == org.id, Product.sku == wine.sku))
        if product is None:
            db.add(Product(organization_id=org.id, sku=wine.sku, **_product_values(wine, category.id)))
            out["created"].append(f"product {wine.sku}")
        else:
            out["updated" if _sync(product, _product_values(wine, category.id)) else "unchanged"].append(
                f"product {wine.sku}")

        _seed_wine_row(db, wine, out)
    db.flush()
    return out


def _seed_wine_row(db: Session, wine: DemoWine, out: dict[str, list[str]]) -> None:
    row = db.scalar(select(WineProduct).where(WineProduct.code == wine.sku))
    if row is None:
        db.add(WineProduct(code=wine.sku, **_wine_values(wine)))
        out["created"].append(f"wine_product {wine.sku}")
    else:
        out["updated" if _sync(row, _wine_values(wine)) else "unchanged"].append(f"wine_product {wine.sku}")


def delete_demo(db: Session) -> dict[str, list[str]]:
    """Remove the DEMO- rows of every organization (and the empty demo category)."""
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

    for category in db.scalars(select(Category).where(Category.name == DEMO_CATEGORY)).all():
        in_use = db.scalar(select(Product.id).where(Product.category_id == category.id).limit(1))
        if in_use is None:
            db.delete(category)
            out["deleted"].append(f"category {DEMO_CATEGORY} (org {category.organization_id})")
    db.flush()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run, rolled back)")
    parser.add_argument("--delete", action="store_true", help="remove the DEMO- data instead of seeding it")
    parser.add_argument("--org-id", type=int, help="organization of the products (default: the sole active one)")
    parser.add_argument("--wine-only", action="store_true",
                        help="wine_products rows only: no category/products, so nothing in the POS or reports")
    args = parser.parse_args(argv)
    if args.delete and args.wine_only:
        parser.error("--delete removes every DEMO- row; --wine-only is for seeding")

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        result = delete_demo(db) if args.delete else seed(db, args.org_id, wine_only=args.wine_only)
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
