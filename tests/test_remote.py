"""Run the full accounting and HTTP test suites against a remote (Turso-style)
database through shop/remote.py, using the fake Hrana server."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import fake_hrana  # noqa: E402
import test_api  # noqa: E402
import test_core  # noqa: E402
from shop import remote  # noqa: E402

SERVER = None
TMP = None
COUNTER = [0]


def setUpModule():
    global SERVER, TMP
    TMP = tempfile.TemporaryDirectory()
    SERVER = fake_hrana.FakeHrana(TMP.name)
    os.environ["TURSO_AUTH_TOKEN"] = fake_hrana.TOKEN


def tearDownModule():
    SERVER.stop()
    TMP.cleanup()
    os.environ.pop("TURSO_AUTH_TOKEN", None)


def fresh_url():
    COUNTER[0] += 1
    return SERVER.url("db%d" % COUNTER[0])


class RemoteMixin:
    def db_target(self):
        return fresh_url()


# Every test class from test_core, re-run over the remote connection.
for _name in dir(test_core):
    _cls = getattr(test_core, _name)
    if isinstance(_cls, type) and issubclass(_cls, test_core.Base) and _cls is not test_core.Base:
        globals()["Remote" + _name] = type("Remote" + _name, (RemoteMixin, _cls), {})


class RemoteApiTests(test_api.ApiTests):
    @classmethod
    def db_target(cls):
        return fresh_url()


class RemoteClientTests(unittest.TestCase):
    def test_bad_token_is_reported(self):
        conn = remote.Connection(fresh_url(), "wrong")
        with self.assertRaises(remote.RemoteError):
            conn.execute("SELECT 1")

    def test_rollback_discards_writes(self):
        conn = remote.Connection(fresh_url(), fake_hrana.TOKEN)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("BEGIN IMMEDIATE")
        self.assertTrue(conn.in_transaction)
        conn.execute("INSERT INTO t VALUES (?)", (1,))
        conn.execute("ROLLBACK")
        self.assertFalse(conn.in_transaction)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM t").fetchone()[0], 0)
        conn.close()

    def test_named_params_rows_and_types(self):
        conn = remote.Connection(fresh_url(), fake_hrana.TOKEN)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b REAL, c INTEGER)")
        cur = conn.execute("INSERT INTO t (a, b, c) VALUES (:a, :b, :c)", {"a": "x", "b": 1.5, "c": True})
        self.assertEqual(cur.lastrowid, 1)
        conn.executemany("INSERT INTO t (a, b, c) VALUES (?, ?, ?)", [("y", 2.0, 3), ("z", None, 4)])
        r = conn.execute("SELECT * FROM t WHERE id = 1").fetchone()
        self.assertEqual((r["a"], r["b"], r["c"], r[0]), ("x", 1.5, 1, 1))
        self.assertEqual(dict(r), {"id": 1, "a": "x", "b": 1.5, "c": 1})
        self.assertEqual([n for (n,) in conn.execute("SELECT id FROM t ORDER BY id")], [1, 2, 3])
        conn.close()


if __name__ == "__main__":
    unittest.main()


class VercelEntryTests(unittest.TestCase):
    """api/index.py as Vercel runs it: rewritten paths and the setup key."""

    def test_rewrite_and_setup_key(self):
        import importlib
        import json
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        os.environ["TURSO_DATABASE_URL"] = fresh_url()
        os.environ["GS_SETUP_KEY"] = "k3y-for-test"
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            entry = importlib.import_module("api.index")
            entry = importlib.reload(entry)
            self.assertIsNone(entry.STARTUP_ERROR)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), entry.handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = "http://127.0.0.1:%d" % httpd.server_address[1]

            def call(path, body=None):
                req = urllib.request.Request(base + path, method="POST" if body else "GET",
                                             data=json.dumps(body).encode() if body else None,
                                             headers={"X-Requested-With": "garment-shop",
                                                      "Content-Type": "application/json",
                                                      "X-Forwarded-Proto": "https"})
                try:
                    with urllib.request.urlopen(req) as r:
                        return r.status, json.loads(r.read()), r.headers
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read()), e.headers

            st, body, _ = call("/api/index?__path=status")
            self.assertEqual(st, 200)
            self.assertTrue(body["needs_owner"] and body["setup_key_required"])
            owner = {"shop_name": "S", "full_name": "O", "username": "owner", "password": "longenough1"}
            st, body, _ = call("/api/index?__path=setup/owner", dict(owner, setup_key="wrong"))
            self.assertEqual((st, body.get("field")), (403, "setup_key"))
            st, body, headers = call("/api/index?__path=setup/owner", dict(owner, setup_key="k3y-for-test"))
            self.assertEqual(st, 200, body)
            self.assertIn("Secure", headers["Set-Cookie"])
            st, body, _ = call("/api/index?__path=reports/monthly-pl&from=2025-01-01")
            self.assertEqual(st, 401)  # path and query restored; needs sign-in
            httpd.shutdown()
            httpd.server_close()
        finally:
            os.environ.pop("TURSO_DATABASE_URL", None)
            os.environ.pop("GS_SETUP_KEY", None)
