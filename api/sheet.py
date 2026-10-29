"""Vercel function: GET /api/sheet → dashboard data from the Google Sheet.

Environment variables (Vercel → Project → Settings → Environment Variables):
    GOOGLE_SHEET_ID    the sheet's ID or its full link (shared as "Anyone with the link — Viewer")
    GOOGLE_INVENTORY_TAB / GOOGLE_SALES_TAB   optional: tab names if not "Inventory" and "Sales"
    GOOGLE_SHEET_GID   optional: read one tab (by gid) that holds stock and sales together
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shop import sheet_data  # noqa: E402

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def build(query):
    fresh = query.get("fresh") == "1"
    sources, sheet_id = sheet_data.load_sources(fresh=fresh)
    rows, issues = sheet_data.parse_workbook(sources["inventory"], sources["sales"])
    f = {}
    for k in ("from", "to"):
        if DATE.fullmatch(query.get(k, "")):
            f[k] = query[k]
    for k in ("category", "type", "seller", "q"):
        if query.get(k):
            f[k] = query[k][:100]
    data = sheet_data.dashboard(rows, f)
    data.update(issues=issues, filters=f, today=sheet_data.today(),
                sheet_url="https://docs.google.com/spreadsheets/d/%s/edit" % sheet_id if sheet_id else None)
    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = dict(parse_qsl(urlparse(self.path).query))
        try:
            status, payload = 200, build(query)
        except (RuntimeError, ValueError, OSError) as e:
            status, payload = 502, {"error": str(e)}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Vercel's CDN keeps a copy for 15 s, so the sheet is not fetched on every view.
        fresh = status != 200 or query.get("fresh") == "1"
        self.send_header("Cache-Control", "no-store" if fresh else "public, s-maxage=15, stale-while-revalidate=60")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
