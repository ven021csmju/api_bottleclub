"""scripts/import_master_data.py, offline: reading, checking and planning (Phase 47).

Every wrong row is reported with its file and row number before anything is
written; money is Decimal; a file read again against what it made plans
nothing. The API is replaced by a World of what "already exists".
"""
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("import_master_data", ROOT / "scripts" / "import_master_data.py")
imd = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = imd  # dataclasses look their module up
_spec.loader.exec_module(imd)


def _write(folder: Path, name: str, text: str, bom: bool = True) -> Path:
    path = folder / name
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


def _empty_world(**kw) -> "imd.World":
    base = dict(branches={}, categories={}, products={}, product_by_barcode={}, costs={},
                registers=set(), inactive_registers=set())
    base.update(kw)
    return imd.World(**base)


def _plan(folder: Path, world=None):
    problems = imd.Problems()
    files = imd.read_files(folder, problems)
    plan = imd.build_plan(files, world or _empty_world(), problems)
    return plan, problems


def test_the_templates_are_clean_and_plan_everything(tmp_path):
    for path in (ROOT / "scripts" / "import_templates").glob("*.csv"):
        if path.name in imd.COLUMNS:
            (tmp_path / path.name).write_bytes(path.read_bytes())
    plan, problems = _plan(tmp_path, _empty_world(roles={"Manager": 2, "Cashier": 3, "Kitchen": 4, "Bar": 5}))
    assert not problems, problems.report()
    assert {c.action for c in plan} == {"create"}
    assert sum(c.file == "products.csv" for c in plan) == 3
    assert sum(c.file == "staff.csv" for c in plan) == 2  # cashier_mnb1 has two rows: one account
    for path in (ROOT / "scripts" / "import_templates").glob("*.csv"):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), path.name  # Excel opens it as UTF-8


def test_cells_are_trimmed_and_empty_rows_skipped_rows_keep_their_excel_number(tmp_path):
    _write(tmp_path, "branches.csv", " code , name ,phone\n  MNB ,  สาขาหลัก  ,\n,,\n\nSKV,สุขุมวิท,02\n")
    problems = imd.Problems()
    rows = imd.read_csv(tmp_path / "branches.csv", problems)
    assert not problems
    assert [(r.line, r["code"], r["name"]) for r in rows] == [(2, "MNB", "สาขาหลัก"), (5, "SKV", "สุขุมวิท")]


def test_columns_unknown_missing_or_twice(tmp_path):
    _write(tmp_path, "products.csv", "sku,name,price,name\nA,x,1,y\n")
    problems = imd.Problems()
    imd.read_csv(tmp_path / "products.csv", problems)
    messages = [m for _, _, m in problems.items]
    assert any("ไม่รู้จักคอลัมน์ 'price'" in m for m in messages)
    assert any("ไม่มีคอลัมน์ 'selling_price'" in m for m in messages)
    assert any("คอลัมน์ 'name' ซ้ำ" in m for m in messages)


@pytest.mark.parametrize("text, positive, expected", [
    ("1250", True, Decimal("1250.00")), ("1250.5", True, Decimal("1250.50")), ("1,250.00", True, Decimal("1250.00")),
    ("12,345,678.90", True, Decimal("12345678.90")), ("0", False, Decimal("0.00")), ("", True, None),
])
def test_money_is_decimal(text, positive, expected):
    problems = imd.Problems()
    value = imd.money(imd.Row("products.csv", 2, {"selling_price": text}), "selling_price", problems, positive=positive)
    assert (value, problems.items) == (expected, [])
    assert value is None or type(value) is Decimal


@pytest.mark.parametrize("text, positive", [
    ("1.234", False), ("abc", False), ("-5", False), ("0", True), ("1,25", False), ("1e3", False), ("฿100", False),
    ("12,34,567", False), ("NaN", False),
])
def test_money_refused(text, positive):
    problems = imd.Problems()
    assert imd.money(imd.Row("products.csv", 7, {"cost_price": text}), "cost_price", problems, positive=positive) is None
    assert [line for _, line, _ in problems.items] == [7]


def test_every_wrong_row_is_reported_with_its_row(tmp_path):
    _write(tmp_path, "categories.csv", "name,station,sort_order\nไวน์,bar,1\nไวน์,kitchen,2\nอาหาร,grill,x\n")
    _write(tmp_path, "products.csv", "sku,name,category,selling_price,cost_price,barcode\n"
                                     "A1,Wine,ไวน์,100,50,111\n"
                                     "A1,Wine again,ไวน์,100,,222\n"
                                     "B1,Beer,เบียร์,0,1.234,111\n"
                                     ",No sku,,10,,\n")
    _write(tmp_path, "registers.csv", "branch,name\nZZZ,Till\n")
    plan, problems = _plan(tmp_path)
    found = {(f, line) for f, line, _ in problems.items}
    assert found == {
        ("categories.csv", 3),  # the same name again
        ("categories.csv", 4),  # station grill, sort_order x
        ("products.csv", 3),    # sku A1 again
        ("products.csv", 4),    # barcode 111 again, no category เบียร์, price 0, cost 3 places
        ("products.csv", 5),    # no sku
        ("registers.csv", 2),   # no branch ZZZ
    }, problems.report()
    assert len([1 for f, line, _ in problems.items if (f, line) == ("products.csv", 4)]) == 4


def test_a_barcode_of_another_product_in_the_system(tmp_path):
    _write(tmp_path, "products.csv", "sku,name,selling_price,barcode\nNEW,New,10,999\n")
    world = _empty_world(products={"OLD": {"id": 1, "sku": "OLD", "barcode": "999"}},
                         product_by_barcode={"999": {"id": 1, "sku": "OLD", "barcode": "999"}})
    _, problems = _plan(tmp_path, world)
    assert [m for _, _, m in problems.items] == ["barcode '999' เป็นของสินค้า OLD ในระบบแล้ว"]


def _existing_world() -> "imd.World":
    return _empty_world(
        branches={"MNB": {"id": 1, "code": "MNB", "name": "สาขาหลัก", "phone": "02", "address": "เดิม"}},
        categories={"ไวน์": {"id": 5, "name": "ไวน์", "station": "bar", "sort_order": 1, "description": None}},
        products={"A1": {"id": 9, "sku": "A1", "name": "Wine", "selling_price": "100.00", "unit": "bottle",
                         "station": None, "barcode": "111", "category_id": 5}},
        product_by_barcode={"111": {"id": 9, "sku": "A1", "barcode": "111"}},
        costs={"A1": Decimal("50.00")},
        registers={("MNB", "Till 1")},
    )


def test_the_same_files_again_change_nothing(tmp_path):
    _write(tmp_path, "branches.csv", "code,name,phone,address\nMNB,สาขาหลัก,,\n")  # empty: keep
    _write(tmp_path, "categories.csv", "name,station,sort_order\nไวน์,bar,1\n")
    _write(tmp_path, "products.csv", "sku,name,category,selling_price,cost_price,unit,station,barcode\n"
                                     "A1,Wine,ไวน์,100,50.00,bottle,,111\n")
    _write(tmp_path, "registers.csv", "branch,name\nMNB,Till 1\n")
    plan, problems = _plan(tmp_path, _existing_world())
    assert not problems, problems.report()
    assert [c.action for c in plan] == ["same", "same", "same", "same"]


def test_a_changed_row_is_an_update_of_only_what_changed(tmp_path):
    _write(tmp_path, "products.csv", "sku,name,category,selling_price,cost_price,station\n"
                                     "A1,Wine,ไวน์,120,,kitchen\n")  # cost empty: kept
    plan, problems = _plan(tmp_path, _existing_world())
    assert not problems, problems.report()
    (change,) = plan
    assert (change.action, change.target_id) == ("update", 9)
    assert change.payload == {"selling_price": Decimal("120.00"), "station": "kitchen"}
    assert type(change.payload["selling_price"]) is Decimal


def test_a_new_category_of_a_product_is_set_when_written(tmp_path):
    _write(tmp_path, "categories.csv", "name\nแดง\n")
    _write(tmp_path, "products.csv", "sku,name,category,selling_price\nA1,Wine,แดง,100\n")
    plan, problems = _plan(tmp_path, _existing_world())
    assert not problems, problems.report()
    product = plan[-1]
    assert (product.action, product.extra) == ("update", {"category": "แดง"})


def test_a_new_product_gets_cost_zero_and_the_categorys_station(tmp_path):
    _write(tmp_path, "products.csv", "sku,name,selling_price\nN1,New,10\n")
    (change,), problems = _plan(tmp_path)
    assert not problems
    assert change.payload == {"sku": "N1", "name": "New", "selling_price": Decimal("10.00"), "station": None,
                              "cost_price": Decimal("0.00")}


def test_a_closed_register_is_left_closed(tmp_path):
    _write(tmp_path, "registers.csv", "branch,name\nMNB,Old till\n")
    world = _existing_world()
    world.inactive_registers.add(("MNB", "Old till"))
    (change,), _ = _plan(tmp_path, world)
    assert change.action == "same" and change.shown


def test_not_utf8_is_one_clear_problem(tmp_path):
    (tmp_path / "branches.csv").write_bytes("code,name\nMNB,สาขา\n".encode("cp874"))
    problems = imd.Problems()
    imd.read_csv(tmp_path / "branches.csv", problems)
    assert [m for _, _, m in problems.items] == ["ไม่ใช่ UTF-8: บันทึกเป็น 'CSV UTF-8' ใน Excel"]


def test_only_https_or_local(tmp_path):
    with pytest.raises(SystemExit):
        imd.main(["--api", "http://api.wayneven.uk", "--dir", str(tmp_path), "--username", "sa"])


# --------------------------------------------------------------------------- staff (item 3)

ROLES = {"Superadmin": 1, "Manager": 2, "Cashier": 3, "Kitchen": 4, "Bar": 5}


def _staff_world(**users) -> "imd.World":
    world = _existing_world()
    world.roles = dict(ROLES)
    world.users = users
    return world


STAFF_HEADER = "username,display_name,email,role,branch,phone\n"


def test_one_person_many_rows_is_one_account_with_its_roles(tmp_path):
    _write(tmp_path, "staff.csv", STAFF_HEADER + "cash1,แคชเชียร์,c1@example.com,Cashier,MNB,\n"
                                                  "cash1,แคชเชียร์,c1@example.com,Bar,,\n")
    (change,), problems = _plan(tmp_path, _staff_world())
    assert not problems, problems.report()
    assert change.action == "create"
    assert change.payload == {"username": "cash1", "display_name": "แคชเชียร์", "email": "c1@example.com"}
    assert change.extra["roles"] == [("Cashier", "MNB"), ("Bar", None)]
    assert "password" not in str(change.payload)


def test_staff_problems_each_with_its_row(tmp_path):
    _write(tmp_path, "staff.csv", STAFF_HEADER
           + "boss,Boss,boss@example.com,Superadmin,,\n"       # 2: not importable
           + "a.b,A,a@example.com,Cashier,NOPE,\n"             # 3: no branch
           + "a.b,A other,a@example.com,Cashier,MNB,\n"        # 4: another name for a.b
           + "a.b,A,a@example.com,Cashier,NOPE,\n"             # 5: same role/branch again (and no branch)
           + "c d,C,not-an-email,Waiter,,\n"                   # 6: username, email, role
           + "e,E,a@example.com,Kitchen,,\n"                   # 7: a.b's email
           + "f,F,owner@example.com,Bar,,\n")                  # 8: another account's email in the system
    world = _staff_world(owner={"id": 50, "username": "owner", "email": "Owner@Example.com", "roles": []})
    _, problems = _plan(tmp_path, world)
    assert {line for _, line, _ in problems.items} == {2, 3, 4, 5, 6, 7, 8}, problems.report()


def test_an_existing_superadmin_is_not_touched(tmp_path):
    _write(tmp_path, "staff.csv", STAFF_HEADER + "root,Root,root@example.com,Manager,,\n")
    world = _staff_world(root={"id": 1, "username": "root", "email": "root@example.com", "display_name": "Root",
                               "is_superadmin": True, "roles": [{"role_id": 1, "branch_id": None}]})
    _, problems = _plan(tmp_path, world)
    assert [m for _, _, m in problems.items] == ["root เป็น Superadmin ในระบบ: ไฟล์นี้ไม่แก้บัญชี Superadmin"]


def test_an_existing_account_gets_what_changed_and_its_missing_roles_none_removed(tmp_path):
    _write(tmp_path, "staff.csv", STAFF_HEADER + "cash1,ชื่อใหม่,c1@example.com,Cashier,MNB,\n"
                                                  "cash1,ชื่อใหม่,c1@example.com,Bar,MNB,\n")
    world = _staff_world(cash1={"id": 7, "username": "cash1", "email": "c1@example.com", "display_name": "ชื่อเดิม",
                                "phone": "081", "is_superadmin": False,
                                "roles": [{"role_id": 3, "branch_id": 1}, {"role_id": 4, "branch_id": None}]})
    (change,), problems = _plan(tmp_path, world)
    assert not problems, problems.report()
    assert (change.action, change.target_id, change.payload) == ("update", 7, {"display_name": "ชื่อใหม่"})
    assert change.extra["roles"] == [("Bar", "MNB")]          # added
    assert any("Kitchen@ทุกสาขา" in s and "ไม่ถอด" in s for s in change.shown)  # reported, kept


def test_the_same_staff_file_again_changes_nothing(tmp_path):
    _write(tmp_path, "staff.csv", STAFF_HEADER + "cash1,แคชเชียร์,c1@example.com,Cashier,MNB,081\n")
    world = _staff_world(cash1={"id": 7, "username": "cash1", "email": "c1@example.com", "display_name": "แคชเชียร์",
                                "phone": "081", "is_superadmin": False, "roles": [{"role_id": 3, "branch_id": 1}]})
    (change,), problems = _plan(tmp_path, world)
    assert (change.action, problems.items) == ("same", [])


def test_the_password_file_is_new_600_under_home_and_outside_git(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setattr(imd.Path, "home", classmethod(lambda cls: home))
    assert imd.check_password_path(home / "p.tsv") is None
    assert "ใต้" in imd.check_password_path(tmp_path / "elsewhere.tsv")
    assert "git" in imd.check_password_path(home / "repo" / "p.tsv")
    (home / "old.tsv").write_text("x")
    assert "อยู่แล้ว" in imd.check_password_path(home / "old.tsv")

    file = imd.PasswordFile(home / "p.tsv")
    file.add("cash1", "Secret-Temp-1", "2026-11-02T10:00:00+07:00")
    file.close()
    assert oct((home / "p.tsv").stat().st_mode & 0o777) == "0o600"
    assert (home / "p.tsv").read_text().splitlines()[1].split("\t")[:2] == ["cash1", "Secret-Temp-1"]
    with pytest.raises(FileExistsError):  # never over an existing file
        again = imd.PasswordFile(home / "p.tsv")
        again.add("x", "y", "")


def test_no_staff_file_no_password_file(tmp_path):
    file = imd.PasswordFile(tmp_path / "never.tsv")
    file.close()
    assert not (tmp_path / "never.tsv").exists()
