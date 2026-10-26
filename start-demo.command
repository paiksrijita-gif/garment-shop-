#!/bin/sh
# macOS: double-click to try the app with fictional demo data at http://127.0.0.1:8001
# (your real data in data/shop.db is not touched). Logins are listed in tools/seed_demo.py.
cd "$(dirname "$0")"
[ -f data/demo.db ] || python3 tools/seed_demo.py
exec python3 server.py --db data/demo.db --port 8001
