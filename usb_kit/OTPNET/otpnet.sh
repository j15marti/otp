#!/bin/sh
# Convenience wrapper: ./otpnet.sh <command> ...
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$(command -v python3 || command -v python)" "$DIR/otpnet.py" "$@"
