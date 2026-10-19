#!/usr/bin/env python3
"""Build the downloadable USB kit: dist/OTPNET-usb-kit.zip

Copies usb_kit/OTPNET, adds offline wheels for `cryptography` (Linux x86_64 /
aarch64, macOS, Windows; Python 3.9-3.13) so a fresh drive can be set up on an
air-gapped machine, and zips it. Unzip onto the root of a USB drive.

    python build_kit.py               # with offline wheels (needs PyPI access)
    python build_kit.py --no-wheels   # code only; setup will fetch from PyPI
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "usb_kit", "OTPNET")
DIST = os.path.join(HERE, "dist")
# Each target lists every tag pip may accept for it (pip does not expand them itself).
PLATFORMS = {
    "linux-x86_64": ["manylinux_2_34_x86_64", "manylinux_2_28_x86_64", "manylinux_2_17_x86_64",
                     "manylinux2014_x86_64"],
    "linux-aarch64": ["manylinux_2_34_aarch64", "manylinux_2_28_aarch64", "manylinux_2_17_aarch64",
                      "manylinux2014_aarch64"],
    # glibc < 2.34 (Debian 11, Ubuntu 20.04, older Raspberry Pi OS)
    "linux-x86_64-old": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"],
    "linux-aarch64-old": ["manylinux_2_28_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"],
    "macos-arm64": ["macosx_11_0_arm64", "macosx_10_9_universal2"],
    "macos-x86_64": ["macosx_10_13_x86_64", "macosx_10_9_x86_64", "macosx_10_9_universal2"],
    "windows-amd64": ["win_amd64"],
}
PYTHONS = ["3.9", "3.10", "3.11", "3.12", "3.13", "3.14"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "data", "vendor", "wheels", "demo_run")


def _download(dest, tags, py, spec):
    cmd = [sys.executable, "-m", "pip", "download", "--quiet", "--disable-pip-version-check",
           "--no-deps", "--only-binary=:all:", "--python-version", py, "--dest", dest, spec]
    for t in tags:
        cmd += ["--platform", t]
    return subprocess.call(cmd, stderr=subprocess.DEVNULL) == 0


def fetch_wheels(dest):
    """One abi3 cryptography wheel per platform (works on every Python >= 3.9),
    plus cffi for each Python version, plus pure-Python pycparser."""
    os.makedirs(dest, exist_ok=True)
    _download(dest, ["any"], "3.9", "pycparser")
    for name, tags in PLATFORMS.items():
        ok = _download(dest, tags, "3.9.2", "cryptography>=41")   # >=44 excludes 3.9.0-3.9.1
        cffi = [py for py in PYTHONS if _download(dest, tags, py, "cffi>=1.12")]
        print("  %-14s cryptography %-4s cffi for py %s" % (name, "ok" if ok else "MISSING", " ".join(cffi) or "none"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-wheels", action="store_true")
    args = ap.parse_args()

    out = os.path.join(DIST, "OTPNET")
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(SRC, out, ignore=IGNORE)
    if not args.no_wheels:
        print("Downloading offline wheels ...")
        fetch_wheels(os.path.join(out, "wheels"))

    zpath = os.path.join(DIST, "OTPNET-usb-kit.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, files in os.walk(out):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                arc = os.path.relpath(full, DIST)
                info = zipfile.ZipInfo.from_file(full, arc)
                with open(full, "rb") as f:
                    z.writestr(info, f.read(), zipfile.ZIP_DEFLATED)   # keeps +x bits
    print("Built %s (%.1f MB)" % (zpath, os.path.getsize(zpath) / 1e6))


if __name__ == "__main__":
    main()
