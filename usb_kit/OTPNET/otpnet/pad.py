"""Secrecy layer: pad files.

A pad is a flat file of true-random bytes that exists, identically, on exactly
two drives. Bytes are addressed by absolute offset (we always seek, never read
sequentially from 0) and nothing in this module ever touches the network.
"""

import hashlib
import os
import stat
import time

from .otpcrypto import xor_bytes

CHUNK = 1 << 20
HWRNG_DEVICES = ("/dev/hwrng",)
PROBE_BYTES = 64 << 10        # auto-detected TRNG must deliver 64 KB/s to be used
PROBE_SECONDS = 1.0
_UNITS = {"": 1, "B": 1, "K": 1 << 10, "KB": 1 << 10, "M": 1 << 20, "MB": 1 << 20,
          "G": 1 << 30, "GB": 1 << 30, "T": 1 << 40, "TB": 1 << 40}


class PadError(Exception):
    pass


class PadExhausted(PadError):
    pass


def parse_size(text) -> int:
    """'10M' -> 10485760. Units are binary (K=1024)."""
    s = str(text).strip().upper()
    num = s.rstrip("KMGTB")
    unit = s[len(num):]
    if not num or unit not in _UNITS:
        raise ValueError("bad size %r (try 10M, 256G, 1048576)" % text)
    return int(float(num) * _UNITS[unit])


def _probe(dev, want=PROBE_BYTES, seconds=PROBE_SECONDS):
    """True if ``dev`` can deliver ``want`` bytes within ``seconds`` (non-blocking)."""
    try:
        fd = os.open(dev, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return False
    got, deadline = 0, time.monotonic() + seconds
    try:
        while got < want and time.monotonic() < deadline:
            try:
                chunk = os.read(fd, want - got)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except OSError:
                return False
            if not chunk:
                return False
            got += len(chunk)
    finally:
        os.close(fd)
    return got >= want


def _pick_source(source):
    """Resolve the entropy source name: an explicit path, 'os', or auto-detect.

    ``source`` may be a character device (/dev/hwrng, a USB TRNG such as
    /dev/ttyACM0) or a file of captured TRNG output. Auto-detection only uses
    the kernel hardware RNG if it is fast enough to fill a pad in reasonable
    time; pass it explicitly to use a slow device anyway.
    """
    if source == "os":
        return None
    if source:
        return source
    for dev in HWRNG_DEVICES:
        if _probe(dev):
            return dev
    return None


def describe_entropy(source=None) -> str:
    name = _pick_source(source)
    if name:
        return "hardware TRNG %s XOR os.urandom()" % name
    return "os.urandom() only (MOCK TRNG: no usable hardware RNG; fine for testing only)"


def _read_exact(f, n):
    out = bytearray()
    while len(out) < n:
        chunk = f.read(n - len(out))
        if not chunk:
            raise PadError("entropy source ran dry after %d bytes" % len(out))
        out += chunk
    return bytes(out)


def generate_pad(path, size, source=None, progress=None) -> str:
    """Write ``size`` random bytes to ``path``; returns a description of the source.

    When a hardware source is present its output is XORed with os.urandom(): the
    result is at least as unpredictable as the better of the two, so a biased or
    backdoored device can't make the pad worse than the OS RNG and vice versa.
    """
    hw_name = _pick_source(source)
    try:
        hw = open(hw_name, "rb", buffering=0) if hw_name else None
    except OSError as e:
        raise PadError("cannot open entropy source %s: %s" % (hw_name, e))
    tmp = path + ".partial"
    written = 0
    try:
        with open(tmp, "wb") as out:
            while written < size:
                n = min(CHUNK, size - written)
                block = os.urandom(n)
                if hw:
                    block = xor_bytes(block, _read_exact(hw, n))
                out.write(block)
                written += n
                if progress:
                    progress(written, size)
            out.flush()
            os.fsync(out.fileno())
    finally:
        if hw:
            hw.close()
    os.replace(tmp, path)
    _restrict(path)
    return describe_entropy(hw_name or "os")


def copy_pad(src, dst, progress=None) -> str:
    """Copy a pad to the other drive of the pair and verify it byte-for-byte."""
    total = os.path.getsize(src)
    h_src = hashlib.sha256()
    done = 0
    tmp = dst + ".partial"
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            chunk = fi.read(CHUNK)
            if not chunk:
                break
            h_src.update(chunk)
            fo.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
        fo.flush()
        os.fsync(fo.fileno())
    os.replace(tmp, dst)
    _restrict(dst)
    digest = sha256_file(dst)
    if digest != h_src.hexdigest():
        raise PadError("pad copy verification failed: %s differs from %s" % (dst, src))
    return digest


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def read_segment(path, offset, length) -> bytes:
    """Read ``length`` pad bytes starting at absolute byte ``offset``."""
    if offset < 0 or length < 0:
        raise PadError("negative offset/length")
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    if len(data) != length:
        raise PadExhausted("pad %s has no bytes [%d, %d)" % (path, offset, offset + length))
    return data


def burn_segment(path, offset, length):
    """Overwrite used pad bytes with zeros so a seized drive can't decrypt past traffic.

    Caveat: flash wear-levelling may keep stale copies of the old blocks; for
    real deployments combine this with full-drive encryption at rest.
    """
    zeros = bytes(min(CHUNK, length))
    with open(path, "r+b") as f:
        f.seek(offset)
        left = length
        while left > 0:
            n = min(len(zeros), left)
            f.write(zeros[:n])
            left -= n
        f.flush()
        os.fsync(f.fileno())


def _restrict(path):
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass   # FAT/exFAT USB drives have no permission bits
