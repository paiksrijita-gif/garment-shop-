#!/usr/bin/env python3
"""Run the Google Sheet dashboard locally, the way Vercel serves it.

    python3 tools/dev_dashboard.py
Uses GOOGLE_SHEET_ID from .env (your real sheet) when present, otherwise the
sample Inventory and Sales tabs in sheet/.
"""
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_dotenv(path):
    """Read KEY=value lines from .env (the same lines you paste into Vercel)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(os.path.join(ROOT, ".env"))
if not os.environ.get("GOOGLE_SHEET_ID"):
    os.environ.setdefault("SHEET_INVENTORY_FILE", os.path.join(ROOT, "sheet", "sample-inventory.csv"))
    os.environ.setdefault("SHEET_SALES_FILE", os.path.join(ROOT, "sheet", "sample-sales.csv"))

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
        port, os.environ.get("GOOGLE_SHEET_ID") or "sample tabs in sheet/"))
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
