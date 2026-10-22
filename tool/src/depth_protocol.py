"""PDK1 fragment reassembly and DPT depth decoding for the desktop GUI."""
import struct
import zlib
from collections import Counter, OrderedDict

HEADER = struct.Struct("<4sBBHIIIIHHHHII")
# DPT: uint8 type/format, then LE uint32 seq/milliseconds/payload bytes.
MAGIC_DPT = 0x01
FRAME_HEADER = struct.Struct("<BBIII")
# All profiles are opaque bytes. The format selects a fixed payload size.
FRAME_PROFILES = {1: (0, 0, 6912),
                  2: (0, 0, 9216),
                  3: (0, 0, 14900)}
PAYLOAD_SIZES = {fmt: profile[2] for fmt, profile in FRAME_PROFILES.items()}
FRAME_SIZES = {fmt: FRAME_HEADER.size + size + 4 for fmt, size in PAYLOAD_SIZES.items()}
CHUNK = 1200


def decode_frame(data):
    if len(data) < FRAME_HEADER.size + 4:
        raise ValueError("Short DPT frame")
    magic, fmt, seq, tick, size = FRAME_HEADER.unpack_from(data)
    if magic != MAGIC_DPT:
        raise ValueError("Unsupported SPI data type (magic 0x01 required)")
    if fmt not in FRAME_PROFILES:
        raise ValueError("Unsupported DPT format profile")
    width, height, expected_size = FRAME_PROFILES[fmt]
    if size != expected_size or len(data) != FRAME_SIZES[fmt]:
        raise ValueError("Unexpected DPT payload or frame size")
    if zlib.crc32(data[:-4]) != struct.unpack_from("<I", data, len(data)-4)[0]:
        raise ValueError("Bad frame CRC32")
    return dict(seq=seq, camera_ms=tick, width=width, height=height,
                format=fmt, payload_size=size, pixels=None)


class Reassembler:
    def __init__(self, timeout=0.3, max_pending=16):
        self.timeout = timeout
        self.max_pending = max_pending
        self.pending = OrderedDict()
        self.closed = OrderedDict()
        self.stats = Counter()

    def _close(self, key, now):
        self.closed[key] = now
        while len(self.closed) > 128:
            self.closed.popitem(last=False)

    def expire(self, now):
        for key, item in list(self.pending.items()):
            if now-item["start"] >= self.timeout:
                del self.pending[key]
                self._close(key, now)
                self.stats["incomplete"] += 1

    def feed(self, packet, source, now):
        self.expire(now)
        if len(packet) < HEADER.size:
            raise ValueError("Short UDP header")
        magic, ver, kind, hlen, session, seq, total, offset, length, index, count, reserved, rx_ms, queue_ms = HEADER.unpack_from(packet)
        if (magic, ver, kind, hlen, reserved) != (b"PDK1", 1, 2, 40, 0):
            raise ValueError("Invalid PDK1 header")
        if total not in FRAME_SIZES.values() or count != (total+CHUNK-1)//CHUNK:
            raise ValueError("Invalid frame size or fragment count")
        if index >= count or offset != index*CHUNK or length != min(CHUNK, total-offset) or len(packet) != hlen+length:
            raise ValueError("Invalid fragment bounds")
        key = (source, session, seq, rx_ms)
        if key in self.closed:
            self.stats["late_or_duplicate"] += 1
            return None
        if key not in self.pending:
            if len(self.pending) >= self.max_pending:
                old, _ = self.pending.popitem(last=False)
                self._close(old, now)
                self.stats["evicted"] += 1
            self.pending[key] = dict(start=now, parts={}, max_queue_ms=0, total=total)
        item = self.pending[key]
        if item["total"] != total:
            del self.pending[key]
            self._close(key, now)
            raise ValueError("Conflicting frame size")
        payload = packet[hlen:]
        if index in item["parts"]:
            if item["parts"][index] != payload:
                del self.pending[key]
                self._close(key, now)
                raise ValueError("Conflicting duplicate fragment")
            self.stats["duplicates"] += 1
            return None
        item["parts"][index] = payload
        item["max_queue_ms"] = max(item["max_queue_ms"], queue_ms)
        self.stats["pending_peak"] = max(self.stats["pending_peak"], len(self.pending))
        if len(item["parts"]) != count:
            return None
        del self.pending[key]
        self._close(key, now)
        raw = b"".join(item["parts"][i] for i in range(count))
        frame = decode_frame(raw)
        if frame["seq"] != seq:
            raise ValueError("Inner/outer frame sequence differs")
        frame.update(raw=raw, session=session, c6_rx_ms=rx_ms,
                     c6_queue_ms=item["max_queue_ms"], reassembly_ms=(now-item["start"])*1000)
        self.stats["complete"] += 1
        return frame
