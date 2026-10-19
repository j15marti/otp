#!/bin/sh
# Double-click to open OTPNET. (First time: right-click > Open.)
cd "$(dirname "$0")" || exit 1
PY=$(command -v python3) || {
  echo "Python 3 is not installed. Opening the download page..."
  open "https://www.python.org/downloads/"
  read -r _
  exit 1
}
"$PY" install_deps.py --quiet && "$PY" otpnet.py
