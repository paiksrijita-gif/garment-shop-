"""HTTP routes. Each handler gets a Ctx and returns JSON-able data or a
(bytes, content_type, filename) tuple for downloads."""
import hmac
import os
import re
import sqlite3
import tempfile

from . import auth, db, metrics, reports, services as S, xlsx
from .auth import require, can
from .db import rows, get_setting
from .util import ApiError, bad, v_date, today

ROUTES = []


def route(method, pattern):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


class Ctx:
    def __init__(self, conn, user, params, query, body, token=None):
        self.conn = conn
        self.user = user
        self.params = params
        self.query = query
        self.body = body or {}
        self.token = token
        self.set_cookie = None

    @property
    def id(self):
        return int(self.params[0])


def filters(q):
    """Parse common list / dashboard filters from the query string."""
    f = {}
    for k in ("from", "to"):
        if q.get(k):
            f[k] = v_date(q[k], k, required=False)
    for k in ("supplier_id", "category_id", "product_id", "variant_id", "customer_id", "staff_user_id", "days"):
        if q.get(k):
            if not str(q[k]).isdigit():
                raise bad("Invalid filter %s" % k, k)
            f[k] = int(q[k])
    if q.get("channel"):
        if q["channel"] not in ("retail", "wholesale"):
            raise bad("Invalid channel", "channel")
        f["channel"] = q["channel"]
    for k in ("q", "status", "kind"):
        if q.get(k):
            f[k] = str(q[k])[:100]
    if q.get("unpaid"):
        f["unpaid"] = True
    if f.get("from") and f.get("to") and f["from"] > f["to"]:
        raise bad("'From' date is after 'To' date", "from")
    return f


# --------------------------------------------------------------------------
# auth & setup

def _setup_key():
    return os.environ.get("GS_SETUP_KEY", "")


@route("GET", "/api/status")
def status(c):
    return {
        "needs_owner": not auth.has_users(c.conn),
        "setup_key_required": bool(_setup_key()),
        "user": auth.public_user(c.user) if c.user else None,
        "shop_name": get_setting(c.conn, "shop_name"),
        "today": today(),
    }


@route("POST", "/api/setup/owner")
def setup_owner(c):
    # On a public deployment, only someone who knows GS_SETUP_KEY can claim the owner account.
    key = _setup_key()
    if key and not hmac.compare_digest(str(c.body.get("setup_key") or ""), key):
        raise ApiError(403, "Setup key is incorrect", "setup_key")
    user = auth.create_owner(c.conn, c.body)
    token, user = auth.login(c.conn, user["username"], c.body.get("password"))
    c.set_cookie = token
    return {"user": auth.public_user(user)}


@route("POST", "/api/login")
def login(c):
    token, user = auth.login(c.conn, c.body.get("username"), c.body.get("password"))
    c.set_cookie = token
    return {"user": auth.public_user(user)}


@route("POST", "/api/logout")
def logout(c):
    auth.logout(c.conn, c.token)
    c.set_cookie = ""
    return {"ok": True}


@route("POST", "/api/me/password")
def change_password(c):
    if not c.user:
        raise ApiError(401, "Please sign in")
    auth.change_password(c.conn, c.user, c.body.get("current_password"), c.body.get("new_password"))
    return {"ok": True}


# --------------------------------------------------------------------------
# users, settings, audit

@route("GET", "/api/users")
def users(c):
    require(c.user, "owner")
    return {"users": auth.list_users(c.conn), "permissions": auth.PERMISSIONS,
            "default_staff_permissions": auth.DEFAULT_STAFF_PERMISSIONS}


@route("GET", "/api/staff")
def staff(c):
    """Names of active users for the 'recorded by' selector."""
    return [{"id": r["id"], "full_name": r["full_name"]} for r in
            c.conn.execute("SELECT id, full_name FROM users WHERE active = 1 ORDER BY full_name")]


@route("POST", "/api/users")
def create_user(c):
    require(c.user, "owner")
    return auth.save_user(c.conn, c.user, c.body)


@route("PUT", r"/api/users/(\d+)")
def update_user(c):
    require(c.user, "owner")
    return auth.save_user(c.conn, c.user, c.body, c.id)


@route("GET", "/api/settings")
def get_settings(c):
    s = S.all_settings(c.conn)
    if not can(c.user, "owner"):
        s = {k: s[k] for k in ("shop_name", "default_tax_rate", "prices_include_tax", "invoice_prefix")}
    return s


@route("PUT", "/api/settings")
def put_settings(c):
    return S.update_settings(c.conn, c.user, c.body)


@route("GET", "/api/backup")
def backup(c):
    """Complete copy of the database as a SQLite file (owner only). Works for
    both the local file and a remote Turso database."""
    require(c.user, "owner")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dest = sqlite3.connect(path)
        dest.executescript(db.SCHEMA)
        tables = [r[0] for r in dest.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT IN ('sessions', 'sqlite_sequence')")]
        for t in tables:
            cols = [r[1] for r in dest.execute("PRAGMA table_info(%s)" % t)]
            data = [tuple(r) for r in c.conn.execute("SELECT %s FROM %s" % (", ".join(cols), t))]
            if data:
                dest.executemany("INSERT INTO %s (%s) VALUES (%s)" % (t, ", ".join(cols), ", ".join("?" * len(cols))), data)
        dest.commit()
        dest.close()
        with open(path, "rb") as fh:
            data = fh.read()
    finally:
        os.remove(path)
    auth.audit(c.conn, c.user, "backup.download")
    return data, "application/x-sqlite3", "shop-backup-%s.db" % today()


@route("GET", "/api/audit")
def audit_log(c):
    require(c.user, "owner")
    sql = ("SELECT a.*, u.full_name AS user_name FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
           "WHERE 1 = 1")
    params = []
    q = c.query
    if q.get("entity"):
        sql += " AND a.entity = ?"
        params.append(q["entity"])
    if q.get("entity_id"):
        sql += " AND a.entity_id = ?"
        params.append(q["entity_id"])
    return rows(c.conn.execute(sql + " ORDER BY a.id DESC LIMIT 500", params))


# --------------------------------------------------------------------------
# master data

@route("GET", "/api/categories")
def categories(c):
    return rows(c.conn.execute("SELECT * FROM categories ORDER BY name"))


@route("POST", "/api/categories")
def create_category(c):
    require(c.user, "products.manage")
    return S.create_category(c.conn, c.user, c.body)


@route("GET", "/api/expense-categories")
def expense_categories(c):
    return rows(c.conn.execute("SELECT * FROM expense_categories ORDER BY name"))


@route("POST", "/api/expense-categories")
def create_expense_category(c):
    require(c.user, "expenses.create")
    return S.create_category(c.conn, c.user, c.body, "expense_categories")


@route("GET", "/api/suppliers")
def suppliers(c):
    require(c.user, "purchases.create", "suppliers.manage", "purchases.view", "reports.view")
    data = S.list_suppliers(c.conn, c.query.get("q", ""))
    if not can(c.user, "purchases.view"):
        data = [{k: s[k] for k in ("id", "code", "name", "phone", "categories", "active")} for s in data]
    return data


@route("POST", "/api/suppliers")
def create_supplier(c):
    return {"id": S.save_supplier(c.conn, c.user, c.body)}


@route("GET", r"/api/suppliers/(\d+)")
def get_supplier(c):
    require(c.user, "purchases.view", "suppliers.manage")
    s = S.get_supplier(c.conn, c.id)
    if not can(c.user, "purchases.view"):
        for k in ("purchases", "payments", "products", "total_purchases", "total_paid", "outstanding",
                  "opening_balance"):
            s.pop(k, None)
    return s


@route("PUT", r"/api/suppliers/(\d+)")
def update_supplier(c):
    return {"id": S.save_supplier(c.conn, c.user, c.body, c.id)}


@route("GET", "/api/customers")
def customers(c):
    require(c.user, "sales.create", "customers.manage", "payments.record")
    return S.list_customers(c.conn, c.query.get("q", ""))


@route("POST", "/api/customers")
def create_customer(c):
    return {"id": S.save_customer(c.conn, c.user, c.body)}


@route("GET", r"/api/customers/(\d+)")
def get_customer(c):
    require(c.user, "customers.manage", "payments.record", "sales.view_all")
    return S.get_customer(c.conn, c.id)


@route("PUT", r"/api/customers/(\d+)")
def update_customer(c):
    return {"id": S.save_customer(c.conn, c.user, c.body, c.id)}


@route("GET", "/api/products")
def products(c):
    require(c.user, "inventory.view", "products.manage", "sales.create", "purchases.create")
    return S.list_products(c.conn, c.user, c.query.get("q", ""), c.query.get("category_id"),
                           bool(c.query.get("all")))


@route("POST", "/api/products")
def create_product(c):
    return {"id": S.save_product(c.conn, c.user, c.body)}


@route("GET", r"/api/products/(\d+)")
def get_product(c):
    require(c.user, "inventory.view", "products.manage", "sales.create", "purchases.create")
    return S.get_product(c.conn, c.user, c.id)


@route("PUT", r"/api/products/(\d+)")
def update_product(c):
    return {"id": S.save_product(c.conn, c.user, c.body, c.id)}


@route("POST", r"/api/products/(\d+)/variants")
def add_variants(c):
    return {"ids": S.add_variants(c.conn, c.user, c.id, c.body)}


@route("PUT", r"/api/variants/(\d+)")
def update_variant(c):
    S.update_variant(c.conn, c.user, c.id, c.body)
    return {"ok": True}


@route("GET", "/api/variants")
def variants(c):
    require(c.user, "inventory.view", "sales.create", "purchases.create", "products.manage", "inventory.adjust")
    limit = c.query.get("limit", "30")
    product_id = c.query.get("product_id")
    return S.search_variants(c.conn, c.user, c.query.get("q", ""), int(limit) if limit.isdigit() else 30,
                             bool(c.query.get("in_stock")), int(product_id) if (product_id or "").isdigit() else None)


# --------------------------------------------------------------------------
# transactions

@route("GET", "/api/purchases")
def purchases(c):
    require(c.user, "purchases.view", "purchases.create")
    return S.list_purchases(c.conn, c.user, filters(c.query))


@route("POST", "/api/purchases")
def create_purchase(c):
    return {"id": S.create_purchase(c.conn, c.user, c.body)}


@route("GET", r"/api/purchases/(\d+)")
def get_purchase(c):
    require(c.user, "purchases.view", "purchases.create")
    return S.get_purchase(c.conn, c.user, c.id)


@route("GET", "/api/sales/next-invoice")
def next_invoice(c):
    require(c.user, "sales.create")
    return {"invoice_no": S.next_invoice_no(c.conn)}


@route("GET", "/api/sales")
def sales(c):
    require(c.user, "sales.create", "sales.view_all")
    return S.list_sales(c.conn, c.user, filters(c.query))


@route("POST", "/api/sales")
def create_sale(c):
    return {"id": S.create_sale(c.conn, c.user, c.body)}


@route("GET", r"/api/sales/(\d+)")
def get_sale(c):
    require(c.user, "sales.create", "sales.view_all")
    return S.get_sale(c.conn, c.user, c.id)


@route("POST", r"/api/sales/(\d+)/returns")
def create_return(c):
    return {"id": S.create_return(c.conn, c.user, c.id, c.body)}


@route("GET", "/api/supplier-payments")
def supplier_payments(c):
    require(c.user, "purchases.view", "payments.record")
    f = filters(c.query)
    sql = ("SELECT sp.*, s.name AS supplier_name, p.invoice_no FROM supplier_payments sp "
           "JOIN suppliers s ON s.id = sp.supplier_id LEFT JOIN purchases p ON p.id = sp.purchase_id WHERE 1 = 1")
    params = []
    for k, col in (("from", "sp.payment_date >= ?"), ("to", "sp.payment_date <= ?"),
                   ("supplier_id", "sp.supplier_id = ?")):
        if f.get(k):
            sql += " AND " + col
            params.append(f[k])
    return rows(c.conn.execute(sql + " ORDER BY sp.payment_date DESC, sp.id DESC LIMIT 1000", params))


@route("POST", "/api/supplier-payments")
def create_supplier_payment(c):
    return {"id": S.create_supplier_payment(c.conn, c.user, c.body)}


@route("GET", "/api/customer-payments")
def customer_payments(c):
    require(c.user, "payments.record", "reports.view")
    f = filters(c.query)
    sql = ("SELECT cp.*, cu.name AS customer_name, s.invoice_no FROM customer_payments cp "
           "LEFT JOIN customers cu ON cu.id = cp.customer_id LEFT JOIN sales s ON s.id = cp.sale_id "
           "WHERE cp.with_document = 0")
    params = []
    for k, col in (("from", "cp.payment_date >= ?"), ("to", "cp.payment_date <= ?"),
                   ("customer_id", "cp.customer_id = ?")):
        if f.get(k):
            sql += " AND " + col
            params.append(f[k])
    return rows(c.conn.execute(sql + " ORDER BY cp.payment_date DESC, cp.id DESC LIMIT 1000", params))


@route("POST", "/api/customer-payments")
def create_customer_payment(c):
    return {"id": S.create_customer_payment(c.conn, c.user, c.body)}


@route("GET", "/api/adjustments")
def adjustments(c):
    require(c.user, "inventory.adjust", "inventory.cost")
    return S.list_adjustments(c.conn, c.user, filters(c.query))


@route("POST", "/api/adjustments")
def create_adjustment(c):
    return {"id": S.create_adjustment(c.conn, c.user, c.body)}


@route("GET", "/api/opening-stock")
def opening_stock(c):
    require(c.user, "owner")
    return S.list_opening_stock(c.conn)


@route("POST", "/api/opening-stock")
def create_opening_stock(c):
    return {"ids": S.add_opening_stock(c.conn, c.user, c.body)}


@route("GET", "/api/expenses")
def expenses(c):
    require(c.user, "expenses.create", "reports.view")
    f = filters(c.query)
    data = S.list_expenses(c.conn, c.user, f)
    summary = None
    if can(c.user, "reports.view"):
        summary = {
            "by_category": sorted(({"category": k, "amount": v} for k, v in
                                   metrics.expenses_by(c.conn, f, "category").items()), key=lambda r: -r["amount"]),
            "by_month": sorted(({"month": k, "amount": v} for k, v in
                                metrics.expenses_by(c.conn, f, "month").items()), key=lambda r: r["month"]),
        }
    return {"rows": data, "summary": summary}


@route("POST", "/api/expenses")
def create_expense(c):
    return {"id": S.create_expense(c.conn, c.user, c.body)}


@route("GET", "/api/cash")
def cash(c):
    require(c.user, "owner")
    return {"rows": S.list_cash_txns(c.conn, filters(c.query)),
            "kinds": {k: v[0] for k, v in S.CASH_KINDS.items()},
            "summary": metrics.capital_summary(c.conn)}


@route("POST", "/api/cash")
def create_cash(c):
    return {"id": S.create_cash_txn(c.conn, c.user, c.body)}


@route("POST", r"/api/void/([a-z_]+)/(\d+)")
def void(c):
    S.void(c.conn, c.user, c.params[0], int(c.params[1]), c.body)
    return {"ok": True}


# --------------------------------------------------------------------------
# inventory, dashboard, reports

@route("GET", "/api/inventory")
def inventory(c):
    require(c.user, "inventory.view")
    return metrics.inventory_overview(c.conn, can(c.user, "inventory.cost"), filters(c.query))


@route("GET", r"/api/inventory/ledger/(\d+)")
def ledger(c):
    require(c.user, "inventory.view")
    data = metrics.variant_ledger(c.conn, c.id, can(c.user, "inventory.cost"))
    if not data:
        raise ApiError(404, "Product not found")
    return data


@route("GET", "/api/dashboard")
def dashboard(c):
    require(c.user, "reports.view")
    return metrics.dashboard(c.conn, filters(c.query))


@route("GET", "/api/home")
def home(c):
    """Lightweight summary for staff without financial access."""
    if not c.user:
        raise ApiError(401, "Please sign in")
    t = today()
    mine = c.conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total_amount), 0) AS amt FROM sales WHERE status = 'final' "
        "AND sale_date = ? AND (staff_user_id = ? OR created_by = ?)", (t, c.user["id"], c.user["id"])).fetchone()
    out = {"my_sales_today": {"count": mine["n"], "amount": mine["amt"]}}
    if can(c.user, "inventory.view"):
        r = c.conn.execute(
            "SELECT COALESCE(SUM(v.stock_qty), 0) AS units, "
            "SUM(CASE WHEN v.stock_qty <= 0 THEN 1 ELSE 0 END) AS out_n, "
            "SUM(CASE WHEN v.stock_qty > 0 AND v.stock_qty <= p.low_stock_level THEN 1 ELSE 0 END) AS low_n "
            "FROM variants v JOIN products p ON p.id = v.product_id WHERE v.active = 1 AND p.active = 1").fetchone()
        out["stock"] = {"units": r["units"], "out": r["out_n"] or 0, "low": r["low_n"] or 0}
    return out


@route("GET", "/api/profit")
def profit(c):
    require(c.user, "reports.view")
    f = filters(c.query)
    return {
        "summary": metrics.profit_summary(c.conn, f),
        "channels": metrics.pl_by(c.conn, f, "channel"),
        "monthly": metrics.monthly_pl(c.conn, f),
        "categories": _json_report(reports.run(c.conn, "category-profit", f)),
        "products": _json_report(reports.run(c.conn, "product-profit", f)),
        "costing_method": get_setting(c.conn, "costing_method"),
    }


def _json_report(r):
    r["columns"] = [{"key": k, "label": l, "type": t} for k, l, t in r["columns"]]
    return r


@route("GET", "/api/reports")
def report_list(c):
    require(c.user, "reports.view")
    return [{"key": k, "title": v[0], "filters": v[2]} for k, v in reports.REPORTS.items()]


def _subtitle(conn, f):
    parts = [get_setting(conn, "shop_name")]
    if f.get("from") or f.get("to"):
        fmt = lambda d: "%s-%s-%s" % (d[8:10], d[5:7], d[:4]) if d else "…"
        parts.append("Period: %s to %s" % (fmt(f.get("from")), fmt(f.get("to"))))
    parts.append("Generated: %s" % "-".join(reversed(today().split("-"))))
    return " · ".join(parts)


@route("GET", "/api/reports/all")
def report_all(c):
    require(c.user, "reports.view")
    f = filters(c.query)
    sheets = []
    for key in reports.REPORTS:
        r = reports.run(c.conn, key, f)
        sheets.append({"name": r["title"], "title": r["title"], "subtitle": _subtitle(c.conn, f),
                       "columns": r["columns"], "rows": r["rows"], "totals": r["totals"]})
    return (xlsx.build_xlsx(sheets),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "all-reports-%s.xlsx" % today())


@route("GET", r"/api/reports/([a-z\-]+)")
def report(c):
    require(c.user, "reports.view")
    key = c.params[0]
    if key not in reports.REPORTS:
        raise ApiError(404, "Unknown report")
    f = filters(c.query)
    r = reports.run(c.conn, key, f)
    fmt = c.query.get("format", "json")
    if fmt == "csv":
        return xlsx.build_csv(r["columns"], r["rows"], r["totals"]), "text/csv; charset=utf-8", \
            "%s-%s.csv" % (key, today())
    if fmt == "xlsx":
        data = xlsx.build_xlsx([{"name": r["title"], "title": r["title"], "subtitle": _subtitle(c.conn, f),
                                 "columns": r["columns"], "rows": r["rows"], "totals": r["totals"]}])
        return data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", \
            "%s-%s.xlsx" % (key, today())
    return _json_report(r)
