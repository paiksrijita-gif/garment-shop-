"""Report definitions. Each report returns columns, rows and totals and is
used for the on-screen table, CSV and Excel downloads."""
from . import metrics
from .db import rows
from .services import CASH_KINDS, CAPITAL_IN, SUPPLIER_VARIANTS_SQL, variant_label, list_suppliers
from .util import money


def _sum(data, keys):
    return {k: money(sum((r.get(k) or 0) for r in data)) for k in keys}


def _qsum(data, keys):
    return {k: round(sum((r.get(k) or 0) for r in data), 3) for k in keys}


def purchase_register(conn, f):
    sql = """SELECT pu.purchase_date, su.code AS supplier_code, su.name AS supplier, pu.invoice_no,
               p.name AS product_name, v.sku, v.size, v.colour, v.design, c.name AS category, p.unit,
               pi.qty, pi.unit_price, pi.line_amount, pi.allocated_cost, pi.landed_value, pi.landed_unit_cost,
               pu.total_cost AS bill_total, pu.amount_paid AS paid_with_bill, pu.id AS purchase_id
             FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id
             JOIN suppliers su ON su.id = pu.supplier_id JOIN variants v ON v.id = pi.variant_id
             JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id
             WHERE pu.status = 'final'"""
    params = []
    for key, col in (("from", "pu.purchase_date >= ?"), ("to", "pu.purchase_date <= ?"),
                     ("supplier_id", "pu.supplier_id = ?"), ("category_id", "p.category_id = ?"),
                     ("product_id", "p.id = ?")):
        if f.get(key):
            sql += " AND " + col
            params.append(f[key])
    data = rows(conn.execute(sql + " ORDER BY su.name, pu.purchase_date, pu.id, pi.id", params))
    for r in data:
        r["item"] = variant_label(r)
        r["landed_unit_cost"] = money(r["landed_unit_cost"])
    cols = [("purchase_date", "Date", "date"), ("supplier_code", "Supplier ID", "text"),
            ("supplier", "Supplier", "text"), ("invoice_no", "Invoice / Ref", "text"), ("item", "Product", "text"),
            ("sku", "SKU", "text"), ("category", "Category", "text"), ("unit", "Unit", "text"),
            ("qty", "Qty", "qty"), ("unit_price", "Price / Unit", "money"), ("line_amount", "Amount", "money"),
            ("allocated_cost", "Addl. Cost − Discount", "money"), ("landed_value", "Landed Cost", "money"),
            ("landed_unit_cost", "Landed Cost / Unit", "money")]
    totals = dict(_sum(data, ["line_amount", "allocated_cost", "landed_value"]), **_qsum(data, ["qty"]))
    return cols, data, totals


def inventory_report(conn, f):
    sql = """SELECT v.sku, p.name AS product_name, v.size, v.colour, v.design, c.name AS category, p.unit,
               v.stock_qty, v.stock_value, v.retail_price, v.wholesale_price, p.low_stock_level
             FROM variants v JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id
             WHERE v.active = 1"""
    params = []
    if f.get("category_id"):
        sql += " AND p.category_id = ?"
        params.append(f["category_id"])
    if f.get("product_id"):
        sql += " AND p.id = ?"
        params.append(f["product_id"])
    if f.get("supplier_id"):
        sql += " AND v.id IN (%s)" % SUPPLIER_VARIANTS_SQL
        params += [f["supplier_id"]] * 2
    data = rows(conn.execute(sql + " ORDER BY c.name, p.name, v.size, v.colour", params))
    for r in data:
        r["item"] = variant_label(r)
        r["avg_cost"] = money(r["stock_value"] / r["stock_qty"]) if r["stock_qty"] > 0 else None
        r["retail_value"] = money(r["stock_qty"] * r["retail_price"])
        r["status"] = "Out of stock" if r["stock_qty"] <= 0 else (
            "Low stock" if r["stock_qty"] <= r["low_stock_level"] else "In stock")
    cols = [("sku", "SKU", "text"), ("item", "Product", "text"), ("category", "Category", "text"),
            ("unit", "Unit", "text"), ("stock_qty", "In Stock", "qty"), ("avg_cost", "Avg Cost / Unit", "money"),
            ("stock_value", "Value at Cost", "money"), ("retail_price", "Retail Price", "money"),
            ("wholesale_price", "Wholesale Price", "money"), ("retail_value", "Value at Retail", "money"),
            ("low_stock_level", "Reorder Level", "qty"), ("status", "Status", "text")]
    totals = dict(_sum(data, ["stock_value", "retail_value"]), **_qsum(data, ["stock_qty"]))
    return cols, data, totals


def daily_sales(conn, f):
    sql = """SELECT s.sale_date, s.invoice_no, s.channel, s.customer_name, s.gross_amount, s.discount_amount,
               s.net_amount, s.tax_amount, s.total_amount, s.amount_received, s.payment_method,
               u.full_name AS staff, (SELECT SUM(qty) FROM sale_items WHERE sale_id = s.id) AS units,
               COALESCE((SELECT SUM(total_refund) FROM sale_returns WHERE sale_id = s.id AND status = 'final'), 0)
                 AS refunded
             FROM sales s LEFT JOIN users u ON u.id = s.staff_user_id WHERE s.status = 'final'"""
    params = []
    for key, col in (("from", "s.sale_date >= ?"), ("to", "s.sale_date <= ?"), ("channel", "s.channel = ?")):
        if f.get(key):
            sql += " AND " + col
            params.append(f[key])
    if f.get("category_id") or f.get("product_id"):
        sub = "SELECT si.sale_id FROM sale_items si JOIN variants v ON v.id = si.variant_id JOIN products p ON p.id = v.product_id WHERE 1=1"
        if f.get("category_id"):
            sub += " AND p.category_id = ?"
            params.append(f["category_id"])
        if f.get("product_id"):
            sub += " AND p.id = ?"
            params.append(f["product_id"])
        sql += " AND s.id IN (%s)" % sub
    data = rows(conn.execute(sql + " ORDER BY s.sale_date, s.id", params))
    for r in data:
        r["channel"] = r["channel"].title()
        r["balance"] = money(r["total_amount"] - r["amount_received"])
    cols = [("sale_date", "Date", "date"), ("invoice_no", "Invoice", "text"), ("channel", "Channel", "text"),
            ("customer_name", "Customer", "text"), ("units", "Units", "qty"), ("gross_amount", "Gross", "money"),
            ("discount_amount", "Discount", "money"), ("net_amount", "Net (ex-GST)", "money"),
            ("tax_amount", "GST", "money"), ("total_amount", "Invoice Total", "money"),
            ("amount_received", "Received", "money"), ("balance", "Balance Due", "money"),
            ("refunded", "Returns", "money"), ("payment_method", "Payment", "text"), ("staff", "Staff", "text")]
    totals = dict(_sum(data, ["gross_amount", "discount_amount", "net_amount", "tax_amount", "total_amount",
                              "amount_received", "balance", "refunded"]), **_qsum(data, ["units"]))
    return cols, data, totals


def channel_report(conn, f):
    data = []
    for ch in ("retail", "wholesale"):
        ff = dict(f, channel=ch)
        for m, d in sorted(metrics.pl_by(conn, ff, "month").items()):
            data.append(dict(d, month=m, channel=ch.title()))
    data.sort(key=lambda r: (r["month"], r["channel"]))
    cols = [("month", "Month", "month"), ("channel", "Channel", "text"), ("invoices", "Invoices", "int"),
            ("units_sold", "Units Sold", "qty"), ("units_returned", "Units Returned", "qty"),
            ("gross", "Gross Sales", "money"), ("discount", "Discounts", "money"), ("returns", "Returns", "money"),
            ("net_sales", "Net Sales", "money"), ("cogs", "COGS", "money"), ("gross_profit", "Gross Profit", "money"),
            ("margin", "Margin %", "pct")]
    totals = _sum(data, ["gross", "discount", "returns", "net_sales", "cogs", "gross_profit"])
    totals.update(_qsum(data, ["units_sold", "units_returned", "invoices"]))
    totals["margin"] = metrics._pct(totals["gross_profit"], totals["net_sales"])
    return cols, data, totals


def _dimension_report(conn, f, group, label):
    data = sorted([dict(d, id=k) for k, d in metrics.pl_by(conn, f, group).items()],
                  key=lambda r: -r["net_sales"])
    for r in data:
        r["name"] = r.get("label")
    cols = [("name", label, "text"), ("units_sold", "Units Sold", "qty"), ("units_returned", "Units Returned", "qty"),
            ("gross", "Gross Sales", "money"), ("discount", "Discounts", "money"), ("returns", "Returns", "money"),
            ("net_sales", "Net Sales", "money"), ("cogs", "COGS", "money"), ("gross_profit", "Gross Profit", "money"),
            ("margin", "Margin %", "pct"), ("writeoffs", "Write-offs", "money")]
    totals = _sum(data, ["gross", "discount", "returns", "net_sales", "cogs", "gross_profit", "writeoffs"])
    totals.update(_qsum(data, ["units_sold", "units_returned"]))
    totals["margin"] = metrics._pct(totals["gross_profit"], totals["net_sales"])
    return cols, data, totals


def category_profit(conn, f):
    return _dimension_report(conn, f, "category", "Category")


def product_profit(conn, f):
    cols, data, totals = _dimension_report(conn, f, "product", "Product")
    cats = {r["id"]: r["name"] for r in conn.execute(
        "SELECT p.id, c.name FROM products p JOIN categories c ON c.id = p.category_id")}
    for r in data:
        r["category"] = cats.get(r["id"], "")
    cols.insert(1, ("category", "Category", "text"))
    return cols, data, totals


def monthly_pl(conn, f):
    data = metrics.monthly_pl(conn, f)
    cols = [("month", "Month", "month"), ("gross", "Gross Sales", "money"), ("discount", "Discounts", "money"),
            ("returns", "Returns", "money"), ("net_sales", "Net Sales", "money"), ("cogs", "COGS", "money"),
            ("gross_profit", "Gross Profit", "money"), ("margin", "Gross Margin %", "pct"),
            ("expenses", "Operating Expenses", "money"), ("writeoffs", "Stock Write-offs", "money"),
            ("net_profit", "Net Operating Profit", "money"), ("net_margin", "Net Margin %", "pct")]
    totals = _sum(data, ["gross", "discount", "returns", "net_sales", "cogs", "gross_profit", "expenses",
                         "writeoffs", "net_profit"])
    totals["margin"] = metrics._pct(totals["gross_profit"], totals["net_sales"])
    totals["net_margin"] = metrics._pct(totals["net_profit"], totals["net_sales"])
    return cols, data, totals


def capital_report(conn, f):
    kinds = CAPITAL_IN + ("owner_withdrawal", "loan_received", "loan_repayment")
    sql = ("SELECT * FROM cash_transactions WHERE status = 'final' AND kind IN (%s)" %
           ",".join("'%s'" % k for k in kinds))
    params = []
    if f.get("from"):
        sql += " AND txn_date >= ?"
        params.append(f["from"])
    if f.get("to"):
        sql += " AND txn_date <= ?"
        params.append(f["to"])
    data = rows(conn.execute(sql + " ORDER BY txn_date, id", params))
    running = 0.0
    for r in data:
        r["type"] = CASH_KINDS[r["kind"]][0]
        r["capital_in"] = r["amount"] if r["kind"] in CAPITAL_IN else None
        r["withdrawn"] = r["amount"] if r["kind"] == "owner_withdrawal" else None
        r["loan_in"] = r["amount"] if r["kind"] == "loan_received" else None
        r["loan_out"] = r["amount"] if r["kind"] == "loan_repayment" else None
        running += (r["capital_in"] or 0) - (r["withdrawn"] or 0)
        r["net_capital"] = money(running)
        r["account"] = r["account"].title()
        r["purpose"] = r["purpose"].title()
    cols = [("txn_date", "Date", "date"), ("type", "Type", "text"), ("party", "Owner / Partner / Lender", "text"),
            ("account", "Account", "text"), ("purpose", "Allocated To", "text"),
            ("capital_in", "Capital In", "money"), ("withdrawn", "Withdrawn", "money"),
            ("loan_in", "Loan Received", "money"), ("loan_out", "Loan Repaid", "money"),
            ("net_capital", "Net Capital (running)", "money"), ("notes", "Notes", "text")]
    totals = _sum(data, ["capital_in", "withdrawn", "loan_in", "loan_out"])
    return cols, data, totals


def supplier_balances(conn, f):
    data = list_suppliers(conn)
    if f.get("supplier_id"):
        data = [s for s in data if s["id"] == int(f["supplier_id"])]
    cols = [("code", "Supplier ID", "text"), ("name", "Supplier", "text"), ("phone", "Contact", "text"),
            ("categories", "Categories", "text"), ("purchase_count", "Bills", "int"),
            ("total_units", "Units Supplied", "qty"), ("opening_balance", "Opening Balance", "money"),
            ("total_purchases", "Purchase Value", "money"), ("total_paid", "Paid", "money"),
            ("outstanding", "Outstanding Payable", "money"), ("last_purchase", "Last Purchase", "date")]
    totals = _sum(data, ["opening_balance", "total_purchases", "total_paid", "outstanding"])
    totals.update(_qsum(data, ["total_units"]))
    return cols, data, totals


def expense_statement(conn, f):
    sql = """SELECT e.expense_date, c.name AS category, e.description, e.recipient, e.method, e.amount
             FROM expenses e JOIN expense_categories c ON c.id = e.category_id WHERE e.status = 'final'"""
    params = []
    if f.get("from"):
        sql += " AND e.expense_date >= ?"
        params.append(f["from"])
    if f.get("to"):
        sql += " AND e.expense_date <= ?"
        params.append(f["to"])
    data = rows(conn.execute(sql + " ORDER BY e.expense_date, e.id", params))
    cols = [("expense_date", "Date", "date"), ("category", "Category", "text"), ("description", "Description", "text"),
            ("recipient", "Paid To", "text"), ("method", "Payment Method", "text"), ("amount", "Amount", "money")]
    return cols, data, _sum(data, ["amount"])


def stock_movement(conn, f):
    data = metrics.movement_summary(conn, f, by="variant")
    cols = [("sku", "SKU", "text"), ("label", "Product", "text"), ("category", "Category", "text"),
            ("unit", "Unit", "text"), ("opening", "Opening Qty", "qty"), ("purchased", "Purchased", "qty"),
            ("sold", "Sold", "qty"), ("returned", "Returned", "qty"), ("adjusted", "Adjusted / Damaged", "qty"),
            ("closing", "Closing Qty", "qty"), ("purchased_value", "Purchase Value", "money"),
            ("sold_cost", "Cost of Units Sold", "money"), ("closing_value", "Closing Value", "money")]
    totals = _qsum(data, ["opening", "purchased", "sold", "returned", "adjusted", "closing"])
    totals.update(_sum(data, ["purchased_value", "sold_cost", "closing_value"]))
    return cols, data, totals


def customer_balances(conn, f):
    from .services import list_customers
    data = [c for c in list_customers(conn) if abs(c["outstanding"]) > 0.004]
    cols = [("name", "Customer", "text"), ("phone", "Phone", "text"), ("kind", "Type", "text"),
            ("total_sales", "Total Billed", "money"), ("total_received", "Received", "money"),
            ("return_credits", "Return Credits", "money"), ("outstanding", "Outstanding", "money"),
            ("last_sale", "Last Sale", "date")]
    return cols, data, _sum(data, ["total_sales", "total_received", "return_credits", "outstanding"])


# key: (title, function, filters it supports)
REPORTS = {
    "purchase-register": ("Supplier-wise Purchase Register", purchase_register,
                          ["date", "supplier", "category", "product"]),
    "inventory": ("Product-wise Inventory Report", inventory_report, ["supplier", "category", "product"]),
    "daily-sales": ("Daily Sales Register", daily_sales, ["date", "channel", "category", "product"]),
    "channel-sales": ("Retail vs Wholesale Sales", channel_report, ["date", "supplier", "category", "product"]),
    "category-profit": ("Category-wise Revenue & Profit", category_profit, ["date", "channel", "supplier"]),
    "product-profit": ("Product-wise Profit", product_profit, ["date", "channel", "supplier", "category"]),
    "monthly-pl": ("Monthly Profit & Loss", monthly_pl, ["date"]),
    "capital": ("Capital Investment & Withdrawals", capital_report, ["date"]),
    "supplier-balances": ("Supplier Outstanding Balances", supplier_balances, ["supplier"]),
    "customer-balances": ("Customer Outstanding Balances", customer_balances, []),
    "expenses": ("Expense Statement", expense_statement, ["date"]),
    "stock-movement": ("Stock Movement Report", stock_movement, ["date", "supplier", "category", "product"]),
}


def run(conn, key, f):
    title, fn, _ = REPORTS[key]
    cols, data, totals = fn(conn, f)
    return {"key": key, "title": title, "columns": cols, "rows": data, "totals": totals}
