#!/usr/bin/env python3
"""Run the Google Sheet dashboard locally, the way Vercel serves it.

    python3 tools/dev_dashboard.py                      # sample data from sheet/garment-shop-database.csv
    GOOGLE_SHEET_ID=<id or link> python3 tools/dev_dashboard.py   # your real Google Sheet
"""
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if not os.environ.get("GOOGLE_SHEET_ID"):
    os.environ.setdefault("SHEET_CSV_FILE", os.path.join(ROOT, "sheet", "garment-shop-database.csv"))

from api.sheet import handler as SheetHandler  # noqa: E402

SITE = os.path.join(ROOT, "site")


class Dev(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def do_GET(self):
        if self.path.startswith("/api/sheet"):
            return SheetHandler.do_GET(self)
        return super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    subprocess.run(["sh", os.path.join(ROOT, "build-site.sh")], check=True)
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else 8002))
    print("Dashboard on http://127.0.0.1:%d  (data: %s)" % (
        port, os.environ.get("GOOGLE_SHEET_ID") or os.environ.get("SHEET_CSV_FILE")))
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
