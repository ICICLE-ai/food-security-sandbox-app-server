#!/bin/sh
set -eu
# HOST/PORT/DEBUG are read from the environment by config.py (defaults 0.0.0.0, 8000, false).
exec python -u app.py
