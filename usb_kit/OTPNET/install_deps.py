#!/usr/bin/env python3
"""Install OTPNET's one dependency (cryptography) onto this drive.

Prefers the offline wheels shipped in ./wheels (so a drive can join the
network from an air-gapped machine); falls back to PyPI if none match.
Installs into ./vendor/<platform>-py<ver>, which otpnet.py adds to sys.path.
"""
import os
import subprocess
import sys

QUIET = "--quiet" in sys.argv
KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
from otpnet import VENDOR_DIR as TARGET  # noqa: E402  (no third-party imports in there)

WHEELS = os.path.join(KIT, "wheels")


def have_crypto():
    code = "import sys; sys.path.insert(0, %r); import cryptography.hazmat.primitives.ciphers.aead" % TARGET
    return subprocess.call([sys.executable, "-c", code], stderr=subprocess.DEVNULL) == 0


def pip(*extra):
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade",
           "--target", TARGET, "cryptography>=41"] + list(extra)
    if QUIET:
        cmd.append("--quiet")
    else:
        print("$ " + " ".join(cmd))
    return subprocess.call(cmd) == 0


def main():
    if sys.version_info < (3, 9):
        sys.exit("OTPNET needs Python 3.9 or newer (found %s)" % sys.version.split()[0])
    if have_crypto():
        if not QUIET:
            print("cryptography already available - nothing to do.")
        return 0
    print("First run on this computer: installing OTPNET's components (about a minute) ...")
    os.makedirs(TARGET, exist_ok=True)
    ok = False
    if os.path.isdir(WHEELS) and os.listdir(WHEELS):
        if not QUIET:
            print("Installing from offline wheels in %s ..." % WHEELS)
        ok = pip("--no-index", "--find-links", WHEELS)
    if not ok:
        print("Offline install unavailable for this platform; trying PyPI ...")
        ok = pip()
    if ok and have_crypto():
        if not QUIET:
            print("\nOK. Run:  python otpnet.py doctor")
        return 0
    print("\nCould not install cryptography. Install it manually: python -m pip install cryptography")
    return 1


if __name__ == "__main__":
    sys.exit(main())
