"""Every route's success answer is described in OpenAPI (Phase 42, item 5).

v0.1.15 had 8 operations whose 2xx schema was {} (no response_model): /auth/google,
/inventory/adjust, /inventory/balances/{branch_id}/{product_id}, /slip-verify/upload,
/checkslip, /{verification_id}, /order/{order_id} and /health/mongodb.
"""
from app.main import create_app

SPEC = create_app().openapi()


def _ref(path: str, method: str = "get", code: str = "200") -> dict:
    return SPEC["paths"][path][method]["responses"][code]["content"]["application/json"]["schema"]


def test_no_success_answer_is_an_empty_schema():
    empty = [f"{m.upper()} {p} {c}" for p, ops in SPEC["paths"].items() for m, op in ops.items()
             for c, r in op.get("responses", {}).items()
             if c.startswith("2") and r.get("content", {}).get("application/json", {}).get("schema") == {}]
    assert empty == []


def test_the_routes_that_had_none():
    assert _ref("/api/v1/slip-verify/upload", "post") == {"$ref": "#/components/schemas/SlipUploadResult"}
    assert _ref("/api/v1/slip-verify/upload", "post", "422") == {"$ref": "#/components/schemas/SlipUploadResult"}
    assert _ref("/api/v1/slip-verify/checkslip", "post") == {"$ref": "#/components/schemas/SlipUploadResult"}
    assert _ref("/api/v1/slip-verify/{verification_id}") == {"$ref": "#/components/schemas/VerificationDetailRead"}
    assert _ref("/api/v1/slip-verify/order/{order_id}")["items"] == {"$ref": "#/components/schemas/VerificationOfOrder"}
    assert _ref("/api/v1/inventory/balances/{branch_id}/{product_id}") == {"$ref": "#/components/schemas/ProductBalance"}
    assert _ref("/api/v1/inventory/adjust", "post") == {"$ref": "#/components/schemas/MessageResponse"}
    assert _ref("/health/mongodb", code="503") == {"$ref": "#/components/schemas/MongoHealth"}
    google = SPEC["paths"]["/api/v1/auth/google"]["get"]["responses"]
    assert list(google) == ["302"] and "content" not in google["302"]


def test_catalog_products_lists_product_responses():
    assert _ref("/api/v1/catalog/products")["items"] == {"$ref": "#/components/schemas/ProductResponse"}
