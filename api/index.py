"""Vercel entry point. Every /api/* request is rewritten here (see vercel.json)
and handled by the same Handler as server.py. Static files in static/ are
served directly by Vercel.

Required environment variables (Vercel → Project → Settings → Environment Variables):
    TURSO_DATABASE_URL   libsql://<db>-<org>.turso.io
    TURSO_AUTH_TOKEN     database token from Turso
    GS_SETUP_KEY         secret needed once to create the owner account
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from server import Handler  # noqa: E402
from shop import db  # noqa: E402

DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
STARTUP_ERROR = None
if not DATABASE_URL:
    STARTUP_ERROR = "Database not configured: set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in Vercel."
elif not db.is_remote(DATABASE_URL):
    STARTUP_ERROR = "TURSO_DATABASE_URL must start with libsql:// or https://"
else:
    try:  # create tables on a fresh database (safe to repeat on every cold start)
        db.init_db(DATABASE_URL).close()
    except Exception as e:  # noqa: BLE001 - reported to the browser below
        STARTUP_ERROR = "Cannot open the database: %s" % e


class handler(Handler):
    db_path = DATABASE_URL

    def _dispatch(self, method):
        if STARTUP_ERROR:
            data = json.dumps({"error": STARTUP_ERROR}).encode()
            return self._send(503, data, "application/json; charset=utf-8")
        return super()._dispatch(method)
