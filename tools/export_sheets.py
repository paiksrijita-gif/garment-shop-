#!/usr/bin/env python3
"""Build the Google Sheets files from shop/sheets_schema.py.

    python3 tools/export_sheets.py                     # template + structure doc
    python3 tools/export_sheets.py --db data/demo.db   # also a workbook filled from a database

Outputs (in docs/ by default):
    google-sheets-template.xlsx    empty tabs with headers and drop-downs
    google-sheets-structure.md     the structure, tab by tab
    google-sheets-<db name>.xlsx   every tab filled from the given database

Import any .xlsx into Google Sheets with File → Import → Upload →
"Replace spreadsheet"; every tab, header row and drop-down comes across.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shop import db, xlsx  # noqa: E402
from shop.sheets_schema import TABS, xlsx_kind  # noqa: E402

TYPE_LABEL = {
    "id": "ID (whole number, unique)", "text": "Text", "money": "Number — ₹, 2 decimals", "qty": "Number — quantity",
    "number": "Number", "date": "Date (DD-MM-YYYY)", "datetime": "Text — YYYY-MM-DD HH:MM:SS", "bool": "1 or 0",
    "choice": "Drop-down", "json": "Text — JSON list",
}


def type_label(t):
    return "ID of a row in %s" % t[4:] if t.startswith("ref:") else TYPE_LABEL[t]


def readme_rows():
    rows = [
        ("About", "Data store for the Garment Shop Manager app. One tab per table; row 1 holds the column names the app uses."),
        ("Rule 1", "Do not rename tabs or header cells, and do not reorder columns — the app maps them by name."),
        ("Rule 2", "Every row has a unique numeric id. Links between tabs use these ids (e.g. Sales.customer_id → Customers.id)."),
        ("Rule 3", "Finalised transactions are never deleted: set status to void and fill void_reason instead."),
        ("Rule 4", "Columns marked 'Calculated by the app' (stock, COGS, inventory values) are written by the app — do not edit them."),
        ("Rule 5", "Dates are real dates shown as DD-MM-YYYY; money is plain numbers in ₹ (no ₹ sign typed in the cell)."),
        ("Rule 6", "Passwords are never stored in this sheet. Logins stay in the app."),
        ("Columns tab", "Lists every column of every tab with its type and meaning."),
    ]
    for tab, _table, desc, _cols in TABS:
        rows.append((tab, desc))
    return [{"section": a, "text": b} for a, b in rows]


def dictionary_rows():
    out = []
    for tab, _table, _desc, cols in TABS:
        for c in cols:
            out.append({"tab": tab, "column": c[0], "type": type_label(c[1]), "required": "Yes" if c[2] else "",
                        "description": c[3] + (" — one of: " + ", ".join(c[4]) if len(c) > 4 else "")})
    return out


def build_workbook(conn=None):
    sheets = [
        {"name": "README", "title": "README", "plain": True, "rows": readme_rows(),
         "columns": [("section", "section", "text"), ("text", "text", "text")]},
        {"name": "Columns", "title": "Columns", "plain": True, "rows": dictionary_rows(),
         "columns": [("tab", "tab", "text"), ("column", "column", "text"), ("type", "type", "text"),
                     ("required", "required", "text"), ("description", "description", "text")]},
    ]
    for tab, table, _desc, cols in TABS:
        columns = [(c[0], c[0], xlsx_kind(c[1]), c[4] if len(c) > 4 else None) for c in cols]
        data = []
        if conn is not None:
            order = "key" if table == "settings" else "id"
            data = [dict(r) for r in conn.execute(
                "SELECT %s FROM %s ORDER BY %s" % (", ".join(c[0] for c in cols), table, order))]
        sheets.append({"name": tab, "title": tab, "plain": True, "columns": columns, "rows": data})
    return xlsx.build_xlsx(sheets)


def build_doc():
    lines = [
        "# Google Sheets structure",
        "",
        "This is the layout for keeping the shop's data in a Google Sheet. It mirrors the app's database "
        "exactly: **one tab per table, one row per record, row 1 = column names**. The same layout is in "
        "`google-sheets-template.xlsx` (empty, with drop-downs) and `google-sheets-demo.xlsx` (filled with "
        "demo data). Import either into Google Sheets with *File → Import → Upload → Replace spreadsheet*.",
        "",
        "Generated from `shop/sheets_schema.py` by `tools/export_sheets.py`; edit the schema file, not this page.",
        "",
        "## How the tabs link",
        "",
        "```",
        "Categories ─< Products ─< Variants ─┬─< PurchaseItems >─ Purchases >─ Suppliers ─< SupplierPayments",
        "                                    ├─< SaleItems ─────> Sales ─────> Customers ─< CustomerPayments",
        "                                    │      └─< SaleReturnItems >─ SaleReturns",
        "                                    ├─< OpeningStock",
        "                                    ├─< StockAdjustments",
        "                                    └─< InventoryMovements   (stock ledger for all of the above)",
        "ExpenseCategories ─< Expenses        CashTransactions        Users        Settings        AuditLog",
        "```",
        "",
        "`A ─< B` means one A has many B; B holds `a_id`.",
        "",
        "## Rules for the sheet",
        "",
    ]
    lines += ["- " + r["text"] for r in readme_rows()[1:7]]
    lines += [
        "",
        "## Where each number comes from",
        "",
        "| Figure | Calculated from |",
        "|---|---|",
        "| Stock on hand | `InventoryMovements.qty` summed per variant (cached in `Variants.stock_qty`) |",
        "| Inventory value | `InventoryMovements.value` summed (cached in `Variants.stock_value`) |",
        "| Net sales | `SaleItems.net_amount` − `SaleReturnItems.net_amount` (status = final) |",
        "| COGS | `SaleItems.cogs` − `SaleReturnItems.cogs_reversed` |",
        "| Gross profit | Net sales − COGS |",
        "| Net operating profit | Gross profit − `Expenses.amount` − stock write-offs (`StockAdjustments.value`, damaged returns) |",
        "| Supplier outstanding | `Suppliers.opening_balance` + `Purchases.total_cost` − `SupplierPayments.amount` |",
        "| Customer outstanding | `Customers.opening_balance` + `Sales.total_amount` − `CustomerPayments.amount` − credit `SaleReturns.total_refund` |",
        "| Cash / bank balance | `CashTransactions` + `CustomerPayments` − `SupplierPayments` − `Expenses` − cash/bank refunds, by `account` |",
        "| Capital invested | `CashTransactions` where kind is initial_investment, additional_capital or partner_contribution |",
        "",
        "## Connecting the app later (planned)",
        "",
        "- **One writer.** Only the app writes to the sheet, through a Google service account that the sheet is "
        "shared with. People read the sheet, and data tabs are protected against hand edits.",
        "- **Keep the local database as a working copy.** Every entry is first saved in the app's local "
        "database, in one transaction, so stock, COGS and balances stay consistent. New and changed rows are "
        "then pushed to the matching tab (append new ids, update changed rows by id). If the internet drops, "
        "the shop keeps working and the push catches up later.",
        "- **Why not read and write the sheet directly for every sale:** Google Sheets has no transactions or locking, "
        "and the API is limited to about 60 write requests per minute per user. A partly written invoice or "
        "two staff saving at the same moment could leave stock wrong.",
        "- **Restore from the sheet.** Because the sheet holds every table, the app can rebuild its database "
        "from the sheet on a new computer.",
        "",
        "## Tabs",
        "",
    ]
    for tab, _table, desc, cols in TABS:
        lines += ["### %s" % tab, "", desc, "", "| Column | Type | Required | Meaning |", "|---|---|---|---|"]
        for c in cols:
            meaning = c[3] + (" — one of: `%s`" % "`, `".join(c[4]) if len(c) > 4 else "")
            lines.append("| `%s` | %s | %s | %s |" % (c[0], type_label(c[1]), "Yes" if c[2] else "", meaning.replace("|", "/")))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "docs"))
    ap.add_argument("--db", help="also export this database into a filled workbook")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    paths = []
    p = os.path.join(args.out_dir, "google-sheets-template.xlsx")
    with open(p, "wb") as fh:
        fh.write(build_workbook())
    paths.append(p)
    p = os.path.join(args.out_dir, "google-sheets-structure.md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(build_doc())
    paths.append(p)
    if args.db:
        name = os.path.splitext(os.path.basename(args.db))[0]
        p = os.path.join(args.out_dir, "google-sheets-%s.xlsx" % name)
        conn = db.connect(args.db)
        with open(p, "wb") as fh:
            fh.write(build_workbook(conn))
        paths.append(p)
    for p in paths:
        print("wrote", os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
