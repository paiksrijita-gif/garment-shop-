"""HTTP-level tests: auth, CSRF guard, permissions, entry and downloads."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["GS_QUIET"] = "1"

import server  # noqa: E402
from shop import db  # noqa: E402


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None, headers=None, raw=False):
        h = {"X-Requested-With": "garment-shop", "Content-Type": "application/json"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else (b"{}" if method != "GET" else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(req) as r:
                payload = r.read()
                return r.status, (payload if raw else json.loads(payload)), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(cls.tmp.name, "api.db")
        db.init_db(path).close()
        handler = type("TestHandler", (server.Handler,), {"db_path": path})
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def test_full_flow(self):
        owner = Client(self.base)
        st, body, _ = owner.call("GET", "/api/status")
        self.assertTrue(body["needs_owner"])
        st, body, _ = owner.call("GET", "/api/dashboard")
        self.assertEqual(st, 401)
        st, body, _ = owner.call("POST", "/api/setup/owner", {"shop_name": "S", "full_name": "O",
                                                               "username": "owner", "password": "short"})
        self.assertEqual(st, 400)
        st, body, _ = owner.call("POST", "/api/setup/owner", {"shop_name": "S", "full_name": "O",
                                                               "username": "owner", "password": "longenough"})
        self.assertEqual(st, 200, body)

        # CSRF: missing header / wrong origin are rejected
        st, _, _ = owner.call("POST", "/api/suppliers", {"name": "X"}, headers={"X-Requested-With": ""})
        self.assertEqual(st, 403)
        st, _, _ = owner.call("POST", "/api/suppliers", {"name": "X"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)

        st, sup, _ = owner.call("POST", "/api/suppliers", {"name": "Supplier One", "phone": "9876543210"})
        self.assertEqual(st, 200, sup)
        cats = owner.call("GET", "/api/categories")[1]
        st, prod, _ = owner.call("POST", "/api/products", {
            "name": "Cotton Kurti", "category_id": cats[0]["id"], "has_variants": True,
            "variants": [{"size": "M", "colour": "Red", "retail_price": 600, "wholesale_price": 450},
                         {"size": "L", "colour": "Red", "retail_price": 600, "wholesale_price": 450}]})
        self.assertEqual(st, 200, prod)
        variants = owner.call("GET", "/api/variants?q=kurti")[1]
        self.assertEqual(len(variants), 2)
        vid = variants[0]["id"]

        st, pur, _ = owner.call("POST", "/api/purchases", {
            "purchase_date": "2025-06-01", "supplier_id": sup["id"], "invoice_no": "SB-1", "additional_cost": 100,
            "amount_paid": 1000, "payment_method": "UPI",
            "items": [{"variant_id": vid, "qty": 10, "unit_price": 300}]})
        self.assertEqual(st, 200, pur)

        st, err, _ = owner.call("POST", "/api/sales", {"sale_date": "2025-06-02", "payment_method": "Cash",
                                                       "items": [{"variant_id": vid, "qty": 1, "unit_price": 600}]})
        self.assertEqual((st, err.get("field")), (400, "channel"))
        st, sale, _ = owner.call("POST", "/api/sales", {
            "sale_date": "2025-06-02", "channel": "retail", "payment_method": "Cash", "tax_inclusive": True,
            "items": [{"variant_id": vid, "qty": 2, "unit_price": 630, "tax_rate": 5}]})
        self.assertEqual(st, 200, sale)
        s = owner.call("GET", "/api/sales/%d" % sale["id"])[1]
        self.assertEqual(s["net_amount"], 1200)
        self.assertEqual(s["cogs"], 620)

        dash = owner.call("GET", "/api/dashboard?from=2025-06-01&to=2025-06-30")[1]
        self.assertEqual(dash["kpis"]["retail_revenue"], 1200)
        self.assertEqual(dash["kpis"]["gross_profit"], 580)
        self.assertEqual(dash["kpis"]["supplier_outstanding"], 2100)

        prof = owner.call("GET", "/api/profit?from=2025-06-01&to=2025-06-30")[1]
        self.assertEqual(prof["summary"]["gross_profit"], 580)
        self.assertEqual(prof["categories"]["columns"][0]["key"], "name")
        self.assertEqual(prof["products"]["rows"][0]["net_sales"], 1200)
        st, data, headers = owner.call("GET", "/api/reports/daily-sales?format=xlsx", raw=True)
        self.assertEqual(st, 200)
        self.assertTrue(data.startswith(b"PK"))
        self.assertIn("attachment", headers["Content-Disposition"])
        st, data, _ = owner.call("GET", "/api/reports/all", raw=True)
        self.assertTrue(data.startswith(b"PK"))
        st, data, _ = owner.call("GET", "/api/backup", raw=True)
        self.assertTrue(data.startswith(b"SQLite format 3"))
        st, data, _ = owner.call("GET", "/api/reports/stock-movement?format=csv", raw=True)
        self.assertIn(b"Closing Qty", data)

        # staff: limited permissions
        st, staff, _ = owner.call("POST", "/api/users", {"full_name": "Asha", "username": "asha",
                                                          "password": "password1",
                                                          "permissions": ["sales.create", "inventory.view"]})
        self.assertEqual(st, 200, staff)
        sc = Client(self.base)
        self.assertEqual(sc.call("POST", "/api/login", {"username": "asha", "password": "password1"})[0], 200)
        self.assertEqual(sc.call("GET", "/api/dashboard")[0], 403)
        self.assertEqual(sc.call("GET", "/api/cash")[0], 403)
        self.assertEqual(sc.call("GET", "/api/backup")[0], 403)
        self.assertEqual(sc.call("GET", "/api/reports/monthly-pl")[0], 403)
        self.assertEqual(sc.call("POST", "/api/void/sales/%d" % sale["id"], {"reason": "x"})[0], 403)
        inv = sc.call("GET", "/api/inventory")[1]
        self.assertNotIn("value", inv["totals"])               # no cost data for staff
        self.assertNotIn("stock_value", inv["variants"][0])
        v = sc.call("GET", "/api/variants?q=kurti")[1][0]
        self.assertNotIn("avg_cost", v)
        st, s2, _ = sc.call("POST", "/api/sales", {"sale_date": "2025-06-03", "channel": "wholesale",
                                                   "payment_method": "Cash",
                                                   "items": [{"variant_id": vid, "qty": 1, "unit_price": 450}]})
        self.assertEqual(st, 200, s2)
        self.assertNotIn("cogs", sc.call("GET", "/api/sales/%d" % s2["id"])[1])
        # staff sees only their own sales
        mine = sc.call("GET", "/api/sales")[1]
        self.assertEqual([r["id"] for r in mine], [s2["id"]])

        # owner voids with a reason; the audit log records it
        self.assertEqual(owner.call("POST", "/api/void/sales/%d" % s2["id"], {"reason": "test"})[0], 200)
        log = owner.call("GET", "/api/audit")[1]
        self.assertTrue(any(r["action"] == "void" for r in log))

        self.assertEqual(owner.call("POST", "/api/logout")[0], 200)
        self.assertEqual(owner.call("GET", "/api/dashboard")[0], 401)

    def test_static_and_traversal(self):
        c = Client(self.base)
        req = urllib.request.Request(self.base + "/static/../server.py")
        try:
            with urllib.request.urlopen(req) as r:
                self.assertNotIn(b"ThreadingHTTPServer", r.read())
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
