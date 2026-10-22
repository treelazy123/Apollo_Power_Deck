"""Decode a DPT SPI/recorded frame: deck-decode capture.bin [out.pgm].

Uses the same decoder/profiles as the GUI.
"""
import argparse
from pathlib import Path

from .depth_protocol import FRAME_HEADER as HEADER, decode_frame


def decode(data):
    frame = decode_frame(data)
    return dict(sequence=frame["seq"], timestamp_ms=frame["camera_ms"],
                format=frame["format"], payload_bytes=frame["payload_size"],
                width=frame["width"], height=frame["height"],
                invalid=None, pixels=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame", type=Path)
    parser.add_argument("pgm", type=Path, nargs="?")
    args = parser.parse_args()
    frame = decode(args.frame.read_bytes())
    print({k: v for k, v in frame.items() if k != "pixels"})
    if args.pgm:
        parser.error(f"Opaque format {frame['format']} has no pixel layout; cannot write PGM")


if __name__ == "__main__":
    main()
