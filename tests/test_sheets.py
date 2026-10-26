"""The Google Sheets layout must stay in step with the database schema."""
import io
import os
import sys
import unittest
import zipfile
from xml.dom import minidom

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shop import db  # noqa: E402
from shop.sheets_schema import TABS  # noqa: E402
from tools import export_sheets  # noqa: E402

# Columns deliberately kept out of the sheet: secrets and local-only keys.
EXCLUDED = {("users", "password_hash"), ("users", "failed_logins"), ("users", "locked_until")}
LOCAL_TABLES = {"sessions"}


class SheetsSchemaTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.init_db(":memory:")

    def test_every_table_and_column_is_mapped(self):
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        mapped = {t[1]: [c[0] for c in t[3]] for t in TABS}
        self.assertEqual(tables - LOCAL_TABLES, set(mapped))
        for table, cols in mapped.items():
            db_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % table)]
            expected = [c for c in db_cols if c != "client_ref" and (table, c) not in EXCLUDED]
            self.assertEqual(cols, expected, table)

    def test_workbook_is_valid(self):
        z = zipfile.ZipFile(io.BytesIO(export_sheets.build_workbook(self.conn)))
        for name in z.namelist():
            minidom.parseString(z.read(name))
        self.assertEqual(len([n for n in z.namelist() if n.startswith("xl/worksheets/")]), len(TABS) + 2)


if __name__ == "__main__":
    unittest.main()
