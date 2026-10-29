# Garment Shop Manager

Inventory, sales, profit and capital tracking for an offline garment shop in India.
It runs on the shop's own computer and opens in any browser on a laptop, desktop or phone.

- **No installation:** it needs only Python 3.9 or newer (already on macOS and most Linux systems; on Windows, install it from python.org).
- **One data file:** everything is stored in a SQLite database, `data/shop.db`.
- **Amounts and dates:** rupees with Indian digit grouping (₹12,34,567.00) and DD-MM-YYYY dates.

## Start

```bash
python3 server.py
```

Then open http://127.0.0.1:8000.

Staff can use phones on the shop Wi-Fi. Start with `--lan`, then open the "Phones" address it prints:

```bash
python3 server.py --lan
```

Shortcuts: on macOS double-click `start.command`; on Windows double-click `start.bat`.

The first time it opens, the owner creates their account. The setup wizard then asks for:

1. Shop name, costing method (weighted average or FIFO), GST defaults and the start date
2. Opening cash and bank balances, capital invested before the app, initial investment and loans
3. Suppliers, with any amount you already owe them
4. Opening stock: the quantity on hand and what each unit actually cost
5. Credit customers, with any amount they already owe you

You can change any of these later under Settings → Opening balances & setup.

## Google Sheet dashboard (online, on Vercel)

A simpler online version keeps the data in one Google Sheet that you edit by hand, and shows the metrics on a website hosted on Vercel. See [DEPLOY.md](DEPLOY.md) for setup and the sheet's columns.

- `sheet/sample-inventory.csv` and `sheet/sample-sales.csv`: sample Inventory and Sales tabs for local testing.
- `shop/sheet_data.py`: reads the sheet and works out the metrics.
- `api/sheet.py`: the Vercel function that serves them.
- `sheet-site/`: the dashboard page.

To try it on your computer, run `python3 tools/dev_dashboard.py`.

## Try it with demo data

```bash
python3 tools/seed_demo.py
python3 server.py --db data/demo.db --port 8001
```

On macOS you can double-click `start-demo.command` instead. Then open http://127.0.0.1:8001.

This builds `data/demo.db`: six months of fictional activity for "DEMO Sample Garments". It includes 6 suppliers, 16 products (76 SKUs), opening stock, purchases, retail and wholesale sales on every day of the week, credit customers, returns, damage, expenses, capital, a loan and GST payments. The owner and staff demo logins are listed at the top of `tools/seed_demo.py`.

The demo database is separate from your real `data/shop.db`, and the script refuses to write into `shop.db`. To rebuild it from scratch, run `python3 tools/seed_demo.py --force`.

## Google Sheets layout

`docs/google-sheets-structure.md` describes the planned Google Sheet: one tab per table and every column. Two files go with it:

- `docs/google-sheets-template.xlsx`: empty tabs with headers and drop-downs.
- `docs/google-sheets-demo.xlsx`: the same tabs filled with the demo data.

To use either one, open Google Sheets and choose File → Import → Upload → Replace spreadsheet. To regenerate the files, run `python3 tools/export_sheets.py --db data/demo.db`.

## What it does

| Area | What it covers |
|---|---|
| Purchases | Supplier bills with many lines. Total = Qty × price + additional costs − discount. Freight and discounts are spread across the lines, so every unit carries its landed cost. Duplicate supplier invoice numbers are blocked. |
| Products | Simple designs, or variants by size, colour and design (with a variant generator). Each variant has its own SKU, stock level and prices. |
| Inventory | Live stock and value at cost, by category and by supplier. Low-stock and out-of-stock lists, fast and slow movers, a stock-movement summary, a per-SKU ledger, and damage or stock-count corrections. |
| Sales | Multi-line invoices. **Sales channel (Retail / Wholesale) must be chosen on every invoice and is never set from the date.** Discounts, GST (inclusive or exclusive), part payments, credit customers, returns (restocked or damaged), voids and printing. |
| Profit | Net Sales = Gross − Discounts − Returns. Gross Profit = Net Sales − COGS. Net Operating Profit = Gross Profit − Expenses − stock write-offs. Shown by product, category, channel and month. |
| COGS | Uses the actual landed cost of the units sold: weighted average by default, FIFO optional. Unsold stock stays in inventory value. Back-dated entries and voids recalculate automatically. |
| Capital & cash | Initial, additional and partner capital, withdrawals, loans, GST payments and cash↔bank transfers. Cash and bank balances come from every transaction, and a balance sheet check shows that the books reconcile. |
| Expenses | Rent, salaries, electricity and so on, with monthly and category breakdowns. |
| Dashboard | 16 KPI cards and 7 charts with date, channel, category, supplier and product filters. Every card and chart links through to the underlying records. |
| Reports | 12 reports, each downloadable as Excel (.xlsx) or CSV, plus a single workbook with all of them. |
| Staff | Owner and Staff roles with per-permission control. Staff never see cost, profit or capital unless allowed, and cannot void finalised entries without permission. |
| Safety | Hashed passwords, login lockout, HttpOnly session cookies, CSRF checks, an audit log of every change, and duplicate-submit protection. Finalised transactions are voided with a reason, never deleted. |

## Backups

Settings → Shop & accounting → **Download backup** saves a complete copy of the database. Keep copies off the computer, on a pen drive or in cloud storage.

To restore: stop the app, replace `data/shop.db` with the backup file, and start the app again.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests check purchase totals, landed-cost allocation, WAC and FIFO COGS, back-dated recalculation, returns, damage write-offs, voids, credit balances, the explicit-channel rule, permissions, the balance-sheet reconciliation and the Excel/CSV exports. All test data lives in temporary databases.

## Layout

```
server.py          HTTP server (Python standard library only)
api/sheet.py       Vercel function for the Google Sheet dashboard
vercel.json        Vercel build, region and security headers
shop/db.py         schema (suppliers, products, variants, purchases, sales, payments,
                   returns, expenses, inventory movements, capital, audit log)
shop/ledger.py     inventory costing engine (WAC / FIFO replay)
shop/services.py   validated entry for every transaction type
shop/metrics.py    revenue, profit, inventory, capital and dashboard maths
shop/reports.py    report definitions; shop/xlsx.py writes Excel and CSV
shop/sheets_schema.py  Google Sheets layout (one tab per table)
tools/             demo data generator, Google Sheets export
docs/              Google Sheets structure, template and demo workbook
static/            browser app (plain JavaScript, no build step)
tests/             unit and HTTP tests
```
