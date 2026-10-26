#!/usr/bin/env python3
"""Garment Shop Manager - web server.

    python3 server.py                 # this computer only: http://127.0.0.1:8000
    python3 server.py --lan           # also reachable from phones on the shop Wi-Fi
    python3 server.py --db path.db --port 8080

Needs only Python 3.9+ (no packages to install). Data is stored in a single
SQLite file (data/shop.db by default) - back it up regularly.
"""
import argparse
import json
import mimetypes
import os
import socket
import sys
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qsl, quote

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from shop import api, auth, db  # noqa: E402
from shop.util import ApiError  # noqa: E402

STATIC = os.path.join(ROOT, "static")
MAX_BODY = 2 * 1024 * 1024
COOKIE = "gs_session"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "GarmentShop/1.0"
    db_path = None

    def log_message(self, fmt, *args):
        if os.environ.get("GS_QUIET"):
            return
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # -- dispatch -----------------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_HEAD(self):
        self._dispatch("GET")

    def _dispatch(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self._send_json(405, {"error": "Method not allowed"})
            return self._static(url.path)
        conn = db.connect(self.db_path)
        try:
            self._api(conn, method, url)
        finally:
            conn.close()

    def _api(self, conn, method, url):
        token = self._cookie_token()
        try:
            for m, rx, fn in api.ROUTES:
                if m != method:
                    continue
                match = rx.match(url.path)
                if match:
                    break
            else:
                raise ApiError(404, "Not found")
            body = None
            if method in ("POST", "PUT"):
                # CSRF defence: state-changing requests must be same-origin JSON from our app.
                if self.headers.get("X-Requested-With") != "garment-shop" or \
                        not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    raise ApiError(403, "Invalid request")
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    raise ApiError(403, "Cross-origin request blocked")
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ApiError(413, "Request too large")
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    raise ApiError(400, "Invalid JSON")
                if not isinstance(body, dict):
                    raise ApiError(400, "Invalid JSON")
            user = auth.user_for_token(conn, token)
            public = url.path in ("/api/status", "/api/login", "/api/setup/owner", "/api/logout")
            if user is None and not public:
                raise ApiError(401, "Please sign in")
            ctx = api.Ctx(conn, user, match.groups(), dict(parse_qsl(url.query)), body, token)
            result = fn(ctx)
            headers = {}
            if ctx.set_cookie is not None:
                headers["Set-Cookie"] = self._cookie_header(ctx.set_cookie)
            if isinstance(result, tuple):
                data, ctype, filename = result
                return self._send(200, data, ctype, dict(headers, **{
                    "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(filename)}))
            self._send_json(200, result, headers)
        except ApiError as e:
            payload = {"error": e.message}
            if e.field:
                payload["field"] = e.field
            self._send_json(e.status, payload)
        except Exception:  # pragma: no cover - logged for diagnosis
            traceback.print_exc()
            self._send_json(500, {"error": "Something went wrong on the server. Nothing was saved."})

    # -- helpers ------------------------------------------------------------
    def _cookie_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        c = SimpleCookie()
        try:
            c.load(raw)
        except Exception:
            return None
        return c[COOKIE].value if COOKIE in c else None

    def _cookie_header(self, token):
        if not token:
            return "%s=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" % COOKIE
        return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (
            COOKIE, token, auth.SESSION_DAYS * 86400)

    def _send_json(self, status, payload, headers=None):
        data = json.dumps(payload, default=str).encode()
        self._send(status, data, "application/json; charset=utf-8",
                   dict(headers or {}, **{"Cache-Control": "no-store"}))

    def _send(self, status, data, ctype, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
            if "." in os.path.basename(rel):
                return self._send(404, b"Not found", "text/plain")
            full = os.path.join(STATIC, "index.html")  # client-side routes
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, ctype, {"Cache-Control": "no-cache"})


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description="Garment Shop Manager")
    ap.add_argument("--port", type=int, default=int(os.environ.get("GS_PORT", 8000)))
    ap.add_argument("--db", default=os.environ.get("GS_DB", os.path.join(ROOT, "data", "shop.db")))
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (shop Wi-Fi access)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    db.init_db(args.db).close()
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    Handler.db_path = args.db

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    httpd = ThreadingHTTPServer((host, args.port), Handler)
    print("Garment Shop Manager running")
    print("  Database : %s" % os.path.abspath(args.db))
    print("  Open     : http://127.0.0.1:%d" % args.port)
    if args.lan and lan_ip():
        print("  Phones   : http://%s:%d  (same Wi-Fi)" % (lan_ip(), args.port))
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
