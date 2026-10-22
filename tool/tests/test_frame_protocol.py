"""DPT wire/PDK1 regression tests, independent of Tkinter."""
import csv
import json
import queue
import socket
import struct
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.depth_protocol import decode_frame, Reassembler
from src.deck_gui_backend import CaptureRecorder, UdpReceiver, SequenceLossEstimator


def frame(fmt=1, seq=7, tick=123, payload=None):
    if payload is None:
        payload = bytes((i * 17 + seq * 13) & 255 for i in range({1: 6912, 2: 9216, 3: 14900}[fmt]))
    body = struct.pack("<BBIII", 0x01, fmt, seq & 0xFFFFFFFF, tick & 0xFFFFFFFF, len(payload)) + payload
    return body + struct.pack("<I", zlib.crc32(body))


def repaired(packet):
    return bytes(packet[:-4]) + struct.pack("<I", zlib.crc32(packet[:-4]))


def fragments(raw, session=1, outer_seq=None, rx_ms=1000):
    seq = struct.unpack_from("<I", raw, 2)[0] if outer_seq is None else outer_seq
    count = (len(raw) + 1199) // 1200
    result = []
    for index in range(count):
        offset = index * 1200
        part = raw[offset:offset + 1200]
        head = struct.pack("<4sBBHIIIIHHHHII", b"PDK1", 1, 2, 40,
                           session, seq, len(raw), offset, len(part), index, count, 0, rx_ms, 2)
        result.append(head + part)
    return result


class DptTests(unittest.TestCase):
    def test_golden_header_offsets_and_endian(self):
        packet = frame(seq=0x01020304, tick=0x05060708)
        self.assertEqual(packet[:14], bytes.fromhex(
            "01 01 04030201 08070605 001b0000"))
        result = decode_frame(packet)
        self.assertEqual((result["seq"], result["camera_ms"]), (0x01020304, 0x05060708))
        self.assertIsNone(result["pixels"])

    def test_all_three_fixed_profiles(self):
        for fmt, expected in ((1, 6930), (2, 9234), (3, 14918)):
            with self.subTest(fmt=fmt):
                packet = frame(fmt)
                result = decode_frame(packet)
                self.assertEqual(len(packet), expected)
                self.assertEqual(result["format"], fmt)
                self.assertEqual(result["payload_size"], expected - 18)
                self.assertIsNone(result["pixels"])
                self.assertEqual((result["width"], result["height"]), (0, 0))

    def test_reject_old_text_headers(self):
        payload = bytes(6912)
        for label in (b"DPT1", b"DPT2"):
            body = struct.pack("<4sIIII", label, 7, 123, len(payload), 1) + payload
            with self.subTest(label=label), self.assertRaises(ValueError):
                decode_frame(body + struct.pack("<I", zlib.crc32(body)))

    def test_spi_padding_is_not_part_of_udp_or_recorded_frame(self):
        for fmt in (1, 2, 3):
            raw = frame(fmt)
            self.assertEqual(len(raw) % 4, 2)
            with self.subTest(fmt=fmt), self.assertRaises(ValueError):
                decode_frame(raw + bytes(2))

    def test_reject_truncated_extra_misaligned(self):
        packet = frame()
        for invalid in (packet[:14], packet[:-1], packet + b"x", packet[1:] + b"x"):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                decode_frame(invalid)

    def test_bad_metadata_even_with_valid_crc(self):
        for offset, code, value in ((0, "<B", 0), (0, "<B", 255),
                                    (10, "<I", 6911), (10, "<I", 0xFFFFFFFF),
                                    (1, "<B", 0), (1, "<B", 255), (1, "<B", 2)):
            packet = bytearray(frame())
            struct.pack_into(code, packet, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                decode_frame(repaired(packet))

    def test_corruption_of_header_payload_and_crc(self):
        for offset in (2, 6, 14, 6929):
            packet = bytearray(frame())
            packet[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                decode_frame(packet)

    def test_opaque_format1_accepts_arbitrary_status_like_bytes(self):
        for prefix in (b"\x01\x00\x00", b"\xd2\x04\xff", b"\xff" * 3):
            payload = prefix + bytes(6912 - len(prefix))
            result = decode_frame(frame(1, payload=payload))
            self.assertIsNone(result["pixels"])

    def test_opaque_format2_accepts_all_float_like_bit_patterns(self):
        for bits in (0x80000000, 0xbf800000, 0x7fc00000, 0x7f800000, 0xff800000):
            payload = struct.pack("<I", bits) + bytes(9212)
            result = decode_frame(frame(2, payload=payload))
            self.assertIsNone(result["pixels"])

    def test_sequence_and_timestamp_wrap_values(self):
        result = decode_frame(frame(seq=0xFFFFFFFF, tick=0xFFFFFFFF))
        self.assertEqual((result["seq"], result["camera_ms"]), (0xFFFFFFFF, 0xFFFFFFFF))

    def test_reject_previous_binary_header(self):
        payload = bytes(6912)
        body = struct.pack("<BIIIB", 0x01, 1, 123, len(payload), 1) + payload
        with self.assertRaises(ValueError):
            decode_frame(body + struct.pack("<I", zlib.crc32(body)))

    def test_loss_estimator_continues_across_uint32_rollover(self):
        tracker = SequenceLossEstimator()
        count = 2 * 65536 + 4
        start = 0xFFFF0000
        for index in range(count):
            tracker.observe("127.0.0.1", 1, (start + index) & 0xFFFFFFFF)
        self.assertEqual((tracker.received, tracker.lost, tracker.reordered, tracker.duplicates),
                         (count, 0, 0, 0))
        self.assertEqual(tracker.last_seq, (start + count - 1) & 0xFFFFFFFF)

    def test_loss_estimator_late_frame_and_duplicate_across_wrap(self):
        tracker = SequenceLossEstimator()
        for seq in (0xFFFFFFFE, 0, 0xFFFFFFFF, 0):
            tracker.observe("127.0.0.1", 1, seq)
        self.assertEqual((tracker.received, tracker.lost, tracker.reordered, tracker.duplicates),
                         (3, 0, 0, 1))

    def test_loss_estimator_sparse_cycle_and_late_gap_repair(self):
        tracker = SequenceLossEstimator()
        for seq in (0, 0x7FFFFFFF, 0xFFFFFFFE, 0, 0xFFFFFFFF):
            tracker.observe("127.0.0.1", 1, seq)
        self.assertEqual((tracker.received, tracker.lost, tracker.reordered, tracker.duplicates),
                         (5, 0xFFFFFFFC, 0, 0))

    def test_source_sequence_and_camera_time_wrap_independently(self):
        before = decode_frame(frame(seq=0xFFFFFFFF, tick=0xFFFFFFFE))
        after = decode_frame(frame(seq=0x100000000, tick=0x100000001))
        self.assertEqual((before["seq"], after["seq"]), (0xFFFFFFFF, 0))
        self.assertEqual((before["camera_ms"], after["camera_ms"]), (0xFFFFFFFE, 1))

    def test_reassembly_reverse_and_duplicate_all_profiles(self):
        for fmt in (1, 2, 3):
            raw = frame(fmt)
            packets = fragments(raw)
            receiver = Reassembler()
            result = None
            for index, packet in enumerate(reversed(packets)):
                result = receiver.feed(packet, ("127.0.0.1", 5000), index * 0.001) or result
                if index == 0:
                    self.assertIsNone(receiver.feed(packet, ("127.0.0.1", 5000), 0.0001))
            self.assertEqual(result["raw"], raw)
            self.assertEqual(receiver.stats["complete"], 1)
            self.assertEqual(receiver.stats["duplicates"], 1)

    def test_missing_fragment_timeout(self):
        receiver = Reassembler()
        receiver.feed(fragments(frame())[0], ("127.0.0.1", 5000), 0)
        receiver.expire(0.31)
        self.assertEqual(receiver.stats["incomplete"], 1)
        self.assertFalse(receiver.pending)

    def test_inner_outer_sequence_mismatch(self):
        receiver = Reassembler()
        packets = fragments(frame(), outer_seq=99)
        with self.assertRaisesRegex(ValueError, "sequence"):
            for packet in packets:
                receiver.feed(packet, ("127.0.0.1", 5000), 0)

    def test_invalid_fragment_offset_and_total(self):
        for offset, value in ((16, 6932), (20, 4)):
            packet = bytearray(fragments(frame())[0])
            struct.pack_into("<I", packet, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                Reassembler().feed(packet, ("127.0.0.1", 5000), 0)

    def test_pending_bound_and_session_isolation(self):
        receiver = Reassembler(max_pending=2)
        for session in (1, 2, 3):
            receiver.feed(fragments(frame(), session=session)[0], ("127.0.0.1", 5000), 0)
        self.assertEqual(len(receiver.pending), 2)
        self.assertEqual(receiver.stats["evicted"], 1)

    def test_udp_backend_and_recording_all_profiles_with_rssi(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as board:
            board.bind(("127.0.0.1", 0))
            board.settimeout(3)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserved:
                reserved.bind(("127.0.0.1", 0))
                port = reserved.getsockname()[1]
            folder = Path(tmp) / "capture"
            folder.mkdir()
            recorder = CaptureRecorder(folder)
            events = queue.Queue(maxsize=1024)
            receiver = UdpReceiver("127.0.0.1", events, lambda: recorder,
                                   port=port, discovery_port=board.getsockname()[1])
            seen, power = [], []
            try:
                hello, peer = board.recvfrom(32)
                self.assertEqual(hello, b"PDHELLO1")
                sample = dict(type="power", session=1, seq=1, timestamp_ms=10,
                              voltage_v=4.1, current_a=0.1, power_w=0.41,
                              rssi_dbm=-62, rssi_valid=True)
                board.sendto(json.dumps(sample).encode(), peer)
                for fmt in (1, 2, 3):
                    for packet in fragments(frame(fmt, seq=fmt)):
                        board.sendto(packet, peer)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and (len(seen) < 3 or not power):
                    try:
                        kind, value = events.get(timeout=0.1)
                        if kind == "frame":
                            seen.append(value[2]["format"])
                        elif kind == "power":
                            power.append(value[2]["rssi_dbm"])
                        elif kind == "error":
                            self.fail(str(value))
                    except queue.Empty:
                        pass
                self.assertEqual(seen, [1, 2, 3])
                self.assertEqual(power, [-62])
            finally:
                receiver.stop()
                recorder.stop()
                recorder.thread.join(timeout=5)
            self.assertTrue(recorder.closed.is_set())
            self.assertIsNone(recorder.error)
            self.assertEqual((recorder.frames, recorder.power, recorder.dropped), (3, 1, 0))
            binaries = list((folder / "frames").glob("*.bin"))
            self.assertEqual(len(binaries), 3)
            self.assertEqual({p.read_bytes() for p in binaries}, {frame(fmt, seq=fmt) for fmt in (1, 2, 3)})
            self.assertEqual(len(list((folder / "frames").glob("*.pgm"))), 0)
            with (folder / "power.csv").open(newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
                self.assertEqual(rows[1][-2:], ["-62", "True"])
            with (folder / "depth.csv").open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(row["pgm_file"] == "" for row in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
