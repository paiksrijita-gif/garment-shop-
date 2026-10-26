"""Read the Google Sheet "database" and turn it into dashboard metrics.

The sheet has one row per stock entry with these columns (header names are
matched case- and space-insensitively):

    Date of Entry | Product ID | Product Category | Product Type | Sizes |
    Seller | Cost | Total Units | Selling Price | Units Sold |
    Units available | Revenue | Profit

Cost and Selling Price are per unit. The three calculated columns are
recomputed here from the others, so a missing or broken formula in the sheet
never changes the numbers on the dashboard:

    Units available = Total Units − Units Sold
    Revenue         = Units Sold × Selling Price
    Profit          = Units Sold × (Selling Price − Cost)

Profit only counts units actually sold; unsold units stay as stock at cost.
"""
import csv
import io
import os
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

COLUMNS = OrderedDict([
    ("date", "Date of Entry"),
    ("product_id", "Product ID"),
    ("category", "Product Category"),
    ("type", "Product Type"),
    ("sizes", "Sizes"),
    ("seller", "Seller"),
    ("cost", "Cost"),
    ("total_units", "Total Units"),
    ("price", "Selling Price"),
    ("units_sold", "Units Sold"),
    ("units_available", "Units available"),
    ("revenue", "Revenue"),
    ("profit", "Profit"),
])
REQUIRED = ["product_id", "cost", "total_units", "price", "units_sold"]
NUMERIC = ["cost", "total_units", "price", "units_sold"]
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _key(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


HEADER_KEYS = {_key(label): field for field, label in COLUMNS.items()}


# ------------------------------------------------------------------ fetching

def sheet_csv_url(value, gid=None):
    """Build the CSV export URL from a sheet ID or any Google Sheets link."""
    value = (value or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", value)
    sheet_id = m.group(1) if m else value
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sheet_id or ""):
        raise ValueError("GOOGLE_SHEET_ID is not a valid Google Sheets ID or link")
    if gid is None:
        g = re.search(r"[#&?]gid=(\d+)", value)
        gid = g.group(1) if g else "0"
    return sheet_id, "https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=%s" % (sheet_id, gid)


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


def load_csv_text(fresh=False, ttl=20):
    """CSV text from SHEET_CSV_FILE (local testing) or the Google Sheet in
    GOOGLE_SHEET_ID, cached briefly so quick filter changes don't refetch."""
    local = os.environ.get("SHEET_CSV_FILE")
    if local:
        with open(local, encoding="utf-8-sig") as fh:
            return fh.read(), None
    sheet_id, url = sheet_csv_url(os.environ.get("GOOGLE_SHEET_ID", ""), os.environ.get("GOOGLE_SHEET_GID"))
    hit = _cache.get(url)
    if hit and not fresh and time.time() - hit[0] < ttl:
        return hit[1], sheet_id
    text = fetch_csv(url)
    _cache[url] = (time.time(), text)
    return text, sheet_id


# ------------------------------------------------------------------ parsing

def parse_number(value):
    text = str(value or "").strip()
    if not text:
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


def parse_sheet(text):
    """Return (rows, issues). Each row has the computed fields filled in."""
    reader = list(csv.reader(io.StringIO(text)))
    issues = []
    if not reader:
        return [], ["The sheet is empty."]
    header = reader[0]
    index = {}
    for i, h in enumerate(header):
        field = HEADER_KEYS.get(_key(h))
        if field and field not in index:
            index[field] = i
    missing = [COLUMNS[f] for f in REQUIRED if f not in index]
    if missing:
        return [], ["Missing column(s) in row 1: %s" % ", ".join(missing)]

    def cell(r, field):
        i = index.get(field)
        return r[i].strip() if i is not None and i < len(r) else ""

    body = [(n + 2, r) for n, r in enumerate(reader[1:]) if any(c.strip() for c in r)]
    dates = _resolve_dates([cell(r, "date") for _, r in body])
    rows = []
    for (line, r), d in zip(body, dates):
        pid = cell(r, "product_id")
        if not pid:
            issues.append("Row %d: Product ID is empty — row skipped." % line)
            continue
        nums = {}
        bad = False
        for f in NUMERIC:
            v = parse_number(cell(r, f))
            if v == "bad":
                issues.append("Row %d (%s): %s is not a number — row skipped." % (line, pid, COLUMNS[f]))
                bad = True
            elif v is not None and v < 0:
                issues.append("Row %d (%s): %s is negative — row skipped." % (line, pid, COLUMNS[f]))
                bad = True
            nums[f] = v or 0.0
        if bad:
            continue
        if d == "bad":
            issues.append("Row %d (%s): Date of Entry '%s' was not understood." % (line, pid, cell(r, "date")))
            d = None
        if nums["units_sold"] > nums["total_units"]:
            issues.append("Row %d (%s): Units Sold (%g) is more than Total Units (%g)." % (
                line, pid, nums["units_sold"], nums["total_units"]))
        row = {
            "row": line, "date": d, "product_id": pid,
            "category": cell(r, "category") or "Uncategorised", "type": cell(r, "type") or "Other",
            "sizes": cell(r, "sizes"), "seller": cell(r, "seller") or "Unknown",
        }
        row.update(nums)
        _compute(row)
        rows.append(row)
    return rows, issues


def _r2(x):
    return round(x + 0.0, 2)


def _compute(row):
    row["units_available"] = row["total_units"] - row["units_sold"]
    row["revenue"] = _r2(row["units_sold"] * row["price"])
    row["cogs"] = _r2(row["units_sold"] * row["cost"])
    row["profit"] = _r2(row["revenue"] - row["cogs"])
    row["stock_cost"] = _r2(row["total_units"] * row["cost"])
    row["unsold_cost"] = _r2(max(row["units_available"], 0) * row["cost"])
    row["unsold_retail"] = _r2(max(row["units_available"], 0) * row["price"])
    row["margin"] = _pct(row["profit"], row["revenue"])
    row["low_stock"] = 0 < row["units_available"] <= max(2, 0.1 * row["total_units"])
    row["out_of_stock"] = row["total_units"] > 0 and row["units_available"] <= 0


def _pct(a, b):
    return round(a * 100.0 / b, 1) if b else None


# ------------------------------------------------------------------ metrics

SUM_FIELDS = ["total_units", "units_sold", "units_available", "revenue", "cogs", "profit",
              "stock_cost", "unsold_cost", "unsold_retail"]


def _totals(rows):
    t = {f: 0.0 for f in SUM_FIELDS}
    for r in rows:
        for f in SUM_FIELDS:
            t[f] += r[f]
    t = {k: _r2(v) for k, v in t.items()}
    t["entries"] = len(rows)
    t["products"] = len({r["product_id"] for r in rows})
    t["margin"] = _pct(t["profit"], t["revenue"])
    t["sell_through"] = _pct(t["units_sold"], t["total_units"])
    t["low_stock"] = sum(1 for r in rows if r["low_stock"])
    t["out_of_stock"] = sum(1 for r in rows if r["out_of_stock"])
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
        out = [r for r in out if q in " ".join(str(r[k]) for k in ("product_id", "category", "type", "sizes", "seller")).lower()]
    return out


def dashboard(rows, f=None):
    f = f or {}
    sel = filter_rows(rows, f)
    by_product = _group(sel, lambda r: r["product_id"])
    info = {}
    for r in sel:
        info.setdefault(r["product_id"], r)
    for p in by_product:
        r = info[p["name"]]
        p.update(category=r["category"], type=r["type"], seller=r["seller"], sizes=r["sizes"])
    months = sorted(_group([r for r in sel if r["date"]], lambda r: r["date"][:7]), key=lambda g: g["name"])
    return {
        "kpis": _totals(sel),
        "by_category": sorted(_group(sel, lambda r: r["category"]), key=lambda g: -g["revenue"]),
        "by_type": sorted(_group(sel, lambda r: r["type"]), key=lambda g: -g["units_sold"]),
        "by_seller": sorted(_group(sel, lambda r: r["seller"]), key=lambda g: -g["stock_cost"]),
        "by_month": months,
        "top_profit": sorted(by_product, key=lambda g: -g["profit"])[:10],
        "attention": sorted([r for r in sel if r["low_stock"] or r["out_of_stock"]],
                            key=lambda r: (not r["out_of_stock"], r["units_available"])),
        "rows": sorted(sel, key=lambda r: (r["date"] or "", r["row"]), reverse=True),
        "options": {k: sorted({r[k] for r in rows}) for k in ("category", "type", "seller")},
        "date_range": [min((r["date"] for r in rows if r["date"]), default=None),
                       max((r["date"] for r in rows if r["date"]), default=None)],
    }


def today():
    return datetime.now(IST).date().isoformat()
