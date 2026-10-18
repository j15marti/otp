#!/bin/sh
# One-time setup for this drive on macOS / Linux.
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3 || command -v python) || { echo "Python 3.9+ is required"; exit 1; }
"$PY" install_deps.py && "$PY" otpnet.py doctor
