"""scripts/seed_demo_wines.py (Phase 50): 24 demo products (is_demo, DEMO-) and
their wine_products rows, idempotent, and a delete that touches DEMO- rows only."""
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import Category, Product, WineProduct
from scripts import seed_demo_wines as demo


def _count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_seeds_24_wines_in_both_tables(session, seed_org):
    result = demo.seed(session, seed_org)

    products = session.scalars(select(Product).order_by(Product.sku)).all()
    assert len(products) == 24 and all(p.sku.startswith("DEMO-") and p.is_demo for p in products)
    assert {p.sku.split("-")[1] for p in products} == {"RED", "WHT", "SPK", "ROS", "DSS"}
    assert not any(p.is_online or p.track_inventory or p.category_id for p in products)
    prices = [p.selling_price for p in products]
    assert min(prices) == Decimal("590.00") and max(prices) == Decimal("30000.00")
    assert all(any("฀" <= ch <= "๿" for ch in p.description) for p in products)  # Thai
    assert all(p.image_url.startswith("/demo-wines/") and p.image_url.endswith(".jpg") for p in products)
    assert _count(session, WineProduct, WineProduct.code.startswith("DEMO-")) == 24
    assert _count(session, Category) == 0
    assert len(result["created"]) == 48  # 24 + 24
    assert len({w.producer for w in demo.WINES}) == 23  # Maison Aubrelle makes two


def test_running_again_creates_nothing(session, seed_org):
    demo.seed(session, seed_org)
    session.scalar(select(Product).where(Product.sku == "DEMO-RED-001")).selling_price = Decimal("1")
    result = demo.seed(session, seed_org)

    assert result["created"] == [] and result["updated"] == ["product DEMO-RED-001"]
    assert len(result["unchanged"]) == 47
    assert _count(session, Product) == 24 and _count(session, WineProduct) == 24


def test_delete_removes_demo_rows_only(session, seed_org):
    session.add(Product(organization_id=seed_org, sku="REAL-1", name="Real", selling_price=Decimal("100")))
    session.add(WineProduct(code="3000000000001", product_name="Real wine"))
    session.add(Category(organization_id=seed_org, name=demo.LEGACY_DEMO_CATEGORY))  # left by v0.1.24
    demo.seed(session, seed_org)

    result = demo.delete_demo(session)

    assert len(result["deleted"]) == 49 and result["soft_deleted"] == []
    assert session.scalars(select(Product.sku)).all() == ["REAL-1"]
    assert session.scalars(select(WineProduct.code)).all() == ["3000000000001"]
    assert _count(session, Category) == 0


def test_a_demo_product_in_use_is_soft_deleted(session, seed_org, seed_branch):
    from app.db.models import Inventory

    demo.seed(session, seed_org)
    used = session.scalar(select(Product).where(Product.sku == "DEMO-RED-001"))
    session.add(Inventory(branch_id=seed_branch, product_id=used.id, on_hand=1))
    session.flush()

    result = demo.delete_demo(session)

    assert result["soft_deleted"] == ["product DEMO-RED-001"]
    assert used.deleted_at is not None and used.is_active is False
    # Seeding again brings it back.
    demo.seed(session, seed_org)
    assert used.deleted_at is None and used.is_active is True


def test_the_wines_are_served_by_wine_products(client, session, seed_org):
    demo.seed(session, seed_org)
    resp = client.get("/api/v1/wine-products/", params={"per_page": 50})
    assert resp.status_code == 200, resp.text
    assert "DEMO-DSS-002" in resp.text
