#!/bin/sh
# macOS: double-click to start the shop app, then open http://127.0.0.1:8000
cd "$(dirname "$0")" && exec python3 server.py --lan
