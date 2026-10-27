"""The whole shop on staging, in order: catalog → purchasing → staff → POS →
slip → KDS → returns → CRM/loyalty/coupons → transfers → shift → reports →
branch isolation (Phase 37, steps a–l).

Every value is invented. Amounts are chosen so each total is distinct.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.e2e_staging.conftest import data, needs
from tests.e2e_staging.slip_image import render_slip

BKK = ZoneInfo("Asia/Bangkok")
RUN = secrets.token_hex(3).upper()  # keeps codes unique if the flow is run twice

P1 = {"name": f"E2E Red {RUN}", "sku": f"E2E-RED-{RUN}", "barcode": f"88500{RUN}01", "selling_price": "350.00"}
P2 = {"name": f"E2E White {RUN}", "sku": f"E2E-WHT-{RUN}", "barcode": f"88500{RUN}02", "selling_price": "420.00"}
P3 = {"name": f"E2E Cheese plate {RUN}", "sku": f"E2E-CHS-{RUN}", "barcode": f"88500{RUN}03",
      "selling_price": "180.00", "track_inventory": False}


CREATED = (200, 201)  # creates answer 200 or 201 depending on the route


def created(resp) -> bool:
    return resp.status_code in CREATED


def D(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def rows(payload) -> list:
    """The list inside a response's data (``{"products": [...]}``, ``[...]``, …)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return value
    return []


def today() -> str:
    return datetime.now(BKK).date().isoformat()


def on_hand(api, branch_id: int, product_id: int) -> int | None:
    resp = api.get(f"/inventory/balances/{branch_id}/{product_id}", "sa", branch=branch_id)
    return data(resp).get("on_hand") if resp.status_code == 200 else None


# ---------------------------------------------------------------------------
# a. SA: catalog
# ---------------------------------------------------------------------------
def test_a_catalog(api, rec, flow, sa_credentials):
    s = "a"
    user, pw = sa_credentials
    resp = api.login("sa", user, pw)
    if not rec.eq(s, "SA login", 200, resp.status_code, resp.status_code):
        rec.finish(s)
    me = data(api.get("/auth/me", "sa", branch=None))
    branches = rows(data(api.get("/branches/", "sa", branch=None)))
    flow["A"] = next(b["id"] for b in branches if b["code"] == "MNB")
    api.branch["sa"] = flow["A"]
    rec.eq(s, "SA is superadmin", True, me.get("is_superadmin"))

    resp = api.post("/catalog/categories", "sa", json={"name": f"E2E Wine {RUN}"})
    rec.check(s, "create category", created(resp), "200/201", resp.status_code, resp.status_code)
    flow["category"] = data(resp).get("id")

    for key, product in (("p1", P1), ("p2", P2), ("p3", P3)):
        resp = api.post("/catalog/products", "sa", json={**product, "category_id": flow["category"]})
        body = data(resp)
        rec.check(s, f"create product {key}", created(resp), "200/201", resp.status_code, resp.status_code)
        rec.eq(s, f"{key} barcode/price stored", (product["barcode"], D(product["selling_price"])),
               (body.get("barcode"), D(body.get("selling_price", 0))))
        flow[key] = body.get("id")
    rec.note(s, "kitchen/bar routing: CategoryCreate has no station field; every item goes to 'kitchen'",
             "kitchen (category.station server default)")

    resp = api.post("/catalog/suppliers", "sa", json={"name": f"E2E Supplier {RUN}", "phone": "000-000-0000"})
    rec.check(s, "create supplier", created(resp), "200/201", resp.status_code, resp.status_code)
    flow["supplier"] = data(resp).get("id")
    rec.finish(s)


# ---------------------------------------------------------------------------
# b. Purchasing: PO → approve → receive → stock
# ---------------------------------------------------------------------------
def test_b_purchasing(api, rec, flow):
    s = "b"
    needs(flow, "p1", "p2", "supplier")
    A = flow["A"]
    before = {k: on_hand(api, A, flow[k]) or 0 for k in ("p1", "p2")}
    resp = api.post("/purchases", "sa", json={
        "supplier_id": flow["supplier"], "branch_id": A,
        "items": [{"product_id": flow["p1"], "quantity_ordered": 24, "unit_cost": "200.00"},
                  {"product_id": flow["p2"], "quantity_ordered": 12, "unit_cost": "250.00"}],
    })
    po = data(resp)
    rec.check(s, "create PO", created(resp), "200/201", resp.status_code, resp.status_code)
    rec.eq(s, "PO total", D(24 * 200 + 12 * 250), D(po.get("total_amount", 0)))
    rec.eq(s, "PO status", "draft", po.get("status"))
    rec.check(s, "PO number has no date (purchases counter)", str(po.get("po_number", "")).startswith("PO-"),
              "PO-…", po.get("po_number"))

    resp = api.post(f"/purchases/{po['id']}/approve", "sa")
    rec.eq(s, "approve PO", (200, "approved"), (resp.status_code, data(resp).get("status")), resp.status_code)

    items = {i["product_id"]: i["id"] for i in po.get("items", [])}
    resp = api.post(f"/purchases/{po['id']}/receive", "sa", json={"received_items": [
        {"purchase_order_item_id": items[flow["p1"]], "quantity_received": 24, "lot_number": f"L{RUN}-1",
         "cost_price": "200.00"},
        {"purchase_order_item_id": items[flow["p2"]], "quantity_received": 12, "lot_number": f"L{RUN}-2",
         "cost_price": "250.00"},
    ]})
    rec.eq(s, "receive PO", 200, resp.status_code, resp.status_code)
    po_after = data(api.get(f"/purchases/{po['id']}", "sa"))
    rec.eq(s, "PO status after full receipt", "received", po_after.get("status"))
    rec.eq(s, "stock p1 +24", before["p1"] + 24, on_hand(api, A, flow["p1"]))
    rec.eq(s, "stock p2 +12", before["p2"] + 12, on_hand(api, A, flow["p2"]))

    resp = api.post(f"/purchases/{po['id']}/receive", "sa", json={"received_items": [
        {"purchase_order_item_id": items[flow["p1"]], "quantity_received": 1, "lot_number": "X", "cost_price": "1"}]})
    rec.check(s, "receiving again beyond the order is refused", resp.status_code in (400, 409),
              "400 OVER_RECEIPT / 409", f"{resp.status_code} {data(resp)}", resp.status_code)
    rec.eq(s, "stock p1 unchanged after the refused receipt", before["p1"] + 24, on_hand(api, A, flow["p1"]))
    flow["stock"] = {"p1": before["p1"] + 24, "p2": before["p2"] + 12}
    rec.finish(s)


# ---------------------------------------------------------------------------
# c. Staff: Branch Admin + POS (+ Kitchen for f) with temporary passwords
# ---------------------------------------------------------------------------
def test_c_staff(api, rec, flow):
    s = "c"
    needs(flow, "A")
    roles = {r["name"]: r["id"] for r in rows(data(api.get("/roles/", "sa")))}
    for who, role in (("manager", "Manager"), ("cashier", "Cashier"), ("kitchen", "Kitchen")):
        username = f"e2e_{who}_{RUN.lower()}"
        resp = api.post("/users/", "sa", json={
            "username": username, "email": f"{username}@e2e.example.com", "display_name": f"E2E {who}",
            "roles": [{"role_id": roles[role], "branch_id": flow["A"]}],
        })
        body = data(resp)
        rec.check(s, f"create {who} ({role})", created(resp), "200/201", resp.status_code, resp.status_code)
        temp = body.get("temporary_password")
        rec.check(s, f"{who}: temporary password returned once", bool(temp), "non-empty", "present" if temp else None)
        if not temp:
            continue
        resp = api.login(who, username, temp)
        rec.eq(s, f"{who}: login with the temporary password", (200, True),
               (resp.status_code, data(resp).get("password_change_required")), resp.status_code)
        api.branch[who] = flow["A"]
        resp = api.get("/catalog/products", who)
        rec.eq(s, f"{who}: other calls before the change", (403, "PASSWORD_CHANGE_REQUIRED"),
               (resp.status_code, resp.json().get("code")), resp.status_code)
        new_pw = secrets.token_urlsafe(18)
        resp = api.post("/auth/change-password", who, json={"current_password": temp, "new_password": new_pw})
        rec.eq(s, f"{who}: change-password", 200, resp.status_code, resp.status_code)
        if resp.status_code == 200:
            api.tokens[who] = data(resp)["access_token"]
        resp = api.get("/auth/me", who)
        rec.eq(s, f"{who}: works after the change", 200, resp.status_code, resp.status_code)
        resp = api.login(who + "_old", username, temp)
        rec.eq(s, f"{who}: the temporary password no longer logs in", 401, resp.status_code, resp.status_code)
        flow[who] = username
    rec.finish(s)


# ---------------------------------------------------------------------------
# d. POS: shift → barcode → order (twice) → cash checkout → receipt
# ---------------------------------------------------------------------------
def test_d_pos_sale(api, rec, flow):
    import os

    s = "d"
    needs(flow, "cashier", "p1", "p3", "stock")
    A = flow["A"]
    register = int(os.environ.get("E2E_REGISTER_ID", "0") or 0)
    rec.note(s, "register: no API creates one; E2E_REGISTER_ID was inserted by the staging setup", register)
    resp = api.post("/shifts/open", "cashier", json={"branch_id": A, "register_id": register, "opening_cash": "1000.00"})
    rec.check(s, "open shift", created(resp), "200/201", resp.status_code, resp.status_code)
    flow["shift"] = data(resp).get("id")

    resp = api.get(f"/catalog/products?search={P1['barcode']}", "cashier")
    found = [p["id"] for p in rows(data(resp))]
    rec.eq(s, "find product by barcode", (200, [flow["p1"]]), (resp.status_code, found), resp.status_code)

    body = {"branch_id": A, "shift_id": flow["shift"], "register_id": register,
            "items": [{"product_id": flow["p1"], "quantity": 2, "unit_price": P1["selling_price"]},
                      {"product_id": flow["p3"], "quantity": 1, "unit_price": P3["selling_price"]}]}
    first = api.post("/orders/", "cashier", json=body)
    order = data(first)
    rec.check(s, "create order", created(first), "200/201", first.status_code, first.status_code)
    rec.eq(s, "order total 2×350 + 180", D(880), D(order.get("grand_total", 0)))
    number = str(order.get("order_number", ""))
    rec.eq(s, "order number carries the Bangkok date", f"MNB-{today().replace('-', '')}", number[:12])
    flow["o1"], flow["o1_items"], flow["o1_token"] = order.get("id"), order.get("items", []), order.get("tracking_token")
    rec.eq(s, "stock p1 −2 at order creation", flow["stock"]["p1"] - 2, on_hand(api, A, flow["p1"]))

    again = api.post("/orders/", "cashier", json=body)
    dup = data(again)
    rec.note(s, "same body sent again (no idempotency_key): second order?",
             f"{again.status_code}: new order {dup.get('order_number')} (id {dup.get('id')})"
             if dup.get("id") != flow["o1"] else "same order returned", again.status_code)
    if created(again) and dup.get("id") != flow["o1"]:
        rec.note(s, "stock after the duplicate", on_hand(api, A, flow["p1"]), expected=flow["stock"]["p1"] - 2)
        resp = api.post(f"/orders/{dup['id']}/cancel", "cashier", json={"reason": "E2E duplicate"})
        rec.note(s, "POS staff cancels its own duplicate", resp.status_code, resp.status_code,
                 expected="Cashier has no orders.cancel; the Branch Admin must void it")
        resp = api.post(f"/orders/{dup['id']}/cancel", "manager", json={"reason": "E2E duplicate"})
        rec.eq(s, "Branch Admin cancels the duplicate", 200, resp.status_code, resp.status_code)
        rec.eq(s, "cancel returns the duplicate's stock", flow["stock"]["p1"] - 2, on_hand(api, A, flow["p1"]))

    key = f"e2e-{RUN}-idem"
    k1 = api.post("/orders/", "cashier", json={**body, "idempotency_key": key})
    k2 = api.post("/orders/", "cashier", json={**body, "idempotency_key": key})
    rec.eq(s, "same idempotency_key twice → one order", data(k1).get("id"), data(k2).get("id"),
           f"{k1.status_code}/{k2.status_code}")
    if created(k1):
        resp = api.post(f"/orders/{data(k1)['id']}/cancel", "manager", json={"reason": "E2E idempotency probe"})
        rec.eq(s, "cancel the idempotency probe", 200, resp.status_code, resp.status_code)
    rec.eq(s, "stock p1 back to −2 after the probes", flow["stock"]["p1"] - 2, on_hand(api, A, flow["p1"]))

    cheap = api.post("/orders/", "cashier", json={**body, "items": [
        {"product_id": flow["p1"], "quantity": 1, "unit_price": "1.00"}]})
    rec.note(s, "POS may send its own unit_price (350 in the catalog, 1.00 sent)",
             f"{cheap.status_code}: grand_total {data(cheap).get('grand_total')}", cheap.status_code,
             expected="catalog price or 400")
    if created(cheap):
        resp = api.post(f"/orders/{data(cheap)['id']}/cancel", "manager", json={"reason": "E2E price probe"})
        rec.eq(s, "cancel the price probe", 200, resp.status_code, resp.status_code)
    rec.eq(s, "stock p1 back to −2 after every probe was cancelled", flow["stock"]["p1"] - 2, on_hand(api, A, flow["p1"]))

    resp = api.post(f"/orders/{flow['o1']}/checkout", "cashier",
                    json={"payments": [{"payment_method": "cash", "amount": "1000.00"}]})
    paid = data(resp)
    rec.eq(s, "checkout cash 1000", 200, resp.status_code, resp.status_code)
    rec.eq(s, "order paid, change 120", ("paid", D(120)), (paid.get("status"), D(paid.get("change_amount", 0))))

    resp = api.get(f"/orders/{flow['o1']}/receipt", "cashier")
    receipt = data(resp).get("order", {})
    rec.eq(s, "receipt", (200, D(880), 2, "paid"), (resp.status_code, D(receipt.get("grand_total", 0)),
                                                  len(receipt.get("items", [])), receipt.get("status")), resp.status_code)
    rec.eq(s, "receipt payments", [D(1000)], [D(p["amount"]) for p in data(resp).get("payments", [])])
    flow["stock"]["p1"] -= 2
    flow["sales"] = {"o1": D(880)}
    flow["cash_in_drawer"] = D(880)
    rec.finish(s)


# ---------------------------------------------------------------------------
# e. Slip: order 2 → synthetic slip → OCR → review → Branch Admin approves
# ---------------------------------------------------------------------------
def test_e_slip(api, rec, flow):
    s = "e"
    needs(flow, "cashier", "manager", "p2", "shift")
    A = flow["A"]
    resp = api.post("/orders/", "cashier", json={
        "branch_id": A, "shift_id": flow["shift"],
        "items": [{"product_id": flow["p2"], "quantity": 1, "unit_price": P2["selling_price"]}]})
    order = data(resp)
    rec.check(s, "create order 2", created(resp) and D(order.get("grand_total", 0)) == D(420), "200/201, 420",
              (resp.status_code, order.get("grand_total")), resp.status_code)
    flow["o2"], flow["o2_token"] = order.get("id"), order.get("tracking_token")

    reference = f"E2E{RUN}{secrets.randbelow(10**12):012d}"
    png = render_slip("krungthai", D(420), reference, datetime.now(BKK) - timedelta(minutes=3))
    resp = api.post("/slip-verify/upload", "cashier",
                    files={"file": ("e2e-slip.png", png, "image/png")}, data={"order_id": str(flow["o2"])})
    up = data(resp)
    inner = up.get("data") or {}
    rec.eq(s, "upload slip", 200, resp.status_code, resp.status_code)
    rec.eq(s, "real OCR read the amount", 420.0, inner.get("amount"))
    rec.eq(s, "held for staff (SLIP_AUTO_VERIFY=false)", "review", up.get("status"))
    rec.note(s, "upload message / reason", f"{up.get('message')} | {inner.get('reason') or inner.get('review_reason')}")
    vid = inner.get("verification_id")
    if vid is None:
        listing = rows(data(api.get("/slip-verify/list?status=review", "manager")))
        vid = next((v["id"] for v in listing if v.get("order_id") == flow["o2"]), None)
    rec.check(s, "verification id", vid is not None, "id", vid)
    if vid is None:
        rec.finish(s)

    resp = api.get(f"/slip-verify/{vid}", "cashier")
    rec.eq(s, "POS cannot view the verification", 403, resp.status_code, resp.status_code)
    resp = api.get(f"/slip-verify/{vid}", "manager")
    detail = data(resp)
    rec.eq(s, "Branch Admin sees it in review", (200, "review"), (resp.status_code, detail.get("status")), resp.status_code)
    rec.note(s, "risk signals", detail.get("risk_signals"))
    rec.eq(s, "OCR reference", reference, detail.get("ocr_reference"))

    approve = {"confirmed_amount": "420.00", "bank_reference": reference, "note": "E2E checked in the bank app"}
    resp = api.post(f"/slip-verify/{vid}/approve", "cashier", json=approve)
    rec.eq(s, "POS cannot approve", 403, resp.status_code, resp.status_code)
    resp = api.post(f"/slip-verify/{vid}/approve", "manager", json=approve)
    rec.eq(s, "Branch Admin approves", (200, "verified"), (resp.status_code, data(resp).get("status")), resp.status_code)
    resp = api.get(f"/orders/{flow['o2']}", "manager")
    rec.eq(s, "order 2 is paid", "paid", data(resp).get("status"))
    pays = rows(data(api.get(f"/payments/{flow['o2']}", "manager")))
    rec.eq(s, "one payment of 420", [D(420)], [D(p["amount"]) for p in pays])

    audit = rows(data(api.get(f"/audit/?entity_id={vid}", "sa")))
    rec.check(s, "audit log of the approval", any("APPROVE" in (a.get("action") or "").upper() for a in audit),
              "an *APPROVE* action", [a.get("action") for a in audit])

    resp = api.post(f"/slip-verify/{vid}/approve", "manager", json=approve)
    rec.note(s, "approve again", f"{resp.status_code} {data(resp).get('status') if resp.status_code == 200 else data(resp)}",
             resp.status_code, expected="200 no-op or 409")
    pays = rows(data(api.get(f"/payments/{flow['o2']}", "manager")))
    rec.eq(s, "still one payment after approving again", 1, len(pays))

    token = flow.get("o2_token")
    resp = api.get(f"/orders/track/public/{token}")
    rec.eq(s, "public tracking with the token (no login)", (200, "paid"),
           (resp.status_code, data(resp).get("status")), resp.status_code)
    resp = api.get(f"/orders/track/public/{token[:-2]}xx" if token else "/orders/track/public/x")
    rec.eq(s, "wrong token is 404", 404, resp.status_code, resp.status_code)
    flow["stock"]["p2"] -= 1
    flow["sales"]["o2"] = D(420)
    rec.finish(s)


# ---------------------------------------------------------------------------
# f. KDS
# ---------------------------------------------------------------------------
def test_f_kds(api, rec, flow):
    s = "f"
    needs(flow, "kitchen", "o1_items")
    resp = api.get("/orders/station/kitchen", "kitchen")
    entries = rows(data(resp))
    o1_item_ids = {i["id"] for i in flow["o1_items"]}
    shown = [(e.get("order_id"), e.get("order_number"), it["id"]) for e in entries for it in e.get("items", [])]
    rec.eq(s, "Kitchen sees order 1's items", (200, o1_item_ids),
           (resp.status_code, {i for _, _, i in shown if i in o1_item_ids}), resp.status_code)
    rec.eq(s, "order 1's items are under order 1's header", {flow["o1"]},
           {oid for oid, _, i in shown if i in o1_item_ids})
    rec.note(s, "kitchen queue: (order_id, order_number, item id)", shown)
    item = next((i for i in flow["o1_items"] if i["product_id"] == flow["p3"]), None)
    rec.check(s, "every item is 'kitchen' (no station on categories)",
              all(it.get("station") == "kitchen" for e in entries for it in e.get("items", [])),
              "kitchen", sorted({it.get("station") for e in entries for it in e.get("items", [])}))
    if item:
        for status in ("preparing", "ready", "served"):
            resp = api.patch(f"/orders/{flow['o1']}/station-items/{item['id']}/status", "kitchen",
                             json={"item_status": status})
            rec.eq(s, f"item → {status}", (200, status), (resp.status_code, data(resp).get("item_status")),
                   resp.status_code)
    resp = api.get("/orders/", "kitchen")
    rec.eq(s, "Kitchen cannot open /orders", 403, resp.status_code, resp.status_code)
    resp = api.get("/orders/station/bar", "kitchen")
    rec.eq(s, "Kitchen cannot open the bar queue", 403, resp.status_code, resp.status_code)

    resp = api.put(f"/orders/{flow['o1']}/complete", "cashier")
    rec.eq(s, "POS completes order 1", (200, "completed"), (resp.status_code, data(resp).get("status")), resp.status_code)
    rec.finish(s)


# ---------------------------------------------------------------------------
# g. Return / refund
# ---------------------------------------------------------------------------
def test_g_return(api, rec, flow):
    s = "g"
    needs(flow, "o1_items", "manager")
    A = flow["A"]
    line = next(i for i in flow["o1_items"] if i["product_id"] == flow["p1"])
    stock_before = on_hand(api, A, flow["p1"])
    resp = api.post("/returns/", "manager", json={
        "order_id": flow["o1"], "reason": "E2E corked",
        "items": [{"order_item_id": line["id"], "product_id": flow["p1"], "quantity": 1, "restock": True}]})
    ret = data(resp)
    rec.check(s, "create return of 1×p1", created(resp) and ret.get("status") == "pending", "200/201 pending",
              (resp.status_code, ret.get("status")), resp.status_code)
    refunds = rows(data(api.get(f"/refunds/?order_id={flow['o1']}", "manager")))
    rec.note(s, "refund created when the return is created (before process)",
             [(r.get("refund_number"), r.get("status"), r.get("refund_amount")) for r in refunds])
    rec.note(s, "stock back at create (before process)", on_hand(api, A, flow["p1"]), expected=stock_before)

    resp = api.put(f"/returns/{ret.get('id')}/process", "manager")
    rec.eq(s, "process the return", (200, "completed"), (resp.status_code, data(resp).get("status")), resp.status_code)
    refunds = rows(data(api.get(f"/refunds/?order_id={flow['o1']}", "manager")))
    done = [D(r["refund_amount"]) for r in refunds if r.get("status") == "completed"]
    rec.eq(s, "one completed refund of 350", [D(350)], done)
    rec.eq(s, "stock p1 +1 (restock)", stock_before + 1, on_hand(api, A, flow["p1"]))

    resp = api.post("/returns/", "manager", json={
        "order_id": flow["o1"], "reason": "E2E second return of the same line",
        "items": [{"order_item_id": line["id"], "product_id": flow["p1"], "quantity": 2, "restock": True}]})
    rec.note(s, "return again more than is left (2 of the 1 not yet returned)",
             f"{resp.status_code} {'created ' + str(data(resp).get('return_number')) if created(resp) else data(resp)}",
             resp.status_code,
             expected="400")
    refunds = rows(data(api.get(f"/refunds/?order_id={flow['o1']}", "manager")))
    total_refunded = sum((D(r["refund_amount"]) for r in refunds if r.get("status") == "completed"), D(0))
    rec.check(s, "refunds never exceed the sale (880)", total_refunded <= D(880), "≤ 880", total_refunded)
    flow["refunds"] = total_refunded

    unpaid = api.post("/orders/", "cashier", json={
        "branch_id": A, "items": [{"product_id": flow["p3"], "quantity": 1, "unit_price": P3["selling_price"]}]})
    u = data(unpaid)
    if created(unpaid):
        resp = api.post("/returns/", "manager", json={
            "order_id": u["id"], "reason": "E2E return of an unpaid order",
            "items": [{"order_item_id": u["items"][0]["id"], "product_id": flow["p3"], "quantity": 1}]})
        refs = rows(data(api.get(f"/refunds/?order_id={u['id']}", "manager")))
        rec.note(s, "return of an order that was never paid", f"{resp.status_code}; refunds "
                 f"{[(r.get('status'), r.get('refund_amount')) for r in refs]}", resp.status_code,
                 expected="400 (nothing was paid)")
        api.post(f"/orders/{u['id']}/cancel", "manager", json={"reason": "E2E unpaid probe"})
    flow["stock"]["p1"] = on_hand(api, A, flow["p1"])
    flow["cash_in_drawer"] -= total_refunded
    rec.finish(s)


# ---------------------------------------------------------------------------
# h. Customers, loyalty, coupons
# ---------------------------------------------------------------------------
def test_h_customers_loyalty_coupons(api, rec, flow):
    s = "h"
    needs(flow, "cashier", "p2", "shift")
    A = flow["A"]
    resp = api.post("/customers/", "cashier", json={"first_name": "ทดลอง", "last_name": f"ลูกค้า{RUN}",
                                                    "phone": f"09{secrets.randbelow(10**8):08d}"})
    rec.check(s, "create customer", created(resp), "200/201", resp.status_code, resp.status_code)
    cid = data(resp).get("id")
    flow["customer"] = cid
    resp = api.post("/loyalty/earn", "cashier", json={"customer_id": cid, "points": 100, "notes": "E2E welcome"})
    rec.check(s, "earn 100 points", created(resp), "200/201", resp.status_code, resp.status_code)
    resp = api.post("/loyalty/redeem", "cashier", json={"customer_id": cid, "points": 30, "notes": "E2E"})
    rec.check(s, "redeem 30 points", created(resp), "200/201", resp.status_code, resp.status_code)
    bal = data(api.get(f"/loyalty/balance/{cid}", "cashier")).get("balance")
    rec.eq(s, "balance 70", 70, bal)
    resp = api.post("/loyalty/redeem", "cashier", json={"customer_id": cid, "points": 1000})
    rec.eq(s, "redeem more than the balance is refused", 400, resp.status_code, resp.status_code)

    resp = api.post("/orders/", "cashier", json={
        "branch_id": A, "shift_id": flow["shift"], "customer_id": cid,
        "items": [{"product_id": flow["p2"], "quantity": 1, "unit_price": P2["selling_price"]}]})
    flow["o3"] = data(resp).get("id")
    rec.check(s, "order 3 for the customer (420)", created(resp), "200/201", resp.status_code, resp.status_code)
    resp = api.post(f"/orders/{flow['o3']}/checkout", "cashier", json={
        "payments": [{"payment_method": "cash", "amount": "500.00"}], "redeem_points": 20})
    paid = data(resp)
    rec.eq(s, "checkout: 20 points off, cash 500, change 100", (200, 20, D(100)),
           (resp.status_code, paid.get("loyalty_points_redeemed"), D(paid.get("change_amount", 0))), resp.status_code)
    rec.eq(s, "points earned on the 400 paid", 400, paid.get("loyalty_points_earned"))
    rec.eq(s, "balance 70 − 20 + 400", 450, data(api.get(f"/loyalty/balance/{cid}", "cashier")).get("balance"))
    resp = api.put(f"/orders/{flow['o3']}/complete", "cashier")
    rec.eq(s, "complete order 3", 200, resp.status_code, resp.status_code)
    flow["stock"]["p2"] -= 1
    flow["sales"]["o3"] = D(420)
    flow["cash_in_drawer"] += D(400)

    now = datetime.now(BKK)
    live = {"code": f"E2E-OK-{RUN}", "promotion_id": 1, "max_uses": 10,
            "start_date": (now - timedelta(days=1)).isoformat(), "end_date": (now + timedelta(days=7)).isoformat()}
    expired = {"code": f"E2E-OLD-{RUN}", "promotion_id": 1, "max_uses": 10,
               "start_date": (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S"),
               "end_date": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")}
    for c in (live, expired):
        resp = api.post("/coupons/", "sa", json=c)
        rec.check(s, f"SA creates coupon {c['code'][:7]}", created(resp), "200/201", resp.status_code, resp.status_code)
    resp = api.post("/coupons/validate", "cashier", json={"code": live["code"], "customer_id": cid})
    rec.eq(s, "valid coupon validates", (200, True), (resp.status_code, data(resp).get("valid")), resp.status_code)
    rec.note(s, "what a valid coupon gives (promotion_id 1 has no discount fields)",
             {k: data(resp).get(k) for k in ("promotion_type", "discount_value", "message")})
    resp = api.post("/coupons/validate", "cashier", json={"code": expired["code"], "customer_id": cid})
    rec.eq(s, "expired coupon is not valid", False, data(resp).get("valid"), resp.status_code)
    rec.note(s, "using a coupon at the POS", "no field: OrderCreate/CheckoutRequest take no coupon code",
             expected="coupon applied to the order")
    rec.finish(s)


# ---------------------------------------------------------------------------
# i. Branch B and a transfer A → B
# ---------------------------------------------------------------------------
def test_i_transfer(api, rec, flow):
    s = "i"
    needs(flow, "p1", "stock")
    A = flow["A"]
    resp = api.post("/branches/", "sa", json={"name": f"E2E Branch B {RUN}", "code": f"B{RUN[:4]}"})
    rec.check(s, "SA creates branch B", created(resp), "200/201", resp.status_code, resp.status_code)
    B = flow["B"] = data(resp).get("id")
    a_before, b_before = on_hand(api, A, flow["p1"]), on_hand(api, B, flow["p1"]) or 0
    resp = api.post("/transfers/", "sa", branch=A, json={
        "dest_branch_id": B, "items": [{"product_id": flow["p1"], "quantity_requested": 3}], "notes": "E2E"})
    tr = data(resp)
    rec.check(s, "create transfer A→B 3×p1", resp.status_code in (200, 201) and tr.get("status") == "draft",
              "200/201 draft", (resp.status_code, tr.get("status")), resp.status_code)
    tid, item_id = tr.get("id"), (tr.get("items") or [{}])[0].get("id")
    resp = api.put(f"/transfers/{tid}/approve", "sa", branch=A)
    rec.eq(s, "approve", (200, "pending"), (resp.status_code, data(resp).get("status")), resp.status_code)
    resp = api.put(f"/transfers/{tid}/ship", "sa", branch=A,
                   json={"items": [{"transfer_item_id": item_id, "quantity_shipped": 3}]})
    rec.eq(s, "ship", (200, "in_transit"), (resp.status_code, data(resp).get("status")), resp.status_code)
    rec.eq(s, "A −3 when shipped", a_before - 3, on_hand(api, A, flow["p1"]))
    resp = api.put(f"/transfers/{tid}/receive", "sa", branch=B,
                   json={"items": [{"transfer_item_id": item_id, "quantity_received": 3, "quantity_damaged": 0}]})
    rec.eq(s, "receive at B", (200, "completed"), (resp.status_code, data(resp).get("status")), resp.status_code)
    rec.eq(s, "A after", a_before - 3, on_hand(api, A, flow["p1"]))
    rec.eq(s, "B after", b_before + 3, on_hand(api, B, flow["p1"]))
    flow["stock"]["p1"] = on_hand(api, A, flow["p1"])  # what really happened, for the reports in k
    flow["stock_b_p1"] = on_hand(api, B, flow["p1"]) or 0
    rec.finish(s)


# ---------------------------------------------------------------------------
# j. Shift: cash in/out, close, x-report
# ---------------------------------------------------------------------------
def test_j_shift(api, rec, flow):
    s = "j"
    needs(flow, "shift", "cash_in_drawer")
    sid = flow["shift"]
    for kind, amount in (("cash_in", "200.00"), ("cash_out", "50.00")):
        resp = api.post(f"/shifts/{sid}/cash-movements", "cashier",
                        json={"amount": amount, "movement_type": kind, "reason": f"E2E {kind}"})
        rec.check(s, f"{kind} {amount}", created(resp), "200/201", resp.status_code, resp.status_code)
    cash_sales = flow["sales"]["o1"] + D(400)  # order 1 cash, order 3 cash after points; order 2 by slip
    expected_cash = D(1000) + cash_sales + D(200) - D(50) - flow.get("refunds", D(0))
    resp = api.put(f"/shifts/{sid}/close", "cashier", json={"closing_cash": str(expected_cash)})
    closed = data(resp)
    rec.eq(s, "close shift with the counted cash", 200, resp.status_code, resp.status_code)
    resp = api.get(f"/shifts/{sid}/x-report", "cashier")
    x = data(resp)
    rec.eq(s, "x-report", 200, resp.status_code, resp.status_code)
    rec.eq(s, "x-report total_sales = 880 + 420 + 420", D(1720), D(x.get("total_sales", 0)))
    rec.eq(s, "x-report total_cash_sales = 880 + 400", cash_sales, D(x.get("total_cash_sales", 0)))
    rec.eq(s, "x-report total_refunds", flow.get("refunds", D(0)), D(x.get("total_refunds", 0)))
    rec.eq(s, "x-report cash in / out", (D(200), D(50)),
           (D(x.get("cash_movements_in", 0)), D(x.get("cash_movements_out", 0))))
    rec.eq(s, "expected_cash = 1000 + cash sales + 200 − 50 − refunds", expected_cash, D(x.get("expected_cash") or 0))
    rec.eq(s, "cash_difference 0 when the drawer matches the sales", D(0), D(x.get("cash_difference") or 0))
    rec.eq(s, "order_count 3", 3, x.get("order_count"))
    rec.note(s, "closed shift", {k: closed.get(k) for k in ("status", "closing_cash", "total_sales")})
    rec.finish(s)


# ---------------------------------------------------------------------------
# k. Reports of today vs what a–j did
# ---------------------------------------------------------------------------
def test_k_reports(api, rec, flow):
    s = "k"
    needs(flow, "sales")
    A, d = flow["A"], today()
    sold = sum(flow["sales"].values(), D(0))
    n_sold = len(flow["sales"])
    refunds = flow.get("refunds", D(0))

    resp = api.get(f"/reports/daily-summary?date={d}&branch_id={A}", "sa")
    day = data(resp)
    rec.eq(s, "daily-summary 200", 200, resp.status_code, resp.status_code)
    rec.eq(s, f"daily-summary orders ({n_sold} sold)", n_sold, day.get("total_orders"))
    rec.eq(s, f"daily-summary revenue {sold}", sold, D(day.get("total_revenue", 0)))
    rec.eq(s, f"daily-summary refunds {refunds}", refunds, D(day.get("total_refunds", 0)))
    rec.eq(s, "daily-summary net", sold - refunds, D(day.get("net_sales", 0)))
    rec.note(s, "status of the slip order (counted only when 'completed')",
             data(api.get(f"/orders/{flow.get('o2')}", "sa")).get("status"))

    resp = api.get(f"/reports/sales?date_from={d}&date_to={d}&branch_id={A}&group_by=category", "sa")
    sales = data(resp)
    rec.eq(s, "sales 200", 200, resp.status_code, resp.status_code)
    rec.eq(s, "sales total", sold, D(sales.get("total_sales", 0)))
    rec.eq(s, "sales orders", n_sold, sales.get("total_orders"))
    top = {p["product_name"]: p["total_qty"] for p in sales.get("top_products", [])}
    rec.eq(s, "top products qty (p1 2, p2 2, p3 1)", {P1["name"]: 2, P2["name"]: 2, P3["name"]: 1}, top)
    cat = {c["category"]: D(c["revenue"]) for c in sales.get("sales_by_category", [])}
    rec.eq(s, "category revenue", {f"E2E Wine {RUN}": sold}, cat)
    hour = datetime.now(BKK).hour
    rec.check(s, "sales_by_hour uses the Bangkok hour", all(abs(h["hour"] - hour) <= 1 for h in sales.get("sales_by_hour", [])),
              f"≈{hour}", [h["hour"] for h in sales.get("sales_by_hour", [])])

    resp = api.get(f"/reports/financial?date_from={d}&date_to={d}&branch_id={A}", "sa")
    fin = data(resp)
    rec.eq(s, "financial 200", 200, resp.status_code, resp.status_code)
    rec.eq(s, "financial gross", sold, D(fin.get("gross_sales", 0)))
    rec.eq(s, "financial refunds", refunds, D(fin.get("refunds", 0)))
    methods = {k: D(v) for k, v in (fin.get("payment_methods") or {}).items()}
    rec.eq(s, "financial payment methods (cash net of change; slip as transfer)",
           {"cash": flow["sales"]["o1"] + D(400), "bank_transfer": D(420)}, methods)

    resp = api.get(f"/reports/inventory?branch_id={A}", "sa")
    inv = {i["product_id"]: i["on_hand"] for i in data(resp).get("items", [])}
    rec.eq(s, "inventory report 200", 200, resp.status_code, resp.status_code)
    rec.eq(s, "inventory p1/p2 at A", (flow["stock"]["p1"], flow["stock"]["p2"]),
           (inv.get(flow["p1"]), inv.get(flow["p2"])))
    rec.finish(s)


# ---------------------------------------------------------------------------
# l. Branch Admin of A cannot see branch B
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "/reports/sales?date_from={d}&date_to={d}&branch_id={B}",
    "/reports/daily-summary?date={d}&branch_id={B}",
    "/inventory/balances?branch_id={B}",
    "/inventory/balances/{B}/{p1}",
    "/shifts/?branch_id={B}",
    "/branches/{B}",
])
def test_l_branch_isolation(api, rec, flow, path):
    s = "l"
    needs(flow, "B", "manager")
    url = path.format(d=today(), B=flow["B"], p1=flow["p1"])
    resp = api.get(url, "manager")
    rec.eq(s, f"Branch Admin A → {path.split('?')[0]}", 404, resp.status_code, resp.status_code)
    rec.finish(s)
