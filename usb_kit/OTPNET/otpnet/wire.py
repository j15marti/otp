"""Length-prefixed JSON over TCP — the transport for every routing-layer message.

Frame: 4-byte big-endian length, then UTF-8 JSON. One request, one response,
then the connection closes.
"""

import asyncio
import json
import struct
import traceback

MAX_FRAME = 16 << 20
DEFAULT_TIMEOUT = 60.0


class WireError(Exception):
    pass


def parse_addr(text):
    host, _, port = str(text).rpartition(":")
    if not host or not port.isdigit():
        raise ValueError("address must be host:port, got %r" % text)
    return host, int(port)


async def read_frame(reader):
    (n,) = struct.unpack(">I", await reader.readexactly(4))
    if n > MAX_FRAME:
        raise WireError("frame of %d bytes exceeds limit" % n)
    return json.loads(await reader.readexactly(n))


async def write_frame(writer, obj):
    data = json.dumps(obj, separators=(",", ":")).encode()
    writer.write(struct.pack(">I", len(data)) + data)
    await writer.drain()


async def request(host, port, obj, timeout=DEFAULT_TIMEOUT):
    async def _go():
        reader, writer = await asyncio.open_connection(host, port)
        try:
            await write_frame(writer, obj)
            return await read_frame(reader)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
    try:
        return await asyncio.wait_for(_go(), timeout)
    except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as e:
        raise WireError("%s:%s unreachable: %s" % (host, port, e or type(e).__name__))


def request_sync(host, port, obj, timeout=DEFAULT_TIMEOUT):
    return asyncio.run(request(host, port, obj, timeout))


async def serve(handler, host, port, verbose=False):
    """Run ``await handler(request) -> response`` for every connection, forever."""
    async def on_conn(reader, writer):
        try:
            req = await read_frame(reader)
            try:
                resp = await handler(req)
            except Exception as e:
                if verbose:
                    traceback.print_exc()
                resp = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
            await write_frame(writer, resp)
        except (asyncio.IncompleteReadError, ConnectionError, WireError, ValueError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(on_conn, host, port, limit=MAX_FRAME)
    async with server:
        await server.serve_forever()
