"""SQLite schema, connections and transaction helpers."""
import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  full_name     TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('owner', 'staff')),
  password_hash TEXT NOT NULL,
  permissions   TEXT NOT NULL DEFAULT '[]',
  active        INTEGER NOT NULL DEFAULT 1,
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until  TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id        INTEGER PRIMARY KEY,
  ts        TEXT NOT NULL DEFAULT (datetime('now')),
  user_id   INTEGER REFERENCES users(id),
  action    TEXT NOT NULL,
  entity    TEXT,
  entity_id INTEGER,
  details   TEXT
);

CREATE TABLE IF NOT EXISTS categories (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS suppliers (
  id              INTEGER PRIMARY KEY,
  code            TEXT NOT NULL UNIQUE,
  name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
  phone           TEXT NOT NULL DEFAULT '',
  address         TEXT NOT NULL DEFAULT '',
  gstin           TEXT NOT NULL DEFAULT '',
  categories      TEXT NOT NULL DEFAULT '',
  opening_balance REAL NOT NULL DEFAULT 0,
  notes           TEXT NOT NULL DEFAULT '',
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  phone           TEXT NOT NULL DEFAULT '',
  address         TEXT NOT NULL DEFAULT '',
  kind            TEXT NOT NULL DEFAULT 'retail' CHECK (kind IN ('retail', 'wholesale')),
  opening_balance REAL NOT NULL DEFAULT 0,
  notes           TEXT NOT NULL DEFAULT '',
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (name COLLATE NOCASE, phone)
);

CREATE TABLE IF NOT EXISTS products (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
  category_id     INTEGER NOT NULL REFERENCES categories(id),
  unit            TEXT NOT NULL DEFAULT 'piece',
  has_variants    INTEGER NOT NULL DEFAULT 0,
  low_stock_level REAL NOT NULL DEFAULT 5,
  description     TEXT NOT NULL DEFAULT '',
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Stock is always held at variant level. A "simple" product has one variant
-- with blank size/colour/design.
CREATE TABLE IF NOT EXISTS variants (
  id              INTEGER PRIMARY KEY,
  product_id      INTEGER NOT NULL REFERENCES products(id),
  sku             TEXT NOT NULL UNIQUE COLLATE NOCASE,
  size            TEXT NOT NULL DEFAULT '',
  colour          TEXT NOT NULL DEFAULT '',
  design          TEXT NOT NULL DEFAULT '',
  retail_price    REAL NOT NULL DEFAULT 0,
  wholesale_price REAL NOT NULL DEFAULT 0,
  stock_qty       REAL NOT NULL DEFAULT 0,
  stock_value     REAL NOT NULL DEFAULT 0,
  active          INTEGER NOT NULL DEFAULT 1,
  UNIQUE (product_id, size, colour, design)
);

CREATE TABLE IF NOT EXISTS purchases (
  id              INTEGER PRIMARY KEY,
  purchase_date   TEXT NOT NULL,
  supplier_id     INTEGER NOT NULL REFERENCES suppliers(id),
  invoice_no      TEXT NOT NULL,
  subtotal        REAL NOT NULL,
  additional_cost REAL NOT NULL DEFAULT 0,
  additional_note TEXT NOT NULL DEFAULT '',
  discount        REAL NOT NULL DEFAULT 0,
  total_cost      REAL NOT NULL,
  amount_paid     REAL NOT NULL DEFAULT 0,
  notes           TEXT NOT NULL DEFAULT '',
  status          TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason     TEXT,
  voided_by       INTEGER REFERENCES users(id),
  voided_at       TEXT,
  client_ref      TEXT UNIQUE,
  created_by      INTEGER REFERENCES users(id),
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_purchase_invoice
  ON purchases (supplier_id, invoice_no COLLATE NOCASE) WHERE status = 'final';

CREATE TABLE IF NOT EXISTS purchase_items (
  id               INTEGER PRIMARY KEY,
  purchase_id      INTEGER NOT NULL REFERENCES purchases(id),
  variant_id       INTEGER NOT NULL REFERENCES variants(id),
  qty              REAL NOT NULL CHECK (qty > 0),
  unit_price       REAL NOT NULL CHECK (unit_price >= 0),
  line_amount      REAL NOT NULL,
  allocated_cost   REAL NOT NULL DEFAULT 0,
  landed_value     REAL NOT NULL,
  landed_unit_cost REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_payments (
  id           INTEGER PRIMARY KEY,
  payment_date TEXT NOT NULL,
  supplier_id  INTEGER NOT NULL REFERENCES suppliers(id),
  purchase_id  INTEGER REFERENCES purchases(id),
  with_document INTEGER NOT NULL DEFAULT 0,
  amount       REAL NOT NULL CHECK (amount > 0),
  method       TEXT NOT NULL,
  account      TEXT NOT NULL CHECK (account IN ('cash', 'bank')),
  reference    TEXT NOT NULL DEFAULT '',
  notes        TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason  TEXT,
  voided_by    INTEGER REFERENCES users(id),
  voided_at    TEXT,
  client_ref   TEXT UNIQUE,
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sales (
  id              INTEGER PRIMARY KEY,
  sale_date       TEXT NOT NULL,
  invoice_no      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  channel         TEXT NOT NULL CHECK (channel IN ('retail', 'wholesale')),
  customer_id     INTEGER REFERENCES customers(id),
  customer_name   TEXT NOT NULL DEFAULT '',
  tax_inclusive   INTEGER NOT NULL DEFAULT 0,
  gross_amount    REAL NOT NULL,
  discount_amount REAL NOT NULL,
  net_amount      REAL NOT NULL,
  tax_amount      REAL NOT NULL,
  total_amount    REAL NOT NULL,
  amount_received REAL NOT NULL DEFAULT 0,
  payment_method  TEXT NOT NULL DEFAULT '',
  staff_user_id   INTEGER REFERENCES users(id),
  notes           TEXT NOT NULL DEFAULT '',
  status          TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason     TEXT,
  voided_by       INTEGER REFERENCES users(id),
  voided_at       TEXT,
  client_ref      TEXT UNIQUE,
  created_by      INTEGER REFERENCES users(id),
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Amounts on a line: gross/discount/net are excluding tax.
CREATE TABLE IF NOT EXISTS sale_items (
  id              INTEGER PRIMARY KEY,
  sale_id         INTEGER NOT NULL REFERENCES sales(id),
  variant_id      INTEGER NOT NULL REFERENCES variants(id),
  qty             REAL NOT NULL CHECK (qty > 0),
  unit_price      REAL NOT NULL CHECK (unit_price >= 0),
  discount        REAL NOT NULL DEFAULT 0,
  tax_rate        REAL NOT NULL DEFAULT 0,
  gross_amount    REAL NOT NULL,
  discount_amount REAL NOT NULL,
  net_amount      REAL NOT NULL,
  tax_amount      REAL NOT NULL,
  line_total      REAL NOT NULL,
  cogs            REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customer_payments (
  id           INTEGER PRIMARY KEY,
  payment_date TEXT NOT NULL,
  customer_id  INTEGER REFERENCES customers(id),
  sale_id      INTEGER REFERENCES sales(id),
  with_document INTEGER NOT NULL DEFAULT 0,
  amount       REAL NOT NULL CHECK (amount > 0),
  method       TEXT NOT NULL,
  account      TEXT NOT NULL CHECK (account IN ('cash', 'bank')),
  reference    TEXT NOT NULL DEFAULT '',
  notes        TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason  TEXT,
  voided_by    INTEGER REFERENCES users(id),
  voided_at    TEXT,
  client_ref   TEXT UNIQUE,
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sale_returns (
  id           INTEGER PRIMARY KEY,
  return_date  TEXT NOT NULL,
  sale_id      INTEGER NOT NULL REFERENCES sales(id),
  refund_mode  TEXT NOT NULL CHECK (refund_mode IN ('cash', 'bank', 'credit')),
  net_amount   REAL NOT NULL,
  tax_amount   REAL NOT NULL,
  total_refund REAL NOT NULL,
  notes        TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason  TEXT,
  voided_by    INTEGER REFERENCES users(id),
  voided_at    TEXT,
  client_ref   TEXT UNIQUE,
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sale_return_items (
  id            INTEGER PRIMARY KEY,
  return_id     INTEGER NOT NULL REFERENCES sale_returns(id),
  sale_item_id  INTEGER NOT NULL REFERENCES sale_items(id),
  qty           REAL NOT NULL CHECK (qty > 0),
  restock       INTEGER NOT NULL DEFAULT 1,
  net_amount    REAL NOT NULL,
  tax_amount    REAL NOT NULL,
  total         REAL NOT NULL,
  cogs_reversed REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_adjustments (
  id         INTEGER PRIMARY KEY,
  adj_date   TEXT NOT NULL,
  variant_id INTEGER NOT NULL REFERENCES variants(id),
  qty        REAL NOT NULL CHECK (qty <> 0),
  reason     TEXT NOT NULL CHECK (reason IN ('damaged', 'lost', 'correction', 'other')),
  value      REAL NOT NULL DEFAULT 0,
  notes      TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason TEXT,
  voided_by  INTEGER REFERENCES users(id),
  voided_at  TEXT,
  client_ref TEXT UNIQUE,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS opening_stock (
  id          INTEGER PRIMARY KEY,
  entry_date  TEXT NOT NULL,
  variant_id  INTEGER NOT NULL REFERENCES variants(id),
  supplier_id INTEGER REFERENCES suppliers(id),
  qty         REAL NOT NULL CHECK (qty > 0),
  unit_cost   REAL NOT NULL CHECK (unit_cost >= 0),
  value       REAL NOT NULL,
  notes       TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason TEXT,
  voided_by   INTEGER REFERENCES users(id),
  voided_at   TEXT,
  client_ref  TEXT UNIQUE,
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The stock ledger. Inbound opening/purchase rows carry a fixed value; the cost
-- of every other row is recomputed by ledger.recost_variant() using the
-- configured costing method (weighted average or FIFO).
CREATE TABLE IF NOT EXISTS inventory_movements (
  id          INTEGER PRIMARY KEY,
  move_date   TEXT NOT NULL,
  variant_id  INTEGER NOT NULL REFERENCES variants(id),
  kind        TEXT NOT NULL CHECK (kind IN ('opening', 'purchase', 'sale', 'return_in', 'adjust')),
  qty         REAL NOT NULL,
  unit_cost   REAL NOT NULL DEFAULT 0,
  value       REAL NOT NULL DEFAULT 0,
  ref_table   TEXT NOT NULL,
  ref_id      INTEGER NOT NULL,
  ref_item_id INTEGER,
  src_item_id INTEGER,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_moves_variant ON inventory_movements (variant_id, move_date, id);
CREATE INDEX IF NOT EXISTS ix_moves_ref ON inventory_movements (ref_table, ref_id);

CREATE TABLE IF NOT EXISTS expense_categories (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS expenses (
  id           INTEGER PRIMARY KEY,
  expense_date TEXT NOT NULL,
  category_id  INTEGER NOT NULL REFERENCES expense_categories(id),
  amount       REAL NOT NULL CHECK (amount > 0),
  method       TEXT NOT NULL,
  account      TEXT NOT NULL CHECK (account IN ('cash', 'bank')),
  description  TEXT NOT NULL DEFAULT '',
  recipient    TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason  TEXT,
  voided_by    INTEGER REFERENCES users(id),
  voided_at    TEXT,
  client_ref   TEXT UNIQUE,
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Capital, loans, opening cash/bank balances, tax payments and transfers.
-- None of these are revenue or expense.
CREATE TABLE IF NOT EXISTS cash_transactions (
  id          INTEGER PRIMARY KEY,
  txn_date    TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN (
                'opening_balance', 'initial_investment', 'additional_capital',
                'partner_contribution', 'owner_withdrawal', 'loan_received',
                'loan_repayment', 'tax_payment', 'cash_to_bank', 'bank_to_cash')),
  amount      REAL NOT NULL CHECK (amount > 0),
  account     TEXT NOT NULL CHECK (account IN ('cash', 'bank')),
  party       TEXT NOT NULL DEFAULT '',
  purpose     TEXT NOT NULL DEFAULT 'general' CHECK (purpose IN ('general', 'inventory', 'expenses')),
  notes       TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'final' CHECK (status IN ('final', 'void')),
  void_reason TEXT,
  voided_by   INTEGER REFERENCES users(id),
  voided_at   TEXT,
  client_ref  TEXT UNIQUE,
  created_by  INTEGER REFERENCES users(id),
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_sales_date ON sales (sale_date);
CREATE INDEX IF NOT EXISTS ix_sale_items_sale ON sale_items (sale_id);
CREATE INDEX IF NOT EXISTS ix_sale_items_variant ON sale_items (variant_id);
CREATE INDEX IF NOT EXISTS ix_purchases_date ON purchases (purchase_date);
CREATE INDEX IF NOT EXISTS ix_purchase_items_purchase ON purchase_items (purchase_id);
CREATE INDEX IF NOT EXISTS ix_expenses_date ON expenses (expense_date);
CREATE INDEX IF NOT EXISTS ix_returns_sale ON sale_returns (sale_id);
"""

DEFAULT_SETTINGS = {
    "shop_name": "My Garment Shop",
    "costing_method": "WAC",
    "default_tax_rate": "5",
    "prices_include_tax": "1",
    "low_stock_default": "5",
    "invoice_prefix": "INV",
    "setup_complete": "0",
    "opening_date": "",
    "opening_capital": "0",
}

DEFAULT_CATEGORIES = [
    "Sarees", "Kurtis", "Salwar Suits", "Lehengas", "Shirts", "T-Shirts",
    "Trousers", "Jeans", "Kids Wear", "Innerwear", "Dupattas", "Fabric",
]

DEFAULT_EXPENSE_CATEGORIES = [
    "Shop Rent", "Salaries", "Electricity", "Transportation", "Packaging",
    "Repairs & Maintenance", "Loan Interest", "Telephone & Internet",
    "Bank Charges", "Marketing", "Other",
]


def connect(path):
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(path):
    conn = connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    with tx(conn):
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
        if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            conn.executemany("INSERT INTO categories (name) VALUES (?)", [(c,) for c in DEFAULT_CATEGORIES])
        if conn.execute("SELECT COUNT(*) FROM expense_categories").fetchone()[0] == 0:
            conn.executemany("INSERT INTO expense_categories (name) VALUES (?)",
                             [(c,) for c in DEFAULT_EXPENSE_CATEGORIES])
    return conn


@contextmanager
def tx(conn):
    """Run a block inside a write transaction (BEGIN IMMEDIATE ... COMMIT)."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key)


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def one(cur):
    r = cur.fetchone()
    return dict(r) if r else None
