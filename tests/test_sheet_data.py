"""Google Sheet dashboard: parsing and metric formulas."""
import io
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from shop import sheet_data as SD  # noqa: E402

HEADER = ("Date of Entry,Product Category,Product Type,Sizes,Seller,CP,Total Units,Total Cost,SP,Units Sold,"
          "Units Available,Revenue - Wholesale,Profit - Wholesale,Units sold,Retail SP,Retail Revenue,Profit - Retail\n")


def parse(body):
    return SD.parse_sheet(HEADER + body)


class ParseTests(unittest.TestCase):
    def test_wholesale_and_retail_recomputed(self):
        # the sheet's own Units Available (28) ignores retail; the dashboard subtracts both channels
        rows, issues = parse("26/10/2026,Salwar Kameez,Pratibha Dresses,XXL,Sachi-2,400,40,16000,450,12,28,5400,600,3,500,1500,300\n")
        self.assertEqual(issues, [])
        r = rows[0]
        self.assertEqual((r["ws_revenue"], r["ws_profit"], r["rt_revenue"], r["rt_profit"]), (5400, 600, 1500, 300))
        self.assertEqual((r["units_sold"], r["units_available"], r["revenue"], r["profit"]), (15, 25, 6900, 900))
        self.assertEqual((r["stock_cost"], r["cogs"], r["unsold_cost"]), (16000, 6000, 10000))
        self.assertEqual(r["date"], "2026-10-26")
        self.assertEqual(r["name"], "Pratibha Dresses · XXL (Sachi-2)")

    def test_dashes_and_blanks_mean_empty(self):
        rows, issues = parse("26/10/2026,One Piece Gown,,XL,Baccha-2,225,8,1800,-,-,-,-,-,-,-,-,-\n"
                             "26/10/2026,One Piece Gown,-,XL,Potol,300,6,1800,350,6,0,2100,300,-,-,-,-\n")
        self.assertEqual(issues, [])
        self.assertEqual([r["type"] for r in rows], ["—", "—"])
        self.assertEqual([r["name"] for r in rows], ["One Piece Gown · XL (Baccha-2)", "One Piece Gown · XL (Potol)"])
        self.assertEqual((rows[0]["units_sold"], rows[0]["revenue"], rows[0]["units_available"]), (0, 0, 8))

    def test_rupee_and_comma_numbers(self):
        rows, _ = parse('2026-10-01,Men,Shirt,,X,"₹1,250.50",10,,"Rs 2,000",3,,,,,,,\n')
        self.assertEqual((rows[0]["cost"], rows[0]["ws_price"], rows[0]["ws_revenue"]), (1250.5, 2000, 6000))

    def test_date_formats(self):
        rows, issues = parse(
            "2026-10-05,C,T,,S,1,1,,2,0,,,,,,,\n"
            "05/10/2026,C,T,,S,1,1,,2,0,,,,,,,\n"
            "5-Oct-2026,C,T,,S,1,1,,2,0,,,,,,,\n"
            '"Oct 5, 2026",C,T,,S,1,1,,2,0,,,,,,,\n')
        self.assertEqual([r["date"] for r in rows], ["2026-10-05"] * 4)
        self.assertEqual(issues, [])

    def test_us_locale_dates_detected(self):
        rows, _ = parse("10/25/2026,C,T,,S,1,1,,2,0,,,,,,,\n10/5/2026,C,T,,S,1,1,,2,0,,,,,,,\n")
        self.assertEqual([r["date"] for r in rows], ["2026-10-25", "2026-10-05"])

    def test_problems_reported(self):
        rows, issues = parse(
            "2026-10-01,C,A,,S,abc,1,,2,0,,,,,,,\n"        # bad number
            "2026-10-01,C,B,,S,10,5,,20,4,,,,2,25,,\n"     # 6 sold of 5
            "someday,C,D,,S,10,5,,20,1,,,,,,,\n"           # bad date
            "2026-10-01,C,E,,S,10,5,,,2,,,,1,,,\n"         # sold without prices
            ",,,,,,,,,,,,,,,,\n")                          # blank row ignored
        self.assertEqual([r["type"] for r in rows], ["B", "D", "E"])
        self.assertEqual(len(issues), 5)
        self.assertIn("more than Total Units", issues[1])
        self.assertIn("SP is empty", issues[3])
        self.assertIn("Retail SP is empty", issues[4])

    def test_missing_columns(self):
        rows, issues = SD.parse_sheet("Product Category,SP\nA,1\n")
        self.assertEqual(rows, [])
        self.assertIn("CP", issues[0])
        self.assertIn("Total Units", issues[0])

    def test_original_layout_still_reads(self):
        rows, _ = SD.parse_sheet("Product ID,Cost,Total Units,Selling Price,Units Sold\nA,10,4,25,2\n")
        self.assertEqual((rows[0]["name"], rows[0]["profit"], rows[0]["units_available"]), ("A", 30, 2))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "sheet", "garment-shop-database.csv"), encoding="utf-8") as fh:
            self.rows, self.issues = SD.parse_sheet(fh.read())

    def test_sample_sheet_totals(self):
        self.assertEqual(self.issues, [])
        d = SD.dashboard(self.rows)
        k = d["kpis"]
        ws = sum(r["ws_sold"] * r["ws_price"] for r in self.rows)
        rt = sum(r["rt_sold"] * r["rt_price"] for r in self.rows)
        cogs = sum((r["ws_sold"] + r["rt_sold"]) * r["cost"] for r in self.rows)
        self.assertAlmostEqual(k["revenue"], ws + rt, places=2)
        self.assertAlmostEqual(k["profit"], ws + rt - cogs, places=2)
        self.assertEqual(k["profit"], k["ws_profit"] + k["rt_profit"])
        self.assertEqual(k["units_available"], k["total_units"] - k["units_sold"])
        self.assertEqual(k["entries"], 8)
        # profit is on units sold only; unsold stock stays at cost
        self.assertAlmostEqual(k["stock_cost"], cogs + k["unsold_cost"], places=2)
        self.assertEqual([c["name"] for c in d["channels"]], ["Wholesale", "Retail"])

    def test_filters_and_groups(self):
        d = SD.dashboard(self.rows, {"category": "Salwar Kameez", "from": "2026-08-01", "to": "2026-09-30"})
        self.assertEqual(len(d["rows"]), 2)
        self.assertTrue(all(r["category"] == "Salwar Kameez" and "2026-08-01" <= r["date"] <= "2026-09-30" for r in d["rows"]))
        self.assertAlmostEqual(sum(g["revenue"] for g in d["by_month"]), d["kpis"]["revenue"], places=2)
        self.assertEqual([g["name"] for g in d["by_category"]], ["Salwar Kameez"])
        self.assertIn("Kurti Set", d["options"]["category"])   # options stay unfiltered

    def test_sheet_url_parsing(self):
        sid, url = SD.sheet_csv_url("https://docs.google.com/spreadsheets/d/1UaY1bIbfIcz0-0INwhkyTeaPEbjUp2GCnZkcb_i6djc/edit#gid=123")
        self.assertEqual(sid, "1UaY1bIbfIcz0-0INwhkyTeaPEbjUp2GCnZkcb_i6djc")
        self.assertTrue(url.endswith("export?format=csv&gid=123"))
        # no gid → first tab, without guessing gid=0
        _, url = SD.sheet_csv_url("1UaY1bIbfIcz0-0INwhkyTeaPEbjUp2GCnZkcb_i6djc")
        self.assertTrue(url.endswith("/export?format=csv"))
        _, url = SD.sheet_csv_url("1UaY1bIbfIcz0-0INwhkyTeaPEbjUp2GCnZkcb_i6djc", "")
        self.assertTrue(url.endswith("/export?format=csv"))
        with self.assertRaises(ValueError):
            SD.sheet_csv_url("not a sheet")


class FunctionTests(unittest.TestCase):
    """api/sheet.py as Vercel runs it, reading a local CSV."""

    def test_endpoint(self):
        import importlib
        os.environ["SHEET_CSV_FILE"] = os.path.join(ROOT, "sheet", "garment-shop-database.csv")
        try:
            mod = importlib.import_module("api.sheet")
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), mod.handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            url = "http://127.0.0.1:%d/api/sheet?category=Co-ord%%20Set&from=bad" % httpd.server_address[1]
            with urllib.request.urlopen(url) as r:
                data = json.loads(r.read())
                self.assertIn("s-maxage", r.headers["Cache-Control"])
            self.assertEqual(data["filters"], {"category": "Co-ord Set"})   # invalid date ignored
            self.assertTrue(data["rows"] and all(row["category"] == "Co-ord Set" for row in data["rows"]))
            httpd.shutdown()
            httpd.server_close()
        finally:
            os.environ.pop("SHEET_CSV_FILE", None)


if __name__ == "__main__":
    unittest.main()
