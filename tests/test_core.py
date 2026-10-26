"""Tests for the database, purchase/sales entry, inventory costing and profit
formulas. Run:  python3 -m unittest discover -s tests -v

All figures here are synthetic test fixtures in a throwaway database."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shop import auth, db, metrics, reports, services as S, xlsx  # noqa: E402
from shop.util import ApiError, today  # noqa: E402

D1, D2, D3, D4 = "2025-04-01", "2025-04-05", "2025-04-10", "2025-04-15"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.init_db(os.path.join(self.tmp.name, "t.db"))
        auth.create_owner(self.conn, {"full_name": "Owner", "username": "owner", "password": "secret123",
                                      "shop_name": "Test Shop"})
        self.owner = self.conn.execute("SELECT * FROM users WHERE username='owner'").fetchone()
        self.cat = self.conn.execute("SELECT id FROM categories WHERE name='Kurtis'").fetchone()[0]
        self.cat2 = self.conn.execute("SELECT id FROM categories WHERE name='Sarees'").fetchone()[0]
        self.sup = S.save_supplier(self.conn, self.owner, {"name": "Supplier A", "phone": "9800000001"})
        self.sup2 = S.save_supplier(self.conn, self.owner, {"name": "Supplier B"})
        self.pid = S.save_product(self.conn, self.owner, {"name": "Kurti K1", "category_id": self.cat,
                                                          "retail_price": 500, "wholesale_price": 400})
        self.v = self.conn.execute("SELECT id FROM variants WHERE product_id=?", (self.pid,)).fetchone()[0]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def stock(self, vid=None):
        r = self.conn.execute("SELECT stock_qty, stock_value FROM variants WHERE id=?", (vid or self.v,)).fetchone()
        return r[0], r[1]

    def buy(self, qty, price, date=D1, sup=None, inv=None, vid=None, add=0, disc=0, paid=0):
        return S.create_purchase(self.conn, self.owner, {
            "purchase_date": date, "supplier_id": sup or self.sup, "invoice_no": inv or "B-%s-%s" % (date, qty),
            "additional_cost": add, "discount": disc, "amount_paid": paid,
            "payment_method": "Cash" if paid else None,
            "items": [{"variant_id": vid or self.v, "qty": qty, "unit_price": price}]})

    def sell(self, qty, price, date=D2, channel="retail", vid=None, tax=0, inclusive=False, disc=0, **kw):
        data = {"sale_date": date, "channel": channel, "tax_inclusive": inclusive,
                "payment_method": "Cash",
                "items": [{"variant_id": vid or self.v, "qty": qty, "unit_price": price, "tax_rate": tax,
                           "discount": disc}]}
        data.update(kw)
        return S.create_sale(self.conn, self.owner, data)


class PurchaseTests(Base):
    def test_total_purchase_cost_formula(self):
        # Total = qty × price + additional − discount = 10×100 + 50 − 30 = 1020
        pid = self.buy(10, 100, add=50, disc=30, paid=500)
        p = S.get_purchase(self.conn, self.owner, pid)
        self.assertEqual(p["subtotal"], 1000)
        self.assertEqual(p["total_cost"], 1020)
        self.assertEqual(p["items"][0]["landed_unit_cost"], 102)
        self.assertEqual(self.stock(), (10, 1020))
        s = S.get_supplier(self.conn, self.sup)
        self.assertEqual(s["total_purchases"], 1020)
        self.assertEqual(s["total_paid"], 500)
        self.assertEqual(s["outstanding"], 520)
        self.assertEqual(s["total_units"], 10)

    def test_additional_cost_allocated_across_lines(self):
        v2 = S.add_variants(self.conn, self.owner, self.pid, {"variants": [{"size": "XL"}]})[0]
        sub, total, allocs = S.purchase_total([(10, 100), (5, 200)], 100, 0)
        self.assertEqual((sub, total), (2000, 2100))
        self.assertEqual([a[1] for a in allocs], [50, 50])
        S.create_purchase(self.conn, self.owner, {
            "purchase_date": D1, "supplier_id": self.sup, "invoice_no": "X1", "additional_cost": 100,
            "items": [{"variant_id": self.v, "qty": 10, "unit_price": 100},
                      {"variant_id": v2, "qty": 5, "unit_price": 200}]})
        self.assertEqual(self.stock(), (10, 1050))
        self.assertEqual(self.stock(v2), (5, 1050))

    def test_duplicate_invoice_rejected(self):
        self.buy(5, 100, inv="DUP-1")
        with self.assertRaises(ApiError) as cm:
            self.buy(5, 100, inv="dup-1")
        self.assertEqual(cm.exception.status, 409)
        # same invoice number from a different supplier is fine
        self.buy(5, 100, inv="DUP-1", sup=self.sup2)

    def test_client_ref_idempotent(self):
        data = {"purchase_date": D1, "supplier_id": self.sup, "invoice_no": "I-1", "client_ref": "abc",
                "items": [{"variant_id": self.v, "qty": 1, "unit_price": 10}]}
        S.create_purchase(self.conn, self.owner, data)
        with self.assertRaises(ApiError):
            S.create_purchase(self.conn, self.owner, dict(data, invoice_no="I-2"))
        self.assertEqual(self.stock()[0], 1)

    def test_validation(self):
        for bad in ({"qty": 0}, {"qty": -2}, {"unit_price": -1}, {"variant_id": 999}):
            item = dict({"variant_id": self.v, "qty": 1, "unit_price": 10}, **bad)
            with self.assertRaises(ApiError):
                S.create_purchase(self.conn, self.owner, {"purchase_date": D1, "supplier_id": self.sup,
                                                          "invoice_no": "V", "items": [item]})
        with self.assertRaises(ApiError):  # paid more than total
            self.buy(1, 10, paid=11)
        with self.assertRaises(ApiError):  # future date
            self.buy(1, 10, date="2999-01-01")
        self.assertEqual(self.stock(), (0, 0))

    def test_multiple_suppliers_same_product(self):
        self.buy(10, 100, sup=self.sup)
        self.buy(10, 120, sup=self.sup2, date=D2)
        self.assertEqual(self.stock(), (20, 2200))


class CostingTests(Base):
    def test_weighted_average_cogs(self):
        self.buy(10, 100, date=D1)
        self.buy(10, 130, date=D2)           # avg = 115
        sid = self.sell(5, 200, date=D3)
        s = S.get_sale(self.conn, self.owner, sid)
        self.assertEqual(s["cogs"], 575)
        self.assertEqual(s["gross_profit"], 1000 - 575)
        self.assertEqual(self.stock(), (15, 1725))

    def test_fifo_cogs(self):
        S.update_settings(self.conn, self.owner, {"costing_method": "FIFO"})
        self.buy(10, 100, date=D1)
        self.buy(10, 130, date=D2)
        sid = self.sell(12, 200, date=D3)     # 10×100 + 2×130 = 1260
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 1260)
        self.assertEqual(self.stock(), (8, 1040))

    def test_switching_method_recosts_history(self):
        self.buy(10, 100, date=D1)
        self.buy(10, 130, date=D2)
        sid = self.sell(12, 200, date=D3)
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 1380)  # 12 × 115
        S.update_settings(self.conn, self.owner, {"costing_method": "FIFO"})
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 1260)
        S.update_settings(self.conn, self.owner, {"costing_method": "WAC"})
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 1380)

    def test_backdated_purchase_recosts_later_sale(self):
        self.buy(10, 100, date=D1)
        sid = self.sell(5, 200, date=D3)
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 500)
        self.buy(10, 160, date=D2)  # entered later but dated before the sale -> avg 130
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 650)
        self.assertEqual(self.stock(), (15, 1950))

    def test_selling_all_stock_leaves_zero_value(self):
        self.buy(3, 100, date=D1, add=1)  # 301 / 3 = 100.333...
        self.sell(1, 200, date=D2)
        self.sell(2, 200, date=D3)
        self.assertEqual(self.stock(), (0, 0))
        cogs = self.conn.execute("SELECT SUM(cogs) FROM sale_items").fetchone()[0]
        self.assertAlmostEqual(cogs, 301, places=2)

    def test_cannot_oversell(self):
        self.buy(5, 100)
        with self.assertRaises(ApiError):
            self.sell(6, 200)
        # same variant split over two lines also counts
        with self.assertRaises(ApiError):
            S.create_sale(self.conn, self.owner, {"sale_date": D2, "channel": "retail", "payment_method": "Cash",
                                                  "items": [{"variant_id": self.v, "qty": 3, "unit_price": 1},
                                                            {"variant_id": self.v, "qty": 3, "unit_price": 1}]})
        self.assertEqual(self.stock()[0], 5)

    def test_opening_stock(self):
        S.add_opening_stock(self.conn, self.owner, {"entry_date": D1, "items": [
            {"variant_id": self.v, "qty": 20, "unit_cost": 90, "supplier_id": self.sup}]})
        self.assertEqual(self.stock(), (20, 1800))
        sid = self.sell(2, 150, date=D2)
        self.assertEqual(S.get_sale(self.conn, self.owner, sid)["cogs"], 180)
        # opening stock is not a purchase and not owed to the supplier
        self.assertEqual(S.get_supplier(self.conn, self.sup)["outstanding"], 0)

    def test_damage_writeoff(self):
        self.buy(10, 100)
        S.create_adjustment(self.conn, self.owner, {"adj_date": D2, "variant_id": self.v, "qty": 2,
                                                    "direction": "out", "reason": "damaged"})
        self.assertEqual(self.stock(), (8, 800))
        p = metrics.profit_summary(self.conn, {})
        self.assertEqual(p["writeoffs"], 200)
        self.assertEqual(p["net_profit"], -200)
        with self.assertRaises(ApiError):
            S.create_adjustment(self.conn, self.owner, {"adj_date": D2, "variant_id": self.v, "qty": 2,
                                                        "direction": "in", "reason": "damaged"})


class SalesTests(Base):
    def setUp(self):
        super().setUp()
        self.buy(100, 100)

    def test_channel_is_required_and_never_inferred(self):
        with self.assertRaises(ApiError) as cm:
            S.create_sale(self.conn, self.owner, {"sale_date": D2, "payment_method": "Cash",
                                                  "items": [{"variant_id": self.v, "qty": 1, "unit_price": 100}]})
        self.assertEqual(cm.exception.field, "channel")
        with self.assertRaises(ApiError):
            self.sell(1, 100, channel="sunday")
        # wholesale and retail on the same day (a Saturday) are both kept as entered
        sat = "2025-04-05"
        a = self.sell(1, 100, date=sat, channel="wholesale")
        b = self.sell(1, 100, date=sat, channel="retail")
        self.assertEqual(S.get_sale(self.conn, self.owner, a)["channel"], "wholesale")
        self.assertEqual(S.get_sale(self.conn, self.owner, b)["channel"], "retail")

    def test_multi_line_invoice_with_discount_and_exclusive_tax(self):
        v2 = S.add_variants(self.conn, self.owner, self.pid, {"variants": [{"size": "L"}]})[0]
        self.buy(10, 50, vid=v2, inv="B2")
        sid = S.create_sale(self.conn, self.owner, {
            "sale_date": D2, "channel": "retail", "payment_method": "UPI", "tax_inclusive": False,
            "items": [{"variant_id": self.v, "qty": 2, "unit_price": 500, "discount": 100, "tax_rate": 5},
                      {"variant_id": v2, "qty": 1, "unit_price": 300, "tax_rate": 12}]})
        s = S.get_sale(self.conn, self.owner, sid)
        self.assertEqual(s["gross_amount"], 1300)
        self.assertEqual(s["discount_amount"], 100)
        self.assertEqual(s["net_amount"], 1200)
        self.assertEqual(s["tax_amount"], 45 + 36)
        self.assertEqual(s["total_amount"], 1281)
        self.assertEqual(s["amount_received"], 1281)  # defaults to fully paid
        self.assertEqual(self.stock()[0], 98)
        self.assertEqual(self.stock(v2)[0], 9)

    def test_tax_inclusive_prices(self):
        sid = self.sell(1, 1050, tax=5, inclusive=True)
        s = S.get_sale(self.conn, self.owner, sid)
        self.assertEqual(s["net_amount"], 1000)
        self.assertEqual(s["tax_amount"], 50)
        self.assertEqual(s["total_amount"], 1050)

    def test_credit_sale_needs_customer_and_tracks_outstanding(self):
        with self.assertRaises(ApiError) as cm:
            self.sell(2, 500, amount_received=0)
        self.assertEqual(cm.exception.field, "customer_id")
        sid = self.sell(2, 500, amount_received=400, new_customer={"name": "Ravi Traders", "phone": "98"},
                        channel="wholesale")
        s = S.get_sale(self.conn, self.owner, sid)
        cust = S.get_customer(self.conn, s["customer_id"])
        self.assertEqual(cust["outstanding"], 600)
        S.create_customer_payment(self.conn, self.owner, {"payment_date": D3, "customer_id": s["customer_id"],
                                                          "amount": 600, "method": "Bank Transfer"})
        self.assertEqual(S.get_customer(self.conn, s["customer_id"])["outstanding"], 0)
        self.assertEqual(metrics.customer_outstanding(self.conn), 0)

    def test_invoice_numbers_unique(self):
        self.sell(1, 100, invoice_no="A-1")
        with self.assertRaises(ApiError):
            self.sell(1, 100, invoice_no="a-1")
        n1 = S.next_invoice_no(self.conn)
        self.sell(1, 100)
        self.assertNotEqual(n1, S.next_invoice_no(self.conn))

    def test_staff_cannot_post_as_someone_else(self):
        staff = auth.save_user(self.conn, self.owner, {"full_name": "S", "username": "staff1",
                                                       "password": "password1", "permissions": ["sales.create"]})
        su = self.conn.execute("SELECT * FROM users WHERE id=?", (staff["id"],)).fetchone()
        with self.assertRaises(ApiError):
            S.create_sale(self.conn, su, {"sale_date": D2, "channel": "retail", "payment_method": "Cash",
                                          "staff_user_id": self.owner["id"],
                                          "items": [{"variant_id": self.v, "qty": 1, "unit_price": 100}]})


class ReturnsAndVoidTests(Base):
    def setUp(self):
        super().setUp()
        self.buy(10, 100)

    def test_restocked_return(self):
        sid = self.sell(4, 250, tax=5)
        item = S.get_sale(self.conn, self.owner, sid)["items"][0]
        S.create_return(self.conn, self.owner, sid, {"return_date": D3, "refund_mode": "cash",
                                                     "items": [{"sale_item_id": item["id"], "qty": 1}]})
        self.assertEqual(self.stock(), (7, 700))
        p = metrics.profit_summary(self.conn, {})
        self.assertEqual(p["gross"], 1000)
        self.assertEqual(p["returns"], 250)
        self.assertEqual(p["net_sales"], 750)          # Net = Gross − Discounts − Returns
        self.assertEqual(p["cogs"], 300)
        self.assertEqual(p["gross_profit"], 450)
        self.assertEqual(p["writeoffs"], 0)
        with self.assertRaises(ApiError):              # cannot return more than sold
            S.create_return(self.conn, self.owner, sid, {"return_date": D3, "refund_mode": "cash",
                                                         "items": [{"sale_item_id": item["id"], "qty": 4}]})

    def test_damaged_return_is_writeoff(self):
        sid = self.sell(4, 250)
        item = S.get_sale(self.conn, self.owner, sid)["items"][0]
        S.create_return(self.conn, self.owner, sid, {"return_date": D3, "refund_mode": "cash",
                                                     "items": [{"sale_item_id": item["id"], "qty": 1,
                                                                "restock": False}]})
        self.assertEqual(self.stock(), (6, 600))
        p = metrics.profit_summary(self.conn, {})
        self.assertEqual(p["cogs"], 300)
        self.assertEqual(p["writeoffs"], 100)
        self.assertEqual(p["net_profit"], 750 - 300 - 100)

    def test_void_sale_restores_stock(self):
        sid = self.sell(4, 250)
        S.void(self.conn, self.owner, "sales", sid, {"reason": "wrong entry"})
        self.assertEqual(self.stock(), (10, 1000))
        self.assertEqual(metrics.profit_summary(self.conn, {})["net_sales"], 0)
        self.assertEqual(metrics.account_balances(self.conn)["cash"], 0)
        with self.assertRaises(ApiError):
            S.void(self.conn, self.owner, "sales", sid, {"reason": "again"})

    def test_void_purchase_blocked_when_stock_sold(self):
        pid2 = self.buy(5, 100, inv="P2", date=D2)
        self.sell(12, 200, date=D3)
        with self.assertRaises(ApiError):
            S.void(self.conn, self.owner, "purchases", pid2, {"reason": "x"})

    def test_staff_void_needs_permission(self):
        staff = auth.save_user(self.conn, self.owner, {"full_name": "S", "username": "staff2",
                                                       "password": "password1", "permissions": ["sales.create"]})
        su = self.conn.execute("SELECT * FROM users WHERE id=?", (staff["id"],)).fetchone()
        sid = self.sell(1, 100)
        with self.assertRaises(ApiError) as cm:
            S.void(self.conn, su, "sales", sid, {"reason": "x"})
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(ApiError):
            S.create_cash_txn(self.conn, su, {"txn_date": D1, "kind": "initial_investment", "amount": 1,
                                              "account": "cash"})


class ProfitAndCapitalTests(Base):
    def test_profit_is_not_purchases_minus_sales(self):
        # Buy 100 units for ₹10,000 but sell only 10: profit must use COGS of
        # the 10 units sold; the other 90 stay in inventory at cost.
        self.buy(100, 100)
        self.sell(10, 150)
        p = metrics.profit_summary(self.conn, {})
        self.assertEqual(p["net_sales"], 1500)
        self.assertEqual(p["cogs"], 1000)
        self.assertEqual(p["gross_profit"], 500)
        self.assertEqual(metrics.inventory_totals(self.conn)["value"], 9000)

    def test_capital_is_not_expense_and_books_reconcile(self):
        o = self.owner
        S.create_cash_txn(self.conn, o, {"txn_date": D1, "kind": "opening_balance", "amount": 5000, "account": "cash"})
        S.create_cash_txn(self.conn, o, {"txn_date": D1, "kind": "initial_investment", "amount": 100000,
                                         "account": "bank", "purpose": "inventory"})
        S.create_cash_txn(self.conn, o, {"txn_date": D1, "kind": "loan_received", "amount": 20000, "account": "bank"})
        S.add_opening_stock(self.conn, o, {"entry_date": D1, "items": [{"variant_id": self.v, "qty": 5,
                                                                        "unit_cost": 80}]})
        S.save_supplier(self.conn, o, {"name": "Old Supplier", "opening_balance": 3000})
        # purchase 50 @ 100 + 200 freight, pay 4000 by bank now
        self.buy(50, 100, add=200, paid=4000)
        self.conn.execute("UPDATE supplier_payments SET method='Bank Transfer', account='bank'")
        S.create_supplier_payment(self.conn, o, {"payment_date": D2, "supplier_id": self.sup, "amount": 1000,
                                                 "method": "UPI"})
        # sales: one retail paid cash (incl. GST), one wholesale on credit
        self.sell(10, 210, date=D3, tax=5, inclusive=True)
        sid = self.sell(20, 150, date=D3, channel="wholesale", amount_received=1000,
                        new_customer={"name": "Shop X", "phone": ""})
        item = S.get_sale(self.conn, o, sid)["items"][0]
        S.create_return(self.conn, o, sid, {"return_date": D4, "refund_mode": "credit",
                                            "items": [{"sale_item_id": item["id"], "qty": 2}]})
        S.create_adjustment(self.conn, o, {"adj_date": D4, "variant_id": self.v, "qty": 1, "direction": "out",
                                           "reason": "damaged"})
        rent = self.conn.execute("SELECT id FROM expense_categories WHERE name='Shop Rent'").fetchone()[0]
        S.create_expense(self.conn, o, {"expense_date": D4, "category_id": rent, "amount": 1500, "method": "Cash"})
        S.create_cash_txn(self.conn, o, {"txn_date": D4, "kind": "owner_withdrawal", "amount": 700, "account": "cash"})
        S.create_cash_txn(self.conn, o, {"txn_date": D4, "kind": "tax_payment", "amount": 50, "account": "bank"})

        cap = metrics.capital_summary(self.conn)
        self.assertEqual(cap["total_contributed"], 100000)
        self.assertEqual(cap["total_withdrawals"], 700)
        self.assertEqual(cap["loans_outstanding"], 20000)
        p = metrics.profit_summary(self.conn, {})
        self.assertEqual(p["expenses"], 1500)     # capital & purchases are not expenses
        # the balance sheet ties out to opening equity + capital + profit
        self.assertAlmostEqual(cap["unreconciled"], 0, places=2)
        self.assertEqual(cap["supplier_outstanding"], 3000 + 5200 - 4000 - 1000)
        self.assertEqual(cap["customer_outstanding"], 3000 - 1000 - 300)
        self.assertEqual(cap["cash"], 5000 + 2100 + 1000 - 1500 - 700)
        self.assertEqual(cap["bank"], 100000 + 20000 - 4000 - 1000 - 50)
        self.assertEqual(cap["gst_payable"], 100 - 50)

    def test_dashboard_and_filters(self):
        self.buy(20, 100)
        self.sell(5, 200, date=D2, channel="retail")
        self.sell(5, 150, date=D2, channel="wholesale")
        d = metrics.dashboard(self.conn, {"from": D1, "to": D4})
        k = d["kpis"]
        self.assertEqual(k["retail_revenue"], 1000)
        self.assertEqual(k["wholesale_revenue"], 750)
        self.assertEqual(k["net_sales"], 1750)
        self.assertEqual(k["gross_profit"], 750)
        self.assertEqual(k["total_purchase_value"], 2000)
        self.assertEqual(k["current_inventory_value"], 1000)
        self.assertEqual(k["total_units_in_stock"], 10)
        w = metrics.dashboard(self.conn, {"from": D1, "to": D4, "channel": "wholesale"})
        self.assertEqual(w["kpis"]["net_sales"], 750)
        other = metrics.dashboard(self.conn, {"from": D1, "to": D4, "category_id": self.cat2})
        self.assertEqual(other["kpis"]["net_sales"], 0)
        s2 = metrics.dashboard(self.conn, {"supplier_id": self.sup2})
        self.assertEqual(s2["kpis"]["net_sales"], 0)
        self.assertEqual(sum(t["net_sales"] for t in d["trend"]), 1750)

    def test_reports_and_exports(self):
        self.buy(20, 100)
        self.sell(5, 200, date=D2)
        for key in reports.REPORTS:
            r = reports.run(self.conn, key, {})
            self.assertIn("rows", r)
            data = xlsx.build_xlsx([{"name": r["title"], "title": r["title"], "columns": r["columns"],
                                     "rows": r["rows"], "totals": r["totals"]}])
            self.assertTrue(data.startswith(b"PK"))
            csv = xlsx.build_csv(r["columns"], r["rows"], r["totals"])
            self.assertTrue(csv.startswith("﻿".encode()))
        mv = reports.run(self.conn, "stock-movement", {"from": D2, "to": D4})
        row = mv["rows"][0]
        self.assertEqual((row["opening"], row["purchased"], row["sold"], row["closing"]), (20, 0, 5, 15))


class AuthTests(Base):
    def test_login_and_lockout(self):
        token, user = auth.login(self.conn, "OWNER", "secret123")
        self.assertEqual(auth.user_for_token(self.conn, token)["id"], user["id"])
        auth.logout(self.conn, token)
        self.assertIsNone(auth.user_for_token(self.conn, token))
        for _ in range(auth.MAX_FAILED_LOGINS):
            with self.assertRaises(ApiError):
                auth.login(self.conn, "owner", "wrong")
        with self.assertRaises(ApiError) as cm:
            auth.login(self.conn, "owner", "secret123")
        self.assertEqual(cm.exception.status, 429)

    def test_second_owner_blocked(self):
        with self.assertRaises(ApiError):
            auth.create_owner(self.conn, {"full_name": "X", "username": "x2", "password": "password1",
                                          "shop_name": "S"})

    def test_audit_log_written(self):
        self.buy(1, 10)
        actions = [r[0] for r in self.conn.execute("SELECT action FROM audit_log")]
        self.assertIn("purchase.create", actions)
        self.assertIn("supplier.create", actions)


if __name__ == "__main__":
    unittest.main()
