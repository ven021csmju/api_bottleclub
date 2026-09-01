"""
Seed script for Bottle Club POS database.

Usage:
    python -m scripts.seed

Idempotent -- skips tables that already contain data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from dotenv import load_dotenv
from passlib.context import CryptContext

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# ---------------------------------------------------------------------------
# Permission definitions: (code, module, description)
# ---------------------------------------------------------------------------
PERMISSIONS: list[tuple[str, str, str]] = [
    ("users.read", "users", "View users"),
    ("users.create", "users", "Create users"),
    ("users.update", "users", "Update users"),
    ("users.delete", "users", "Delete users"),
    ("users.assign_roles", "users", "Assign roles to users"),
    ("roles.read", "roles", "View roles"),
    ("roles.create", "roles", "Create roles"),
    ("roles.update", "roles", "Update roles"),
    ("roles.delete", "roles", "Delete roles"),
    ("catalog.read", "catalog", "View products and categories"),
    ("catalog.create", "catalog", "Create and manage products/categories"),
    ("orders.create", "orders", "Create orders"),
    ("orders.read", "orders", "View orders"),
    ("orders.cancel", "orders", "Cancel orders"),
    ("orders.complete", "orders", "Complete orders"),
    ("orders.update", "orders", "Update order workflow status"),
    ("kds.kitchen.read", "kds", "View kitchen queue"),
    ("kds.kitchen.update", "kds", "Advance kitchen item status"),
    ("kds.bar.read", "kds", "View bar queue"),
    ("kds.bar.update", "kds", "Advance bar item status"),
    ("payments.create", "payments", "Process payments"),
    ("payments.read", "payments", "View payments"),
    ("payments.refund", "payments", "Process refunds"),
    ("refunds.read", "refunds", "View refunds"),
    ("returns.create", "returns", "Create returns"),
    ("returns.read", "returns", "View returns"),
    ("returns.process", "returns", "Process returns"),
    ("customers.read", "customers", "View customers"),
    ("customers.create", "customers", "Create customers"),
    ("customers.update", "customers", "Update customers"),
    ("customers.delete", "customers", "Delete customers"),
    ("loyalty.earn", "loyalty", "Issue loyalty points"),
    ("loyalty.redeem", "loyalty", "Redeem loyalty points"),
    ("loyalty.read", "loyalty", "View loyalty balances"),
    ("inventory.read", "inventory", "View inventory"),
    ("inventory.adjust", "inventory", "Adjust inventory"),
    ("purchases.read", "purchases", "View purchase orders"),
    ("purchases.create", "purchases", "Create purchase orders"),
    ("purchases.approve", "purchases", "Approve purchase orders"),
    ("purchases.receive", "purchases", "Receive purchases"),
    ("transfers.create", "transfers", "Create stock transfers"),
    ("transfers.read", "transfers", "View stock transfers"),
    ("transfers.approve", "transfers", "Approve stock transfers"),
    ("transfers.ship", "transfers", "Ship stock transfers"),
    ("transfers.receive", "transfers", "Receive stock transfers"),
    ("promotions.read", "promotions", "View promotions"),
    ("promotions.create", "promotions", "Create promotions"),
    ("promotions.update", "promotions", "Update promotions"),
    ("promotions.delete", "promotions", "Delete promotions"),
    ("coupons.read", "coupons", "View coupons"),
    ("coupons.create", "coupons", "Create coupons"),
    ("coupons.update", "coupons", "Update coupons"),
    ("coupons.delete", "coupons", "Delete coupons"),
    ("reports.sales", "reports", "View sales reports"),
    ("reports.read", "reports", "View general reports"),
    ("audit.read", "audit", "View audit logs"),
    ("settings.read", "settings", "View system settings"),
    ("settings.update", "settings", "Update system settings"),
    ("branches.read", "branches", "View branches"),
    ("branches.create", "branches", "Create branches"),
    ("branches.update", "branches", "Update branches"),
    ("branches.delete", "branches", "Delete branches"),
    ("shifts.open", "shifts", "Open shifts"),
    ("shifts.close", "shifts", "Close shifts"),
    ("shifts.cash_movement", "shifts", "Record cash movements"),
    ("shifts.read", "shifts", "View shifts"),
]

# Role -> list of permission codes
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "Superadmin": [p[0] for p in PERMISSIONS],  # everything
    "Manager": [
        "users.read", "users.create", "users.update", "users.assign_roles",
        "roles.read", "roles.create", "roles.update",
        "catalog.read", "catalog.create",
        "orders.create", "orders.read", "orders.cancel", "orders.complete", "orders.update",
        "payments.create", "payments.read", "payments.refund",
        "refunds.read",
        "returns.create", "returns.read", "returns.process",
        "customers.read", "customers.create", "customers.update", "customers.delete",
        "loyalty.earn", "loyalty.redeem", "loyalty.read",
        "inventory.read", "inventory.adjust",
        "purchases.read", "purchases.create", "purchases.approve", "purchases.receive",
        "transfers.create", "transfers.read", "transfers.approve", "transfers.ship", "transfers.receive",
        "promotions.read", "promotions.create", "promotions.update", "promotions.delete",
        "coupons.read", "coupons.create", "coupons.update", "coupons.delete",
        "reports.sales", "reports.read",
        "audit.read",
        "settings.read", "settings.update",
        "branches.read", "branches.create", "branches.update",
        "shifts.open", "shifts.close", "shifts.cash_movement", "shifts.read",
    ],
    "Cashier": [
        "orders.create", "orders.read", "orders.update", "orders.complete",
        "payments.create", "payments.read",
        "customers.read", "customers.create",
        "loyalty.earn", "loyalty.redeem", "loyalty.read",
        "inventory.read",
        "shifts.read",
        "returns.read",
        "coupons.read",
        "refunds.read",
    ],
    "Staff": [
        "orders.read", "orders.update",
        "payments.read",
        "customers.read",
        "inventory.read",
        "catalog.read",
        "shifts.read",
    ],
    "Kitchen": [
        "kds.kitchen.read", "kds.kitchen.update",
        "orders.read",
        "catalog.read",
    ],
    "Bar": [
        "kds.bar.read", "kds.bar.update",
        "orders.read",
        "catalog.read",
    ],
}

# Sample Thai beverage products
PRODUCTS: list[dict] = [
    {"name": "Chang Beer 640ml", "sku": "CHG-640", "selling_price": 60, "category": "Beer", "barcode": "8850999001016"},
    {"name": "Singha Beer 640ml", "sku": "SNG-640", "selling_price": 65, "category": "Beer", "barcode": "8850290001018"},
    {"name": "Leo Beer 640ml", "sku": "LEO-640", "selling_price": 55, "category": "Beer", "barcode": "8850186001015"},
    {"name": "Heineken Beer 330ml", "sku": "HNK-330", "selling_price": 55, "category": "Beer", "barcode": "8712000001019"},
    {"name": "Asahi Super Dry 350ml", "sku": "ASH-350", "selling_price": 70, "category": "Beer", "barcode": "4901777244101"},
    {"name": "Siam Winery White Wine 750ml", "sku": "SW-W750", "selling_price": 290, "category": "Wine", "barcode": "8851234001012"},
    {"name": "Mont Clair Red Wine 750ml", "sku": "MNC-R750", "selling_price": 350, "category": "Wine", "barcode": "8851234002019"},
    {"name": "Mekhong Whiskey 700ml", "sku": "MKH-700", "selling_price": 190, "category": "Spirits", "barcode": "8851061001018"},
    {"name": "SangSom Whiskey 700ml", "sku": "SNS-700", "selling_price": 180, "category": "Spirits", "barcode": "8850123001015"},
    {"name": "Thai Spirit 300ml", "sku": "TSP-300", "selling_price": 95, "category": "Spirits", "barcode": "8851061002015"},
    {"name": "Coca-Cola 330ml", "sku": "CC-330", "selling_price": 20, "category": "Non-Alcoholic", "barcode": "5000128301011"},
    {"name": "Sprite 330ml", "sku": "SPT-330", "selling_price": 20, "category": "Non-Alcoholic", "barcode": "5000128302018"},
    {"name": "Fanta Orange 330ml", "sku": "FNT-330", "selling_price": 20, "category": "Non-Alcoholic", "barcode": "5000128303015"},
    {"name": "Namthip Water 600ml", "sku": "NTP-600", "selling_price": 7, "category": "Non-Alcoholic", "barcode": "8850999003010"},
    {"name": "Lays Classic Chips 63g", "sku": "LYS-063", "selling_price": 35, "category": "Snacks", "barcode": "8851123001012"},
    {"name": " Nori Seaweed Snack 25g", "sku": "NRI-025", "selling_price": 45, "category": "Snacks", "barcode": "8851123002019"},
    {"name": "Peanut Butter Wings 35g", "sku": "WNG-035", "selling_price": 15, "category": "Snacks", "barcode": "8851123003016"},
]

SUPPLIERS: list[dict] = [
    {"name": "Thai Beverage Public Co.", "contact_name": "Somchai Jaidee", "phone": "02-123-4567", "email": "info@thaibev.co.th"},
    {"name": "Boon Rawd Brewery", "contact_name": "Prasert Prasert", "phone": "02-298-1111", "email": "sales@boonrawd.co.th"},
    {"name": "Carabao Group", "contact_name": "Chaiwat Wongthong", "phone": "02-345-6789", "email": "order@carabao.com"},
]


def table_empty(cur: psycopg.Cursor, table: str) -> bool:
    cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
    return cur.fetchone() is None


def seed(conn: psycopg.Connection) -> None:
    cur = conn.cursor()

    # --- Organization ---
    if table_empty(cur, "organizations"):
        cur.execute(
            """INSERT INTO organizations (name, slug, phone, address, is_active)
               VALUES (%s, %s, %s, %s, true) RETURNING id""",
            ("The Bottle Club", "bottle-club", "02-123-4567", "123 Sukhumvit Road, Bangkok 10110"),
        )
        org_id = cur.fetchone()[0]
        print(f"  [+] Organization  id={org_id}  'The Bottle Club'")
    else:
        cur.execute("SELECT id FROM organizations WHERE slug = %s", ("bottle-club",))
        org_id = cur.fetchone()[0]
        print(f"  [=] Organization  id={org_id}  already exists")

    # --- Branch ---
    if table_empty(cur, "branches"):
        cur.execute(
            """INSERT INTO branches (organization_id, name, code, phone, address, is_active)
               VALUES (%s, %s, %s, %s, %s, true) RETURNING id""",
            (org_id, "Main Branch", "MNB", "02-123-4568", "123 Sukhumvit Road, Bangkok 10110"),
        )
        branch_id = cur.fetchone()[0]
        print(f"  [+] Branch       id={branch_id}  'Main Branch'")
    else:
        cur.execute("SELECT id FROM branches WHERE code = %s", ("MNB",))
        branch_id = cur.fetchone()[0]
        print(f"  [=] Branch       id={branch_id}  already exists")

    # --- Permissions ---
    if table_empty(cur, "permissions"):
        perm_ids: dict[str, int] = {}
        for code, module, desc in PERMISSIONS:
            cur.execute(
                "INSERT INTO permissions (code, module, description) VALUES (%s, %s, %s) RETURNING id",
                (code, module, desc),
            )
            perm_ids[code] = cur.fetchone()[0]
        print(f"  [+] Permissions  {len(PERMISSIONS)} created")
    else:
        cur.execute("SELECT id, code FROM permissions")
        perm_ids = {code: pid for pid, code in cur.fetchall()}
        print(f"  [=] Permissions  {len(perm_ids)} already exist")

    # --- Roles (idempotent upsert: create any missing roles) ---
    role_descriptions = {
        "Superadmin": "Full system access with all permissions",
        "Manager": "Branch management with most operational permissions",
        "Cashier": "Point-of-sale operations and basic customer management",
        "Staff": "Basic read-only access",
        "Kitchen": "Kitchen station queue operations",
        "Bar": "Bar station queue operations",
    }
    if table_empty(cur, "roles"):
        role_ids: dict[str, int] = {}
        for role_name in ROLE_PERMISSIONS:
            cur.execute(
                """INSERT INTO roles (organization_id, name, description, is_system)
                   VALUES (%s, %s, %s, true) RETURNING id""",
                (org_id, role_name, role_descriptions.get(role_name)),
            )
            role_ids[role_name] = cur.fetchone()[0]
        print(f"  [+] Roles        {len(ROLE_PERMISSIONS)} created")

        # Assign permissions to roles
        for role_name, perm_codes in ROLE_PERMISSIONS.items():
            for code in perm_codes:
                if code in perm_ids:
                    cur.execute(
                        "INSERT INTO role_permissions (role_id, permission_id) VALUES (%s, %s)",
                        (role_ids[role_name], perm_ids[code]),
                    )
        print(f"  [+] Role-Permission assignments created")
    else:
        cur.execute("SELECT id, name FROM roles WHERE organization_id = %s", (org_id,))
        role_ids = {name: rid for rid, name in cur.fetchall()}
        # Upsert any roles not yet present (e.g. Kitchen / Bar on existing installs).
        created = 0
        for role_name in ROLE_PERMISSIONS:
            if role_name in role_ids:
                continue
            cur.execute(
                """INSERT INTO roles (organization_id, name, description, is_system)
                   VALUES (%s, %s, %s, true) RETURNING id""",
                (org_id, role_name, role_descriptions.get(role_name)),
            )
            role_ids[role_name] = cur.fetchone()[0]
            created += 1
        if created:
            print(f"  [+] Roles        {created} missing roles created")
        else:
            print(f"  [=] Roles        already exist")

    # --- Ensure missing permission codes + role-permission assignments (idempotent) ---
    cur.execute("SELECT id, code FROM permissions")
    known_perms = {code: pid for pid, code in cur.fetchall()}
    added = 0
    for code, module, desc in PERMISSIONS:
        if code in known_perms:
            continue
        cur.execute(
            "INSERT INTO permissions (code, module, description) VALUES (%s, %s, %s) RETURNING id",
            (code, module, desc),
        )
        known_perms[code] = cur.fetchone()[0]
        added += 1
    if added:
        print(f"  [+] Permissions  {added} missing codes inserted")
        for role_name, perm_codes in ROLE_PERMISSIONS.items():
            for code in perm_codes:
                perm_id = known_perms.get(code)
                if perm_id is None:
                    continue
                cur.execute(
                    """SELECT 1 FROM role_permissions rp
                       JOIN roles r ON r.id = rp.role_id
                       WHERE r.organization_id = %s AND r.name = %s AND rp.permission_id = %s""",
                    (org_id, role_name, perm_id),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        """INSERT INTO role_permissions (role_id, permission_id)
                           SELECT id, %s FROM roles
                           WHERE organization_id = %s AND name = %s""",
                        (perm_id, org_id, role_name),
                    )

    # --- Admin User ---
    admin_user_id: int | None = None
    if table_empty(cur, "users"):
        password_hash = pwd_context.hash("admin123")
        cur.execute(
            """INSERT INTO users
               (organization_id, username, email, password_hash, display_name, status, is_superadmin)
               VALUES (%s, %s, %s, %s, %s, 'active', true) RETURNING id""",
            (org_id, "admin", "admin@bottleclub.com", password_hash, "System Admin"),
        )
        admin_user_id = cur.fetchone()[0]
        print(f"  [+] User         id={admin_user_id}  'admin' / 'admin123'")

        # Assign superadmin role
        cur.execute(
            "INSERT INTO user_roles (user_id, role_id, branch_id) VALUES (%s, %s, %s)",
            (admin_user_id, role_ids["Superadmin"], branch_id),
        )
        print(f"  [+] UserRole     admin -> Superadmin @ Main Branch")

        # --- Ven User ---
        ven_password_hash = pwd_context.hash("0217")
        cur.execute(
            """INSERT INTO users
               (organization_id, username, email, password_hash, display_name, status, is_superadmin)
               VALUES (%s, %s, %s, %s, %s, 'active', false) RETURNING id""",
            (org_id, "ven", "ven@bottleclub.com", ven_password_hash, "Ven User"),
        )
        ven_user_id = cur.fetchone()[0]
        print(f"  [+] User         id={ven_user_id}  'ven' / '0217'")

        cur.execute(
            "INSERT INTO user_roles (user_id, role_id, branch_id) VALUES (%s, %s, %s)",
            (ven_user_id, role_ids["Cashier"], branch_id),
        )
        print(f"  [+] UserRole     ven -> Cashier @ Main Branch")
    else:
        cur.execute("SELECT id FROM users WHERE username = %s", ("admin",))
        row = cur.fetchone()
        if row:
            admin_user_id = row[0]
        print(f"  [=] Users        already exist")

        # --- Ven User (add if missing) ---
        cur.execute("SELECT id FROM users WHERE username = %s", ("ven",))
        if cur.fetchone() is None:
            ven_password_hash = pwd_context.hash("0217")
            cur.execute(
                """INSERT INTO users
                   (organization_id, username, email, password_hash, display_name, status, is_superadmin)
                   VALUES (%s, %s, %s, %s, %s, 'active', false) RETURNING id""",
                (org_id, "ven", "ven@bottleclub.com", ven_password_hash, "Ven User"),
            )
            ven_user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO user_roles (user_id, role_id, branch_id) VALUES (%s, %s, %s)",
                (ven_user_id, role_ids["Cashier"], branch_id),
            )
            print(f"  [+] User         id={ven_user_id}  'ven' / '0217' -> Cashier")

    # --- Categories ---
    cat_ids: dict[str, int] = {}
    if table_empty(cur, "categories"):
        for idx, name in enumerate(["Beer", "Wine", "Spirits", "Non-Alcoholic", "Snacks"]):
            cur.execute(
                """INSERT INTO categories (organization_id, name, sort_order, is_active)
                   VALUES (%s, %s, %s, true) RETURNING id""",
                (org_id, name, idx),
            )
            cat_ids[name] = cur.fetchone()[0]
        print(f"  [+] Categories   5 created")
    else:
        cur.execute("SELECT id, name FROM categories WHERE organization_id = %s", (org_id,))
        cat_ids = {name: cid for cid, name in cur.fetchall()}
        print(f"  [=] Categories   already exist")

    # --- Suppliers ---
    supplier_ids: list[int] = []
    if table_empty(cur, "suppliers"):
        for s in SUPPLIERS:
            cur.execute(
                """INSERT INTO suppliers (organization_id, name, contact_name, phone, email, is_active)
                   VALUES (%s, %s, %s, %s, %s, true) RETURNING id""",
                (org_id, s["name"], s["contact_name"], s["phone"], s["email"]),
            )
            supplier_ids.append(cur.fetchone()[0])
        print(f"  [+] Suppliers    {len(SUPPLIERS)} created")
    else:
        cur.execute("SELECT id FROM suppliers WHERE organization_id = %s", (org_id,))
        supplier_ids = [row[0] for row in cur.fetchall()]
        print(f"  [=] Suppliers    already exist")

    # --- Products ---
    product_ids: list[int] = []
    if table_empty(cur, "products"):
        for p in PRODUCTS:
            cur.execute(
                """INSERT INTO products
                   (organization_id, category_id, name, sku, barcode, selling_price, unit, is_active, track_inventory)
                   VALUES (%s, %s, %s, %s, %s, %s, 'each', true, true) RETURNING id""",
                (org_id, cat_ids.get(p["category"]), p["name"], p["sku"], p["barcode"], p["selling_price"]),
            )
            product_ids.append(cur.fetchone()[0])
        print(f"  [+] Products     {len(PRODUCTS)} created")

        # Link first 3 products to first supplier
        for pid in product_ids[:3]:
            cur.execute(
                """INSERT INTO supplier_products (supplier_id, product_id, cost_price, supplier_sku)
                   VALUES (%s, %s, %s, %s)""",
                (supplier_ids[0], pid, 40.00, f"SP-{pid}"),
            )
        print(f"  [+] SupplierProducts 3 links created")
    else:
        cur.execute("SELECT id FROM products WHERE organization_id = %s", (org_id,))
        product_ids = [row[0] for row in cur.fetchall()]
        print(f"  [=] Products     already exist")

    # --- Register ---
    if table_empty(cur, "registers"):
        cur.execute(
            """INSERT INTO registers (branch_id, name, is_active) VALUES (%s, %s, true)""",
            (branch_id, "Register 1"),
        )
        print(f"  [+] Register     'Register 1' @ Main Branch")
    else:
        print(f"  [=] Registers    already exist")

    # --- System Settings ---
    if table_empty(cur, "system_settings"):
        settings_data = [
            ("tax_rate", "0", "number", "Tax rate percentage (0 = no tax)"),
            ("currency", "THB", "string", "Currency code"),
            ("loyalty_points_per_baht", "1", "number", "Loyalty points earned per 1 THB spent"),
        ]
        for key, value, vtype, desc in settings_data:
            cur.execute(
                """INSERT INTO system_settings (organization_id, key, value, value_type, description)
                   VALUES (%s, %s, %s, %s, %s)""",
                (org_id, key, value, vtype, desc),
            )
        print(f"  [+] SystemSettings 3 created")
    else:
        print(f"  [=] SystemSettings already exist")

    conn.commit()
    cur.close()

    # --- Summary ---
    print("\n" + "=" * 56)
    print(" SEED COMPLETE")
    print("=" * 56)
    print(f" Organization : The Bottle Club  (slug: bottle-club)")
    print(f" Branch       : Main Branch      (code: MNB)")
    print(f" Admin login  : admin / admin123")
    print(f" Test login   : ven / 0217")
    print(f" Roles        : Superadmin, Manager, Cashier, Staff, Kitchen, Bar")
    print(f" Categories   : Beer, Wine, Spirits, Non-Alcoholic, Snacks")
    print(f" Suppliers    : {len(SUPPLIERS)}")
    print(f" Products     : {len(PRODUCTS)}")
    print(f" Currency     : THB")
    print("=" * 56)


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment or .env file")
        sys.exit(1)

    database_url = database_url.replace("postgresql+psycopg://", "postgresql://")

    print(f"Connecting to database...")
    with psycopg.connect(database_url) as conn:
        print("Connected. Seeding data...\n")
        seed(conn)
        print("\nDone.")


if __name__ == "__main__":
    main()
