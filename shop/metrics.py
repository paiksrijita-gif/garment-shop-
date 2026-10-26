"""Business metrics: revenue, COGS, profit, inventory, capital and cash.

Accounting rules applied throughout:
* Revenue (Net Sales) = Gross Sales − Discounts − Sales Returns, excluding GST.
* COGS = inventory cost of the units actually sold (from the stock ledger),
  less the cost of units returned. Unsold purchases stay in inventory value.
* Gross Profit = Net Sales − COGS.
* Net Operating Profit = Gross Profit − Operating Expenses − Stock write-offs
  (damaged / lost stock and returned goods that could not be restocked).
* Capital, loans, withdrawals, supplier payments and GST are balance-sheet
  movements and never touch profit.
"""
from datetime import date, timedelta

from .db import rows, get_setting
from .services import CASH_KINDS, CAPITAL_IN, SUPPLIER_VARIANTS_SQL, variant_label
from .util import money, today, EPS

SALES_FROM = """FROM sale_items si JOIN sales s ON s.id = si.sale_id
  JOIN variants v ON v.id = si.variant_id JOIN products p ON p.id = v.product_id
  JOIN categories c ON c.id = p.category_id WHERE s.status = 'final'"""

RETURNS_FROM = """FROM sale_return_items ri JOIN sale_returns r ON r.id = ri.return_id
  JOIN sale_items si ON si.id = ri.sale_item_id JOIN sales s ON s.id = si.sale_id
  JOIN variants v ON v.id = si.variant_id JOIN products p ON p.id = v.product_id
  JOIN categories c ON c.id = p.category_id WHERE r.status = 'final' AND s.status = 'final'"""

ADJ_FROM = """FROM stock_adjustments a JOIN variants v ON v.id = a.variant_id
  JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id
  WHERE a.status = 'final'"""

GROUPS = {
    "all": ("'all'", "'All'"),
    "month": ("substr({d}, 1, 7)", "substr({d}, 1, 7)"),
    "day": ("{d}", "{d}"),
    "channel": ("s.channel", "s.channel"),
    "category": ("c.id", "c.name"),
    "product": ("p.id", "p.name"),
    "variant": ("v.id", "p.name"),
}


def _where(f, date_col, with_channel=True):
    sql, params = "", []
    if f.get("from"):
        sql += " AND %s >= ?" % date_col
        params.append(f["from"])
    if f.get("to"):
        sql += " AND %s <= ?" % date_col
        params.append(f["to"])
    if with_channel and f.get("channel"):
        sql += " AND s.channel = ?"
        params.append(f["channel"])
    if f.get("category_id"):
        sql += " AND p.category_id = ?"
        params.append(f["category_id"])
    if f.get("product_id"):
        sql += " AND p.id = ?"
        params.append(f["product_id"])
    if f.get("variant_id"):
        sql += " AND v.id = ?"
        params.append(f["variant_id"])
    if f.get("supplier_id"):
        sql += " AND v.id IN (%s)" % SUPPLIER_VARIANTS_SQL
        params += [f["supplier_id"]] * 2
    return sql, params


def _empty():
    return dict(gross=0.0, discount=0.0, returns=0.0, net_sales=0.0, tax=0.0, cogs=0.0,
                gross_profit=0.0, units_sold=0.0, units_returned=0.0, invoices=0,
                writeoffs=0.0, total_billed=0.0)


def pl_by(conn, f, group="all"):
    """Revenue / COGS / gross profit per group key."""
    key_t, label_t = GROUPS[group]
    out = {}

    key, label = key_t.format(d="s.sale_date"), label_t.format(d="s.sale_date")
    w, p = _where(f, "s.sale_date")
    for r in conn.execute(
            "SELECT %s AS k, %s AS label, SUM(si.gross_amount) AS gross, SUM(si.discount_amount) AS discount, "
            "SUM(si.net_amount) AS net, SUM(si.tax_amount) AS tax, SUM(si.cogs) AS cogs, SUM(si.qty) AS units, "
            "SUM(si.line_total) AS billed, COUNT(DISTINCT s.id) AS invoices %s %s GROUP BY k"
            % (key, label, SALES_FROM, w), p):
        d = out.setdefault(r["k"], _empty())
        d.update(label=r["label"], gross=r["gross"], discount=r["discount"], net_sales=r["net"], tax=r["tax"],
                 cogs=r["cogs"], units_sold=r["units"], invoices=r["invoices"], total_billed=r["billed"])

    key, label = key_t.format(d="r.return_date"), label_t.format(d="r.return_date")
    w, p = _where(f, "r.return_date")
    for r in conn.execute(
            "SELECT %s AS k, %s AS label, SUM(ri.net_amount) AS net, SUM(ri.tax_amount) AS tax, "
            "SUM(ri.total) AS total, SUM(ri.cogs_reversed) AS cogs, SUM(ri.qty) AS units, "
            "SUM(CASE WHEN ri.restock = 0 THEN ri.cogs_reversed ELSE 0 END) AS damaged %s %s GROUP BY k"
            % (key, label, RETURNS_FROM, w), p):
        d = out.setdefault(r["k"], _empty())
        d.setdefault("label", r["label"])
        d["returns"] = r["net"]
        d["net_sales"] -= r["net"]
        d["tax"] -= r["tax"]
        d["total_billed"] -= r["total"]
        d["cogs"] -= r["cogs"]
        d["units_returned"] = r["units"]
        d["writeoffs"] += r["damaged"]

    if group != "channel" and not f.get("channel"):
        key, label = key_t.format(d="a.adj_date"), label_t.format(d="a.adj_date")
        w, p = _where(f, "a.adj_date", with_channel=False)
        for r in conn.execute("SELECT %s AS k, %s AS label, SUM(a.value) AS value %s %s GROUP BY k"
                              % (key, label, ADJ_FROM, w), p):
            d = out.setdefault(r["k"], _empty())
            d.setdefault("label", r["label"])
            d["writeoffs"] -= r["value"]

    for d in out.values():
        for k in ("gross", "discount", "returns", "net_sales", "tax", "cogs", "writeoffs", "total_billed"):
            d[k] = money(d[k] or 0)
        d["gross_profit"] = money(d["net_sales"] - d["cogs"])
        d["margin"] = _pct(d["gross_profit"], d["net_sales"])
    return out


def expenses_by(conn, f, group="all"):
    key = {"all": "'all'", "month": "substr(e.expense_date, 1, 7)", "day": "e.expense_date",
           "category": "c.name"}[group]
    sql = ("SELECT %s AS k, SUM(e.amount) AS amount FROM expenses e JOIN expense_categories c ON c.id = e.category_id "
           "WHERE e.status = 'final'" % key)
    params = []
    if f.get("from"):
        sql += " AND e.expense_date >= ?"
        params.append(f["from"])
    if f.get("to"):
        sql += " AND e.expense_date <= ?"
        params.append(f["to"])
    sql += " GROUP BY k"
    return {r["k"]: money(r["amount"]) for r in conn.execute(sql, params)}


def _pct(a, b):
    return round(a * 100.0 / b, 2) if abs(b) > EPS else None


def profit_summary(conn, f):
    t = pl_by(conn, f, "all").get("all", _empty())
    if "margin" not in t:
        t["margin"] = None
    t["expenses"] = expenses_by(conn, f).get("all", 0.0)
    t["net_profit"] = money(t["gross_profit"] - t["expenses"] - t["writeoffs"])
    t["net_margin"] = _pct(t["net_profit"], t["net_sales"])
    return t


def monthly_pl(conn, f):
    pl = pl_by(conn, f, "month")
    ex = expenses_by(conn, f, "month")
    months = sorted(set(pl) | set(ex))
    out = []
    for m in months:
        d = pl.get(m, _empty())
        d = dict(d, month=m, expenses=ex.get(m, 0.0))
        d["gross_profit"] = money(d["net_sales"] - d["cogs"])
        d["net_profit"] = money(d["gross_profit"] - d["expenses"] - d["writeoffs"])
        d["margin"] = _pct(d["gross_profit"], d["net_sales"])
        d["net_margin"] = _pct(d["net_profit"], d["net_sales"])
        out.append(d)
    return out


# --------------------------------------------------------------------------
# balances

def supplier_outstanding(conn):
    r = conn.execute(
        "SELECT COALESCE((SELECT SUM(opening_balance) FROM suppliers), 0) + "
        "COALESCE((SELECT SUM(total_cost) FROM purchases WHERE status = 'final'), 0) - "
        "COALESCE((SELECT SUM(amount) FROM supplier_payments WHERE status = 'final'), 0)").fetchone()[0]
    return money(r)


def customer_outstanding(conn):
    r = conn.execute(
        "SELECT COALESCE((SELECT SUM(opening_balance) FROM customers), 0) + "
        "COALESCE((SELECT SUM(total_amount) FROM sales WHERE status = 'final'), 0) - "
        "COALESCE((SELECT SUM(amount) FROM customer_payments WHERE status = 'final'), 0) - "
        "COALESCE((SELECT SUM(total_refund) FROM sale_returns WHERE status = 'final' AND refund_mode = 'credit'), 0)"
    ).fetchone()[0]
    return money(r)


def inventory_totals(conn, f=None):
    f = f or {}
    sql = ("SELECT COALESCE(SUM(v.stock_qty), 0) AS qty, COALESCE(SUM(v.stock_value), 0) AS value "
           "FROM variants v JOIN products p ON p.id = v.product_id WHERE 1 = 1")
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
    r = conn.execute(sql, params).fetchone()
    return {"qty": round(r["qty"], 3), "value": money(r["value"])}


def account_balances(conn, as_of=None):
    """Cash and bank balances derived from every recorded money movement."""
    bal = {"cash": 0.0, "bank": 0.0}
    date_cond = " AND {col} <= ?" if as_of else ""
    params = [as_of] if as_of else []

    for r in conn.execute("SELECT kind, account, SUM(amount) AS amt FROM cash_transactions WHERE status = 'final'"
                          + date_cond.format(col="txn_date") + " GROUP BY kind, account", params):
        sign = CASH_KINDS[r["kind"]][1]
        bal[r["account"]] += sign * r["amt"]
        if r["kind"] == "cash_to_bank":
            bal["bank"] += r["amt"]
        elif r["kind"] == "bank_to_cash":
            bal["cash"] += r["amt"]
    for table, col, sign in (("customer_payments", "payment_date", 1), ("supplier_payments", "payment_date", -1),
                             ("expenses", "expense_date", -1)):
        for r in conn.execute("SELECT account, SUM(amount) AS amt FROM %s WHERE status = 'final'" % table
                              + date_cond.format(col=col) + " GROUP BY account", params):
            bal[r["account"]] += sign * r["amt"]
    for r in conn.execute("SELECT refund_mode, SUM(total_refund) AS amt FROM sale_returns WHERE status = 'final' "
                          "AND refund_mode IN ('cash', 'bank')" + date_cond.format(col="return_date")
                          + " GROUP BY refund_mode", params):
        bal[r["refund_mode"]] -= r["amt"]
    return {k: money(v) for k, v in bal.items()}


def capital_summary(conn):
    sums = {r["kind"]: r["amt"] for r in conn.execute(
        "SELECT kind, SUM(amount) AS amt FROM cash_transactions WHERE status = 'final' GROUP BY kind")}
    g = lambda k: money(sums.get(k, 0.0))
    contributed = money(sum(g(k) for k in CAPITAL_IN))
    withdrawals = g("owner_withdrawal")
    loans_out = money(g("loan_received") - g("loan_repayment"))
    balances = account_balances(conn)
    inv = inventory_totals(conn)
    receivables = customer_outstanding(conn)
    payables = supplier_outstanding(conn)
    gst_collected = money(conn.execute(
        "SELECT COALESCE((SELECT SUM(tax_amount) FROM sales WHERE status = 'final'), 0) - "
        "COALESCE((SELECT SUM(tax_amount) FROM sale_returns WHERE status = 'final'), 0)").fetchone()[0])
    gst_payable = money(gst_collected - g("tax_payment"))

    assets = money(balances["cash"] + balances["bank"] + inv["value"] + receivables)
    liabilities = money(payables + loans_out + gst_payable)
    net_worth = money(assets - liabilities)

    opening_stock = money(conn.execute(
        "SELECT COALESCE(SUM(value), 0) FROM opening_stock WHERE status = 'final'").fetchone()[0])
    opening_cust = money(conn.execute("SELECT COALESCE(SUM(opening_balance), 0) FROM customers").fetchone()[0])
    opening_supp = money(conn.execute("SELECT COALESCE(SUM(opening_balance), 0) FROM suppliers").fetchone()[0])
    opening_equity = money(g("opening_balance") + opening_stock + opening_cust - opening_supp)
    profit = profit_summary(conn, {})
    expected = money(opening_equity + contributed - withdrawals + profit["net_profit"])

    purpose = {r["purpose"]: money(r["amt"]) for r in conn.execute(
        "SELECT purpose, SUM(amount) AS amt FROM cash_transactions WHERE status = 'final' AND kind IN (%s) "
        "GROUP BY purpose" % ",".join("'%s'" % k for k in CAPITAL_IN + ("loan_received",)))}
    supplier_paid = money(conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE status = 'final'").fetchone()[0])
    expenses_paid = money(conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE status = 'final'").fetchone()[0])

    opening_capital = money(float(get_setting(conn, "opening_capital") or 0))
    return {
        "opening_capital": opening_capital,
        "total_capital_invested": money(opening_capital + contributed),
        "contributions": {k: g(k) for k in CAPITAL_IN},
        "total_contributed": contributed,
        "total_withdrawals": withdrawals,
        "net_capital": money(contributed - withdrawals),
        "loans_received": g("loan_received"),
        "loans_repaid": g("loan_repayment"),
        "loans_outstanding": loans_out,
        "cash": balances["cash"],
        "bank": balances["bank"],
        "cash_and_bank": money(balances["cash"] + balances["bank"]),
        "inventory_value": inv["value"],
        "inventory_units": inv["qty"],
        "customer_outstanding": receivables,
        "supplier_outstanding": payables,
        "gst_collected": gst_collected,
        "gst_paid": g("tax_payment"),
        "gst_payable": gst_payable,
        "total_assets": assets,
        "total_liabilities": liabilities,
        "capital_deployed": net_worth,
        "opening_equity": opening_equity,
        "net_profit_to_date": profit["net_profit"],
        "expected_equity": expected,
        "unreconciled": money(net_worth - expected),
        "allocation": {
            "capital_for_inventory": purpose.get("inventory", 0.0),
            "capital_for_expenses": purpose.get("expenses", 0.0),
            "capital_general": purpose.get("general", 0.0),
            "paid_to_suppliers": supplier_paid,
            "paid_for_expenses": expenses_paid,
        },
    }


def cashflow_by_month(conn, f):
    params, cond = [], ""
    if f.get("from"):
        cond += " AND {d} >= ?"
        params.append(f["from"])
    if f.get("to"):
        cond += " AND {d} <= ?"
        params.append(f["to"])
    out = {}

    def add(sql, col, field, sign=1):
        for r in conn.execute(sql + cond.format(d=col) + " GROUP BY m", params):
            d = out.setdefault(r["m"], dict(month=r["m"], capital_in=0.0, withdrawals=0.0, loans_net=0.0,
                                            receipts=0.0, supplier_payments=0.0, expenses=0.0, refunds=0.0,
                                            tax_paid=0.0))
            d[field] += sign * r["amt"]

    cap = ",".join("'%s'" % k for k in CAPITAL_IN)
    add("SELECT substr(txn_date,1,7) m, SUM(amount) amt FROM cash_transactions WHERE status='final' AND kind IN (%s)"
        % cap, "txn_date", "capital_in")
    add("SELECT substr(txn_date,1,7) m, SUM(amount) amt FROM cash_transactions WHERE status='final' "
        "AND kind='owner_withdrawal'", "txn_date", "withdrawals")
    add("SELECT substr(txn_date,1,7) m, SUM(amount) amt FROM cash_transactions WHERE status='final' "
        "AND kind='loan_received'", "txn_date", "loans_net")
    add("SELECT substr(txn_date,1,7) m, SUM(amount) amt FROM cash_transactions WHERE status='final' "
        "AND kind='loan_repayment'", "txn_date", "loans_net", -1)
    add("SELECT substr(txn_date,1,7) m, SUM(amount) amt FROM cash_transactions WHERE status='final' "
        "AND kind='tax_payment'", "txn_date", "tax_paid")
    add("SELECT substr(payment_date,1,7) m, SUM(amount) amt FROM customer_payments WHERE status='final'",
        "payment_date", "receipts")
    add("SELECT substr(payment_date,1,7) m, SUM(amount) amt FROM supplier_payments WHERE status='final'",
        "payment_date", "supplier_payments")
    add("SELECT substr(expense_date,1,7) m, SUM(amount) amt FROM expenses WHERE status='final'",
        "expense_date", "expenses")
    add("SELECT substr(return_date,1,7) m, SUM(total_refund) amt FROM sale_returns WHERE status='final' "
        "AND refund_mode IN ('cash','bank')", "return_date", "refunds")
    res = []
    for m in sorted(out):
        d = {k: (money(v) if isinstance(v, float) else v) for k, v in out[m].items()}
        d["net_cash_flow"] = money(d["capital_in"] - d["withdrawals"] + d["loans_net"] + d["receipts"]
                                   - d["supplier_payments"] - d["expenses"] - d["refunds"] - d["tax_paid"])
        res.append(d)
    return res


# --------------------------------------------------------------------------
# dashboard

def _days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def dashboard(conn, f):
    t = today()
    month_start = t[:8] + "01"
    flt = {k: f.get(k) for k in ("supplier_id", "category_id", "product_id", "channel") if f.get(k)}
    period = profit_summary(conn, f)
    today_pl = pl_by(conn, dict(flt, **{"from": t, "to": t})).get("all", _empty())
    month_pl = pl_by(conn, dict(flt, **{"from": month_start, "to": t})).get("all", _empty())
    channels = pl_by(conn, f, "channel")
    for ch in ("retail", "wholesale"):
        channels.setdefault(ch, _empty())
        channels[ch].setdefault("margin", None)
        channels[ch]["label"] = ch

    # purchases (landed value of items so product filters apply)
    pw = ""
    pp = []
    for key, col in (("from", "pu.purchase_date >= ?"), ("to", "pu.purchase_date <= ?"),
                     ("supplier_id", "pu.supplier_id = ?"), ("category_id", "p.category_id = ?"),
                     ("product_id", "p.id = ?")):
        if f.get(key):
            pw += " AND " + col
            pp.append(f[key])
    purchase_base = ("FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id "
                     "JOIN suppliers su ON su.id = pu.supplier_id JOIN variants v ON v.id = pi.variant_id "
                     "JOIN products p ON p.id = v.product_id WHERE pu.status = 'final'" + pw)
    purchase_total = money(conn.execute("SELECT COALESCE(SUM(pi.landed_value), 0) " + purchase_base, pp)
                           .fetchone()[0])
    by_supplier = rows(conn.execute(
        "SELECT su.id, su.name, SUM(pi.landed_value) AS value, SUM(pi.qty) AS units, COUNT(DISTINCT pu.id) AS bills "
        + purchase_base + " GROUP BY su.id ORDER BY value DESC LIMIT 12", pp))

    inv = inventory_totals(conn, f)
    cap = capital_summary(conn)

    # trend granularity
    start = f.get("from") or conn.execute(
        "SELECT MIN(d) FROM (SELECT MIN(sale_date) d FROM sales UNION SELECT MIN(expense_date) FROM expenses)"
    ).fetchone()[0] or t
    end = f.get("to") or t
    gran = "day" if _days_between(start, end) <= 62 else "month"
    pl = pl_by(conn, f, gran)
    ex = expenses_by(conn, f, gran)
    ch_trend = {}
    for ch in ("retail", "wholesale"):
        for k, d in pl_by(conn, dict(f, channel=ch), gran).items():
            ch_trend.setdefault(k, {})[ch] = d["net_sales"]
    keys = _period_keys(start, end, gran)
    trend = []
    for k in keys:
        d = pl.get(k, _empty())
        e = ex.get(k, 0.0)
        trend.append({
            "period": k, "net_sales": d["net_sales"], "gross_profit": money(d["net_sales"] - d["cogs"]),
            "expenses": e, "net_profit": money(d["net_sales"] - d["cogs"] - e - d["writeoffs"]),
            "retail": ch_trend.get(k, {}).get("retail", 0.0),
            "wholesale": ch_trend.get(k, {}).get("wholesale", 0.0),
        })

    by_cat = sorted(
        [dict(v, id=k) for k, v in pl_by(conn, f, "category").items()], key=lambda d: -d["net_sales"])
    top_products = sorted(
        [dict(v, id=k) for k, v in pl_by(conn, f, "product").items()],
        key=lambda d: (-d["units_sold"] + d["units_returned"], -d["net_sales"]))[:10]

    inv_sql = ("SELECT c.id, c.name, SUM(v.stock_qty) AS qty, SUM(v.stock_value) AS value FROM variants v "
               "JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id WHERE 1 = 1")
    ip = []
    if f.get("category_id"):
        inv_sql += " AND c.id = ?"
        ip.append(f["category_id"])
    if f.get("product_id"):
        inv_sql += " AND p.id = ?"
        ip.append(f["product_id"])
    if f.get("supplier_id"):
        inv_sql += " AND v.id IN (%s)" % SUPPLIER_VARIANTS_SQL
        ip += [f["supplier_id"]] * 2
    inv_by_cat = [r for r in rows(conn.execute(inv_sql + " GROUP BY c.id ORDER BY value DESC", ip))
                  if (r["qty"] or 0) > EPS]

    return {
        "filters": f,
        "granularity": gran,
        "kpis": {
            "total_capital_invested": cap["total_capital_invested"],
            "total_purchase_value": purchase_total,
            "current_inventory_value": inv["value"],
            "total_units_in_stock": inv["qty"],
            "todays_sales": money(today_pl["total_billed"]),
            "todays_invoices": today_pl["invoices"],
            "todays_net_sales": today_pl["net_sales"],
            "monthly_revenue": month_pl["net_sales"],
            "net_sales": period["net_sales"],
            "retail_revenue": channels["retail"]["net_sales"],
            "wholesale_revenue": channels["wholesale"]["net_sales"],
            "gross_profit": period["gross_profit"],
            "gross_margin": period["margin"],
            "net_operating_profit": period["net_profit"],
            "profit_margin": period["net_margin"],
            "supplier_outstanding": cap["supplier_outstanding"],
            "customer_outstanding": cap["customer_outstanding"],
            "total_operating_expenses": period["expenses"],
            "writeoffs": period["writeoffs"],
            "cogs": period["cogs"],
            "cash_and_bank": cap["cash_and_bank"],
        },
        "period": period,
        "channels": channels,
        "trend": trend,
        "by_category": by_cat,
        "by_supplier": by_supplier,
        "inventory_by_category": inv_by_cat,
        "top_products": top_products,
        "cashflow": cashflow_by_month(conn, f),
        "expenses_filtered_note": bool(flt),
    }


def _period_keys(start, end, gran):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if e < s:
        s, e = e, s
    keys = []
    if gran == "day":
        while s <= e:
            keys.append(s.isoformat())
            s += timedelta(days=1)
    else:
        y, m = s.year, s.month
        while (y, m) <= (e.year, e.month):
            keys.append("%04d-%02d" % (y, m))
            m += 1
            if m > 12:
                y, m = y + 1, 1
    return keys[-400:]


# --------------------------------------------------------------------------
# inventory

def inventory_overview(conn, user_can_cost, f):
    days = int(f.get("days") or 30)
    since = (date.fromisoformat(today()) - timedelta(days=days)).isoformat()
    where, params = "", []
    if f.get("category_id"):
        where += " AND p.category_id = ?"
        params.append(f["category_id"])
    if f.get("supplier_id"):
        where += " AND v.id IN (%s)" % SUPPLIER_VARIANTS_SQL
        params += [f["supplier_id"]] * 2
    if f.get("q"):
        where += " AND (p.name LIKE ? OR v.sku LIKE ? OR c.name LIKE ?)"
        params += ["%" + f["q"] + "%"] * 3
    variants = rows(conn.execute(
        """SELECT v.id, v.sku, v.size, v.colour, v.design, v.stock_qty, v.stock_value, v.retail_price,
                  v.wholesale_price, p.id AS product_id, p.name AS product_name, p.unit, p.low_stock_level,
                  c.id AS category_id, c.name AS category,
                  COALESCE((SELECT SUM(si.qty) FROM sale_items si JOIN sales s ON s.id = si.sale_id
                            WHERE si.variant_id = v.id AND s.status = 'final' AND s.sale_date >= ?), 0) AS sold_recent,
                  (SELECT MAX(s.sale_date) FROM sale_items si JOIN sales s ON s.id = si.sale_id
                   WHERE si.variant_id = v.id AND s.status = 'final') AS last_sale
           FROM variants v JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id
           WHERE v.active = 1 AND p.active = 1""" + where + " ORDER BY p.name, v.size, v.colour",
        [since] + params))
    t = today()
    for v in variants:
        v["label"] = variant_label(v)
        v["avg_cost"] = money(v["stock_value"] / v["stock_qty"]) if v["stock_qty"] > EPS else None
        if v["stock_qty"] <= EPS:
            v["status"] = "out"
        elif v["stock_qty"] <= v["low_stock_level"] + EPS:
            v["status"] = "low"
        else:
            v["status"] = "ok"
        v["days_since_sale"] = _days_between(v["last_sale"], t) if v["last_sale"] else None

    products = {}
    for v in variants:
        p = products.setdefault(v["product_id"], dict(
            product_id=v["product_id"], product_name=v["product_name"], category=v["category"], unit=v["unit"],
            stock_qty=0.0, stock_value=0.0, sold_recent=0.0, last_sale=None, low_stock_level=v["low_stock_level"],
            variants=0))
        p["stock_qty"] += v["stock_qty"]
        p["stock_value"] += v["stock_value"]
        p["sold_recent"] += v["sold_recent"]
        p["variants"] += 1
        if v["last_sale"] and (not p["last_sale"] or v["last_sale"] > p["last_sale"]):
            p["last_sale"] = v["last_sale"]
    plist = list(products.values())
    for p in plist:
        p["stock_value"] = money(p["stock_value"])
        p["days_since_sale"] = _days_between(p["last_sale"], t) if p["last_sale"] else None
        rate = p["sold_recent"] / days
        p["days_of_cover"] = round(p["stock_qty"] / rate, 1) if rate > 0 else None
        total = p["sold_recent"] + p["stock_qty"]
        p["sell_through"] = round(p["sold_recent"] * 100 / total, 1) if total > 0 else None

    fast = sorted([p for p in plist if p["sold_recent"] > 0], key=lambda p: -p["sold_recent"])[:10]
    slow = sorted([p for p in plist if p["stock_qty"] > EPS],
                  key=lambda p: (p["sold_recent"], -(p["days_since_sale"] or 10 ** 6)))[:10]

    cats = {}
    for v in variants:
        c = cats.setdefault(v["category_id"], dict(category_id=v["category_id"], category=v["category"],
                                                   stock_qty=0.0, stock_value=0.0, products=set()))
        c["stock_qty"] += v["stock_qty"]
        c["stock_value"] += v["stock_value"]
        c["products"].add(v["product_id"])
    cat_list = []
    for c in cats.values():
        c["products"] = len(c["products"])
        c["stock_value"] = money(c["stock_value"])
        cat_list.append(c)
    cat_list.sort(key=lambda c: -c["stock_value"])

    movement = movement_summary(conn, {"from": f.get("from"), "to": f.get("to"),
                                       "category_id": f.get("category_id"), "supplier_id": f.get("supplier_id")},
                                by="product")
    totals = {
        "units": round(sum(v["stock_qty"] for v in variants), 3),
        "value": money(sum(v["stock_value"] for v in variants)),
        "products": len(plist),
        "variants": len(variants),
        "low": sum(1 for v in variants if v["status"] == "low"),
        "out": sum(1 for v in variants if v["status"] == "out"),
        "purchased": round(sum(m["purchased"] for m in movement), 3),
        "sold": round(sum(m["sold"] for m in movement), 3),
        "returned": round(sum(m["returned"] for m in movement), 3),
        "adjusted": round(sum(m["adjusted"] for m in movement), 3),
    }

    sp = []
    sw = ""
    if f.get("from"):
        sw += " AND pu.purchase_date >= ?"
        sp.append(f["from"])
    if f.get("to"):
        sw += " AND pu.purchase_date <= ?"
        sp.append(f["to"])
    by_supplier = rows(conn.execute(
        "SELECT su.id, su.name, SUM(pi.qty) AS units, SUM(pi.landed_value) AS value, COUNT(DISTINCT pu.id) AS bills, "
        "COUNT(DISTINCT pi.variant_id) AS skus FROM purchase_items pi JOIN purchases pu ON pu.id = pi.purchase_id "
        "JOIN suppliers su ON su.id = pu.supplier_id WHERE pu.status = 'final'" + sw +
        " GROUP BY su.id ORDER BY value DESC", sp))

    result = {"totals": totals, "variants": variants, "products": plist, "categories": cat_list,
              "fast": fast, "slow": slow, "movement": movement, "by_supplier": by_supplier, "days": days}
    if not user_can_cost:
        totals.pop("value")
        for coll in (variants, plist, cat_list, movement):
            for r in coll:
                for k in ("stock_value", "avg_cost", "closing_value", "purchased_value", "sold_cost"):
                    r.pop(k, None)
        for r in by_supplier:
            r.pop("value", None)
    return result


def movement_summary(conn, f, by="variant"):
    """Opening, purchased, sold, returned, adjusted and closing stock per item."""
    frm, to = f.get("from"), f.get("to")
    where, params = "", []
    if f.get("category_id"):
        where += " AND p.category_id = ?"
        params.append(f["category_id"])
    if f.get("product_id"):
        where += " AND p.id = ?"
        params.append(f["product_id"])
    if f.get("supplier_id"):
        where += " AND v.id IN (%s)" % SUPPLIER_VARIANTS_SQL
        params += [f["supplier_id"]] * 2
    before = "m.move_date < ?" if frm else "0"
    within = []
    wp = []
    if frm:
        within.append("m.move_date >= ?")
        wp.append(frm)
    if to:
        within.append("m.move_date <= ?")
        wp.append(to)
    within_sql = " AND ".join(within) or "1"
    upto = "m.move_date <= ?" if to else "1"

    key = "v.id" if by == "variant" else "p.id"
    sql = """SELECT {key} AS k, p.id AS product_id, p.name AS product_name, p.unit, c.name AS category,
               MIN(v.sku) AS sku, v.size, v.colour, v.design,
               SUM(CASE WHEN {before} OR ({within} AND m.kind = 'opening') THEN m.qty ELSE 0 END) AS opening,
               SUM(CASE WHEN {within} AND m.kind = 'purchase' THEN m.qty ELSE 0 END) AS purchased,
               SUM(CASE WHEN {within} AND m.kind = 'purchase' THEN m.value ELSE 0 END) AS purchased_value,
               SUM(CASE WHEN {within} AND m.kind = 'sale' THEN -m.qty ELSE 0 END) AS sold,
               SUM(CASE WHEN {within} AND m.kind = 'sale' THEN -m.value ELSE 0 END) AS sold_cost,
               SUM(CASE WHEN {within} AND m.kind = 'return_in' THEN m.qty ELSE 0 END) AS returned,
               SUM(CASE WHEN {within} AND m.kind = 'adjust' THEN m.qty ELSE 0 END) AS adjusted,
               SUM(CASE WHEN {upto} THEN m.qty ELSE 0 END) AS closing,
               SUM(CASE WHEN {upto} THEN m.value ELSE 0 END) AS closing_value
             FROM inventory_movements m JOIN variants v ON v.id = m.variant_id
             JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id
             WHERE m.active = 1 {where} GROUP BY {key} ORDER BY p.name, v.size, v.colour""".format(
        key=key, before=before, within=within_sql, upto=upto, where=where)
    # parameter order follows placeholder order in the SELECT list
    p = ([frm] if frm else []) + wp + wp + wp + wp + wp + wp + wp + ([to] if to else []) + ([to] if to else []) + params
    out = rows(conn.execute(sql, p))
    for r in out:
        for k in ("opening", "purchased", "sold", "returned", "adjusted", "closing"):
            r[k] = round(r[k] or 0, 3)
        for k in ("purchased_value", "sold_cost", "closing_value"):
            r[k] = money(r[k] or 0)
        if by == "variant":
            r["label"] = variant_label(r)
        else:
            r["label"] = r["product_name"]
    return out


def variant_ledger(conn, variant_id, show_cost):
    v = conn.execute(
        "SELECT v.*, p.name AS product_name, p.unit, c.name AS category FROM variants v "
        "JOIN products p ON p.id = v.product_id JOIN categories c ON c.id = p.category_id WHERE v.id = ?",
        (variant_id,)).fetchone()
    if not v:
        return None
    moves = rows(conn.execute(
        """SELECT m.*,
             CASE m.ref_table
               WHEN 'purchases' THEN (SELECT pu.invoice_no || ' · ' || su.name FROM purchases pu
                                      JOIN suppliers su ON su.id = pu.supplier_id WHERE pu.id = m.ref_id)
               WHEN 'sales' THEN (SELECT invoice_no || ' · ' || channel FROM sales WHERE id = m.ref_id)
               WHEN 'sale_returns' THEN (SELECT 'Return on ' || s.invoice_no FROM sale_returns r
                                         JOIN sales s ON s.id = r.sale_id WHERE r.id = m.ref_id)
               WHEN 'stock_adjustments' THEN (SELECT reason || CASE WHEN notes <> '' THEN ' · ' || notes ELSE '' END
                                              FROM stock_adjustments WHERE id = m.ref_id)
               WHEN 'opening_stock' THEN 'Opening stock'
             END AS reference
           FROM inventory_movements m WHERE m.variant_id = ? AND m.active = 1 ORDER BY m.move_date, m.id""",
        (variant_id,)))
    bal_q = bal_v = 0.0
    for m in moves:
        bal_q += m["qty"]
        bal_v += m["value"]
        m["balance_qty"] = round(bal_q, 3)
        m["balance_value"] = money(bal_v)
        if not show_cost:
            for k in ("unit_cost", "value", "balance_value"):
                m.pop(k)
    info = dict(v)
    info["label"] = variant_label(v)
    if not show_cost:
        info.pop("stock_value")
    return {"variant": info, "moves": moves}
