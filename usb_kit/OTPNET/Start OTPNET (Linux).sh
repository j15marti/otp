#!/bin/sh
# Run to open OTPNET (or double-click and choose "Run in Terminal").
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3) || { echo "Please install Python 3 (e.g. sudo apt install python3)"; exit 1; }
"$PY" install_deps.py --quiet && "$PY" otpnet.py
