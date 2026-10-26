#!/bin/sh
# Assemble the static files Vercel serves (see vercel.json "outputDirectory").
set -e
cd "$(dirname "$0")"
rm -rf site
mkdir -p site
cp sheet-site/* site/
cp static/js/core.js static/js/charts.js static/css/app.css site/
