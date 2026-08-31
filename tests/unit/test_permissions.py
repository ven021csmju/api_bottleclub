from app.shared.permissions import (
    CONTRACT_PERMISSIONS,
    contract_code,
    normalize_permission,
)


class TestNormalizePermission:
    def test_contract_style_maps_to_internal(self):
        assert normalize_permission("USER.READ") == "users.read"
        assert normalize_permission("ROLE.CREATE") == "roles.create"
        assert normalize_permission("COUPON.UPDATE") == "coupons.update"
        assert normalize_permission("ORDER.CANCEL") == "orders.cancel"

    def test_internal_style_is_preserved(self):
        assert normalize_permission("users.read") == "users.read"
        assert normalize_permission("orders.cancel") == "orders.cancel"

    def test_unknown_contract_code_lowercases(self):
        assert normalize_permission("FOO.BAR") == "foo.bar"

    def test_contract_mapping_covers_spec_modules(self):
        required = {
            "USER.READ",
            "USER.ASSIGN_ROLE",
            "ROLE.ASSIGN_PERMISSION",
            "BRANCH.UPDATE",
            "REGISTER.READ",
            "SHIFT.CLOSE",
            "PRODUCT.READ",
            "INVENTORY.ADJUST",
            "PURCHASE.RECEIVE",
            "TRANSFER.SHIP",
            "ORDER.READ",
            "PAYMENT.REFUND",
            "CUSTOMER.CREATE",
            "LOYALTY.ADJUST",
            "PROMOTION.UPDATE",
            "COUPON.UPDATE",
            "REPORT.LOYALTY",
            "SYSTEM.AUDIT_LOG",
            "SYSTEM.UPDATE",
        }
        assert required.issubset(CONTRACT_PERMISSIONS.keys())

    def test_round_trip(self):
        assert normalize_permission(contract_code("users.read")) == "users.read"

    def test_system_codes_covered(self):
        assert CONTRACT_PERMISSIONS["SYSTEM.AUDIT_LOG"] == "audit.read"
        assert CONTRACT_PERMISSIONS["SYSTEM.READ"] == "settings.read"
        assert CONTRACT_PERMISSIONS["SYSTEM.UPDATE"] == "settings.update"

    def test_order_workflow_mapping(self):
        assert CONTRACT_PERMISSIONS["ORDER.UPDATE"] == "orders.update"