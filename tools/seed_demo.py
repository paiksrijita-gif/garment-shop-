#!/usr/bin/env python3
"""Create a DEMO database full of realistic but fictional transactions.

    python3 tools/seed_demo.py              # writes data/demo.db
    python3 server.py --db data/demo.db --port 8001

Everything goes through the same service layer the app uses, so stock, COGS,
balances and profit are calculated exactly as for real entries. The demo
database is separate from the real one (data/shop.db) and is never used
unless you start the server with --db data/demo.db.

Demo logins (test-only accounts that exist only in demo.db):
    owner:  demo-owner / demo-owner-2026
    staff:  demo-staff / demo-staff-2026
"""
import argparse
import os
import random
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shop import auth, db, metrics, services as S  # noqa: E402
from shop.util import ApiError, today  # noqa: E402

OWNER = ("demo-owner", "demo-owner-2026")
STAFF = ("demo-staff", "demo-staff-2026")
START = date(2026, 5, 1)

SUPPLIERS = [
    # name, phone, city/address, categories, opening balance owed
    ("Surat Silk House (demo)", "9824000101", "Ring Road, Surat, Gujarat", "Sarees, Lehengas, Fabric", 18000),
    ("Jaipur Prints Co. (demo)", "9829000202", "Sanganer, Jaipur, Rajasthan", "Kurtis, Salwar Suits, Dupattas", 0),
    ("Tiruppur Knitwear (demo)", "9843000303", "Avinashi Road, Tiruppur, Tamil Nadu", "T-Shirts, Innerwear", 6500),
    ("Kolkata Handloom (demo)", "9831000404", "Burrabazar, Kolkata, West Bengal", "Sarees", 0),
    ("Delhi Menswear (demo)", "9811000505", "Gandhi Nagar, Delhi", "Shirts, Jeans, Trousers", 0),
    ("Delhi Kids Fashion (demo)", "9811000606", "Karol Bagh, Delhi", "Kids Wear", 0),
]

# name, category, unit, sizes, colours, designs, cost, retail, wholesale, supplier indexes, demand weight
PRODUCTS = [
    ("Cotton Kurti Floral D-101", "Kurtis", "piece", ["S", "M", "L", "XL"], ["Blue", "Maroon"], [], 380, 799, 560, [1], 9),
    ("Rayon Kurti Plain D-215", "Kurtis", "piece", ["M", "L", "XL", "XXL"], ["Black", "Mustard"], [], 320, 699, 490, [1, 0], 8),
    ("Banarasi Silk Saree", "Sarees", "piece", [], ["Red", "Green"], ["Zari", "Butta"], 2200, 4499, 3200, [0, 3], 2),
    ("Georgette Printed Saree", "Sarees", "piece", [], [], [], 650, 1299, 899, [0], 5),
    ("Cotton Tant Saree", "Sarees", "piece", [], [], [], 520, 999, 720, [3], 4),
    ("Chanderi Salwar Suit", "Salwar Suits", "set", [], ["Peach", "Teal"], [], 900, 1899, 1350, [1], 3),
    ("Bridal Lehenga", "Lehengas", "set", ["M", "L"], [], [], 6500, 12999, 9500, [0], 0.4),
    ("Men's Formal Shirt", "Shirts", "piece", ["38", "40", "42", "44"], ["White", "Sky"], [], 380, 899, 560, [4], 6),
    ("Round-neck Cotton Tee", "T-Shirts", "piece", ["S", "M", "L", "XL"], ["Black", "White", "Navy"], [], 140, 349, 220, [2], 12),
    ("Men's Slim Jeans", "Jeans", "piece", ["30", "32", "34", "36"], [], [], 520, 1299, 850, [4], 5),
    ("Kids Frock", "Kids Wear", "piece", ["2-3Y", "4-5Y", "6-7Y"], ["Pink", "Yellow"], [], 260, 599, 400, [5], 5),
    ("Boys T-shirt & Shorts Set", "Kids Wear", "set", ["4Y", "6Y", "8Y"], [], [], 220, 499, 330, [5], 4),
    ("Men's Cotton Vest", "Innerwear", "piece", ["85", "90", "95", "100"], [], [], 75, 169, 110, [2], 6),
    ("Phulkari Dupatta", "Dupattas", "piece", [], ["Pink", "Orange", "Green"], [], 180, 449, 300, [1], 4),
    ("Cotton Suiting Fabric", "Fabric", "metre", [], ["Grey", "Navy"], [], 120, 220, 170, [0], 3),
    ("Men's Chino Trousers", "Trousers", "piece", ["30", "32", "34", "36"], ["Khaki", "Olive"], [], 450, 1099, 720, [4], 3),
]

WHOLESALE_BUYERS = [
    ("Sharma Cloth Store (demo)", "9876500011"), ("New Fashion Point (demo)", "9876500022"),
    ("Gupta Garments (demo)", "9876500033"), ("Laxmi Saree Centre (demo)", "9876500044"),
    ("Royal Kids Corner (demo)", "9876500055"),
]


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def gst_for(price):
    # Indicative garment GST slabs: 5% up to ₹1,000 per piece, 12% above.
    return 5 if price <= 1000 else 12


class Demo:
    def __init__(self, path, seed):
        self.rnd = random.Random(seed)
        self.conn = db.init_db(path)
        self.end = date.fromisoformat(today())

    def user(self, username):
        return self.conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def run(self):
        c, r = self.conn, self.rnd
        auth.create_owner(c, {"shop_name": "DEMO Sample Garments (test data)", "full_name": "Demo Owner",
                              "username": OWNER[0], "password": OWNER[1]})
        self.owner = self.user(OWNER[0])
        auth.save_user(c, self.owner, {"full_name": "Demo Staff (Asha)", "username": STAFF[0], "password": STAFF[1],
                                       "permissions": auth.DEFAULT_STAFF_PERMISSIONS})
        self.staff = self.user(STAFF[0])
        S.update_settings(c, self.owner, {"opening_date": START.isoformat(), "default_tax_rate": "5",
                                          "prices_include_tax": "1", "invoice_prefix": "DEMO"})
        cats = {row["name"]: row["id"] for row in c.execute("SELECT id, name FROM categories")}
        ecats = {row["name"]: row["id"] for row in c.execute("SELECT id, name FROM expense_categories")}
        self.ecats = ecats

        # money in at the start
        d0 = START.isoformat()
        self.cash("opening_balance", 25000, "cash", d0, notes="Opening cash (demo)")
        self.cash("opening_balance", 150000, "bank", d0, notes="Opening bank (demo)")
        self.cash("initial_investment", 500000, "bank", d0, party="Demo Owner", purpose="inventory")

        self.suppliers = []
        for name, phone, addr, cats_txt, ob in SUPPLIERS:
            self.suppliers.append(S.save_supplier(c, self.owner, {
                "name": name, "phone": phone, "address": addr, "categories": cats_txt, "opening_balance": ob}))

        # the first buyer already owed ₹8,500 before the shop started using the app
        self.customers = [S.save_customer(c, self.owner, {"name": n, "phone": p, "kind": "wholesale",
                                                          "opening_balance": 8500 if i == 0 else 0})
                          for i, (n, p) in enumerate(WHOLESALE_BUYERS)]

        # products & variants
        self.items = []  # dicts per variant
        for (name, cat, unit, sizes, colours, designs, cost, retail, whole, sups, weight) in PRODUCTS:
            variants = [{"size": s_, "colour": c_, "design": d_, "retail_price": retail, "wholesale_price": whole}
                        for s_ in (sizes or [""]) for c_ in (colours or [""]) for d_ in (designs or [""])]
            has_var = len(variants) > 1 or bool(variants[0]["size"] or variants[0]["colour"] or variants[0]["design"])
            data = {"name": name, "category_id": cats[cat], "unit": unit, "has_variants": has_var,
                    "low_stock_level": 3 if cost < 2000 else 1}
            if has_var:
                data["variants"] = variants
            else:
                data.update(retail_price=retail, wholesale_price=whole)
            pid = S.save_product(c, self.owner, data)
            for v in c.execute("SELECT id FROM variants WHERE product_id = ?", (pid,)):
                self.items.append({"vid": v["id"], "cost": cost, "retail": retail, "whole": whole,
                                   "sups": [self.suppliers[i] for i in sups], "weight": weight / max(1, len(variants)) * 4,
                                   "unit": unit})

        # opening stock
        lines = []
        for it in self.items:
            q = r.randint(3, 10) if it["cost"] < 2000 else r.randint(1, 2)
            lines.append({"variant_id": it["vid"], "qty": q, "unit_cost": round(it["cost"] * r.uniform(0.94, 0.99), 2),
                          "supplier_id": it["sups"][0]})
        S.add_opening_stock(c, self.owner, {"entry_date": d0, "items": lines})

        self.bill_no = 1000
        self.pending_returns = []  # (date, sale_id, refund_mode)
        for d in daterange(START, self.end):
            self.day(d)
        S.update_settings(c, self.owner, {"setup_complete": True})
        return self

    # ---------------------------------------------------------------- helpers
    def cash(self, kind, amount, account, d, party="", purpose="general", notes=""):
        S.create_cash_txn(self.conn, self.owner, {"kind": kind, "amount": amount, "account": account, "txn_date": d,
                                                  "party": party, "purpose": purpose, "notes": notes})

    def expense(self, cat, amount, d, method, desc, recipient=""):
        S.create_expense(self.conn, self.owner, {"expense_date": d, "category_id": self.ecats[cat], "amount": round(amount),
                                                 "method": method, "description": desc, "recipient": recipient})

    def stock(self, vid):
        return self.conn.execute("SELECT stock_qty FROM variants WHERE id = ?", (vid,)).fetchone()[0]

    def pick(self, k, min_stock=1):
        pool = [it for it in self.items if self.stock(it["vid"]) >= min_stock]
        if not pool:
            return []
        chosen = []
        for _ in range(k):
            it = self.rnd.choices(pool, weights=[p["weight"] for p in pool])[0]
            if it not in chosen:
                chosen.append(it)
        return chosen

    def festive(self, d):
        # demand lift for Navratri / Diwali season and weekends
        lift = 1.0
        if date(2026, 10, 1) <= d <= date(2026, 11, 10):
            lift = 1.8
        if d.weekday() >= 5:
            lift *= 1.5
        return lift

    # ---------------------------------------------------------------- one day
    def day(self, d):
        c, r, ds = self.conn, self.rnd, d.isoformat()

        # customer returns that come back today
        for due, sid, mode in [x for x in self.pending_returns if x[0] == d]:
            line = S.get_sale(c, self.owner, sid)["items"][0]
            S.create_return(c, self.owner, sid, {
                "return_date": ds, "refund_mode": mode,
                "notes": r.choice(["Size issue", "Colour not liked", "Stitching defect"]),
                "items": [{"sale_item_id": line["id"], "qty": 1, "restock": r.random() < 0.8}]})
        self.pending_returns = [x for x in self.pending_returns if x[0] != d]

        # monthly fixed costs and capital movements
        if d.day == 1 and d > START:
            self.expense("Salaries", 15000, ds, "Bank Transfer", "Salary — senior salesperson", "Asha")
            self.expense("Salaries", 12000, ds, "Bank Transfer", "Salary — helper", "Ravi")
            self.cash("owner_withdrawal", 20000, "bank", ds, party="Demo Owner", notes="Monthly drawings")
            prev_end = d - timedelta(days=1)
            gst = c.execute("SELECT COALESCE(SUM(tax_amount), 0) FROM sales WHERE status = 'final' AND sale_date BETWEEN ? AND ?",
                            (prev_end.replace(day=1).isoformat(), prev_end.isoformat())).fetchone()[0]
            if gst > 0:
                self.cash("tax_payment", round(gst), "bank", ds, notes="GST for %s" % prev_end.strftime("%b %Y"))
        if d.day == 5:
            self.expense("Shop Rent", 35000, ds, "Bank Transfer", "Shop rent %s" % d.strftime("%b"), "Landlord (demo)")
        if d.day == 10:
            self.expense("Electricity", r.randint(3200, 5600), ds, "UPI", "Electricity bill")
            self.expense("Telephone & Internet", 799, ds, "UPI", "Broadband")
        if d.day in (3, 18):
            self.expense("Packaging", r.randint(1200, 2600), ds, "Cash", "Carry bags & boxes")
        if d.weekday() == 0:
            self.expense("Transportation", r.randint(300, 900), ds, "Cash", "Local delivery / auto")
        if r.random() < 0.03:
            self.expense("Repairs & Maintenance", r.randint(800, 4500), ds, "Cash", "Shop repairs")
        if d == date(2026, 6, 15):
            self.cash("loan_received", 300000, "bank", ds, party="Demo Bank Ltd", purpose="inventory", notes="Working capital loan")
        if d.day == 15 and d > date(2026, 6, 30):
            self.cash("loan_repayment", 15000, "bank", ds, party="Demo Bank Ltd")
            self.expense("Loan Interest", 2600, ds, "Bank Transfer", "Loan interest", "Demo Bank Ltd")
        if d == date(2026, 7, 10):
            self.cash("partner_contribution", 200000, "bank", ds, party="Demo Partner", purpose="inventory")
        if d.weekday() == 4:  # Friday: bank the cash above a ₹25,000 float
            spare = metrics.account_balances(c)["cash"] - 25000
            if spare > 10000:
                self.cash("cash_to_bank", round(spare, -3), "cash", ds, notes="Weekly cash deposit")

        # restock: each supplier checks every 9-12 days what is running low
        if (d - START).days % 10 == 2:
            for sid in self.suppliers:
                self.restock(sid, d)

        # pay suppliers on Saturdays
        if d.weekday() == 5:
            for sid in self.suppliers:
                out = S.get_supplier(c, sid)["outstanding"]
                if out > 5000 and r.random() < 0.6:
                    amt = round(out * r.uniform(0.4, 0.9), -2)
                    S.create_supplier_payment(c, self.owner, {"payment_date": ds, "supplier_id": sid, "amount": amt,
                                                              "method": r.choice(["Bank Transfer", "UPI", "Cheque"])})

        # retail sales
        n = int(r.uniform(2, 6) * self.festive(d))
        for _ in range(n):
            self.retail_sale(d)

        # wholesale: any day of the week, about 3 a week
        if r.random() < 0.42:
            self.wholesale_sale(d)

        # collect from wholesale customers on Mondays and Thursdays
        if d.weekday() in (0, 3):
            for cid in self.customers:
                out = S.get_customer(c, cid)["outstanding"]
                if out > 2000 and r.random() < 0.5:
                    S.create_customer_payment(c, self.owner, {"payment_date": ds, "customer_id": cid,
                                                              "amount": round(out * r.uniform(0.5, 1.0), -1),
                                                              "method": r.choice(["Bank Transfer", "UPI", "Cheque"])})

        # occasional damage found during stock check
        if r.random() < 0.05:
            its = self.pick(1, 2)
            if its:
                S.create_adjustment(c, self.owner, {"adj_date": ds, "variant_id": its[0]["vid"], "qty": 1, "direction": "out",
                                                    "reason": r.choice(["damaged", "damaged", "lost"]),
                                                    "notes": "Found during stock check (demo)"})

    def restock(self, sid, d):
        c, r = self.conn, self.rnd
        lines = []
        drift = 1 + (d - START).days / 365 * 0.06  # mild cost inflation
        for it in self.items:
            if sid not in it["sups"]:
                continue
            target = 4 if it["cost"] >= 2000 else int(6 + it["weight"] * 3)
            have = self.stock(it["vid"])
            if have < target * 0.6:
                q = max(1, int(target * r.uniform(1.4, 2.2) - have))
                lines.append({"variant_id": it["vid"], "qty": q,
                              "unit_price": round(it["cost"] * drift * r.uniform(0.96, 1.05), 0)})
        if not lines:
            return
        value = sum(l["qty"] * l["unit_price"] for l in lines)
        self.bill_no += 1
        paid_share = r.choice([0, 0.3, 0.5, 1.0])
        add = round(value * r.uniform(0.008, 0.02))
        disc = round(value * 0.02) if r.random() < 0.25 else 0
        total = value + add - disc
        S.create_purchase(c, self.owner, {
            "purchase_date": d.isoformat(), "supplier_id": sid, "invoice_no": "SB-%d" % self.bill_no,
            "additional_cost": add, "additional_note": "Transport / courier", "discount": disc,
            "amount_paid": round(total * paid_share, -1) if paid_share < 1 else total,
            "payment_method": r.choice(["Bank Transfer", "UPI"]), "items": lines,
            "notes": "Demo purchase"})

    def retail_sale(self, d):
        c, r = self.conn, self.rnd
        its = self.pick(r.choices([1, 2, 3], weights=[6, 3, 1])[0])
        if not its:
            return
        items = []
        for it in its:
            q = 1 if r.random() < 0.8 else 2
            if it["unit"] == "metre":
                q = r.choice([2, 2.5, 3, 4])
            q = min(q, self.stock(it["vid"]))
            if q <= 0:
                continue
            disc = round(it["retail"] * q * r.choice([0.05, 0.1])) if r.random() < 0.2 else 0
            items.append({"variant_id": it["vid"], "qty": q, "unit_price": it["retail"], "discount": disc,
                          "tax_rate": gst_for(it["retail"])})
        if not items:
            return
        method = r.choices(["Cash", "UPI", "Card"], weights=[45, 45, 10])[0]
        staff = r.choice([self.owner["id"], self.staff["id"]])
        sid = S.create_sale(c, self.owner, {"sale_date": d.isoformat(), "channel": "retail", "tax_inclusive": True,
                                            "payment_method": method, "items": items, "staff_user_id": staff})
        if r.random() < 0.03:
            back = d + timedelta(days=r.randint(1, 3))
            if back <= self.end:
                self.pending_returns.append((back, sid, "cash" if method == "Cash" else "bank"))

    def wholesale_sale(self, d):
        c, r = self.conn, self.rnd
        its = self.pick(r.randint(2, 4), min_stock=4)
        items = []
        for it in its:
            have = self.stock(it["vid"])
            q = min(int(have * r.uniform(0.3, 0.6)), r.randint(4, 12))
            if q < 2:
                continue
            items.append({"variant_id": it["vid"], "qty": q, "unit_price": it["whole"], "discount": 0, "tax_rate": 5})
        if not items:
            return
        total = sum(i["qty"] * i["unit_price"] for i in items) * 1.05
        share = r.choice([0.4, 0.5, 0.75, 1.0, 1.0])
        try:
            S.create_sale(c, self.owner, {
                "sale_date": d.isoformat(), "channel": "wholesale", "tax_inclusive": False,
                "customer_id": r.choice(self.customers), "items": items,
                "amount_received": round(total * share, -1) if share < 1 else None,
                "payment_method": r.choice(["Bank Transfer", "UPI", "Cash"]),
                "staff_user_id": self.owner["id"], "notes": "Demo wholesale order"})
        except ApiError:
            pass


def main():
    ap = argparse.ArgumentParser(description="Create a demo database with fictional test data")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "demo.db"))
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--force", action="store_true", help="replace an existing demo database")
    args = ap.parse_args()
    path = os.path.abspath(args.db)
    if os.path.basename(path) == "shop.db":
        sys.exit("Refusing to write demo data into shop.db — that is your real database.")
    if os.path.exists(path):
        if not args.force:
            sys.exit("%s already exists. Use --force to rebuild it." % path)
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print("Building demo data from %s to %s …" % (START.strftime("%d-%m-%Y"), "-".join(reversed(today().split("-")))))
    demo = Demo(path, args.seed).run()
    c = demo.conn
    count = lambda t: c.execute("SELECT COUNT(*) FROM %s WHERE status = 'final'" % t).fetchone()[0]
    print("Done: %d sales, %d purchases, %d expenses, %d returns." % (
        count("sales"), count("purchases"), count("expenses"), count("sale_returns")))
    print("Database: %s" % path)
    print("Start it:  python3 server.py --db %s --port 8001" % os.path.relpath(path, ROOT))
    print("Logins are listed at the top of tools/seed_demo.py.")


if __name__ == "__main__":
    main()
