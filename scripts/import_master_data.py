#!/usr/bin/env python3
"""Import the shop's master data from CSV through the API (Phase 47).

    python3 scripts/import_master_data.py --api https://api.wayneven.uk \\
        --dir ~/bottleclub-prod/import --username <superadmin> [--apply]

Files (all optional; templates and their Thai README in scripts/import_templates/):
branches.csv, categories.csv, products.csv, registers.csv, staff.csv.

- Reads every file and checks every row first (and the rows against what the
  API already has); one wrong row and nothing is written: each problem is
  listed with its file and row number (the header is row 1, as in Excel).
- Writes only through the API, as a Superadmin whose password is asked with
  getpass. Without --apply (the default) it writes nothing: it shows what
  --apply would create and change.
- Runs again safely: a row whose code / name / sku / (branch, name) /
  username exists is brought in line with the file, never made twice; the
  same files again change nothing. Nothing is deleted. An optional cell left
  empty keeps the existing value (a new row gets the default), except a
  product's station: empty = the category's.
- Money is Decimal (at most 2 places), never float; cells are trimmed.

Standard library only: runs with the system python3, no venv.
Exit status: 0 done (or nothing to do), 1 problems in the files, 2 the API refused.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

STATIONS = ("none", "kitchen", "bar")

#: file -> (required columns, optional columns)
COLUMNS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "branches.csv": (("code", "name"), ("phone", "address")),
    "categories.csv": (("name",), ("station", "sort_order", "description")),
    "products.csv": (("sku", "name", "selling_price"), ("category", "cost_price", "unit", "station", "barcode")),
    "registers.csv": (("branch", "name"), ()),
}
#: the order the files are read and written in (later files refer to earlier ones)
ORDER = tuple(COLUMNS)

MAX_LENGTH = {
    ("branches.csv", "code"): 50, ("branches.csv", "name"): 255, ("branches.csv", "phone"): 50,
    ("categories.csv", "name"): 255,
    ("products.csv", "sku"): 100, ("products.csv", "name"): 255, ("products.csv", "unit"): 20,
    ("products.csv", "barcode"): 255, ("products.csv", "category"): 255,
    ("registers.csv", "name"): 100, ("registers.csv", "branch"): 50,
}
CODE = re.compile(r"[A-Za-z0-9_-]+")
PLAIN_NUMBER = re.compile(r"\d+(\.\d+)?")
GROUPED_NUMBER = re.compile(r"\d{1,3}(,\d{3})+(\.\d+)?")


# --------------------------------------------------------------------------- reading


@dataclass
class Row:
    file: str
    line: int  # as Excel shows it: the header is row 1
    cells: dict[str, str]

    def __getitem__(self, column: str) -> str:
        return self.cells.get(column, "")


@dataclass
class Problems:
    items: list[tuple[str, int, str]] = field(default_factory=list)

    def add(self, file: str, line: int, message: str) -> None:
        self.items.append((file, line, message))

    def __bool__(self) -> bool:
        return bool(self.items)

    def report(self) -> str:
        return "\n".join(f"  {file} แถว {line}: {message}" for file, line, message in sorted(self.items))


def read_csv(path: Path, problems: Problems) -> list[Row]:
    name = path.name
    required, optional = COLUMNS[name]
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            problems.add(name, 1, "ไฟล์ว่าง (ไม่มีหัวคอลัมน์)")
            return []
        except UnicodeDecodeError:
            problems.add(name, 1, "ไม่ใช่ UTF-8: บันทึกเป็น 'CSV UTF-8' ใน Excel")
            return []
        for column in sorted(set(header) - set(required) - set(optional) - {""}):
            problems.add(name, 1, f"ไม่รู้จักคอลัมน์ '{column}' (มีได้: {', '.join(required + optional)})")
        for column in required:
            if column not in header:
                problems.add(name, 1, f"ไม่มีคอลัมน์ '{column}' ที่บังคับ")
        for column in {h for h in header if header.count(h) > 1 and h}:
            problems.add(name, 1, f"คอลัมน์ '{column}' ซ้ำ")
        rows = []
        try:
            for number, values in enumerate(reader, start=2):
                values = [v.strip() for v in values]
                if not any(values):
                    continue
                if len(values) > len(header) and any(values[len(header):]):
                    problems.add(name, number, "มีค่าเกินจำนวนคอลัมน์")
                cells = {h: (values[i] if i < len(values) else "") for i, h in enumerate(header) if h}
                rows.append(Row(name, number, cells))
        except UnicodeDecodeError:
            problems.add(name, 1, "ไม่ใช่ UTF-8: บันทึกเป็น 'CSV UTF-8' ใน Excel")
        return rows


def money(row: Row, column: str, problems: Problems, *, positive: bool) -> Decimal | None:
    """A baht amount: 1250 / 1250.00 / 1,250.00; at most 2 places. None: empty or wrong."""
    text = row[column]
    if not text:
        return None
    plain = text.replace(",", "") if GROUPED_NUMBER.fullmatch(text) else text
    if not PLAIN_NUMBER.fullmatch(plain):
        problems.add(row.file, row.line, f"{column} '{text}' ไม่ใช่จำนวนเงิน (เช่น 1250.00)")
        return None
    try:
        value = Decimal(plain)
    except InvalidOperation:
        problems.add(row.file, row.line, f"{column} '{text}' ไม่ใช่จำนวนเงิน")
        return None
    if value.as_tuple().exponent < -2:
        problems.add(row.file, row.line, f"{column} '{text}' มีทศนิยมเกิน 2 ตำแหน่ง")
        return None
    if positive and value <= 0:
        problems.add(row.file, row.line, f"{column} ต้องมากกว่า 0")
        return None
    return value.quantize(Decimal("0.01"))


def check_lengths(row: Row, problems: Problems) -> None:
    for (file, column), limit in MAX_LENGTH.items():
        if file == row.file and len(row[column]) > limit:
            problems.add(row.file, row.line, f"{column} ยาวเกิน {limit} ตัวอักษร")


def check_required(row: Row, problems: Problems) -> bool:
    missing = [c for c in COLUMNS[row.file][0] if not row[c]]
    for column in missing:
        problems.add(row.file, row.line, f"{column} ว่าง (บังคับ)")
    return not missing


def station(row: Row, problems: Problems) -> str | None:
    value = row["station"].lower()
    if value and value not in STATIONS:
        problems.add(row.file, row.line, f"station '{row['station']}' ต้องเป็น {' / '.join(STATIONS)} หรือว่าง")
        return None
    return value or None


def first_seen(rows: list[Row], key, what: str, problems: Problems) -> list[Row]:
    """The rows but those whose ``key(row)`` an earlier row has (a problem on
    the later row). A row with an empty key stays: its own check reports it."""
    seen: dict = {}
    kept = []
    for row in rows:
        k = key(row)
        if k and (all(k) if isinstance(k, tuple) else True) and k in seen:
            problems.add(row.file, row.line, f"{what} '{k if isinstance(k, str) else ' / '.join(k)}' ซ้ำกับแถว {seen[k].line}")
            continue
        if k:
            seen.setdefault(k, row)
        kept.append(row)
    return kept


# --------------------------------------------------------------------------- the API


class ApiError(Exception):
    def __init__(self, method: str, path: str, status: int, body):
        self.status = status
        detail = body.get("detail") if isinstance(body, dict) else body
        code = body.get("code") if isinstance(body, dict) else None
        super().__init__(f"{method} {path} → {status} {code or ''} {detail}".strip())


class Api:
    def __init__(self, base: str, username: str, password: str):
        self.base = base.rstrip("/") + "/api/v1"
        self._login = {"username": username, "password": password}
        self.token: str | None = None

    def login(self) -> None:
        status, body = self._send("POST", "/auth/login", self._login, auth=False)
        if status != 200:
            raise ApiError("POST", "/auth/login", status, body)
        data = body["data"]
        if data.get("password_change_required"):
            raise SystemExit("บัญชีนี้ต้องเปลี่ยนรหัสผ่านก่อน (login ในหน้าเว็บแล้วเปลี่ยนรหัส)")
        self.token = data["access_token"]

    def _send(self, method: str, path: str, body=None, params=None, auth=True):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Accept": "application/json", "User-Agent": "bottleclub-import/1"}
        data = None
        if body is not None:
            data = json.dumps(body, default=str).encode()
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, raw.decode("utf-8", "replace")[:200]

    def call(self, method: str, path: str, body=None, params=None):
        status, answer = self._send(method, path, body, params)
        if status == 401:  # the access token lasts 15 minutes
            self.login()
            status, answer = self._send(method, path, body, params)
        if status >= 400:
            raise ApiError(method, path, status, answer)
        return answer.get("data") if isinstance(answer, dict) and "data" in answer else answer

    def items(self, path: str, key: str, params=None) -> list[dict]:
        data = self.call("GET", path, params=params)
        return data if isinstance(data, list) else data[key]

    def pages(self, path: str, key: str, per_page: int = 100) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self.items(path, key, {"page": page, "per_page": per_page})
            out.extend(batch)
            if len(batch) < per_page:
                return out
            page += 1


# --------------------------------------------------------------------------- the plan


@dataclass
class Change:
    file: str
    line: int
    action: str  # "create" / "update" / "same"
    label: str
    payload: dict = field(default_factory=dict)
    target_id: int | None = None
    shown: list[str] = field(default_factory=list)  # "field: old → new"
    extra: dict = field(default_factory=dict)


def _diff(existing: dict, wanted: dict, compare=None) -> tuple[dict, list[str]]:
    payload, shown = {}, []
    for key, value in wanted.items():
        old = existing.get(key)
        same = compare(key, old, value) if compare else old == value
        if not same:
            payload[key] = value
            shown.append(f"{key}: {old if old not in (None, '') else '—'} → {value if value not in (None, '') else '—'}")
    return payload, shown


def _money_equal(key, old, new) -> bool:
    if key in ("selling_price", "cost_price"):
        return old is not None and new is not None and Decimal(str(old)) == Decimal(str(new))
    return old == new


@dataclass
class World:
    """What the API has before anything is written."""
    branches: dict[str, dict]
    categories: dict[str, dict]
    products: dict[str, dict]
    product_by_barcode: dict[str, dict]
    costs: dict[str, Decimal]
    registers: set[tuple[str, str]]
    inactive_registers: set[tuple[str, str]]


def load_world(api: Api) -> World:
    branches = {b["code"]: b for b in api.items("/branches/", "branches")}
    categories = {c["name"]: c for c in api.items("/catalog/categories", "categories")}
    products = {p["sku"]: p for p in api.pages("/catalog/products", "products")}
    costs = {c["sku"]: Decimal(str(c["cost_price"])) for c in api.items("/catalog/products/costs", "costs")}
    registers, inactive = set(), set()
    for code, branch in branches.items():
        for r in api.items("/registers/", "registers", {"branch_id": branch["id"], "include_inactive": "true"}):
            (registers if r["is_active"] else inactive).add((code, r["name"]))
    return World(branches, categories, products, {p["barcode"]: p for p in products.values() if p.get("barcode")},
                 costs, registers, inactive)


def plan_branches(rows: list[Row], world: World, problems: Problems) -> list[Change]:
    changes = []
    for row in first_seen(rows, lambda r: r["code"], "code", problems):
        if not check_required(row, problems):
            continue
        check_lengths(row, problems)
        if not CODE.fullmatch(row["code"]):
            problems.add(row.file, row.line, f"code '{row['code']}' ใช้ได้แค่ตัวอักษรอังกฤษ ตัวเลข - _")
        wanted = {"name": row["name"], **{k: row[k] for k in ("phone", "address") if row[k]}}
        existing = world.branches.get(row["code"])
        if existing is None:
            changes.append(Change(row.file, row.line, "create", f"สาขา {row['code']}", {"code": row["code"], **wanted}))
        else:
            payload, shown = _diff(existing, wanted)
            changes.append(Change(row.file, row.line, "update" if payload else "same", f"สาขา {row['code']}",
                                  payload, existing["id"], shown))
    return changes


def plan_categories(rows: list[Row], world: World, problems: Problems) -> list[Change]:
    changes = []
    for row in first_seen(rows, lambda r: r["name"], "หมวด", problems):
        if not check_required(row, problems):
            continue
        check_lengths(row, problems)
        wanted: dict = {}
        st = station(row, problems)
        if st:
            wanted["station"] = st
        if row["sort_order"]:
            if re.fullmatch(r"-?\d+", row["sort_order"]):
                wanted["sort_order"] = int(row["sort_order"])
            else:
                problems.add(row.file, row.line, f"sort_order '{row['sort_order']}' ต้องเป็นจำนวนเต็ม")
        if row["description"]:
            wanted["description"] = row["description"]
        existing = world.categories.get(row["name"])
        if existing is None:
            changes.append(Change(row.file, row.line, "create", f"หมวด {row['name']}", {"name": row["name"], **wanted}))
        else:
            payload, shown = _diff(existing, wanted)
            changes.append(Change(row.file, row.line, "update" if payload else "same", f"หมวด {row['name']}",
                                  payload, existing["id"], shown))
    return changes


def plan_products(rows: list[Row], world: World, categories_in_file: set[str], problems: Problems) -> list[Change]:
    changes = []
    first_seen(rows, lambda r: r["barcode"], "barcode", problems)
    for row in first_seen(rows, lambda r: r["sku"], "sku", problems):
        if not check_required(row, problems):
            continue
        check_lengths(row, problems)
        price = money(row, "selling_price", problems, positive=True)
        cost = money(row, "cost_price", problems, positive=False)
        st = station(row, problems)
        category = row["category"]
        if category and category not in categories_in_file and category not in world.categories:
            problems.add(row.file, row.line, f"ไม่มีหมวด '{category}' (ใน categories.csv หรือในระบบ)")
        other = world.product_by_barcode.get(row["barcode"]) if row["barcode"] else None
        if other is not None and other["sku"] != row["sku"]:
            problems.add(row.file, row.line, f"barcode '{row['barcode']}' เป็นของสินค้า {other['sku']} ในระบบแล้ว")
        if price is None:
            continue
        existing = world.products.get(row["sku"])
        wanted: dict = {"name": row["name"], "selling_price": price, "station": st}
        for column in ("unit", "barcode"):
            if row[column]:
                wanted[column] = row[column]
        if cost is not None:
            wanted["cost_price"] = cost
        extra = {"category": category} if category else {}
        if existing is None:
            wanted.setdefault("cost_price", Decimal("0.00"))
            changes.append(Change(row.file, row.line, "create", f"สินค้า {row['sku']}", {"sku": row["sku"], **wanted},
                                  extra=extra))
            continue
        current = {**existing, "cost_price": world.costs.get(row["sku"])}
        payload, shown = _diff(current, wanted, _money_equal)
        if category and (world.categories.get(category) or {}).get("id") != existing.get("category_id"):
            shown.append(f"category → {category}")
        else:
            extra = {}
        changes.append(Change(row.file, row.line, "update" if payload or extra else "same", f"สินค้า {row['sku']}",
                              payload, existing["id"], shown, extra))
    return changes


def plan_registers(rows: list[Row], world: World, branches_in_file: set[str], problems: Problems) -> list[Change]:
    changes = []
    for row in first_seen(rows, lambda r: (r["branch"], r["name"]), "เครื่อง (สาขา / ชื่อ)", problems):
        if not check_required(row, problems):
            continue
        check_lengths(row, problems)
        code = row["branch"]
        if code not in branches_in_file and code not in world.branches:
            problems.add(row.file, row.line, f"ไม่มีสาขา '{code}' (ใน branches.csv หรือในระบบ)")
            continue
        key = (code, row["name"])
        label = f"เครื่อง {code} / {row['name']}"
        if key in world.registers:
            changes.append(Change(row.file, row.line, "same", label))
        elif key in world.inactive_registers:
            changes.append(Change(row.file, row.line, "same", label, shown=["ปิดใช้งานอยู่ — ไม่เปิดให้ (เปิดในหน้า Admin)"]))
        else:
            changes.append(Change(row.file, row.line, "create", label, {"name": row["name"]}, extra={"branch": code}))
    return changes


def build_plan(files: dict[str, list[Row]], world: World, problems: Problems) -> list[Change]:
    plan = plan_branches(files.get("branches.csv", []), world, problems)
    plan += plan_categories(files.get("categories.csv", []), world, problems)
    categories_in_file = {r["name"] for r in files.get("categories.csv", []) if r["name"]}
    plan += plan_products(files.get("products.csv", []), world, categories_in_file, problems)
    branches_in_file = {r["code"] for r in files.get("branches.csv", []) if r["code"]}
    plan += plan_registers(files.get("registers.csv", []), world, branches_in_file, problems)
    return plan


# --------------------------------------------------------------------------- writing


def apply_plan(api: Api, plan: list[Change], world: World, out=print) -> None:
    branch_id = {code: b["id"] for code, b in world.branches.items()}
    category_id = {name: c["id"] for name, c in world.categories.items()}
    for change in plan:
        if change.action == "same":
            continue
        kind = change.file
        payload = dict(change.payload)
        if kind == "branches.csv":
            if change.action == "create":
                branch_id[payload["code"]] = api.call("POST", "/branches/", payload)["id"]
            else:
                api.call("PUT", f"/branches/{change.target_id}", payload)
        elif kind == "categories.csv":
            if change.action == "create":
                category_id[payload["name"]] = api.call("POST", "/catalog/categories", payload)["id"]
            else:
                api.call("PUT", f"/catalog/categories/{change.target_id}", payload)
        elif kind == "products.csv":
            if "category" in change.extra:
                payload["category_id"] = category_id[change.extra["category"]]
            if change.action == "create":
                api.call("POST", "/catalog/products", payload)
            else:
                api.call("PUT", f"/catalog/products/{change.target_id}", payload)
        elif kind == "registers.csv":
            api.call("POST", "/registers/", {"branch_id": branch_id[change.extra["branch"]], **payload})
        out(f"  ✓ {'สร้าง' if change.action == 'create' else 'แก้'} {change.label}")


# --------------------------------------------------------------------------- main


def show_plan(plan: list[Change], out=print) -> None:
    for file in ORDER:
        mine = [c for c in plan if c.file == file]
        if not mine:
            continue
        counts = {a: sum(c.action == a for c in mine) for a in ("create", "update", "same")}
        out(f"{file}: สร้าง {counts['create']}, แก้ {counts['update']}, เหมือนเดิม {counts['same']}")
        for change in mine:
            if change.action == "create":
                out(f"  + {change.label} (แถว {change.line})")
            elif change.action == "update" or change.shown:
                out(f"  ~ {change.label} (แถว {change.line}): {'; '.join(change.shown)}")


def read_files(directory: Path, problems: Problems) -> dict[str, list[Row]]:
    files = {}
    for name in ORDER:
        path = directory / name
        if path.exists():
            files[name] = read_csv(path, problems)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True, help="e.g. https://api.wayneven.uk")
    parser.add_argument("--dir", required=True, type=Path, help="the folder of the CSV files")
    parser.add_argument("--username", required=True, help="a Superadmin")
    parser.add_argument("--apply", action="store_true", help="write (without it: check and show only)")
    args = parser.parse_args(argv)

    parts = urllib.parse.urlsplit(args.api)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        parser.error("--api must be https (http only for 127.0.0.1 / localhost)")
    directory = args.dir.expanduser()
    if not directory.is_dir():
        parser.error(f"no folder {directory}")

    problems = Problems()
    files = read_files(directory, problems)
    if not files:
        print(f"ไม่มีไฟล์ CSV ใน {directory} ({', '.join(ORDER)})")
        return 1

    api = Api(args.api, args.username, getpass.getpass(f"รหัสผ่าน {args.username} @ {args.api}: "))
    try:
        api.login()
        world = load_world(api)
    except ApiError as exc:
        print(f"เรียก API ไม่สำเร็จ: {exc}")
        return 2
    plan = build_plan(files, world, problems)
    if problems:
        print(f"พบ {len(problems.items)} ปัญหา — ไม่ได้นำเข้าอะไรเลย:\n{problems.report()}")
        return 1

    show_plan(plan)
    if not any(c.action != "same" for c in plan):
        print("ไม่มีอะไรต้องเปลี่ยน")
        return 0
    if not args.apply:
        print("ยังไม่ได้เขียนอะไร (ตรวจอย่างเดียว) — ใส่ --apply เพื่อนำเข้า")
        return 0
    print("กำลังนำเข้า…")
    try:
        apply_plan(api, plan, world)
    except ApiError as exc:
        print(f"หยุด: API ปฏิเสธ — {exc}\nแถวก่อนหน้านี้นำเข้าแล้ว; แก้แล้วรันใหม่ได้ (รันซ้ำไม่สร้างซ้ำ)")
        return 2
    print("นำเข้าเสร็จ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
