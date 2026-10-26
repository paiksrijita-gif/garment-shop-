"""Minimal sqlite3-compatible connection to a remote libSQL / Turso database.

Speaks the Hrana-over-HTTP protocol (POST <url>/v2/pipeline) with only the
standard library, so the app needs no extra packages on Vercel. It covers the
part of the sqlite3 API this app uses: execute / executemany / executescript,
cursors with fetchone / fetchall / iteration / lastrowid, Row objects that
work like sqlite3.Row, and transactions (one HTTP "stream" per connection,
kept alive with a baton so BEGIN ... COMMIT spans several requests).
"""
import base64
import json
import re
import urllib.error
import urllib.request

TIMEOUT = 30


class RemoteError(Exception):
    pass


class IntegrityError(RemoteError):
    pass


class Row:
    __slots__ = ("_cols", "_vals", "_index")

    def __init__(self, cols, vals, index):
        self._cols, self._vals, self._index = cols, vals, index

    def keys(self):
        return list(self._cols)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._vals[key]
        return self._vals[self._index[key]]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __repr__(self):
        return "Row(%r)" % dict(zip(self._cols, self._vals))


class Cursor:
    def __init__(self, cols, rows, lastrowid, rowcount):
        index = {c: i for i, c in enumerate(cols)}
        self._rows = [Row(cols, r, index) for r in rows]
        self._pos = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        self._pos += 1
        return self._rows[self._pos - 1]

    def fetchall(self):
        rest = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rest

    def __iter__(self):
        while True:
            r = self.fetchone()
            if r is None:
                return
            yield r


def _encode(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _decode(v):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v.get("base64", ""))
    return v.get("value")


_NAMED = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _positional(sql, params):
    """Turn :name parameters into ? placeholders (sqlite3 allows a dict)."""
    if not isinstance(params, dict):
        return sql, list(params or ())
    order = []

    def sub(m):
        order.append(params[m.group(1)])
        return "?"
    return _NAMED.sub(sub, sql), order


class Connection:
    def __init__(self, url, token=None):
        url = url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self._base = url.rstrip("/")
        self._token = token
        self._baton = None
        self._closed = False
        self.in_transaction = False
        self.row_factory = None  # accepted for sqlite3 compatibility

    # -------------------------------------------------------------- transport
    def _pipeline(self, requests):
        body = json.dumps({"baton": self._baton, "requests": requests}).encode()
        req = urllib.request.Request(self._base + "/v2/pipeline", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        if self._token:
            req.add_header("Authorization", "Bearer " + self._token)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise RemoteError("Database request failed (%s): %s" % (e.code, detail))
        except urllib.error.URLError as e:
            raise RemoteError("Cannot reach the database: %s" % e.reason)
        self._baton = data.get("baton")
        if data.get("base_url"):
            self._base = data["base_url"].rstrip("/")
        out = []
        for res in data.get("results", []):
            if res.get("type") == "error":
                msg = res.get("error", {}).get("message", "database error")
                cls = IntegrityError if "constraint" in msg.lower() else RemoteError
                raise cls(msg)
            out.append(res.get("response", {}))
        return out

    @staticmethod
    def _stmt(sql, params):
        sql, args = _positional(sql, params)
        return {"type": "execute", "stmt": {"sql": sql, "args": [_encode(a) for a in args], "want_rows": True}}

    @staticmethod
    def _cursor(resp):
        result = resp.get("result", {})
        cols = [c.get("name") for c in result.get("cols", [])]
        rows = [[_decode(v) for v in r] for r in result.get("rows", [])]
        rid = result.get("last_insert_rowid")
        return Cursor(cols, rows, int(rid) if rid is not None else None, result.get("affected_row_count", -1))

    # -------------------------------------------------------------- sqlite3 API
    def execute(self, sql, params=()):
        word = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        cur = self._cursor(self._pipeline([self._stmt(sql, params)])[0])
        if word == "BEGIN":
            self.in_transaction = True
        elif word in ("COMMIT", "ROLLBACK", "END"):
            self.in_transaction = False
        return cur

    def executemany(self, sql, seq):
        reqs = [self._stmt(sql, p) for p in seq]
        for i in range(0, len(reqs), 200):  # one HTTP round trip per 200 rows
            self._pipeline(reqs[i:i + 200])

    def executescript(self, script):
        self._pipeline([{"type": "sequence", "sql": script}])

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._baton:
            try:
                self._pipeline([{"type": "close"}])
            except RemoteError:
                pass
