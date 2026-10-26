# Google Sheets structure

This is the layout for keeping the shop's data in a Google Sheet. It mirrors the app's database exactly: **one tab per table, one row per record, row 1 = column names**. The same layout is in `google-sheets-template.xlsx` (empty, with drop-downs) and `google-sheets-demo.xlsx` (filled with demo data). Import either into Google Sheets with *File → Import → Upload → Replace spreadsheet*.

Generated from `shop/sheets_schema.py` by `tools/export_sheets.py`; edit the schema file, not this page.

## How the tabs link

```
Categories ─< Products ─< Variants ─┬─< PurchaseItems >─ Purchases >─ Suppliers ─< SupplierPayments
                                    ├─< SaleItems ─────> Sales ─────> Customers ─< CustomerPayments
                                    │      └─< SaleReturnItems >─ SaleReturns
                                    ├─< OpeningStock
                                    ├─< StockAdjustments
                                    └─< InventoryMovements   (stock ledger for all of the above)
ExpenseCategories ─< Expenses        CashTransactions        Users        Settings        AuditLog
```

`A ─< B` means one A has many B; B holds `a_id`.

## Rules for the sheet

- Do not rename tabs or header cells, and do not reorder columns — the app maps them by name.
- Every row has a unique numeric id. Links between tabs use these ids (e.g. Sales.customer_id → Customers.id).
- Finalised transactions are never deleted: set status to void and fill void_reason instead.
- Columns marked 'Calculated by the app' (stock, COGS, inventory values) are written by the app — do not edit them.
- Dates are real dates shown as DD-MM-YYYY; money is plain numbers in ₹ (no ₹ sign typed in the cell).
- Passwords are never stored in this sheet. Logins stay in the app.

## Where each number comes from

| Figure | Calculated from |
|---|---|
| Stock on hand | `InventoryMovements.qty` summed per variant (cached in `Variants.stock_qty`) |
| Inventory value | `InventoryMovements.value` summed (cached in `Variants.stock_value`) |
| Net sales | `SaleItems.net_amount` − `SaleReturnItems.net_amount` (status = final) |
| COGS | `SaleItems.cogs` − `SaleReturnItems.cogs_reversed` |
| Gross profit | Net sales − COGS |
| Net operating profit | Gross profit − `Expenses.amount` − stock write-offs (`StockAdjustments.value`, damaged returns) |
| Supplier outstanding | `Suppliers.opening_balance` + `Purchases.total_cost` − `SupplierPayments.amount` |
| Customer outstanding | `Customers.opening_balance` + `Sales.total_amount` − `CustomerPayments.amount` − credit `SaleReturns.total_refund` |
| Cash / bank balance | `CashTransactions` + `CustomerPayments` − `SupplierPayments` − `Expenses` − cash/bank refunds, by `account` |
| Capital invested | `CashTransactions` where kind is initial_investment, additional_capital or partner_contribution |

## Connecting the app later (planned)

- **One writer.** Only the app writes to the sheet, through a Google service account that the sheet is shared with. People read the sheet, and data tabs are protected against hand edits.
- **Keep the local database as a working copy.** Every entry is first saved in the app's local database, in one transaction, so stock, COGS and balances stay consistent. New and changed rows are then pushed to the matching tab (append new ids, update changed rows by id). If the internet drops, the shop keeps working and the push catches up later.
- **Why not read and write the sheet directly for every sale:** Google Sheets has no transactions or locking, and the API is limited to about 60 write requests per minute per user. A partly written invoice or two staff saving at the same moment could leave stock wrong.
- **Restore from the sheet.** Because the sheet holds every table, the app can rebuild its database from the sheet on a new computer.

## Tabs

### Settings

Shop settings as key / value pairs.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `key` | Text | Yes | Setting name, e.g. shop_name, costing_method (WAC or FIFO), opening_date |
| `value` | Text | Yes | Setting value |

### Users

Owner and staff accounts. Passwords are never stored in the sheet.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | User ID |
| `username` | Text | Yes | Login name (unique) |
| `full_name` | Text | Yes | Display name |
| `role` | Drop-down | Yes | Owner or staff — one of: `owner`, `staff` |
| `permissions` | Text — JSON list |  | Staff permissions, e.g. ["sales.create","inventory.view"] |
| `active` | 1 or 0 | Yes | 1 = can sign in, 0 = disabled |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When the account was created |

### Categories

Product categories.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Category ID |
| `name` | Text | Yes | Category name (unique), e.g. Sarees |

### Suppliers

Supplier master. Balances are calculated from Purchases and SupplierPayments.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Supplier ID |
| `code` | Text | Yes | Supplier code, e.g. SUP-0001 |
| `name` | Text | Yes | Supplier name (unique) |
| `phone` | Text |  | Contact number |
| `address` | Text |  | Address |
| `gstin` | Text |  | GST number |
| `categories` | Text |  | Categories supplied (comma separated) |
| `opening_balance` | Number — ₹, 2 decimals | Yes | Amount owed to the supplier before using the app |
| `notes` | Text |  | Notes |
| `active` | 1 or 0 | Yes | 1 = active, 0 = hidden |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When added |

### Customers

Named customers (mainly wholesale / credit). Walk-in retail sales need no customer.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Customer ID |
| `name` | Text | Yes | Customer name |
| `phone` | Text |  | Phone |
| `address` | Text |  | Address |
| `kind` | Drop-down | Yes | Customer type — one of: `retail`, `wholesale` |
| `opening_balance` | Number — ₹, 2 decimals | Yes | Amount the customer owed before using the app |
| `notes` | Text |  | Notes |
| `active` | 1 or 0 | Yes | 1 = active |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When added |

### Products

Product / design master. Stock is held per variant.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Product ID |
| `name` | Text | Yes | Product name or design (unique) |
| `category_id` | ID of a row in Categories | Yes | Category |
| `unit` | Drop-down | Yes | How quantity is counted — one of: `piece`, `set`, `pair`, `dozen`, `metre`, `box` |
| `has_variants` | 1 or 0 | Yes | 1 = tracked by size / colour / design, 0 = simple |
| `low_stock_level` | Number — quantity | Yes | Low-stock alert level per variant |
| `description` | Text |  | Description |
| `active` | 1 or 0 | Yes | 1 = active |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When added |

### Variants

Sellable SKUs. A simple product has exactly one variant with blank size / colour / design.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Variant ID |
| `product_id` | ID of a row in Products | Yes | Product |
| `sku` | Text | Yes | SKU code (unique) |
| `size` | Text |  | Size |
| `colour` | Text |  | Colour |
| `design` | Text |  | Design |
| `retail_price` | Number — ₹, 2 decimals | Yes | Retail selling price |
| `wholesale_price` | Number — ₹, 2 decimals | Yes | Wholesale selling price |
| `stock_qty` | Number — quantity | Yes | Units in stock — Calculated by the app — do not edit |
| `stock_value` | Number — ₹, 2 decimals | Yes | Stock value at cost — Calculated by the app — do not edit |
| `active` | 1 or 0 | Yes | 1 = active |

### OpeningStock

Stock on hand when the shop started using the app, at historical cost.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Entry ID |
| `entry_date` | Date (DD-MM-YYYY) | Yes | As-of date |
| `variant_id` | ID of a row in Variants | Yes | Variant |
| `supplier_id` | ID of a row in Suppliers |  | Supplier it was bought from (optional) |
| `qty` | Number — quantity | Yes | Quantity |
| `unit_cost` | Number — ₹, 2 decimals | Yes | Cost per unit |
| `value` | Number — ₹, 2 decimals | Yes | qty × unit_cost |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### Purchases

Supplier bills (one row per bill). Lines are in PurchaseItems.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Purchase ID |
| `purchase_date` | Date (DD-MM-YYYY) | Yes | Date goods were received |
| `supplier_id` | ID of a row in Suppliers | Yes | Supplier |
| `invoice_no` | Text | Yes | Supplier invoice / reference no. (unique per supplier) |
| `subtotal` | Number — ₹, 2 decimals | Yes | Σ qty × purchase price |
| `additional_cost` | Number — ₹, 2 decimals | Yes | Transport and other costs |
| `additional_note` | Text |  | What the additional cost was for |
| `discount` | Number — ₹, 2 decimals | Yes | Purchase discount |
| `total_cost` | Number — ₹, 2 decimals | Yes | subtotal + additional_cost − discount |
| `amount_paid` | Number — ₹, 2 decimals | Yes | Paid at the time of purchase |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### PurchaseItems

Lines on each purchase bill.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Line ID |
| `purchase_id` | ID of a row in Purchases | Yes | Purchase bill |
| `variant_id` | ID of a row in Variants | Yes | Variant received |
| `qty` | Number — quantity | Yes | Quantity received |
| `unit_price` | Number — ₹, 2 decimals | Yes | Purchase price per unit |
| `line_amount` | Number — ₹, 2 decimals | Yes | qty × unit_price |
| `allocated_cost` | Number — ₹, 2 decimals | Yes | Share of additional cost − discount |
| `landed_value` | Number — ₹, 2 decimals | Yes | line_amount + allocated_cost |
| `landed_unit_cost` | Number — ₹, 2 decimals | Yes | landed_value ÷ qty (used for COGS) |

### SupplierPayments

Money paid to suppliers.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Payment ID |
| `payment_date` | Date (DD-MM-YYYY) | Yes | Date paid |
| `supplier_id` | ID of a row in Suppliers | Yes | Supplier |
| `purchase_id` | ID of a row in Purchases |  | Bill it was paid against (blank = on account) |
| `with_document` | 1 or 0 | Yes | 1 = paid together with the purchase entry |
| `amount` | Number — ₹, 2 decimals | Yes | Amount |
| `method` | Drop-down | Yes | Payment method — one of: `Cash`, `UPI`, `Card`, `Bank Transfer`, `Cheque` |
| `account` | Drop-down | Yes | Paid from — one of: `cash`, `bank` |
| `reference` | Text |  | UTR / cheque no. |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### Sales

Sales invoices (one row per invoice). Channel is always entered explicitly.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Sale ID |
| `sale_date` | Date (DD-MM-YYYY) | Yes | Invoice date |
| `invoice_no` | Text | Yes | Invoice number (unique) |
| `channel` | Drop-down | Yes | Sales channel — chosen on every invoice, never from the weekday — one of: `retail`, `wholesale` |
| `customer_id` | ID of a row in Customers |  | Customer (blank = walk-in) |
| `customer_name` | Text |  | Customer name as printed |
| `tax_inclusive` | 1 or 0 | Yes | 1 = prices included GST |
| `gross_amount` | Number — ₹, 2 decimals | Yes | Gross sales excluding GST |
| `discount_amount` | Number — ₹, 2 decimals | Yes | Discounts excluding GST |
| `net_amount` | Number — ₹, 2 decimals | Yes | gross − discount (revenue, excl. GST) |
| `tax_amount` | Number — ₹, 2 decimals | Yes | GST |
| `total_amount` | Number — ₹, 2 decimals | Yes | Invoice total = net + GST |
| `amount_received` | Number — ₹, 2 decimals | Yes | Received at the time of sale |
| `payment_method` | Drop-down |  | Payment method — one of: `Cash`, `UPI`, `Card`, `Bank Transfer`, `Cheque` |
| `staff_user_id` | ID of a row in Users | Yes | Staff member who made the sale |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### SaleItems

Lines on each invoice.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Line ID |
| `sale_id` | ID of a row in Sales | Yes | Invoice |
| `variant_id` | ID of a row in Variants | Yes | Variant sold |
| `qty` | Number — quantity | Yes | Quantity |
| `unit_price` | Number — ₹, 2 decimals | Yes | Selling price per unit as entered |
| `discount` | Number — ₹, 2 decimals | Yes | Line discount as entered (₹) |
| `tax_rate` | Number | Yes | GST rate % |
| `gross_amount` | Number — ₹, 2 decimals | Yes | Gross excluding GST |
| `discount_amount` | Number — ₹, 2 decimals | Yes | Discount excluding GST |
| `net_amount` | Number — ₹, 2 decimals | Yes | Net revenue excluding GST |
| `tax_amount` | Number — ₹, 2 decimals | Yes | GST |
| `line_total` | Number — ₹, 2 decimals | Yes | net + GST |
| `cogs` | Number — ₹, 2 decimals | Yes | Cost of goods sold — Calculated by the app — do not edit |

### CustomerPayments

Money received from customers (at the sale or later).

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Receipt ID |
| `payment_date` | Date (DD-MM-YYYY) | Yes | Date received |
| `customer_id` | ID of a row in Customers |  | Customer (blank = walk-in) |
| `sale_id` | ID of a row in Sales |  | Invoice it was received against |
| `with_document` | 1 or 0 | Yes | 1 = received together with the sale entry |
| `amount` | Number — ₹, 2 decimals | Yes | Amount |
| `method` | Drop-down | Yes | Payment method — one of: `Cash`, `UPI`, `Card`, `Bank Transfer`, `Cheque` |
| `account` | Drop-down | Yes | Received into — one of: `cash`, `bank` |
| `reference` | Text |  | UPI ref / cheque no. |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### SaleReturns

Customer returns against an invoice.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Return ID |
| `return_date` | Date (DD-MM-YYYY) | Yes | Date returned |
| `sale_id` | ID of a row in Sales | Yes | Original invoice |
| `refund_mode` | Drop-down | Yes | How the customer was refunded — one of: `cash`, `bank`, `credit` |
| `net_amount` | Number — ₹, 2 decimals | Yes | Revenue reversed (excl. GST) |
| `tax_amount` | Number — ₹, 2 decimals | Yes | GST reversed |
| `total_refund` | Number — ₹, 2 decimals | Yes | Total refunded / credited |
| `notes` | Text |  | Reason |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### SaleReturnItems

Lines on each return.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Line ID |
| `return_id` | ID of a row in SaleReturns | Yes | Return |
| `sale_item_id` | ID of a row in SaleItems | Yes | Invoice line being returned |
| `qty` | Number — quantity | Yes | Quantity returned |
| `restock` | 1 or 0 | Yes | 1 = back into stock, 0 = damaged (written off) |
| `net_amount` | Number — ₹, 2 decimals | Yes | Revenue reversed |
| `tax_amount` | Number — ₹, 2 decimals | Yes | GST reversed |
| `total` | Number — ₹, 2 decimals | Yes | Refund for this line |
| `cogs_reversed` | Number — ₹, 2 decimals | Yes | Cost taken back out of COGS — Calculated by the app — do not edit |

### StockAdjustments

Damage, loss and stock-count corrections.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Adjustment ID |
| `adj_date` | Date (DD-MM-YYYY) | Yes | Date |
| `variant_id` | ID of a row in Variants | Yes | Variant |
| `qty` | Number — quantity | Yes | Change in quantity (negative = reduced) |
| `reason` | Drop-down | Yes | Reason — one of: `damaged`, `lost`, `correction`, `other` |
| `value` | Number — ₹, 2 decimals | Yes | Change in stock value at cost — Calculated by the app — do not edit |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### InventoryMovements

Stock ledger: every unit in or out. Calculated by the app — do not edit.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Movement ID |
| `move_date` | Date (DD-MM-YYYY) | Yes | Date |
| `variant_id` | ID of a row in Variants | Yes | Variant |
| `kind` | Drop-down | Yes | Movement type — one of: `opening`, `purchase`, `sale`, `return_in`, `adjust` |
| `qty` | Number — quantity | Yes | Quantity (+ in, − out) |
| `unit_cost` | Number — ₹, 2 decimals | Yes | Cost per unit |
| `value` | Number — ₹, 2 decimals | Yes | Value at cost (+ in, − out) |
| `ref_table` | Text | Yes | Source tab: opening_stock / purchases / sales / sale_returns / stock_adjustments |
| `ref_id` | Number | Yes | ID of the source record |
| `ref_item_id` | Number |  | ID of the source line |
| `src_item_id` | Number |  | Sale line ID (for sales and returns) |
| `active` | 1 or 0 | Yes | 0 = source was voided |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When written |

### ExpenseCategories

Expense heads.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Category ID |
| `name` | Text | Yes | Name, e.g. Shop Rent |

### Expenses

Operating expenses (reduce net operating profit).

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Expense ID |
| `expense_date` | Date (DD-MM-YYYY) | Yes | Date |
| `category_id` | ID of a row in ExpenseCategories | Yes | Expense category |
| `amount` | Number — ₹, 2 decimals | Yes | Amount |
| `method` | Drop-down | Yes | Payment method — one of: `Cash`, `UPI`, `Card`, `Bank Transfer`, `Cheque` |
| `account` | Drop-down | Yes | Paid from — one of: `cash`, `bank` |
| `description` | Text |  | Description |
| `recipient` | Text |  | Paid to |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### CashTransactions

Capital, loans, withdrawals, opening cash/bank, GST payments and transfers. Never revenue or expense.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Entry ID |
| `txn_date` | Date (DD-MM-YYYY) | Yes | Date |
| `kind` | Drop-down | Yes | Type of entry — one of: `opening_balance`, `initial_investment`, `additional_capital`, `partner_contribution`, `owner_withdrawal`, `loan_received`, `loan_repayment`, `tax_payment`, `cash_to_bank`, `bank_to_cash` |
| `amount` | Number — ₹, 2 decimals | Yes | Amount |
| `account` | Drop-down | Yes | Cash or bank account affected (source account for transfers) — one of: `cash`, `bank` |
| `party` | Text |  | Owner / partner / lender name |
| `purpose` | Drop-down | Yes | What capital was allocated to — one of: `general`, `inventory`, `expenses` |
| `notes` | Text |  | Notes |
| `status` | Drop-down | Yes | final = counts; void = cancelled, kept for audit — one of: `final`, `void` |
| `void_reason` | Text |  | Why it was voided |
| `voided_by` | ID of a row in Users |  | Who voided it |
| `voided_at` | Text — YYYY-MM-DD HH:MM:SS |  | When it was voided |
| `created_by` | ID of a row in Users | Yes | Who entered it |
| `created_at` | Text — YYYY-MM-DD HH:MM:SS | Yes | When it was entered |

### AuditLog

Every create, update, void and login. Append-only.

| Column | Type | Required | Meaning |
|---|---|---|---|
| `id` | ID (whole number, unique) | Yes | Log ID |
| `ts` | Text — YYYY-MM-DD HH:MM:SS | Yes | Timestamp (UTC) |
| `user_id` | ID of a row in Users |  | User |
| `action` | Text | Yes | Action, e.g. sale.create, void |
| `entity` | Text |  | Table affected |
| `entity_id` | Number |  | Record ID |
| `details` | Text — JSON list |  | Details |
