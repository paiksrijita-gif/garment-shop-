"""Google Sheets layout for the shop database.

One tab per table, one row per record, row 1 = column headers that match the
database column names exactly, so a sync job can map rows 1:1. This module is
the single source of truth for the template workbook, the demo export and the
structure document (tools/export_sheets.py builds all three).

Column tuple: (name, type, required, description[, choices])
Types: id, ref:<Tab>, text, money, qty, number, date, datetime, bool, choice, json
"""

CALC = "Calculated by the app — do not edit"

STATUS = ("status", "choice", True, "final = counts; void = cancelled, kept for audit", ["final", "void"])
VOID_COLS = [
    STATUS,
    ("void_reason", "text", False, "Why it was voided"),
    ("voided_by", "ref:Users", False, "Who voided it"),
    ("voided_at", "datetime", False, "When it was voided"),
]
AUDIT_COLS = [
    ("created_by", "ref:Users", True, "Who entered it"),
    ("created_at", "datetime", True, "When it was entered"),
]
METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Cheque"]
ACCOUNTS = ["cash", "bank"]

TABS = [
    ("Settings", "settings", "Shop settings as key / value pairs.", [
        ("key", "text", True, "Setting name, e.g. shop_name, costing_method (WAC or FIFO), opening_date"),
        ("value", "text", True, "Setting value"),
    ]),
    ("Users", "users", "Owner and staff accounts. Passwords are never stored in the sheet.", [
        ("id", "id", True, "User ID"),
        ("username", "text", True, "Login name (unique)"),
        ("full_name", "text", True, "Display name"),
        ("role", "choice", True, "Owner or staff", ["owner", "staff"]),
        ("permissions", "json", False, 'Staff permissions, e.g. ["sales.create","inventory.view"]'),
        ("active", "bool", True, "1 = can sign in, 0 = disabled"),
        ("created_at", "datetime", True, "When the account was created"),
    ]),
    ("Categories", "categories", "Product categories.", [
        ("id", "id", True, "Category ID"),
        ("name", "text", True, "Category name (unique), e.g. Sarees"),
    ]),
    ("Suppliers", "suppliers", "Supplier master. Balances are calculated from Purchases and SupplierPayments.", [
        ("id", "id", True, "Supplier ID"),
        ("code", "text", True, "Supplier code, e.g. SUP-0001"),
        ("name", "text", True, "Supplier name (unique)"),
        ("phone", "text", False, "Contact number"),
        ("address", "text", False, "Address"),
        ("gstin", "text", False, "GST number"),
        ("categories", "text", False, "Categories supplied (comma separated)"),
        ("opening_balance", "money", True, "Amount owed to the supplier before using the app"),
        ("notes", "text", False, "Notes"),
        ("active", "bool", True, "1 = active, 0 = hidden"),
        ("created_at", "datetime", True, "When added"),
    ]),
    ("Customers", "customers", "Named customers (mainly wholesale / credit). Walk-in retail sales need no customer.", [
        ("id", "id", True, "Customer ID"),
        ("name", "text", True, "Customer name"),
        ("phone", "text", False, "Phone"),
        ("address", "text", False, "Address"),
        ("kind", "choice", True, "Customer type", ["retail", "wholesale"]),
        ("opening_balance", "money", True, "Amount the customer owed before using the app"),
        ("notes", "text", False, "Notes"),
        ("active", "bool", True, "1 = active"),
        ("created_at", "datetime", True, "When added"),
    ]),
    ("Products", "products", "Product / design master. Stock is held per variant.", [
        ("id", "id", True, "Product ID"),
        ("name", "text", True, "Product name or design (unique)"),
        ("category_id", "ref:Categories", True, "Category"),
        ("unit", "choice", True, "How quantity is counted", ["piece", "set", "pair", "dozen", "metre", "box"]),
        ("has_variants", "bool", True, "1 = tracked by size / colour / design, 0 = simple"),
        ("low_stock_level", "qty", True, "Low-stock alert level per variant"),
        ("description", "text", False, "Description"),
        ("active", "bool", True, "1 = active"),
        ("created_at", "datetime", True, "When added"),
    ]),
    ("Variants", "variants", "Sellable SKUs. A simple product has exactly one variant with blank size / colour / design.", [
        ("id", "id", True, "Variant ID"),
        ("product_id", "ref:Products", True, "Product"),
        ("sku", "text", True, "SKU code (unique)"),
        ("size", "text", False, "Size"),
        ("colour", "text", False, "Colour"),
        ("design", "text", False, "Design"),
        ("retail_price", "money", True, "Retail selling price"),
        ("wholesale_price", "money", True, "Wholesale selling price"),
        ("stock_qty", "qty", True, "Units in stock — " + CALC),
        ("stock_value", "money", True, "Stock value at cost — " + CALC),
        ("active", "bool", True, "1 = active"),
    ]),
    ("OpeningStock", "opening_stock", "Stock on hand when the shop started using the app, at historical cost.", [
        ("id", "id", True, "Entry ID"),
        ("entry_date", "date", True, "As-of date"),
        ("variant_id", "ref:Variants", True, "Variant"),
        ("supplier_id", "ref:Suppliers", False, "Supplier it was bought from (optional)"),
        ("qty", "qty", True, "Quantity"),
        ("unit_cost", "money", True, "Cost per unit"),
        ("value", "money", True, "qty × unit_cost"),
        ("notes", "text", False, "Notes"),
    ] + VOID_COLS + AUDIT_COLS),
    ("Purchases", "purchases", "Supplier bills (one row per bill). Lines are in PurchaseItems.", [
        ("id", "id", True, "Purchase ID"),
        ("purchase_date", "date", True, "Date goods were received"),
        ("supplier_id", "ref:Suppliers", True, "Supplier"),
        ("invoice_no", "text", True, "Supplier invoice / reference no. (unique per supplier)"),
        ("subtotal", "money", True, "Σ qty × purchase price"),
        ("additional_cost", "money", True, "Transport and other costs"),
        ("additional_note", "text", False, "What the additional cost was for"),
        ("discount", "money", True, "Purchase discount"),
        ("total_cost", "money", True, "subtotal + additional_cost − discount"),
        ("amount_paid", "money", True, "Paid at the time of purchase"),
        ("notes", "text", False, "Notes"),
    ] + VOID_COLS + AUDIT_COLS),
    ("PurchaseItems", "purchase_items", "Lines on each purchase bill.", [
        ("id", "id", True, "Line ID"),
        ("purchase_id", "ref:Purchases", True, "Purchase bill"),
        ("variant_id", "ref:Variants", True, "Variant received"),
        ("qty", "qty", True, "Quantity received"),
        ("unit_price", "money", True, "Purchase price per unit"),
        ("line_amount", "money", True, "qty × unit_price"),
        ("allocated_cost", "money", True, "Share of additional cost − discount"),
        ("landed_value", "money", True, "line_amount + allocated_cost"),
        ("landed_unit_cost", "money", True, "landed_value ÷ qty (used for COGS)"),
    ]),
    ("SupplierPayments", "supplier_payments", "Money paid to suppliers.", [
        ("id", "id", True, "Payment ID"),
        ("payment_date", "date", True, "Date paid"),
        ("supplier_id", "ref:Suppliers", True, "Supplier"),
        ("purchase_id", "ref:Purchases", False, "Bill it was paid against (blank = on account)"),
        ("with_document", "bool", True, "1 = paid together with the purchase entry"),
        ("amount", "money", True, "Amount"),
        ("method", "choice", True, "Payment method", METHODS),
        ("account", "choice", True, "Paid from", ACCOUNTS),
        ("reference", "text", False, "UTR / cheque no."),
        ("notes", "text", False, "Notes"),
    ] + VOID_COLS + AUDIT_COLS),
    ("Sales", "sales", "Sales invoices (one row per invoice). Channel is always entered explicitly.", [
        ("id", "id", True, "Sale ID"),
        ("sale_date", "date", True, "Invoice date"),
        ("invoice_no", "text", True, "Invoice number (unique)"),
        ("channel", "choice", True, "Sales channel — chosen on every invoice, never from the weekday", ["retail", "wholesale"]),
        ("customer_id", "ref:Customers", False, "Customer (blank = walk-in)"),
        ("customer_name", "text", False, "Customer name as printed"),
        ("tax_inclusive", "bool", True, "1 = prices included GST"),
        ("gross_amount", "money", True, "Gross sales excluding GST"),
        ("discount_amount", "money", True, "Discounts excluding GST"),
        ("net_amount", "money", True, "gross − discount (revenue, excl. GST)"),
        ("tax_amount", "money", True, "GST"),
        ("total_amount", "money", True, "Invoice total = net + GST"),
        ("amount_received", "money", True, "Received at the time of sale"),
        ("payment_method", "choice", False, "Payment method", METHODS),
        ("staff_user_id", "ref:Users", True, "Staff member who made the sale"),
        ("notes", "text", False, "Notes"),
    ] + VOID_COLS + AUDIT_COLS),
    ("SaleItems", "sale_items", "Lines on each invoice.", [
        ("id", "id", True, "Line ID"),
        ("sale_id", "ref:Sales", True, "Invoice"),
        ("variant_id", "ref:Variants", True, "Variant sold"),
        ("qty", "qty", True, "Quantity"),
        ("unit_price", "money", True, "Selling price per unit as entered"),
        ("discount", "money", True, "Line discount as entered (₹)"),
        ("tax_rate", "number", True, "GST rate %"),
        ("gross_amount", "money", True, "Gross excluding GST"),
        ("discount_amount", "money", True, "Discount excluding GST"),
        ("net_amount", "money", True, "Net revenue excluding GST"),
        ("tax_amount", "money", True, "GST"),
        ("line_total", "money", True, "net + GST"),
        ("cogs", "money", True, "Cost of goods sold — " + CALC),
    ]),
    ("CustomerPayments", "customer_payments", "Money received from customers (at the sale or later).", [
        ("id", "id", True, "Receipt ID"),
        ("payment_date", "date", True, "Date received"),
        ("customer_id", "ref:Customers", False, "Customer (blank = walk-in)"),
        ("sale_id", "ref:Sales", False, "Invoice it was received against"),
        ("with_document", "bool", True, "1 = received together with the sale entry"),
        ("amount", "money", True, "Amount"),
        ("method", "choice", True, "Payment method", METHODS),
        ("account", "choice", True, "Received into", ACCOUNTS),
        ("reference", "text", False, "UPI ref / cheque no."),
        ("notes", "text", False, "Notes"),
    ] + VOID_COLS + AUDIT_COLS),
    ("SaleReturns", "sale_returns", "Customer returns against an invoice.", [
        ("id", "id", True, "Return ID"),
        ("return_date", "date", True, "Date returned"),
        ("sale_id", "ref:Sales", True, "Original invoice"),
        ("refund_mode", "choice", True, "How the customer was refunded", ["cash", "bank", "credit"]),
        ("net_amount", "money", True, "Revenue reversed (excl. GST)"),
        ("tax_amount", "money", True, "GST reversed"),
        ("total_refund", "money", True, "Total refunded / credited"),
        ("notes", "text", False, "Reason"),
    ] + VOID_COLS + AUDIT_COLS),
    ("SaleReturnItems", "sale_return_items", "Lines on each return.", [
        ("id", "id", True, "Line ID"),
        ("return_id", "ref:SaleReturns", True, "Return"),
        ("sale_item_id", "ref:SaleItems", True, "Invoice line being returned"),
        ("qty", "qty", True, "Quantity returned"),
        ("restock", "bool", True, "1 = back into stock, 0 = damaged (written off)"),
        ("net_amount", "money", True, "Revenue reversed"),
        ("tax_amount", "money", True, "GST reversed"),
        ("total", "money", True, "Refund for this line"),
        ("cogs_reversed", "money", True, "Cost taken back out of COGS — " + CALC),
    ]),
    ("StockAdjustments", "stock_adjustments", "Damage, loss and stock-count corrections.", [
        ("id", "id", True, "Adjustment ID"),
        ("adj_date", "date", True, "Date"),
        ("variant_id", "ref:Variants", True, "Variant"),
        ("qty", "qty", True, "Change in quantity (negative = reduced)"),
        ("reason", "choice", True, "Reason", ["damaged", "lost", "correction", "other"]),
        ("value", "money", True, "Change in stock value at cost — " + CALC),
        ("notes", "text", False, "Notes"),
    ] + VOID_COLS + AUDIT_COLS),
    ("InventoryMovements", "inventory_movements", "Stock ledger: every unit in or out. " + CALC + ".", [
        ("id", "id", True, "Movement ID"),
        ("move_date", "date", True, "Date"),
        ("variant_id", "ref:Variants", True, "Variant"),
        ("kind", "choice", True, "Movement type", ["opening", "purchase", "sale", "return_in", "adjust"]),
        ("qty", "qty", True, "Quantity (+ in, − out)"),
        ("unit_cost", "money", True, "Cost per unit"),
        ("value", "money", True, "Value at cost (+ in, − out)"),
        ("ref_table", "text", True, "Source tab: opening_stock / purchases / sales / sale_returns / stock_adjustments"),
        ("ref_id", "number", True, "ID of the source record"),
        ("ref_item_id", "number", False, "ID of the source line"),
        ("src_item_id", "number", False, "Sale line ID (for sales and returns)"),
        ("active", "bool", True, "0 = source was voided"),
        ("created_at", "datetime", True, "When written"),
    ]),
    ("ExpenseCategories", "expense_categories", "Expense heads.", [
        ("id", "id", True, "Category ID"),
        ("name", "text", True, "Name, e.g. Shop Rent"),
    ]),
    ("Expenses", "expenses", "Operating expenses (reduce net operating profit).", [
        ("id", "id", True, "Expense ID"),
        ("expense_date", "date", True, "Date"),
        ("category_id", "ref:ExpenseCategories", True, "Expense category"),
        ("amount", "money", True, "Amount"),
        ("method", "choice", True, "Payment method", METHODS),
        ("account", "choice", True, "Paid from", ACCOUNTS),
        ("description", "text", False, "Description"),
        ("recipient", "text", False, "Paid to"),
    ] + VOID_COLS + AUDIT_COLS),
    ("CashTransactions", "cash_transactions",
     "Capital, loans, withdrawals, opening cash/bank, GST payments and transfers. Never revenue or expense.", [
         ("id", "id", True, "Entry ID"),
         ("txn_date", "date", True, "Date"),
         ("kind", "choice", True, "Type of entry", [
             "opening_balance", "initial_investment", "additional_capital", "partner_contribution",
             "owner_withdrawal", "loan_received", "loan_repayment", "tax_payment", "cash_to_bank", "bank_to_cash"]),
         ("amount", "money", True, "Amount"),
         ("account", "choice", True, "Cash or bank account affected (source account for transfers)", ACCOUNTS),
         ("party", "text", False, "Owner / partner / lender name"),
         ("purpose", "choice", True, "What capital was allocated to", ["general", "inventory", "expenses"]),
         ("notes", "text", False, "Notes"),
     ] + VOID_COLS + AUDIT_COLS),
    ("AuditLog", "audit_log", "Every create, update, void and login. Append-only.", [
        ("id", "id", True, "Log ID"),
        ("ts", "datetime", True, "Timestamp (UTC)"),
        ("user_id", "ref:Users", False, "User"),
        ("action", "text", True, "Action, e.g. sale.create, void"),
        ("entity", "text", False, "Table affected"),
        ("entity_id", "number", False, "Record ID"),
        ("details", "json", False, "Details"),
    ]),
]

# xlsx cell formatting for each column type
XLSX_KIND = {"money": "money", "qty": "qty", "number": "qty", "date": "date", "id": "int", "bool": "int"}


def xlsx_kind(col_type):
    if col_type.startswith("ref:"):
        return "int"
    return XLSX_KIND.get(col_type, "text")
