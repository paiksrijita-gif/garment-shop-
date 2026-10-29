"""Read the Google Sheet "database" and turn it into dashboard metrics.

One row per stock entry. Header names are matched case- and
space-insensitively, and extra columns are ignored:

    Date of Entry | Product Category | Product Type | Sizes | Seller |
    CP | Total Units | Total Cost | SP | Units Sold | Units Available |
    Revenue - Wholesale | Profit - Wholesale |
    Units sold | Retail SP | Retail Revenue | Profit - Retail

CP, SP and Retail SP are per unit; "-" or blank means none. The first
"Units Sold" column is wholesale and the second (after it) is retail.
An optional "Product ID" column is used as the product name when present.

Totals and profits are recomputed here from the inputs, so a missing or
wrong formula in the sheet never changes the dashboard:

    Total Cost       = CP × Total Units
    Units Available  = Total Units − wholesale units sold − retail units sold
    Wholesale revenue = Units Sold × SP          profit = Units Sold × (SP − CP)
    Retail revenue    = Units sold × Retail SP   profit = Units sold × (Retail SP − CP)

Profit only counts units actually sold; unsold units stay as stock at cost.
"""
import csv
import io
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

LABELS = OrderedDict([
    ("date", "Date of Entry"), ("product_id", "Product ID"), ("category", "Product Category"),
    ("type", "Product Type"), ("sizes", "Sizes"), ("seller", "Seller"), ("cost", "CP"),
    ("total_units", "Total Units"), ("ws_price", "SP"), ("ws_sold", "Units Sold"),
    ("rt_sold", "Units sold (retail)"), ("rt_price", "Retail SP"),
])
# header text (letters only, lower case) → field
ALIASES = {
    "dateofentry": "date", "date": "date", "productid": "product_id",
    "productcategory": "category", "category": "category", "producttype": "type", "type": "type",
    "sizes": "sizes", "size": "sizes", "seller": "seller", "supplier": "seller",
    "cp": "cost", "cost": "cost", "costprice": "cost",
    "totalunits": "total_units",
    "sp": "ws_price", "sellingprice": "ws_price", "wholesalesp": "ws_price", "wholesaleprice": "ws_price",
    "retailsp": "rt_price", "retailsellingprice": "rt_price", "retailprice": "rt_price",
    "retailunitssold": "rt_sold", "wholesaleunitssold": "ws_sold",
}
REQUIRED = ["cost", "total_units"]
NUMERIC = ["cost", "total_units", "ws_price", "ws_sold", "rt_price", "rt_sold"]
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _key(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


def map_header(header):
    """Column index for each field. "Units Sold" is wholesale the first
    time it appears and retail the second time."""
    index = {}
    for i, h in enumerate(header):
        k = _key(h)
        field = "ws_sold" if k == "unitssold" and "ws_sold" not in index else \
            "rt_sold" if k == "unitssold" else ALIASES.get(k)
        if field and field not in index:
            index[field] = i
    return index


# ------------------------------------------------------------------ fetching

def sheet_csv_url(value, gid=None):
    """Build the CSV export URL from a sheet ID or any Google Sheets link."""
    value = (value or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    sheet_id = m.group(1) if m else value
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sheet_id or ""):
        raise ValueError("GOOGLE_SHEET_ID is not a valid Google Sheets ID or link")
    if not gid:
        g = re.search(r"[#&?]gid=(\d+)", value)
        gid = g.group(1) if g else None
    url = "https://docs.google.com/spreadsheets/d/%s/export?format=csv" % sheet_id
    # Without a gid Google exports the first tab. Don't assume gid=0: a sheet
    # created by uploading a file gets a different gid, and gid=0 then fails (400).
    if gid:
        url += "&gid=%s" % gid
    return sheet_id, url


def fetch_csv(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "garment-shop-dashboard"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8-sig", errors="replace")
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise RuntimeError("Google refused access to the sheet (%d). Share it as "
                               "'Anyone with the link — Viewer' and check GOOGLE_SHEET_ID." % e.code)
        raise RuntimeError("Google Sheets returned an error (%d)" % e.code)
    except urllib.error.URLError as e:
        raise RuntimeError("Cannot reach Google Sheets: %s" % e.reason)
    if "text/html" in ctype or body.lstrip().startswith("<"):
        raise RuntimeError("The sheet is not publicly readable. Share it as 'Anyone with the link — Viewer'.")
    return body


_cache = {}


def tab_csv_url(sheet_id, tab_name):
    return "https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&sheet=%s" % (sheet_id, quote(tab_name))


def _cached_fetch(url, fresh, ttl):
    hit = _cache.get(url)
    if hit and not fresh and time.time() - hit[0] < ttl:
        return hit[1]
    text = fetch_csv(url)
    _cache[url] = (time.time(), text)
    return text


def load_sources(fresh=False, ttl=20):
    """The sheet's CSV, cached briefly so quick filter changes don't refetch.

    Returns ({"inventory": text, "sales": text or None}, sheet_id). By default
    the "Inventory" and "Sales" tabs are read by name (GOOGLE_INVENTORY_TAB /
    GOOGLE_SALES_TAB override the names). GOOGLE_SHEET_GID reads one tab that
    holds everything. For local testing, SHEET_CSV_FILE (one tab) or
    SHEET_INVENTORY_FILE + SHEET_SALES_FILE are read from disk."""
    def read(path):
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()
    if os.environ.get("SHEET_INVENTORY_FILE"):
        sales = os.environ.get("SHEET_SALES_FILE")
        return {"inventory": read(os.environ["SHEET_INVENTORY_FILE"]), "sales": read(sales) if sales else None}, None
    if os.environ.get("SHEET_CSV_FILE"):
        return {"inventory": read(os.environ["SHEET_CSV_FILE"]), "sales": None}, None
    sheet_id, url = sheet_csv_url(os.environ.get("GOOGLE_SHEET_ID", ""), os.environ.get("GOOGLE_SHEET_GID"))
    if os.environ.get("GOOGLE_SHEET_GID"):
        return {"inventory": _cached_fetch(url, fresh, ttl), "sales": None}, sheet_id
    inv = _cached_fetch(tab_csv_url(sheet_id, os.environ.get("GOOGLE_INVENTORY_TAB") or "Inventory"), fresh, ttl)
    sales = _cached_fetch(tab_csv_url(sheet_id, os.environ.get("GOOGLE_SALES_TAB") or "Sales"), fresh, ttl)
    # Google answers an unknown tab name with the first tab, so identical text
    # means the sheet has a single tab holding everything.
    return {"inventory": inv, "sales": None if sales == inv else sales}, sheet_id


# ------------------------------------------------------------------ parsing

def parse_number(value):
    text = str(value or "").strip()
    if not text or text in ("-", "–", "—", "NA", "N/A"):
        return None
    neg = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[₹,\s()]|Rs\.?|INR", "", text, flags=re.I)
    if text in ("", "-"):
        return None
    try:
        n = float(text)
    except ValueError:
        return "bad"
    return -n if neg else n


def _date_parts(text):
    text = text.strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?", text)
    if m:
        return ("ymd", int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?:\s.*)?", text)
    if m:
        y = int(m.group(3))
        return ("ab", int(m.group(1)), int(m.group(2)), y + 2000 if y < 100 else y)
    m = re.fullmatch(r"(\d{1,2})[-\s/]([A-Za-z]{3,9})[-\s/,]*(\d{2,4})", text)
    if m and m.group(2)[:3].lower() in MONTHS:
        y = int(m.group(3))
        return ("ymd", y + 2000 if y < 100 else y, MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.fullmatch(r"([A-Za-z]{3,9})[\s-]+(\d{1,2}),?\s+(\d{4})", text)
    if m and m.group(1)[:3].lower() in MONTHS:
        return ("ymd", int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    return "bad"


def _resolve_dates(raw_values):
    """Decide whether a/b/yyyy dates are day-first (India) or month-first
    (a sheet left on US locale) by looking at all of them together."""
    parts = [_date_parts(v) for v in raw_values]
    ab = [p for p in parts if isinstance(p, tuple) and p[0] == "ab"]
    day_first = True
    if ab and any(p[2] > 12 for p in ab) and not any(p[1] > 12 for p in ab):
        day_first = False
    out = []
    for p in parts:
        if p is None or p == "bad":
            out.append(p)
            continue
        if p[0] == "ymd":
            y, mo, d = p[1], p[2], p[3]
        elif day_first:
            d, mo, y = p[1], p[2], p[3]
        else:
            mo, d, y = p[1], p[2], p[3]
        try:
            out.append(date(y, mo, d).isoformat())
        except ValueError:
            out.append("bad")
    return out


DASHES = ("-", "–", "—")
SALES_FIELDS = ["ws_price", "ws_sold", "rt_sold", "rt_price"]
MATCH_FIELDS = ["date", "type", "category", "sizes", "seller"]


def _records(text, tab=None):
    """Non-blank rows of one tab as {field: text}, plus the header index."""
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        return [], {}
    index = map_header(reader[0])
    out = []
    for n, r in enumerate(reader[1:]):
        if not any(c.strip() and c.strip() not in DASHES for c in r):
            continue
        cells = {}
        for field, i in index.items():
            v = r[i].strip() if i < len(r) else ""
            cells[field] = "" if v in DASHES else v
        out.append({"where": "%s row %d" % (tab, n + 2) if tab else "Row %d" % (n + 2), "cells": cells})
    return out, index


def _missing(index):
    return [LABELS[f] for f in REQUIRED if f not in index]


def parse_sheet(text):
    """One tab holding stock and sales columns. Returns (rows, issues)."""
    recs, index = _records(text)
    if not index:
        return [], ["The sheet is empty."]
    if _missing(index):
        return [], ["Missing column(s) in row 1: %s" % ", ".join(_missing(index))]
    return _build_rows(recs)


def _match_key(cells):
    return tuple(re.sub(r"\s+", " ", cells.get(f, "")).lower() for f in MATCH_FIELDS)


def parse_workbook(inventory_text, sales_text=None):
    """Stock from the Inventory tab joined with the Sales tab. A Sales row
    belongs to the Inventory row with the same Date of Entry, Product Type,
    Product Category, Sizes and Seller. Returns (rows, issues)."""
    if sales_text is None:
        return parse_sheet(inventory_text)
    inv, inv_index = _records(inventory_text, "Inventory")
    if not inv_index:
        return [], ["The Inventory tab is empty."]
    if _missing(inv_index):
        return [], ["Missing column(s) in row 1 of the Inventory tab: %s" % ", ".join(_missing(inv_index))]
    sales, sales_index = _records(sales_text, "Sales")
    issues = []
    if not any(f in sales_index for f in ("ws_sold", "rt_sold")):
        rows, more = _build_rows(inv)
        return rows, ["The Sales tab has no 'Units Sold' column, so only stock is shown."] + more

    pending = OrderedDict()
    for rec in sales:
        pending.setdefault(_match_key(rec["cells"]), []).append(rec)
    merged = []
    for rec in inv:
        match = pending.get(_match_key(rec["cells"]))
        cells = dict(rec["cells"])
        if match:
            sold = match.pop(0)["cells"]
            cells.update({f: sold.get(f, "") for f in SALES_FIELDS})
        merged.append({"where": rec["where"], "cells": cells})
    for recs in pending.values():
        for rec in recs:
            label = " / ".join(x for x in (rec["cells"].get("type"), rec["cells"].get("category"), rec["cells"].get("sizes")) if x)
            has_sales = any(rec["cells"].get(f) for f in ("ws_sold", "rt_sold"))
            if not _missing(sales_index) and has_sales:
                issues.append("%s (%s): no matching row in Inventory, so the Sales tab's own CP and Total Units "
                              "were used." % (rec["where"], label))
                merged.append(rec)
            elif has_sales:
                issues.append("%s (%s): no matching row in Inventory — sale not counted. Check Date of Entry, "
                              "Product Type, Product Category, Sizes and Seller match exactly." % (rec["where"], label))
    rows, more = _build_rows(merged)
    return rows, issues + more


def _build_rows(records):
    issues = []
    dates = _resolve_dates([rec["cells"].get("date", "") for rec in records])
    rows = []
    for order, (rec, d) in enumerate(zip(records, dates)):
        c = rec["cells"].get
        where = rec["where"]
        name = c("product_id", "")
        if not name:  # e.g. "Pratibha Dresses · XXL (Sachi-2)"
            name = " · ".join(x for x in (c("type", "") or c("category", ""), c("sizes", "")) if x) or where
            if c("seller", ""):
                name += " (%s)" % c("seller", "")
        nums, bad = {}, False
        for f in NUMERIC:
            v = parse_number(c(f, ""))
            if v == "bad":
                issues.append("%s (%s): %s '%s' is not a number — row skipped." % (where, name, LABELS[f], c(f, "")))
                bad = True
            elif v is not None and v < 0:
                issues.append("%s (%s): %s is negative — row skipped." % (where, name, LABELS[f]))
                bad = True
            nums[f] = v or 0.0
        if bad:
            continue
        if d == "bad":
            issues.append("%s (%s): Date of Entry '%s' was not understood." % (where, name, c("date", "")))
            d = None
        if nums["ws_sold"] and not nums["ws_price"]:
            issues.append("%s (%s): %g units sold wholesale but SP is empty." % (where, name, nums["ws_sold"]))
        if nums["rt_sold"] and not nums["rt_price"]:
            issues.append("%s (%s): %g units sold retail but Retail SP is empty." % (where, name, nums["rt_sold"]))
        if nums["ws_sold"] + nums["rt_sold"] > nums["total_units"]:
            issues.append("%s (%s): %g units sold is more than Total Units (%g)." % (
                where, name, nums["ws_sold"] + nums["rt_sold"], nums["total_units"]))
        row = {
            "row": order, "where": where, "date": d, "name": name, "product_id": c("product_id", ""),
            "category": c("category", "") or "Uncategorised", "type": c("type", "") or "—",
            "sizes": c("sizes", ""), "seller": c("seller", "") or "Unknown",
        }
        row.update(nums)
        _compute(row)
        rows.append(row)
    return rows, issues


def _r2(x):
    return round(x + 0.0, 2)


def _pct(a, b):
    return round(a * 100.0 / b, 1) if b else None


def _compute(row):
    c = row["cost"]
    row["units_sold"] = row["ws_sold"] + row["rt_sold"]
    row["units_available"] = row["total_units"] - row["units_sold"]
    row["stock_cost"] = _r2(row["total_units"] * c)
    row["ws_revenue"] = _r2(row["ws_sold"] * row["ws_price"])
    row["ws_profit"] = _r2(row["ws_revenue"] - row["ws_sold"] * c)
    row["rt_revenue"] = _r2(row["rt_sold"] * row["rt_price"])
    row["rt_profit"] = _r2(row["rt_revenue"] - row["rt_sold"] * c)
    row["revenue"] = _r2(row["ws_revenue"] + row["rt_revenue"])
    row["cogs"] = _r2(row["units_sold"] * c)
    row["profit"] = _r2(row["ws_profit"] + row["rt_profit"])
    row["unsold_cost"] = _r2(max(row["units_available"], 0) * c)
    row["margin"] = _pct(row["profit"], row["revenue"])
    row["low_stock"] = 0 < row["units_available"] <= max(2, 0.1 * row["total_units"])
    row["out_of_stock"] = row["total_units"] > 0 and row["units_available"] <= 0
    row["unsold"] = row["units_sold"] == 0


# ------------------------------------------------------------------ metrics

SUM_FIELDS = ["total_units", "units_sold", "ws_sold", "rt_sold", "units_available", "stock_cost",
              "revenue", "cogs", "profit", "ws_revenue", "ws_profit", "rt_revenue", "rt_profit", "unsold_cost"]


def _totals(rows):
    t = {f: 0.0 for f in SUM_FIELDS}
    for r in rows:
        for f in SUM_FIELDS:
            t[f] += r[f]
    t = {k: _r2(v) for k, v in t.items()}
    t["entries"] = len(rows)
    t["products"] = len({r["name"] for r in rows})
    t["margin"] = _pct(t["profit"], t["revenue"])
    t["ws_margin"] = _pct(t["ws_profit"], t["ws_revenue"])
    t["rt_margin"] = _pct(t["rt_profit"], t["rt_revenue"])
    t["sell_through"] = _pct(t["units_sold"], t["total_units"])
    t["low_stock"] = sum(1 for r in rows if r["low_stock"])
    t["out_of_stock"] = sum(1 for r in rows if r["out_of_stock"])
    t["not_sold_yet"] = sum(1 for r in rows if r["unsold"])
    return t


def _group(rows, key):
    groups = OrderedDict()
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    out = []
    for k, rs in groups.items():
        t = _totals(rs)
        t["name"] = k
        out.append(t)
    return out


def filter_rows(rows, f):
    out = rows
    if f.get("from"):
        out = [r for r in out if r["date"] and r["date"] >= f["from"]]
    if f.get("to"):
        out = [r for r in out if r["date"] and r["date"] <= f["to"]]
    for field in ("category", "type", "seller"):
        if f.get(field):
            out = [r for r in out if r[field] == f[field]]
    if f.get("q"):
        q = f["q"].lower()
        out = [r for r in out if q in " ".join(str(r[k]) for k in ("name", "category", "type", "sizes", "seller")).lower()]
    return out


def dashboard(rows, f=None):
    f = f or {}
    sel = filter_rows(rows, f)
    by_product = _group(sel, lambda r: r["name"])
    info = {}
    for r in sel:
        info.setdefault(r["name"], r)
    for p in by_product:
        r = info[p["name"]]
        p.update(category=r["category"], type=r["type"], seller=r["seller"], sizes=r["sizes"])
    months = sorted(_group([r for r in sel if r["date"]], lambda r: r["date"][:7]), key=lambda g: g["name"])
    k = _totals(sel)
    return {
        "kpis": k,
        "channels": [
            {"name": "Wholesale", "units_sold": k["ws_sold"], "revenue": k["ws_revenue"], "profit": k["ws_profit"], "margin": k["ws_margin"]},
            {"name": "Retail", "units_sold": k["rt_sold"], "revenue": k["rt_revenue"], "profit": k["rt_profit"], "margin": k["rt_margin"]},
        ],
        "by_category": sorted(_group(sel, lambda r: r["category"]), key=lambda g: (-g["revenue"], -g["stock_cost"])),
        "by_type": sorted(_group(sel, lambda r: r["type"]), key=lambda g: (-g["units_sold"], -g["total_units"])),
        "by_seller": sorted(_group(sel, lambda r: r["seller"]), key=lambda g: -g["stock_cost"]),
        "by_month": months,
        "top_profit": sorted(by_product, key=lambda g: -g["profit"])[:10],
        "attention": sorted([r for r in sel if r["low_stock"] or r["out_of_stock"]],
                            key=lambda r: (not r["out_of_stock"], r["units_available"])),
        "rows": sorted(sel, key=lambda r: (r["date"] or "", -r["row"]), reverse=True),
        "options": {k2: sorted({r[k2] for r in rows}) for k2 in ("category", "type", "seller")},
        "date_range": [min((r["date"] for r in rows if r["date"]), default=None),
                       max((r["date"] for r in rows if r["date"]), default=None)],
    }


def today():
    return datetime.now(IST).date().isoformat()
