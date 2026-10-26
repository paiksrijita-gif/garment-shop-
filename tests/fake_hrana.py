"""A tiny stand-in for a Turso / libSQL server, for tests only.

Implements the Hrana-over-HTTP pipeline (POST /<db>/v2/pipeline) on top of
local SQLite files, including batons so a transaction spans requests."""
import base64
import json
import os
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "test-token"


def _decode(v):
    t = v["type"]
    if t == "null":
        return None
    if t == "integer":
        assert isinstance(v["value"], str), "integers travel as strings"
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v["base64"])
    return v["value"]


def _encode(x):
    if x is None:
        return {"type": "null"}
    if isinstance(x, int):
        return {"type": "integer", "value": str(x)}
    if isinstance(x, float):
        return {"type": "float", "value": x}
    if isinstance(x, bytes):
        return {"type": "blob", "base64": base64.b64encode(x).decode()}
    return {"type": "text", "value": x}


class FakeHrana:
    def __init__(self, root):
        self.root = root
        self.streams = {}
        self.lock = threading.Lock()
        self.requests = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.requests += 1
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    self.send_response(401)
                    self.end_headers()
                    return
                name, _, rest = self.path.strip("/").partition("/")
                if rest != "v2/pipeline":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps(outer.pipeline(name, body)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, name):
        return "http://127.0.0.1:%d/%s" % (self.httpd.server_address[1], name)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def pipeline(self, name, body):
        baton = body.get("baton")
        with self.lock:
            conn = self.streams.pop(baton, None) if baton else None
        if conn is None:
            conn = sqlite3.connect(os.path.join(self.root, name + ".db"), isolation_level=None,
                                   check_same_thread=False, timeout=15)
        results = []
        closed = False
        for req in body["requests"]:
            try:
                if req["type"] == "execute":
                    st = req["stmt"]
                    cur = conn.execute(st["sql"], [_decode(a) for a in st.get("args", [])])
                    rows = cur.fetchall() if cur.description else []
                    results.append({"type": "ok", "response": {"type": "execute", "result": {
                        "cols": [{"name": d[0], "decltype": None} for d in (cur.description or [])],
                        "rows": [[_encode(v) for v in r] for r in rows],
                        "affected_row_count": max(cur.rowcount, 0),
                        "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None}}})
                elif req["type"] == "sequence":
                    conn.executescript(req["sql"])
                    results.append({"type": "ok", "response": {"type": "sequence"}})
                elif req["type"] == "close":
                    conn.close()
                    closed = True
                    results.append({"type": "ok", "response": {"type": "close"}})
            except sqlite3.Error as e:
                results.append({"type": "error", "error": {"message": str(e), "code": "SQLITE_ERROR"}})
        new_baton = None
        if not closed:
            new_baton = secrets.token_hex(8)
            with self.lock:
                self.streams[new_baton] = conn
        return {"baton": new_baton, "base_url": None, "results": results}
