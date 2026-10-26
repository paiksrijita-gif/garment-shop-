"""Master data and transaction entry. Every write runs in one DB transaction,
updates the stock ledger where needed and writes an audit-log entry."""
import re

from .auth import audit, can, require
from .db import tx, get_setting, rows, one
from .ledger import recost_variants, recost_all
from .util import (
    ApiError, bad, money, qty_round, today, now_iso, v_date, v_str, v_num, v_int,
    v_choice, v_method, account_for, EPS,
)

UNITS = ["piece", "set", "pair", "dozen", "metre", "box"]


# --------------------------------------------------------------------------
# helpers

def _client_ref(conn, table, data):
    """Idempotency: the same form submission (client_ref) is only saved once."""
    ref = data.get("client_ref")
    if ref in (None, ""):
        return None
    ref = v_str(ref, "client_ref", max_len=64)
    row = conn.execute("SELECT id FROM %s WHERE client_ref = ?" % table, (ref,)).fetchone()
    if row:
        raise ApiError(409, "This entry was already saved", "duplicate:%d" % row["id"])
    return ref


def _get(conn, table, id_, label):
    row = conn.execute("SELECT * FROM %s WHERE id = ?" % table, (id_,)).fetchone()
    if not row:
        raise ApiError(404, "%s not found" % label)
    return row


def _items(data):
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise bad("Add at least one product line", "items")
    if len(items) > 200:
        raise bad("Too many lines in one entry", "items")
    return items


def _variant(conn, vid, field):
    vid = v_int(vid, field, label="product")
    row = conn.execute(
        "SELECT v.*, p.name AS product_name, p.unit, p.active AS product_active "
        "FROM variants v JOIN products p ON p.id = v.product_id WHERE v.id = ?",
        (vid,),
    ).fetchone()
    if not row:
        raise bad("Select a product", field)
    return row


def variant_label(row):
    attrs = " / ".join(x for x in (row["size"], row["colour"], row["design"]) if x)
    return row["product_name"] + (" (%s)" % attrs if attrs else "")


# --------------------------------------------------------------------------
# settings

def update_settings(conn, user, data):
    require(user, "owner")
    allowed = {
        "shop_name": lambda v: v_str(v, "shop_name", required=True, max_len=100),
        "default_tax_rate": lambda v: str(v_num(v, "default_tax_rate", 0, 28)),
        "prices_include_tax": lambda v: "1" if v in (True, "1", 1) else "0",
        "low_stock_default": lambda v: str(v_num(v, "low_stock_default", 0)),
        "invoice_prefix": lambda v: v_str(v, "invoice_prefix", required=True, max_len=10),
        "costing_method": lambda v: v_choice(v, "costing_method", ("WAC", "FIFO"), "costing method"),
        "setup_complete": lambda v: "1" if v in (True, "1", 1) else "0",
        "opening_date": lambda v: v_date(v, "opening_date", required=False) or "",
        "opening_capital": lambda v: str(money(v_num(v, "opening_capital", 0, required=False))),
    }
    with tx(conn):
        changed = {}
        for k, fn in allowed.items():
            if k in data:
                val = fn(data[k])
                if val != get_setting(conn, k):
                    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, val))
                    changed[k] = val
        if "costing_method" in changed:
            recost_all(conn)
        if changed:
            audit(conn, user, "settings.update", "settings", None, changed)
    return all_settings(conn)


def all_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


# --------------------------------------------------------------------------
# categories

def create_category(conn, user, data, table="categories"):
    name = v_str(data.get("name"), "name", required=True, max_len=60, label="Category name")
    with tx(conn):
        if conn.execute("SELECT 1 FROM %s WHERE name = ?" % table, (name,)).fetchone():
            raise ApiError(409, "Category already exists", "name")
        cur = conn.execute("INSERT INTO %s (name) VALUES (?)" % table, (name,))
        audit(conn, user, "category.create", table, cur.lastrowid, {"name": name})
    return {"id": cur.lastrowid, "name": name}


# --------------------------------------------------------------------------
# suppliers

def _supplier_fields(data):
    return dict(
        name=v_str(data.get("name"), "name", required=True, max_len=100, label="Supplier name"),
        phone=v_str(data.get("phone"), "phone", max_len=30),
        address=v_str(data.get("address"), "address", max_len=300),
        gstin=v_str(data.get("gstin"), "gstin", max_len=20).upper(),
        categories=v_str(data.get("categories"), "categories", max_len=300),
        notes=v_str(data.get("notes"), "notes", max_len=500),
    )


def save_supplier(conn, user, data, supplier_id=None):
    require(user, "suppliers.manage")
    f = _supplier_fields(data)
    if f["phone"] and not re.fullmatch(r"[0-9+\-() ]{6,30}", f["phone"]):
        raise bad("Enter a valid contact number", "phone")
    with tx(conn):
        dup = conn.execute("SELECT id FROM suppliers WHERE name = ? AND id IS NOT ?",
                           (f["name"], supplier_id)).fetchone()
        if dup:
            raise ApiError(409, "A supplier with this name already exists", "name")
        if supplier_id is None:
            opening = 0.0
            if "opening_balance" in data and can(user, "owner"):
                opening = money(v_num(data.get("opening_balance"), "opening_balance", 0, required=False))
            cur = conn.execute(
                "INSERT INTO suppliers (code, name, phone, address, gstin, categories, notes, opening_balance) "
                "VALUES ('', :name, :phone, :address, :gstin, :categories, :notes, :ob)",
                dict(f, ob=opening),
            )
            supplier_id = cur.lastrowid
            conn.execute("UPDATE suppliers SET code = ? WHERE id = ?", ("SUP-%04d" % supplier_id, supplier_id))
            audit(conn, user, "supplier.create", "suppliers", supplier_id, dict(f, opening_balance=opening))
        else:
            _get(conn, "suppliers", supplier_id, "Supplier")
            f["id"] = supplier_id
            f["active"] = 0 if data.get("active") is False else 1
            conn.execute(
                "UPDATE suppliers SET name=:name, phone=:phone, address=:address, gstin=:gstin, "
                "categories=:categories, notes=:notes, active=:active WHERE id=:id", f)
            if "opening_balance" in data and can(user, "owner"):
                conn.execute("UPDATE suppliers SET opening_balance = ? WHERE id = ?",
                             (money(v_num(data["opening_balance"], "opening_balance", 0)), supplier_id))
            audit(conn, user, "supplier.update", "suppliers", supplier_id, data)
    return supplier_id


SUPPLIER_BALANCE_SQL = """
SELECT s.*,
  COALESCE((SELECT SUM(total_cost) FROM purchases WHERE supplier_id = s.id AND status = 'final'), 0) AS total_purchases,
  COALESCE((SELECT SUM(pi.qty) FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id
            WHERE pu.supplier_id = s.id AND pu.status = 'final'), 0) AS total_units,
  COALESCE((SELECT SUM(amount) FROM supplier_payments WHERE supplier_id = s.id AND status = 'final'), 0) AS total_paid,
  (SELECT MAX(purchase_date) FROM purchases WHERE supplier_id = s.id AND status = 'final') AS last_purchase,
  (SELECT COUNT(*) FROM purchases WHERE supplier_id = s.id AND status = 'final') AS purchase_count
FROM suppliers s
"""


def _supplier_row(r):
    r = dict(r)
    r["outstanding"] = money(r["opening_balance"] + r["total_purchases"] - r["total_paid"])
    return r


def list_suppliers(conn, q=""):
    sql = SUPPLIER_BALANCE_SQL
    params = []
    if q:
        sql += " WHERE s.name LIKE ? OR s.code LIKE ? OR s.phone LIKE ? OR s.categories LIKE ?"
        params = ["%" + q + "%"] * 4
    sql += " ORDER BY s.active DESC, s.name"
    return [_supplier_row(r) for r in conn.execute(sql, params)]


def get_supplier(conn, supplier_id):
    r = conn.execute(SUPPLIER_BALANCE_SQL + " WHERE s.id = ?", (supplier_id,)).fetchone()
    if not r:
        raise ApiError(404, "Supplier not found")
    s = _supplier_row(r)
    s["purchases"] = rows(conn.execute(
        "SELECT p.*, (SELECT SUM(qty) FROM purchase_items WHERE purchase_id = p.id) AS units "
        "FROM purchases p WHERE supplier_id = ? ORDER BY purchase_date DESC, id DESC", (supplier_id,)))
    s["payments"] = rows(conn.execute(
        "SELECT sp.*, p.invoice_no FROM supplier_payments sp LEFT JOIN purchases p ON p.id = sp.purchase_id "
        "WHERE sp.supplier_id = ? ORDER BY payment_date DESC, sp.id DESC", (supplier_id,)))
    s["supplied_categories"] = [r["name"] for r in conn.execute(
        "SELECT DISTINCT c.name FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id "
        "JOIN variants v ON v.id = pi.variant_id JOIN products p ON p.id = v.product_id "
        "JOIN categories c ON c.id = p.category_id WHERE pu.supplier_id = ? AND pu.status = 'final' "
        "ORDER BY c.name", (supplier_id,))]
    s["products"] = rows(conn.execute(
        """SELECT p.id AS product_id, p.name AS product_name, c.name AS category, p.unit,
                  SUM(pi.qty) AS units, SUM(pi.landed_value) AS value, MAX(pu.purchase_date) AS last_date
           FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id
           JOIN variants v ON v.id = pi.variant_id JOIN products p ON p.id = v.product_id
           JOIN categories c ON c.id = p.category_id
           WHERE pu.supplier_id = ? AND pu.status = 'final'
           GROUP BY p.id ORDER BY value DESC""", (supplier_id,)))
    return s


# --------------------------------------------------------------------------
# customers

def save_customer(conn, user, data, customer_id=None):
    require(user, "customers.manage", "sales.create")
    name = v_str(data.get("name"), "name", required=True, max_len=100, label="Customer name")
    phone = v_str(data.get("phone"), "phone", max_len=30)
    address = v_str(data.get("address"), "address", max_len=300)
    kind = v_choice(data.get("kind") or "retail", "kind", ("retail", "wholesale"), "customer type")
    notes = v_str(data.get("notes"), "notes", max_len=500)
    with tx(conn):
        dup = conn.execute("SELECT id FROM customers WHERE name = ? COLLATE NOCASE AND phone = ? AND id IS NOT ?",
                           (name, phone, customer_id)).fetchone()
        if dup:
            raise ApiError(409, "This customer already exists", "name")
        if customer_id is None:
            opening = 0.0
            if "opening_balance" in data and can(user, "owner"):
                opening = money(v_num(data.get("opening_balance"), "opening_balance", 0, required=False))
            cur = conn.execute(
                "INSERT INTO customers (name, phone, address, kind, notes, opening_balance) VALUES (?, ?, ?, ?, ?, ?)",
                (name, phone, address, kind, notes, opening))
            customer_id = cur.lastrowid
            audit(conn, user, "customer.create", "customers", customer_id, {"name": name, "phone": phone,
                                                                          "opening_balance": opening})
        else:
            _get(conn, "customers", customer_id, "Customer")
            conn.execute("UPDATE customers SET name=?, phone=?, address=?, kind=?, notes=? WHERE id=?",
                         (name, phone, address, kind, notes, customer_id))
            if "opening_balance" in data and can(user, "owner"):
                conn.execute("UPDATE customers SET opening_balance = ? WHERE id = ?",
                             (money(v_num(data["opening_balance"], "opening_balance", 0)), customer_id))
            audit(conn, user, "customer.update", "customers", customer_id, data)
    return customer_id


CUSTOMER_BALANCE_SQL = """
SELECT c.*,
  COALESCE((SELECT SUM(total_amount) FROM sales WHERE customer_id = c.id AND status = 'final'), 0) AS total_sales,
  COALESCE((SELECT SUM(amount) FROM customer_payments WHERE customer_id = c.id AND status = 'final'), 0) AS total_received,
  COALESCE((SELECT SUM(r.total_refund) FROM sale_returns r JOIN sales s ON s.id = r.sale_id
            WHERE s.customer_id = c.id AND r.status = 'final' AND r.refund_mode = 'credit'), 0) AS return_credits,
  (SELECT MAX(sale_date) FROM sales WHERE customer_id = c.id AND status = 'final') AS last_sale
FROM customers c
"""


def _customer_row(r):
    r = dict(r)
    r["outstanding"] = money(r["opening_balance"] + r["total_sales"] - r["total_received"] - r["return_credits"])
    return r


def list_customers(conn, q=""):
    sql = CUSTOMER_BALANCE_SQL
    params = []
    if q:
        sql += " WHERE c.name LIKE ? OR c.phone LIKE ?"
        params = ["%" + q + "%"] * 2
    sql += " ORDER BY c.name"
    return [_customer_row(r) for r in conn.execute(sql, params)]


def get_customer(conn, customer_id):
    r = conn.execute(CUSTOMER_BALANCE_SQL + " WHERE c.id = ?", (customer_id,)).fetchone()
    if not r:
        raise ApiError(404, "Customer not found")
    c = _customer_row(r)
    c["sales"] = rows(conn.execute(
        "SELECT * FROM sales WHERE customer_id = ? ORDER BY sale_date DESC, id DESC", (customer_id,)))
    c["payments"] = rows(conn.execute(
        "SELECT cp.*, s.invoice_no FROM customer_payments cp LEFT JOIN sales s ON s.id = cp.sale_id "
        "WHERE cp.customer_id = ? ORDER BY payment_date DESC, cp.id DESC", (customer_id,)))
    return c


# --------------------------------------------------------------------------
# products & variants

def _sku_base(conn, product_id, category_id):
    cat = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
    letters = re.sub(r"[^A-Za-z]", "", cat["name"] if cat else "PRD").upper()[:3] or "PRD"
    return "%s-%04d" % (letters, product_id)


def _clean_attr(v, field):
    return v_str(v, field, max_len=40)


def save_product(conn, user, data, product_id=None):
    require(user, "products.manage")
    name = v_str(data.get("name"), "name", required=True, max_len=120, label="Product name / design")
    category_id = v_int(data.get("category_id"), "category_id", label="category")
    unit = v_choice(data.get("unit") or "piece", "unit", UNITS, "unit")
    low = v_num(data.get("low_stock_level"), "low_stock_level", 0, required=False,
                default=float(get_setting(conn, "low_stock_default") or 5))
    desc = v_str(data.get("description"), "description", max_len=500)
    has_variants = 1 if data.get("has_variants") else 0
    with tx(conn):
        _get(conn, "categories", category_id, "Category")
        dup = conn.execute("SELECT id FROM products WHERE name = ? AND id IS NOT ?", (name, product_id)).fetchone()
        if dup:
            raise ApiError(409, "A product with this name already exists", "name")
        if product_id is None:
            cur = conn.execute(
                "INSERT INTO products (name, category_id, unit, has_variants, low_stock_level, description) "
                "VALUES (?, ?, ?, ?, ?, ?)", (name, category_id, unit, has_variants, low, desc))
            product_id = cur.lastrowid
            variants = data.get("variants") or []
            if not has_variants or not variants:
                variants = [{"size": "", "colour": "", "design": "",
                             "retail_price": data.get("retail_price"),
                             "wholesale_price": data.get("wholesale_price"),
                             "sku": data.get("sku")}]
            for i, v in enumerate(variants):
                _insert_variant(conn, product_id, category_id, v, "variants.%d" % i)
            audit(conn, user, "product.create", "products", product_id, {"name": name, "variants": len(variants)})
        else:
            prod = _get(conn, "products", product_id, "Product")
            active = 0 if data.get("active") is False else 1
            conn.execute(
                "UPDATE products SET name=?, category_id=?, unit=?, low_stock_level=?, description=?, active=?, "
                "has_variants = MAX(has_variants, ?) WHERE id=?",
                (name, category_id, unit, low, desc, active, has_variants, product_id))
            if not prod["has_variants"] and not has_variants:
                # simple product: allow price edits on its single variant
                v = conn.execute("SELECT id FROM variants WHERE product_id = ?", (product_id,)).fetchone()
                if v and ("retail_price" in data or "wholesale_price" in data):
                    _update_variant_prices(conn, v["id"], data)
            audit(conn, user, "product.update", "products", product_id, data)
    return product_id


def _insert_variant(conn, product_id, category_id, v, field):
    size = _clean_attr(v.get("size"), field + ".size")
    colour = _clean_attr(v.get("colour"), field + ".colour")
    design = _clean_attr(v.get("design"), field + ".design")
    retail = money(v_num(v.get("retail_price"), field + ".retail_price", 0, required=False, label="Retail price"))
    whole = money(v_num(v.get("wholesale_price"), field + ".wholesale_price", 0, required=False,
                        label="Wholesale price"))
    sku = v_str(v.get("sku"), field + ".sku", max_len=40).upper()
    if not sku:
        parts = [_sku_base(conn, product_id, category_id)]
        parts += [re.sub(r"[^A-Za-z0-9]", "", x).upper()[:6] for x in (size, colour, design) if x]
        sku = "-".join(parts)
    if conn.execute("SELECT 1 FROM variants WHERE sku = ?", (sku,)).fetchone():
        raise ApiError(409, "SKU %s already exists" % sku, field + ".sku")
    if conn.execute("SELECT 1 FROM variants WHERE product_id = ? AND size = ? AND colour = ? AND design = ?",
                    (product_id, size, colour, design)).fetchone():
        raise ApiError(409, "This size / colour / design already exists for the product", field)
    cur = conn.execute(
        "INSERT INTO variants (product_id, sku, size, colour, design, retail_price, wholesale_price) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (product_id, sku, size, colour, design, retail, whole))
    return cur.lastrowid


def _update_variant_prices(conn, variant_id, data):
    retail = money(v_num(data.get("retail_price"), "retail_price", 0, required=False))
    whole = money(v_num(data.get("wholesale_price"), "wholesale_price", 0, required=False))
    conn.execute("UPDATE variants SET retail_price = ?, wholesale_price = ? WHERE id = ?", (retail, whole, variant_id))


def add_variants(conn, user, product_id, data):
    require(user, "products.manage")
    variants = data.get("variants") or []
    if not variants:
        raise bad("Add at least one variant", "variants")
    with tx(conn):
        prod = _get(conn, "products", product_id, "Product")
        ids = [_insert_variant(conn, product_id, prod["category_id"], v, "variants.%d" % i)
               for i, v in enumerate(variants)]
        conn.execute("UPDATE products SET has_variants = 1 WHERE id = ?", (product_id,))
        audit(conn, user, "variant.create", "products", product_id, {"count": len(ids)})
    return ids


def update_variant(conn, user, variant_id, data):
    require(user, "products.manage")
    with tx(conn):
        _get(conn, "variants", variant_id, "Variant")
        _update_variant_prices(conn, variant_id, data)
        if "active" in data:
            conn.execute("UPDATE variants SET active = ? WHERE id = ?", (1 if data["active"] else 0, variant_id))
        audit(conn, user, "variant.update", "variants", variant_id, data)


def list_products(conn, user, q="", category_id=None, include_inactive=False):
    show_cost = can(user, "inventory.cost")
    sql = """SELECT p.*, c.name AS category,
               COUNT(v.id) AS variant_count, COALESCE(SUM(v.stock_qty), 0) AS stock_qty,
               COALESCE(SUM(v.stock_value), 0) AS stock_value,
               MIN(v.retail_price) AS min_retail, MAX(v.retail_price) AS max_retail
             FROM products p JOIN categories c ON c.id = p.category_id
             LEFT JOIN variants v ON v.product_id = p.id
             WHERE 1 = 1"""
    params = []
    if not include_inactive:
        sql += " AND p.active = 1"
    if q:
        sql += " AND (p.name LIKE ? OR c.name LIKE ? OR p.id IN (SELECT product_id FROM variants WHERE sku LIKE ?))"
        params += ["%" + q + "%"] * 3
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
    sql += " GROUP BY p.id ORDER BY p.name"
    out = rows(conn.execute(sql, params))
    if not show_cost:
        for r in out:
            r.pop("stock_value", None)
    return out


def get_product(conn, user, product_id):
    p = one(conn.execute(
        "SELECT p.*, c.name AS category FROM products p JOIN categories c ON c.id = p.category_id WHERE p.id = ?",
        (product_id,)))
    if not p:
        raise ApiError(404, "Product not found")
    p["variants"] = rows(conn.execute("SELECT * FROM variants WHERE product_id = ? ORDER BY id", (product_id,)))
    if not can(user, "inventory.cost"):
        for v in p["variants"]:
            v.pop("stock_value", None)
    return p


def search_variants(conn, user, q="", limit=30, in_stock=False, product_id=None):
    show_cost = can(user, "inventory.cost")
    sql = """SELECT v.id, v.sku, v.size, v.colour, v.design, v.retail_price, v.wholesale_price,
                    v.stock_qty, v.stock_value, p.id AS product_id, p.name AS product_name, p.unit,
                    p.low_stock_level, c.id AS category_id, c.name AS category
             FROM variants v JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id
             WHERE v.active = 1 AND p.active = 1"""
    params = []
    for term in (q or "").split():
        sql += " AND (p.name LIKE ? OR v.sku LIKE ? OR v.size LIKE ? OR v.colour LIKE ? OR v.design LIKE ? OR c.name LIKE ?)"
        params += ["%" + term + "%"] * 6
    if in_stock:
        sql += " AND v.stock_qty > 0"
    if product_id:
        sql += " AND p.id = ?"
        params.append(int(product_id))
    sql += " ORDER BY p.name, v.size, v.colour LIMIT ?"
    params.append(min(int(limit), 200))
    out = rows(conn.execute(sql, params))
    for r in out:
        r["label"] = variant_label(r)
        r["avg_cost"] = money(r["stock_value"] / r["stock_qty"]) if r["stock_qty"] > 0 else None
        if not show_cost:
            r.pop("stock_value")
            r.pop("avg_cost")
    return out


# --------------------------------------------------------------------------
# opening stock (setup)

def add_opening_stock(conn, user, data):
    require(user, "owner")
    entry_date = v_date(data.get("entry_date") or get_setting(conn, "opening_date") or today(), "entry_date")
    items = _items(data)
    with tx(conn):
        ref = _client_ref(conn, "opening_stock", data)
        ids, vids = [], []
        for i, it in enumerate(items):
            f = "items.%d" % i
            v = _variant(conn, it.get("variant_id"), f + ".variant_id")
            q = qty_round(v_num(it.get("qty"), f + ".qty", gt=0, label="Quantity"))
            uc = v_num(it.get("unit_cost"), f + ".unit_cost", 0, label="Unit cost")
            sid = v_int(it.get("supplier_id"), f + ".supplier_id", required=False)
            if sid:
                _get(conn, "suppliers", sid, "Supplier")
            value = money(q * uc)
            cur = conn.execute(
                "INSERT INTO opening_stock (entry_date, variant_id, supplier_id, qty, unit_cost, value, notes, "
                "client_ref, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_date, v["id"], sid, q, uc, value, v_str(it.get("notes"), f + ".notes", max_len=200),
                 ref if i == 0 else None, user["id"]))
            conn.execute(
                "INSERT INTO inventory_movements (move_date, variant_id, kind, qty, unit_cost, value, ref_table, "
                "ref_id) VALUES (?, ?, 'opening', ?, ?, ?, 'opening_stock', ?)",
                (entry_date, v["id"], q, uc, value, cur.lastrowid))
            ids.append(cur.lastrowid)
            vids.append(v["id"])
        recost_variants(conn, vids)
        audit(conn, user, "opening_stock.create", "opening_stock", ids[0], {"lines": len(ids)})
    return ids


def list_opening_stock(conn):
    out = rows(conn.execute(
        """SELECT o.*, v.sku, v.size, v.colour, v.design, p.name AS product_name, s.name AS supplier_name
           FROM opening_stock o JOIN variants v ON v.id = o.variant_id JOIN products p ON p.id = v.product_id
           LEFT JOIN suppliers s ON s.id = o.supplier_id ORDER BY o.entry_date DESC, o.id DESC"""))
    for r in out:
        r["label"] = variant_label(r)
    return out


# --------------------------------------------------------------------------
# purchases

def purchase_total(lines, additional_cost, discount):
    """Total Purchase Cost = Σ(qty × unit price) + additional costs − discount.
    Additional costs and discount are spread over lines by value so each unit's
    landed cost (used for inventory valuation and COGS) includes its share."""
    subtotal = money(sum(money(q * p) for q, p in lines))
    total = money(subtotal + additional_cost - discount)
    extra = money(additional_cost - discount)
    allocs = []
    remaining = extra
    for i, (q, p) in enumerate(lines):
        amt = money(q * p)
        if i == len(lines) - 1:
            share = remaining
        elif subtotal > 0:
            share = money(extra * amt / subtotal)
        else:
            share = money(extra * q / sum(x[0] for x in lines))
        remaining = money(remaining - share)
        allocs.append((amt, share, money(amt + share)))
    return subtotal, total, allocs


def create_purchase(conn, user, data):
    require(user, "purchases.create")
    pdate = v_date(data.get("purchase_date"), "purchase_date")
    supplier_id = v_int(data.get("supplier_id"), "supplier_id", label="supplier")
    invoice_no = v_str(data.get("invoice_no"), "invoice_no", required=True, max_len=50,
                       label="Invoice / reference number")
    add_cost = money(v_num(data.get("additional_cost"), "additional_cost", 0, required=False))
    discount = money(v_num(data.get("discount"), "discount", 0, required=False))
    items = _items(data)
    with tx(conn):
        ref = _client_ref(conn, "purchases", data)
        supplier = _get(conn, "suppliers", supplier_id, "Supplier")
        if not supplier["active"]:
            raise bad("This supplier is inactive", "supplier_id")
        if conn.execute("SELECT 1 FROM purchases WHERE supplier_id = ? AND invoice_no = ? COLLATE NOCASE "
                        "AND status = 'final'", (supplier_id, invoice_no)).fetchone():
            raise ApiError(409, "Invoice %s from %s is already recorded" % (invoice_no, supplier["name"]),
                           "invoice_no")
        lines, variants = [], []
        for i, it in enumerate(items):
            f = "items.%d" % i
            v = _variant(conn, it.get("variant_id"), f + ".variant_id")
            q = qty_round(v_num(it.get("qty"), f + ".qty", gt=0, label="Quantity"))
            p = v_num(it.get("unit_price"), f + ".unit_price", 0, label="Purchase price")
            lines.append((q, p))
            variants.append(v)
        subtotal, total, allocs = purchase_total(lines, add_cost, discount)
        if total < 0:
            raise bad("Discount cannot exceed the purchase value", "discount")
        paid = money(v_num(data.get("amount_paid"), "amount_paid", 0, total, required=False,
                           label="Amount paid"))
        method = account = None
        if paid > 0:
            method = v_method(data.get("payment_method"))
            account = account_for(method)
        cur = conn.execute(
            "INSERT INTO purchases (purchase_date, supplier_id, invoice_no, subtotal, additional_cost, "
            "additional_note, discount, total_cost, amount_paid, notes, client_ref, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pdate, supplier_id, invoice_no, subtotal, add_cost,
             v_str(data.get("additional_note"), "additional_note", max_len=200),
             discount, total, paid, v_str(data.get("notes"), "notes", max_len=500), ref, user["id"]))
        pid = cur.lastrowid
        for (q, p), v, (amt, share, landed) in zip(lines, variants, allocs):
            ic = conn.execute(
                "INSERT INTO purchase_items (purchase_id, variant_id, qty, unit_price, line_amount, "
                "allocated_cost, landed_value, landed_unit_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, v["id"], q, p, amt, share, landed, landed / q))
            conn.execute(
                "INSERT INTO inventory_movements (move_date, variant_id, kind, qty, unit_cost, value, ref_table, "
                "ref_id, ref_item_id) VALUES (?, ?, 'purchase', ?, ?, ?, 'purchases', ?, ?)",
                (pdate, v["id"], q, landed / q, landed, pid, ic.lastrowid))
        if paid > 0:
            conn.execute(
                "INSERT INTO supplier_payments (payment_date, supplier_id, purchase_id, with_document, amount, method, "
                "account, notes, created_by) VALUES (?, ?, ?, 1, ?, ?, ?, 'Paid with purchase', ?)",
                (pdate, supplier_id, pid, paid, method, account, user["id"]))
        recost_variants(conn, [v["id"] for v in variants])
        audit(conn, user, "purchase.create", "purchases", pid,
              {"invoice_no": invoice_no, "supplier_id": supplier_id, "total": total, "paid": paid})
    return pid


def get_purchase(conn, user, purchase_id):
    p = one(conn.execute(
        "SELECT pu.*, s.name AS supplier_name, s.code AS supplier_code, u.full_name AS created_by_name "
        "FROM purchases pu JOIN suppliers s ON s.id = pu.supplier_id LEFT JOIN users u ON u.id = pu.created_by "
        "WHERE pu.id = ?", (purchase_id,)))
    if not p:
        raise ApiError(404, "Purchase not found")
    if not can(user, "purchases.view") and p["created_by"] != user["id"]:
        raise ApiError(403, "You do not have permission to view this purchase")
    p["items"] = rows(conn.execute(
        """SELECT pi.*, v.sku, v.size, v.colour, v.design, p.name AS product_name, p.unit, c.name AS category
           FROM purchase_items pi JOIN variants v ON v.id = pi.variant_id JOIN products p ON p.id = v.product_id
           JOIN categories c ON c.id = p.category_id WHERE pi.purchase_id = ? ORDER BY pi.id""", (purchase_id,)))
    for it in p["items"]:
        it["label"] = variant_label(it)
    p["payments"] = rows(conn.execute(
        "SELECT * FROM supplier_payments WHERE purchase_id = ? ORDER BY id", (purchase_id,)))
    return p


def list_purchases(conn, user, f):
    sql = """SELECT pu.*, s.name AS supplier_name,
               (SELECT SUM(qty) FROM purchase_items WHERE purchase_id = pu.id) AS units,
               (SELECT COUNT(*) FROM purchase_items WHERE purchase_id = pu.id) AS lines
             FROM purchases pu JOIN suppliers s ON s.id = pu.supplier_id WHERE 1 = 1"""
    params = []
    if not can(user, "purchases.view"):
        sql += " AND pu.created_by = ?"
        params.append(user["id"])
    if f.get("from"):
        sql += " AND pu.purchase_date >= ?"
        params.append(f["from"])
    if f.get("to"):
        sql += " AND pu.purchase_date <= ?"
        params.append(f["to"])
    if f.get("supplier_id"):
        sql += " AND pu.supplier_id = ?"
        params.append(f["supplier_id"])
    if f.get("category_id") or f.get("product_id"):
        sub = ("SELECT pi.purchase_id FROM purchase_items pi JOIN variants v ON v.id = pi.variant_id "
               "JOIN products p ON p.id = v.product_id WHERE 1 = 1")
        if f.get("category_id"):
            sub += " AND p.category_id = ?"
            params.append(f["category_id"])
        if f.get("product_id"):
            sub += " AND p.id = ?"
            params.append(f["product_id"])
        sql += " AND pu.id IN (%s)" % sub
    if f.get("q"):
        sql += " AND (pu.invoice_no LIKE ? OR s.name LIKE ? OR pu.notes LIKE ?)"
        params += ["%" + f["q"] + "%"] * 3
    if f.get("status"):
        sql += " AND pu.status = ?"
        params.append(f["status"])
    sql += " ORDER BY pu.purchase_date DESC, pu.id DESC LIMIT 1000"
    return rows(conn.execute(sql, params))


# --------------------------------------------------------------------------
# sales

def sale_line(qty, price, discount, rate, inclusive):
    """Return (gross_ex, discount_ex, net_ex, tax, line_total) for a sale line.
    Net Sales = Gross Sales − Discounts (all excluding tax)."""
    line_value = qty * price - discount
    r = rate / 100.0
    if inclusive:
        gross = money(qty * price / (1 + r))
        net = money(line_value / (1 + r))
        tax = money(line_value - net)
    else:
        gross = money(qty * price)
        net = money(line_value)
        tax = money(net * r)
    disc = money(gross - net)
    return gross, disc, net, tax, money(net + tax)


def next_invoice_no(conn):
    prefix = get_setting(conn, "invoice_prefix") or "INV"
    fy = today()[:4] if today()[5:7] >= "04" else str(int(today()[:4]) - 1)
    stem = "%s/%s-%s/" % (prefix, fy, str(int(fy) + 1)[2:])
    row = conn.execute("SELECT invoice_no FROM sales WHERE invoice_no LIKE ? ORDER BY id DESC LIMIT 50",
                       (stem + "%",)).fetchall()
    n = 0
    for r in row:
        tail = r["invoice_no"][len(stem):]
        if tail.isdigit():
            n = max(n, int(tail))
    return "%s%04d" % (stem, n + 1)


def create_sale(conn, user, data):
    require(user, "sales.create")
    sdate = v_date(data.get("sale_date"), "sale_date")
    # Business rule: the channel is always chosen explicitly; never inferred from the date.
    channel = data.get("channel")
    if channel not in ("retail", "wholesale"):
        raise bad("Select the sales channel: Retail or Wholesale", "channel")
    inclusive = 1 if data.get("tax_inclusive") in (True, 1, "1") else 0
    items = _items(data)
    with tx(conn):
        ref = _client_ref(conn, "sales", data)
        invoice_no = v_str(data.get("invoice_no"), "invoice_no", max_len=50) or next_invoice_no(conn)
        if conn.execute("SELECT 1 FROM sales WHERE invoice_no = ?", (invoice_no,)).fetchone():
            raise ApiError(409, "Invoice number %s already exists" % invoice_no, "invoice_no")

        customer_id = v_int(data.get("customer_id"), "customer_id", required=False)
        customer_name = v_str(data.get("customer_name"), "customer_name", max_len=100)
        if customer_id:
            cust = _get(conn, "customers", customer_id, "Customer")
            customer_name = cust["name"]
        elif data.get("new_customer"):
            nc = data["new_customer"]
            name = v_str(nc.get("name"), "new_customer.name", required=True, max_len=100, label="Customer name")
            phone = v_str(nc.get("phone"), "new_customer.phone", max_len=30)
            existing = conn.execute("SELECT id FROM customers WHERE name = ? COLLATE NOCASE AND phone = ?",
                                    (name, phone)).fetchone()
            if existing:
                customer_id = existing["id"]
            else:
                customer_id = conn.execute(
                    "INSERT INTO customers (name, phone, kind) VALUES (?, ?, ?)", (name, phone, channel)).lastrowid
                audit(conn, user, "customer.create", "customers", customer_id, {"name": name, "phone": phone})
            customer_name = name

        lines = []
        need = {}
        for i, it in enumerate(items):
            f = "items.%d" % i
            v = _variant(conn, it.get("variant_id"), f + ".variant_id")
            q = qty_round(v_num(it.get("qty"), f + ".qty", gt=0, label="Quantity"))
            price = v_num(it.get("unit_price"), f + ".unit_price", 0, label="Selling price")
            disc = money(v_num(it.get("discount"), f + ".discount", 0, money(q * price), required=False,
                               label="Discount"))
            rate = v_num(it.get("tax_rate"), f + ".tax_rate", 0, 28, required=False, label="Tax rate")
            need[v["id"]] = need.get(v["id"], 0) + q
            if need[v["id"]] > v["stock_qty"] + EPS:
                raise bad("Only %s %s of %s in stock" % (_n(v["stock_qty"]), v["unit"], variant_label(v)),
                          f + ".qty")
            lines.append((v, q, price, disc, rate) + sale_line(q, price, disc, rate, inclusive))

        gross = money(sum(l[5] for l in lines))
        disc_total = money(sum(l[6] for l in lines))
        net = money(sum(l[7] for l in lines))
        tax = money(sum(l[8] for l in lines))
        total = money(sum(l[9] for l in lines))
        received = money(v_num(data.get("amount_received"), "amount_received", 0, total, required=False,
                               label="Amount received", default=total))
        method = ""
        if received > 0:
            method = v_method(data.get("payment_method"))
        if received < total - EPS and not customer_id:
            raise bad("Select or add a customer to record a credit (unpaid) balance", "customer_id")

        staff_id = v_int(data.get("staff_user_id"), "staff_user_id", required=False) or user["id"]
        if staff_id != user["id"]:
            if not can(user, "owner"):
                raise bad("You can only record sales under your own name", "staff_user_id")
            if not conn.execute("SELECT 1 FROM users WHERE id = ? AND active = 1", (staff_id,)).fetchone():
                raise bad("Select a valid staff member", "staff_user_id")

        cur = conn.execute(
            "INSERT INTO sales (sale_date, invoice_no, channel, customer_id, customer_name, tax_inclusive, "
            "gross_amount, discount_amount, net_amount, tax_amount, total_amount, amount_received, payment_method, "
            "staff_user_id, notes, client_ref, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sdate, invoice_no, channel, customer_id, customer_name, inclusive, gross, disc_total, net, tax, total,
             received, method, staff_id, v_str(data.get("notes"), "notes", max_len=500), ref, user["id"]))
        sid = cur.lastrowid
        for (v, q, price, disc, rate, g, d, n, t, lt) in lines:
            ic = conn.execute(
                "INSERT INTO sale_items (sale_id, variant_id, qty, unit_price, discount, tax_rate, gross_amount, "
                "discount_amount, net_amount, tax_amount, line_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, v["id"], q, price, disc, rate, g, d, n, t, lt))
            conn.execute(
                "INSERT INTO inventory_movements (move_date, variant_id, kind, qty, ref_table, ref_id, ref_item_id, "
                "src_item_id) VALUES (?, ?, 'sale', ?, 'sales', ?, ?, ?)",
                (sdate, v["id"], -q, sid, ic.lastrowid, ic.lastrowid))
        if received > 0:
            conn.execute(
                "INSERT INTO customer_payments (payment_date, customer_id, sale_id, with_document, amount, method, "
                "account, notes, created_by) VALUES (?, ?, ?, 1, ?, ?, ?, 'Received with sale', ?)",
                (sdate, customer_id, sid, received, method, account_for(method), user["id"]))
        recost_variants(conn, [l[0]["id"] for l in lines])
        audit(conn, user, "sale.create", "sales", sid,
              {"invoice_no": invoice_no, "channel": channel, "total": total, "received": received})
    return sid


def _n(x):
    return ("%d" % x) if float(x).is_integer() else ("%.3f" % x).rstrip("0")


def get_sale(conn, user, sale_id):
    s = one(conn.execute(
        "SELECT s.*, u.full_name AS staff_name, cb.full_name AS created_by_name, c.phone AS customer_phone "
        "FROM sales s LEFT JOIN users u ON u.id = s.staff_user_id LEFT JOIN users cb ON cb.id = s.created_by "
        "LEFT JOIN customers c ON c.id = s.customer_id WHERE s.id = ?", (sale_id,)))
    if not s:
        raise ApiError(404, "Sale not found")
    if not can(user, "sales.view_all") and user["id"] not in (s["created_by"], s["staff_user_id"]):
        raise ApiError(403, "You do not have permission to view this sale")
    s["items"] = rows(conn.execute(
        """SELECT si.*, v.sku, v.size, v.colour, v.design, p.name AS product_name, p.unit, c.name AS category,
             COALESCE((SELECT SUM(ri.qty) FROM sale_return_items ri JOIN sale_returns r ON r.id = ri.return_id
                       WHERE ri.sale_item_id = si.id AND r.status = 'final'), 0) AS returned_qty
           FROM sale_items si JOIN variants v ON v.id = si.variant_id JOIN products p ON p.id = v.product_id
           JOIN categories c ON c.id = p.category_id WHERE si.sale_id = ? ORDER BY si.id""", (sale_id,)))
    show_cost = can(user, "reports.view")
    for it in s["items"]:
        it["label"] = variant_label(it)
        if show_cost:
            it["gross_profit"] = money(it["net_amount"] - it["cogs"])
        else:
            it.pop("cogs")
    s["returns"] = rows(conn.execute("SELECT * FROM sale_returns WHERE sale_id = ? ORDER BY id", (sale_id,)))
    for r in s["returns"]:
        r["items"] = rows(conn.execute(
            "SELECT ri.*, si.variant_id FROM sale_return_items ri JOIN sale_items si ON si.id = ri.sale_item_id "
            "WHERE ri.return_id = ?", (r["id"],)))
    s["payments"] = rows(conn.execute(
        "SELECT * FROM customer_payments WHERE sale_id = ? ORDER BY id", (sale_id,)))
    if show_cost:
        s["cogs"] = money(sum(i["cogs"] for i in s["items"]))
        s["gross_profit"] = money(s["net_amount"] - s["cogs"])
    s["shop_name"] = get_setting(conn, "shop_name")
    return s


def list_sales(conn, user, f):
    sql = """SELECT s.*, u.full_name AS staff_name,
               (SELECT SUM(qty) FROM sale_items WHERE sale_id = s.id) AS units,
               COALESCE((SELECT SUM(total_refund) FROM sale_returns WHERE sale_id = s.id AND status = 'final'), 0)
                 AS refunded
             FROM sales s LEFT JOIN users u ON u.id = s.staff_user_id WHERE 1 = 1"""
    params = []
    if not can(user, "sales.view_all"):
        sql += " AND (s.created_by = ? OR s.staff_user_id = ?)"
        params += [user["id"], user["id"]]
    for key, col in (("from", "s.sale_date >= ?"), ("to", "s.sale_date <= ?"), ("channel", "s.channel = ?"),
                     ("customer_id", "s.customer_id = ?"), ("staff_user_id", "s.staff_user_id = ?"),
                     ("status", "s.status = ?")):
        if f.get(key):
            sql += " AND " + col
            params.append(f[key])
    if f.get("category_id") or f.get("product_id") or f.get("variant_id") or f.get("supplier_id"):
        sub = ("SELECT si.sale_id FROM sale_items si JOIN variants v ON v.id = si.variant_id "
               "JOIN products p ON p.id = v.product_id WHERE 1 = 1")
        if f.get("category_id"):
            sub += " AND p.category_id = ?"
            params.append(f["category_id"])
        if f.get("product_id"):
            sub += " AND p.id = ?"
            params.append(f["product_id"])
        if f.get("variant_id"):
            sub += " AND v.id = ?"
            params.append(f["variant_id"])
        if f.get("supplier_id"):
            sub += " AND v.id IN (%s)" % SUPPLIER_VARIANTS_SQL
            params += [f["supplier_id"]] * 2
        sql += " AND s.id IN (%s)" % sub
    if f.get("q"):
        sql += " AND (s.invoice_no LIKE ? OR s.customer_name LIKE ?)"
        params += ["%" + f["q"] + "%"] * 2
    if f.get("unpaid"):
        sql += " AND s.status = 'final' AND s.amount_received < s.total_amount - 0.005"
    sql += " ORDER BY s.sale_date DESC, s.id DESC LIMIT 1000"
    return rows(conn.execute(sql, params))


SUPPLIER_VARIANTS_SQL = (
    "SELECT pi.variant_id FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id "
    "WHERE pu.supplier_id = ? AND pu.status = 'final' "
    "UNION SELECT variant_id FROM opening_stock WHERE supplier_id = ? AND status = 'final'"
)


# --------------------------------------------------------------------------
# returns

def create_return(conn, user, sale_id, data):
    require(user, "returns.create")
    rdate = v_date(data.get("return_date"), "return_date")
    items = _items(data)
    with tx(conn):
        ref = _client_ref(conn, "sale_returns", data)
        sale = _get(conn, "sales", sale_id, "Sale")
        if sale["status"] != "final":
            raise bad("Cannot return items from a voided sale")
        if rdate < sale["sale_date"]:
            raise bad("Return date cannot be before the sale date", "return_date")
        mode = v_choice(data.get("refund_mode"), "refund_mode", ("cash", "bank", "credit"), "refund mode")
        if mode == "credit" and not sale["customer_id"]:
            raise bad("Credit to account needs a customer on the sale; refund in cash or bank instead",
                      "refund_mode")
        lines, vids = [], []
        for i, it in enumerate(items):
            f = "items.%d" % i
            sid_ = v_int(it.get("sale_item_id"), f + ".sale_item_id", label="sale line")
            si = conn.execute("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?", (sid_, sale_id)).fetchone()
            if not si:
                raise bad("Invalid sale line", f + ".sale_item_id")
            q = qty_round(v_num(it.get("qty"), f + ".qty", 0, required=False))
            if q <= 0:
                continue
            already = conn.execute(
                "SELECT COALESCE(SUM(ri.qty), 0) FROM sale_return_items ri JOIN sale_returns r ON r.id = ri.return_id "
                "WHERE ri.sale_item_id = ? AND r.status = 'final'", (si["id"],)).fetchone()[0]
            left = si["qty"] - already
            if q > left + EPS:
                raise bad("Only %s left to return on this line" % _n(left), f + ".qty")
            if abs(q - left) <= EPS:  # final return of the line takes the exact remainder
                prev = conn.execute(
                    "SELECT COALESCE(SUM(ri.net_amount), 0), COALESCE(SUM(ri.tax_amount), 0) "
                    "FROM sale_return_items ri JOIN sale_returns r ON r.id = ri.return_id "
                    "WHERE ri.sale_item_id = ? AND r.status = 'final'", (si["id"],)).fetchone()
                net = money(si["net_amount"] - prev[0])
                tax = money(si["tax_amount"] - prev[1])
            else:
                net = money(si["net_amount"] * q / si["qty"])
                tax = money(si["tax_amount"] * q / si["qty"])
            restock = 0 if it.get("restock") in (False, 0, "0") else 1
            lines.append((si, q, restock, net, tax))
        if not lines:
            raise bad("Enter the quantity being returned", "items")
        net_total = money(sum(l[3] for l in lines))
        tax_total = money(sum(l[4] for l in lines))
        total = money(net_total + tax_total)
        cur = conn.execute(
            "INSERT INTO sale_returns (return_date, sale_id, refund_mode, net_amount, tax_amount, total_refund, notes, "
            "client_ref, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rdate, sale_id, mode, net_total, tax_total, total, v_str(data.get("notes"), "notes", max_len=500),
             ref, user["id"]))
        rid = cur.lastrowid
        for si, q, restock, net, tax in lines:
            ri = conn.execute(
                "INSERT INTO sale_return_items (return_id, sale_item_id, qty, restock, net_amount, tax_amount, total) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (rid, si["id"], q, restock, net, tax, money(net + tax)))
            if restock:
                conn.execute(
                    "INSERT INTO inventory_movements (move_date, variant_id, kind, qty, ref_table, ref_id, "
                    "ref_item_id, src_item_id) VALUES (?, ?, 'return_in', ?, 'sale_returns', ?, ?, ?)",
                    (rdate, si["variant_id"], q, rid, ri.lastrowid, si["id"]))
            vids.append(si["variant_id"])
        recost_variants(conn, vids)
        audit(conn, user, "return.create", "sale_returns", rid,
              {"sale_id": sale_id, "invoice_no": sale["invoice_no"], "refund": total, "mode": mode})
    return rid


# --------------------------------------------------------------------------
# payments

def create_supplier_payment(conn, user, data):
    require(user, "payments.record")
    pdate = v_date(data.get("payment_date"), "payment_date")
    supplier_id = v_int(data.get("supplier_id"), "supplier_id", label="supplier")
    amount = money(v_num(data.get("amount"), "amount", gt=0, label="Amount"))
    method = v_method(data.get("method"), "method")
    with tx(conn):
        ref = _client_ref(conn, "supplier_payments", data)
        _get(conn, "suppliers", supplier_id, "Supplier")
        purchase_id = v_int(data.get("purchase_id"), "purchase_id", required=False)
        if purchase_id:
            pu = _get(conn, "purchases", purchase_id, "Purchase")
            if pu["supplier_id"] != supplier_id or pu["status"] != "final":
                raise bad("Invalid purchase for this supplier", "purchase_id")
        cur = conn.execute(
            "INSERT INTO supplier_payments (payment_date, supplier_id, purchase_id, amount, method, account, "
            "reference, notes, client_ref, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pdate, supplier_id, purchase_id, amount, method, account_for(method),
             v_str(data.get("reference"), "reference", max_len=60), v_str(data.get("notes"), "notes", max_len=300),
             ref, user["id"]))
        audit(conn, user, "supplier_payment.create", "supplier_payments", cur.lastrowid,
              {"supplier_id": supplier_id, "amount": amount})
    return cur.lastrowid


def create_customer_payment(conn, user, data):
    require(user, "payments.record")
    pdate = v_date(data.get("payment_date"), "payment_date")
    customer_id = v_int(data.get("customer_id"), "customer_id", label="customer")
    amount = money(v_num(data.get("amount"), "amount", gt=0, label="Amount"))
    method = v_method(data.get("method"), "method")
    with tx(conn):
        ref = _client_ref(conn, "customer_payments", data)
        _get(conn, "customers", customer_id, "Customer")
        sale_id = v_int(data.get("sale_id"), "sale_id", required=False)
        if sale_id:
            s = _get(conn, "sales", sale_id, "Sale")
            if s["customer_id"] != customer_id or s["status"] != "final":
                raise bad("Invalid sale for this customer", "sale_id")
        cur = conn.execute(
            "INSERT INTO customer_payments (payment_date, customer_id, sale_id, amount, method, account, reference, "
            "notes, client_ref, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pdate, customer_id, sale_id, amount, method, account_for(method),
             v_str(data.get("reference"), "reference", max_len=60), v_str(data.get("notes"), "notes", max_len=300),
             ref, user["id"]))
        audit(conn, user, "customer_payment.create", "customer_payments", cur.lastrowid,
              {"customer_id": customer_id, "amount": amount})
    return cur.lastrowid


# --------------------------------------------------------------------------
# stock adjustments

def create_adjustment(conn, user, data):
    require(user, "inventory.adjust")
    adate = v_date(data.get("adj_date"), "adj_date")
    reason = v_choice(data.get("reason"), "reason", ("damaged", "lost", "correction", "other"), "reason")
    direction = v_choice(data.get("direction") or "out", "direction", ("in", "out"), "direction")
    q = qty_round(v_num(data.get("qty"), "qty", gt=0, label="Quantity"))
    if reason in ("damaged", "lost") and direction == "in":
        raise bad("Damaged or lost stock can only reduce inventory", "direction")
    with tx(conn):
        ref = _client_ref(conn, "stock_adjustments", data)
        v = _variant(conn, data.get("variant_id"), "variant_id")
        signed = q if direction == "in" else -q
        if signed < 0 and q > v["stock_qty"] + EPS:
            raise bad("Only %s in stock" % _n(v["stock_qty"]), "qty")
        cur = conn.execute(
            "INSERT INTO stock_adjustments (adj_date, variant_id, qty, reason, notes, client_ref, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (adate, v["id"], signed, reason, v_str(data.get("notes"), "notes", max_len=300), ref, user["id"]))
        conn.execute(
            "INSERT INTO inventory_movements (move_date, variant_id, kind, qty, ref_table, ref_id) "
            "VALUES (?, ?, 'adjust', ?, 'stock_adjustments', ?)", (adate, v["id"], signed, cur.lastrowid))
        recost_variants(conn, [v["id"]])
        audit(conn, user, "adjustment.create", "stock_adjustments", cur.lastrowid,
              {"variant_id": v["id"], "qty": signed, "reason": reason})
    return cur.lastrowid


def list_adjustments(conn, user, f):
    sql = """SELECT a.*, v.sku, v.size, v.colour, v.design, p.name AS product_name, p.unit, u.full_name AS created_by_name
             FROM stock_adjustments a JOIN variants v ON v.id = a.variant_id JOIN products p ON p.id = v.product_id
             LEFT JOIN users u ON u.id = a.created_by WHERE 1 = 1"""
    params = []
    if f.get("from"):
        sql += " AND a.adj_date >= ?"
        params.append(f["from"])
    if f.get("to"):
        sql += " AND a.adj_date <= ?"
        params.append(f["to"])
    sql += " ORDER BY a.adj_date DESC, a.id DESC LIMIT 1000"
    out = rows(conn.execute(sql, params))
    for r in out:
        r["label"] = variant_label(r)
        if not can(user, "inventory.cost"):
            r.pop("value")
    return out


# --------------------------------------------------------------------------
# expenses

def create_expense(conn, user, data):
    require(user, "expenses.create")
    edate = v_date(data.get("expense_date"), "expense_date")
    cat = v_int(data.get("category_id"), "category_id", label="expense category")
    amount = money(v_num(data.get("amount"), "amount", gt=0, label="Amount"))
    method = v_method(data.get("method"), "method")
    with tx(conn):
        ref = _client_ref(conn, "expenses", data)
        _get(conn, "expense_categories", cat, "Expense category")
        cur = conn.execute(
            "INSERT INTO expenses (expense_date, category_id, amount, method, account, description, recipient, "
            "client_ref, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (edate, cat, amount, method, account_for(method),
             v_str(data.get("description"), "description", max_len=300),
             v_str(data.get("recipient"), "recipient", max_len=100), ref, user["id"]))
        audit(conn, user, "expense.create", "expenses", cur.lastrowid, {"amount": amount, "category_id": cat})
    return cur.lastrowid


def list_expenses(conn, user, f):
    sql = """SELECT e.*, c.name AS category, u.full_name AS created_by_name FROM expenses e
             JOIN expense_categories c ON c.id = e.category_id LEFT JOIN users u ON u.id = e.created_by WHERE 1 = 1"""
    params = []
    if not can(user, "reports.view"):
        sql += " AND e.created_by = ?"
        params.append(user["id"])
    for key, col in (("from", "e.expense_date >= ?"), ("to", "e.expense_date <= ?"),
                     ("category_id", "e.category_id = ?"), ("status", "e.status = ?")):
        if f.get(key):
            sql += " AND " + col
            params.append(f[key])
    if f.get("q"):
        sql += " AND (e.description LIKE ? OR e.recipient LIKE ?)"
        params += ["%" + f["q"] + "%"] * 2
    sql += " ORDER BY e.expense_date DESC, e.id DESC LIMIT 2000"
    return rows(conn.execute(sql, params))


# --------------------------------------------------------------------------
# capital & cash

CASH_KINDS = {
    # kind: (label, effect on the chosen account)
    "opening_balance": ("Opening cash / bank balance", +1),
    "initial_investment": ("Initial investment by owner", +1),
    "additional_capital": ("Additional capital", +1),
    "partner_contribution": ("Partner contribution", +1),
    "owner_withdrawal": ("Owner withdrawal", -1),
    "loan_received": ("Business loan received", +1),
    "loan_repayment": ("Loan principal repayment", -1),
    "tax_payment": ("GST / tax paid to government", -1),
    "cash_to_bank": ("Cash deposited to bank", -1),
    "bank_to_cash": ("Cash withdrawn from bank", -1),
}
CAPITAL_IN = ("initial_investment", "additional_capital", "partner_contribution")


def create_cash_txn(conn, user, data):
    require(user, "owner")
    tdate = v_date(data.get("txn_date"), "txn_date")
    kind = v_choice(data.get("kind"), "kind", tuple(CASH_KINDS), "transaction type")
    amount = money(v_num(data.get("amount"), "amount", gt=0, label="Amount"))
    account = v_choice(data.get("account"), "account", ("cash", "bank"), "account")
    if kind == "cash_to_bank":
        account = "cash"
    elif kind == "bank_to_cash":
        account = "bank"
    purpose = v_choice(data.get("purpose") or "general", "purpose", ("general", "inventory", "expenses"), "purpose")
    with tx(conn):
        ref = _client_ref(conn, "cash_transactions", data)
        if kind == "opening_balance" and conn.execute(
                "SELECT 1 FROM cash_transactions WHERE kind = 'opening_balance' AND account = ? AND status = 'final'",
                (account,)).fetchone():
            raise ApiError(409, "An opening %s balance is already recorded. Void it first to change it." % account,
                           "kind")
        cur = conn.execute(
            "INSERT INTO cash_transactions (txn_date, kind, amount, account, party, purpose, notes, client_ref, "
            "created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tdate, kind, amount, account, v_str(data.get("party"), "party", max_len=100), purpose,
             v_str(data.get("notes"), "notes", max_len=300), ref, user["id"]))
        audit(conn, user, "cash_txn.create", "cash_transactions", cur.lastrowid,
              {"kind": kind, "amount": amount, "account": account})
    return cur.lastrowid


def list_cash_txns(conn, f):
    sql = "SELECT t.*, u.full_name AS created_by_name FROM cash_transactions t LEFT JOIN users u ON u.id = t.created_by WHERE 1 = 1"
    params = []
    for key, col in (("from", "t.txn_date >= ?"), ("to", "t.txn_date <= ?"), ("kind", "t.kind = ?")):
        if f.get(key):
            sql += " AND " + col
            params.append(f[key])
    sql += " ORDER BY t.txn_date DESC, t.id DESC"
    out = rows(conn.execute(sql, params))
    for r in out:
        r["kind_label"] = CASH_KINDS[r["kind"]][0]
    return out


# --------------------------------------------------------------------------
# voiding finalised transactions

VOIDABLE = {
    "purchases": "Purchase", "sales": "Sale", "sale_returns": "Return",
    "supplier_payments": "Supplier payment", "customer_payments": "Customer receipt",
    "expenses": "Expense", "cash_transactions": "Capital / cash entry",
    "stock_adjustments": "Stock adjustment", "opening_stock": "Opening stock entry",
}


def void(conn, user, table, record_id, data):
    if table not in VOIDABLE:
        raise ApiError(404, "Not found")
    if table in ("cash_transactions", "opening_stock"):
        require(user, "owner")
    else:
        require(user, "transactions.void")
    reason = v_str(data.get("reason"), "reason", required=True, max_len=300, label="Reason")
    with tx(conn):
        rec = _get(conn, table, record_id, VOIDABLE[table])
        if rec["status"] == "void":
            raise bad("Already voided")
        moves = conn.execute(
            "SELECT variant_id, SUM(qty) AS q FROM inventory_movements WHERE ref_table = ? AND ref_id = ? "
            "AND active = 1 GROUP BY variant_id", (table, record_id)).fetchall()
        if table == "sales":
            if conn.execute("SELECT 1 FROM sale_returns WHERE sale_id = ? AND status = 'final'",
                            (record_id,)).fetchone():
                raise bad("Void the returns on this sale first")
            if conn.execute("SELECT 1 FROM customer_payments WHERE sale_id = ? AND status = 'final' "
                            "AND with_document = 0", (record_id,)).fetchone():
                raise bad("Void the later receipts recorded against this sale first")
        # Removing inbound stock must not drive current stock below zero.
        for m in moves:
            if m["q"] > 0:
                stock = conn.execute("SELECT stock_qty FROM variants WHERE id = ?", (m["variant_id"],)).fetchone()[0]
                if stock - m["q"] < -EPS:
                    raise bad("Some of this stock has already been sold, so it cannot be voided. "
                              "Record a stock adjustment or return instead.")
        stamp = (reason, user["id"], now_iso(), record_id)
        conn.execute("UPDATE %s SET status = 'void', void_reason = ?, voided_by = ?, voided_at = ? WHERE id = ?"
                     % table, stamp)
        conn.execute("UPDATE inventory_movements SET active = 0 WHERE ref_table = ? AND ref_id = ?",
                     (table, record_id))
        # payments captured together with the purchase / sale go with it
        if table == "purchases":
            conn.execute("UPDATE supplier_payments SET status = 'void', void_reason = ?, voided_by = ?, voided_at = ? "
                         "WHERE purchase_id = ? AND status = 'final' AND with_document = 1", stamp)
        if table == "sales":
            conn.execute("UPDATE customer_payments SET status = 'void', void_reason = ?, voided_by = ?, voided_at = ? "
                         "WHERE sale_id = ? AND status = 'final' AND with_document = 1", stamp)
        if moves:
            recost_variants(conn, [m["variant_id"] for m in moves])
        audit(conn, user, "void", table, record_id, {"reason": reason})
