"""OTPNET: TRNG one-time-pad messaging over a token-incentivized onion relay network.

V1 proof-of-concept. Two strictly separated layers:

* Secrecy layer (pad, otpcrypto, packet, state): local-only, information-theoretic.
* Routing layer (onion, wire, relay, bootstrap): public, computationally secure,
  protects metadata only.
"""

import os
import platform
import sys

__version__ = "0.1.0"
PROTOCOL = "OTPNET/1"

# Dependencies installed by setup.sh / setup.bat live on the drive itself, one
# directory per OS/arch/Python so the same stick works on several machines.
KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_DIR = os.path.join(KIT_ROOT, "vendor", "%s-%s-py%d%d" % (
    sys.platform, platform.machine().lower(), sys.version_info[0], sys.version_info[1]))
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)
