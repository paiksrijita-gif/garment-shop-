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

HEADER = ("Date of Entry,Product ID,Product Category,Product Type,Sizes,Seller,Cost,Total Units,"
          "Selling Price,Units Sold,Units available,Revenue,Profit\n")


def parse(body):
    return SD.parse_sheet(HEADER + body)


class ParseTests(unittest.TestCase):
    def test_formulas_recomputed_from_inputs(self):
        # broken formula cells (#NAME?) in the sheet never change the numbers
        rows, issues = parse('27/10/2026,KUR-1,Women,Kurti,"S, M",Jaipur,400,20,800,5,#NAME?,#NAME?,#NAME?\n')
        self.assertEqual(issues, [])
        r = rows[0]
        self.assertEqual((r["units_available"], r["revenue"], r["profit"]), (15, 4000, 2000))
        self.assertEqual((r["stock_cost"], r["cogs"], r["unsold_cost"]), (8000, 2000, 6000))
        self.assertEqual(r["date"], "2026-10-27")
        self.assertEqual(r["sizes"], "S, M")

    def test_rupee_and_comma_numbers(self):
        rows, _ = parse('2026-10-01,A,Men,Shirt,,X,"₹1,250.50",10,"Rs 2,000",3,,,\n')
        self.assertEqual((rows[0]["cost"], rows[0]["price"]), (1250.5, 2000))

    def test_date_formats(self):
        rows, issues = parse(
            "2026-10-05,A,C,T,,S,1,1,2,0,,,\n"
            "05/10/2026,B,C,T,,S,1,1,2,0,,,\n"
            "5-Oct-2026,C,C,T,,S,1,1,2,0,,,\n"
            "Oct 5, 2026,D,C,T,,S,1,1,2,0,,,\n".replace("Oct 5, 2026", '"Oct 5, 2026"'))
        self.assertEqual([r["date"] for r in rows], ["2026-10-05"] * 4)
        self.assertEqual(issues, [])

    def test_us_locale_dates_detected(self):
        rows, _ = parse("10/25/2026,A,C,T,,S,1,1,2,0,,,\n10/5/2026,B,C,T,,S,1,1,2,0,,,\n")
        self.assertEqual([r["date"] for r in rows], ["2026-10-25", "2026-10-05"])

    def test_problems_reported(self):
        rows, issues = parse(
            "2026-10-01,,C,T,,S,1,1,2,0,,,\n"          # no product id
            "2026-10-01,B,C,T,,S,abc,1,2,0,,,\n"       # bad number
            "2026-10-01,C,C,T,,S,10,5,20,7,,,\n"       # sold more than stocked
            "someday,D,C,T,,S,10,5,20,1,,,\n"          # bad date
            ",,,,,,,,,,,,\n")                          # blank row ignored
        self.assertEqual([r["product_id"] for r in rows], ["C", "D"])
        self.assertEqual(len(issues), 4)
        self.assertIn("Units Sold", issues[2])

    def test_missing_columns(self):
        rows, issues = SD.parse_sheet("Product ID,Cost\nA,1\n")
        self.assertEqual(rows, [])
        self.assertIn("Total Units", issues[0])

    def test_header_matching_is_forgiving(self):
        rows, _ = SD.parse_sheet("product id ,COST,total units,Selling price,units sold\nA,10,4,25,2\n")
        self.assertEqual(rows[0]["profit"], 30)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "sheet", "garment-shop-database.csv"), encoding="utf-8") as fh:
            self.rows, self.issues = SD.parse_sheet(fh.read())

    def test_sample_sheet_totals(self):
        self.assertEqual(self.issues, [])
        k = SD.dashboard(self.rows)["kpis"]
        exp_rev = sum(r["units_sold"] * r["price"] for r in self.rows)
        exp_cogs = sum(r["units_sold"] * r["cost"] for r in self.rows)
        self.assertAlmostEqual(k["revenue"], exp_rev, places=2)
        self.assertAlmostEqual(k["profit"], exp_rev - exp_cogs, places=2)
        self.assertEqual(k["units_available"], k["total_units"] - k["units_sold"])
        self.assertEqual(k["entries"], 24)
        # profit is on units sold only; unsold stock stays at cost
        self.assertAlmostEqual(k["stock_cost"], exp_cogs + k["unsold_cost"], places=2)

    def test_filters_and_groups(self):
        d = SD.dashboard(self.rows, {"category": "Kids", "from": "2026-08-01", "to": "2026-09-30"})
        self.assertTrue(d["rows"])
        self.assertTrue(all(r["category"] == "Kids" and "2026-08-01" <= r["date"] <= "2026-09-30" for r in d["rows"]))
        self.assertAlmostEqual(sum(g["revenue"] for g in d["by_month"]), d["kpis"]["revenue"], places=2)
        self.assertEqual([g["name"] for g in d["by_category"]], ["Kids"])
        self.assertIn("Women", d["options"]["category"])   # options stay unfiltered

    def test_sheet_url_parsing(self):
        sid, url = SD.sheet_csv_url("https://docs.google.com/spreadsheets/d/1UaY1bIbfIcz0-0INwhkyTeaPEbjUp2GCnZkcb_i6djc/edit#gid=123")
        self.assertEqual(sid, "1UaY1bIbfIcz0-0INwhkyTeaPEbjUp2GCnZkcb_i6djc")
        self.assertTrue(url.endswith("export?format=csv&gid=123"))
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
            url = "http://127.0.0.1:%d/api/sheet?category=Men&from=bad" % httpd.server_address[1]
            with urllib.request.urlopen(url) as r:
                data = json.loads(r.read())
                self.assertIn("s-maxage", r.headers["Cache-Control"])
            self.assertEqual(data["filters"], {"category": "Men"})   # invalid date ignored
            self.assertTrue(all(row["category"] == "Men" for row in data["rows"]))
            httpd.shutdown()
            httpd.server_close()
        finally:
            os.environ.pop("SHEET_CSV_FILE", None)


if __name__ == "__main__":
    unittest.main()
