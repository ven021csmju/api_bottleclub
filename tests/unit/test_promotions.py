from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.session import get_db
from app.domains.promotions.schemas import PromotionCreate, PromotionUpdate
from app.domains.promotions.service import PromotionService
from app.main import create_app
from app.shared.exceptions import ConflictException, NotFoundException


def payload(**overrides):
    value = {
        "id": "grand-cru-2026",
        "title": "GRAND CRU & VINTAGE",
        "description": "รายละเอียดโปรโมชั่น",
        "imageUrl": "https://example.test/promo.jpg",
        "images": ["/images/promo-1.jpg"],
        "heroImageUrl": "data:image/png;base64,abc",
        "isFeatured": True,
        "isActive": True,
        "sortOrder": 1,
    }
    value.update(overrides)
    return value


def promotion(**overrides):
    value = dict(
        id="grand-cru-2026",
        title="GRAND CRU & VINTAGE",
        subtitle=None,
        description="รายละเอียดโปรโมชั่น",
        image_url="https://example.test/promo.jpg",
        images=["/images/promo-1.jpg"],
        hero_image_url=None,
        badge="PROMOTION",
        discount_tag=None,
        valid_until=None,
        link_url="/#products",
        cta_text="ดูสินค้าโปรโมชั่น",
        secondary_cta_text=None,
        secondary_link_url=None,
        is_featured=True,
        is_active=True,
        sort_order=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    value.update(overrides)
    return SimpleNamespace(**value)


def test_create_schema_maps_camel_case_to_snake_case():
    data = PromotionCreate.model_validate(payload())
    dumped = data.model_dump()
    assert dumped["image_url"] == payload()["imageUrl"]
    assert dumped["hero_image_url"] == payload()["heroImageUrl"]
    assert dumped["is_featured"] is True
    assert dumped["sort_order"] == 1


def test_images_must_be_an_array():
    with pytest.raises(ValidationError):
        PromotionCreate.model_validate(payload(images="not-an-array"))


@pytest.mark.parametrize("field", ["title", "description", "imageUrl"])
def test_required_text_fields_cannot_be_blank(field):
    with pytest.raises(ValidationError):
        PromotionCreate.model_validate(payload(**{field: "  "}))


def test_sort_order_and_booleans_are_strict_types():
    with pytest.raises(ValidationError):
        PromotionCreate.model_validate(payload(sortOrder="1"))
    with pytest.raises(ValidationError):
        PromotionCreate.model_validate(payload(isActive=1))


def test_update_preserves_unset_fields():
    data = PromotionUpdate.model_validate({"id": "promo-1", "isActive": False})
    assert data.model_dump(exclude_unset=True) == {"id": "promo-1", "is_active": False}


def test_public_endpoint_returns_camel_case_and_filters_via_service(monkeypatch):
    item = promotion()
    seen = {}

    def list_promotions(db, featured):
        seen["featured"] = featured
        return [item]

    monkeypatch.setattr(PromotionService, "list", list_promotions)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    with TestClient(app) as client:
        response = client.get("/api/promotions?featured=true")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["promotions"][0]["imageUrl"] == item.image_url
    assert "image_url" not in response.json()["promotions"][0]
    assert seen["featured"] is True


def test_public_endpoint_accepts_unfiltered_query(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        PromotionService,
        "list",
        lambda db, featured: seen.setdefault("featured", featured) or [],
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    with TestClient(app) as client:
        response = client.get("/api/promotions")
    assert response.status_code == 200
    assert seen["featured"] is None


def test_admin_routes_require_existing_authentication():
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    with TestClient(app) as client:
        response = client.post("/api/admin/promotions", json=payload())
    # Existing auth middleware treats a missing required Authorization header
    # as a validation error; invalid credentials are returned as 401.
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_openapi_exposes_all_contract_routes():
    paths = create_app().openapi()["paths"]
    assert "/api/promotions" in paths
    assert "/api/admin/promotions" in paths
    assert "/api/admin/promotions/bulk" in paths
    assert "delete" in paths["/api/admin/promotions"]


class FakeSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.added = None

    def add(self, value):
        self.added = value

    def commit(self):
        self.committed = True

    def refresh(self, value):
        return None

    def rollback(self):
        self.rolled_back = True

    def delete(self, value):
        self.deleted = value


def test_duplicate_id_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.domains.promotions.service.PromotionRepository.get",
        lambda db, promotion_id: promotion(),
    )
    with pytest.raises(ConflictException):
        PromotionService.create(FakeSession(), payload(image_url="https://example.test/x"))


def test_update_missing_promotion_is_404(monkeypatch):
    monkeypatch.setattr(
        "app.domains.promotions.service.PromotionRepository.get",
        lambda db, promotion_id: None,
    )
    with pytest.raises(NotFoundException):
        PromotionService.update(FakeSession(), {"id": "missing", "is_active": True})


def test_bulk_missing_item_rolls_back(monkeypatch):
    calls = iter([promotion(), None])
    monkeypatch.setattr(
        "app.domains.promotions.service.PromotionRepository.get",
        lambda db, promotion_id: next(calls),
    )
    session = FakeSession()
    with pytest.raises(NotFoundException):
        PromotionService.bulk_update(
            session,
            [{"id": "promo-1", "sort_order": 1}, {"id": "promo-2", "is_active": False}],
        )
    assert session.committed is False
    assert session.rolled_back is True


def test_delete_missing_promotion_is_404(monkeypatch):
    monkeypatch.setattr(
        "app.domains.promotions.service.PromotionRepository.get",
        lambda db, promotion_id: None,
    )
    with pytest.raises(NotFoundException):
        PromotionService.delete(FakeSession(), "missing")
