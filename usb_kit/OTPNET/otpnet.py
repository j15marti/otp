#!/usr/bin/env python3
"""OTPNET launcher. Run from the USB drive: python otpnet.py <command> ..."""
import os
import sys

if sys.version_info < (3, 9):
    sys.exit("OTPNET needs Python 3.9 or newer")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from otpnet.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
