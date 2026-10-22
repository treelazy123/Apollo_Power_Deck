"""Checks that the capture decoder CLI shares the DPT GUI profiles."""
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.decode_depth import decode

TOOL_ROOT = Path(__file__).resolve().parents[1]


def fixture(fmt=1):
    payload = bytes((i * 17 + 7 * 13) & 255 for i in range({1: 6912, 2: 9216, 3: 14900}[fmt]))
    body = struct.pack("<BBIII", 0x01, fmt, 7, 123, len(payload)) + payload
    return body + struct.pack("<I", zlib.crc32(body))


class CaptureDecoderTests(unittest.TestCase):
    def test_decode_all_profiles(self):
        for fmt in (1, 2, 3):
            result = decode(fixture(fmt))
            self.assertEqual((result["sequence"], result["timestamp_ms"], result["format"]), (7, 123, fmt))
            self.assertIsNone(result["pixels"])
            self.assertEqual((result["width"], result["height"]), (0, 0))

    def test_cli_metadata_for_all_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp)/"frame.bin"
            for fmt in (1, 2, 3):
                binary.write_bytes(fixture(fmt))
                result = subprocess.run([sys.executable, "-m", "src.decode_depth", str(binary)],
                                        capture_output=True, check=True, cwd=TOOL_ROOT)
                self.assertIn(f"'format': {fmt}".encode(), result.stdout)
                self.assertIn(b"'width': 0", result.stdout)

    def test_cli_all_opaque_profiles_cannot_be_saved_as_pgm(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary, image = Path(tmp)/"frame.bin", Path(tmp)/"raw.pgm"
            for fmt in (1, 2, 3):
                binary.write_bytes(fixture(fmt))
                result = subprocess.run([sys.executable, "-m", "src.decode_depth", str(binary), str(image)],
                                        capture_output=True, cwd=TOOL_ROOT)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"no pixel layout", result.stderr)
                self.assertFalse(image.exists())

    def test_crc_and_length_rejection(self):
        packet = fixture()
        for invalid in (packet[:-1], packet+b"x",packet[:-1]+bytes([packet[-1]^1])):
            with self.assertRaises(ValueError):
                decode(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
