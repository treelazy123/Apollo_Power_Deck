"""Network reception and capture writing for the Power Deck desktop app."""
import csv
import json
import math
import queue
import secrets
import select
import socket
import struct
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .depth_protocol import Reassembler

# Text transport only: no device command semantics are defined here.
MESSAGE_MAGIC = b"PDMSG1"
MESSAGE_ACK_MAGIC = b"PDACK1"
MESSAGE_HEADER = struct.Struct("<6sI")
MESSAGE_MAX_BYTES = 512
MESSAGE_ACK_TIMEOUT = 2.0


def encode_message(message_id, text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请输入要发送的消息。")
    if "\0" in text:
        raise ValueError("消息不能包含 NUL 字符。")
    payload = text.encode("utf-8")
    if len(payload) > MESSAGE_MAX_BYTES:
        raise ValueError(f"消息最多 {MESSAGE_MAX_BYTES} 字节，当前为 {len(payload)} 字节（UTF-8）。")
    return MESSAGE_HEADER.pack(MESSAGE_MAGIC, message_id) + payload


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_power(packet):
    obj = json.loads(packet)
    if obj.get("type") != "power":
        raise ValueError("Unexpected JSON type")
    for key in ("session", "seq", "timestamp_ms"):
        if not isinstance(obj.get(key), int) or obj[key] < 0:
            raise ValueError("Invalid power counter")
    for key in ("voltage_v", "current_a", "power_w"):
        if not isinstance(obj.get(key), (int, float)) or not math.isfinite(obj[key]):
            raise ValueError("Invalid power value")
    rssi_valid = obj.get("rssi_valid", False)
    rssi_dbm = obj.get("rssi_dbm")
    if not isinstance(rssi_valid, bool):
        raise ValueError("Invalid RSSI validity flag")
    if rssi_valid:
        if not isinstance(rssi_dbm, int) or isinstance(rssi_dbm, bool) or not -127 <= rssi_dbm <= 0:
            raise ValueError("Invalid RSSI value")
    else:
        rssi_dbm = None
    obj["rssi_valid"] = rssi_valid
    obj["rssi_dbm"] = rssi_dbm
    return obj


class SequenceLossEstimator:
    """Estimate missing source frames from valid DPT1 sequence numbers."""
    MASK = 0xFFFFFFFF
    HALF_RANGE = 0x80000000

    def __init__(self, reorder_window=256, history_size=512):
        self.reorder_window = reorder_window
        self.history_size = history_size
        self.reset(None)

    def reset(self, stream_key):
        self.stream_key = stream_key
        self.first_seq = None
        self.last_seq = None
        self.received = 0
        self.lost = 0
        self.reordered = 0
        self.duplicates = 0
        self._history = deque()
        self._seen = set()

    def _remember(self, seq):
        if len(self._history) >= self.history_size:
            self._seen.discard(self._history.popleft())
        self._history.append(seq)
        self._seen.add(seq)

    def observe(self, source, session, seq):
        key = (source, session)
        if key != self.stream_key:
            self.reset(key)

        seq &= self.MASK
        if self.last_seq is None:
            self.first_seq = self.last_seq = seq
            self.received = 1
            self._remember(seq)
            return
        if seq in self._seen:
            self.duplicates += 1
            return

        forward = (seq - self.last_seq) & self.MASK
        if 0 < forward < self.HALF_RANGE:
            self.lost += forward - 1
            self.received += 1
            self.last_seq = seq
            self._remember(seq)
            return

        backward = (self.last_seq - seq) & self.MASK
        observed_span = (self.last_seq - self.first_seq) & self.MASK
        if backward <= self.reorder_window and backward <= observed_span:
            # A late frame can fill a gap already counted within the recent window.
            if self.lost:
                self.lost -= 1
            self.received += 1
            self._remember(seq)
        else:
            self.reordered += 1

    def snapshot(self):
        total = self.received + self.lost
        return dict(seq_received=self.received, seq_lost=self.lost,
                    seq_loss_pct=(100.0 * self.lost / total) if total else 0.0,
                    seq_reordered=self.reordered, seq_duplicates=self.duplicates)


class CaptureRecorder:
    """Writes complete frames and power samples without blocking UDP reception."""
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.items = queue.Queue(maxsize=512)
        self.closing = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.frames = 0
        self.power = 0
        self.dropped = 0
        self.error = None
        self.thread = threading.Thread(target=self._run, name="capture-writer", daemon=False)
        self.thread.start()

    def submit(self, kind, source, value, host_utc):
        with self.lock:
            if self.closing.is_set():
                return
            try:
                self.items.put_nowait((kind, source, value, host_utc))
            except queue.Full:
                self.dropped += 1

    def stop(self):
        with self.lock:
            self.closing.set()

    def _run(self):
        try:
            frames_dir = self.folder / "frames"
            frames_dir.mkdir()
            with (self.folder / "power.csv").open("w", newline="", encoding="utf-8") as power_file, \
                 (self.folder / "depth.csv").open("w", newline="", encoding="utf-8") as depth_file:
                pw = csv.writer(power_file)
                dw = csv.writer(depth_file)
                pw.writerow(("host_utc", "board", "session", "seq", "timestamp_ms",
                             "voltage_v", "current_a", "power_w", "rssi_dbm", "rssi_valid"))
                dw.writerow(("host_utc", "board", "session", "seq", "camera_ms",
                             "format", "payload_size", "c6_rx_ms", "c6_queue_ms",
                             "reassembly_ms", "bin_file", "pgm_file"))
                while not self.closing.is_set() or not self.items.empty():
                    try:
                        kind, source, value, host_utc = self.items.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if kind == "power":
                        pw.writerow((host_utc, source, value["session"], value["seq"],
                                     value["timestamp_ms"], value["voltage_v"],
                                     value["current_a"], value["power_w"],
                                     value["rssi_dbm"], value["rssi_valid"]))
                        self.power += 1
                    else:
                        stem = (f"{source.replace('.', '_')}_{value['session']:08x}_"
                                f"{value['c6_rx_ms']:010d}_{value['seq']:010d}")
                        bin_name = stem + ".bin"
                        (frames_dir / bin_name).write_bytes(value["raw"])
                        pgm_name = ""
                        if value["pixels"] is not None:
                            pgm_name = stem + ".pgm"
                            pgm = (f"P5\n{value['width']} {value['height']}\n65535\n".encode()
                                   + b"".join(struct.pack(">H", max(0, min(65535, depth)))
                                              for depth, _ in value["pixels"]))
                            (frames_dir / pgm_name).write_bytes(pgm)
                        dw.writerow((host_utc, source, value["session"], value["seq"],
                                     value["camera_ms"], value["format"], value["payload_size"],
                                     value["c6_rx_ms"], value["c6_queue_ms"],
                                     f"{value['reassembly_ms']:.3f}",
                                     "frames/" + bin_name,
                                     "frames/" + pgm_name if pgm_name else ""))
                        self.frames += 1
                power_file.flush()
                depth_file.flush()
        except (OSError, ValueError, struct.error) as exc:
            self.error = str(exc)
        finally:
            self.closed.set()


class UdpReceiver:
    def __init__(self, board, events, recorder_getter, port=5005, discovery_port=5006):
        # An empty board means discover through limited UDP broadcast.
        self.board = board.strip()
        self.auto_discover = not self.board
        self.events = events
        self.recorder_getter = recorder_getter
        self.port = port
        self.discovery_port = discovery_port
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.outgoing_messages = queue.Queue(maxsize=16)
        self.thread = threading.Thread(target=self._run, name="deck-udp", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1.0)

    def send_message(self, text):
        """Queue one UTF-8 datagram; the worker owns socket I/O and ACK waiting."""
        message_id = secrets.randbits(32)
        packet = encode_message(message_id, text)
        if self.stop_event.is_set() or not self.ready.is_set() or not self.thread.is_alive():
            raise ValueError("请先连接 Power Deck。")
        if not self.board or self.board == "255.255.255.255":
            raise ValueError("请等待自动发现设备，或填写 C6 IP 后重新连接。")
        try:
            self.outgoing_messages.put_nowait((message_id, packet))
        except queue.Full:
            raise ValueError("消息发送队列已满，请稍后重试。") from None
        return message_id

    def _send_messages(self, sock, pending):
        # Bound work per loop so text traffic does not starve frame reception.
        for _ in range(min(4, 16 - len(pending))):
            try:
                message_id, packet = self.outgoing_messages.get_nowait()
            except queue.Empty:
                break
            endpoint = (self.board, self.discovery_port)
            try:
                if sock.sendto(packet, endpoint) != len(packet):
                    raise OSError("UDP datagram was not sent in full")
            except OSError as exc:
                self._event("message_error", dict(id=message_id, error=str(exc)))
                continue
            pending[message_id] = dict(endpoint=endpoint,
                                       deadline=time.monotonic() + MESSAGE_ACK_TIMEOUT,
                                       bytes=len(packet) - MESSAGE_HEADER.size)
            self._event("message_sent", dict(id=message_id, board=endpoint[0],
                                               bytes=len(packet) - MESSAGE_HEADER.size))

    def _receive_message_ack(self, raw, address, pending):
        if len(raw) != MESSAGE_HEADER.size:
            raise ValueError("Invalid message ACK length")
        magic, message_id = MESSAGE_HEADER.unpack(raw)
        if magic != MESSAGE_ACK_MAGIC:
            raise ValueError("Invalid message ACK magic")
        item = pending.get(message_id)
        if item is not None and address == item["endpoint"]:
            del pending[message_id]
            self._event("message_ack", dict(id=message_id, board=address[0], bytes=item["bytes"]))

    def _expire_messages(self, pending, now):
        for message_id, item in list(pending.items()):
            if now >= item["deadline"]:
                del pending[message_id]
                self._event("message_timeout", dict(id=message_id, board=item["endpoint"][0]))

    def _event(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
            return True
        except queue.Full:
            return False

    def _run(self):
        reassembler = Reassembler()
        sequence_loss = SequenceLossEstimator()
        pending_messages = {}
        power_count = invalid = discovery_errors = ui_dropped = 0
        previous = 0
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
                sock.bind(("0.0.0.0", self.port))
                sock.setblocking(False)
                self.ready.set()
                self._event("listening", f"0.0.0.0:{self.port}")
                next_hello = 0.0
                next_report = time.monotonic() + 1.0
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if now >= next_hello:
                        try:
                            destination = self.board or "255.255.255.255"
                            sock.sendto(b"PDHELLO1", (destination, self.discovery_port))
                        except OSError:
                            discovery_errors += 1
                        next_hello = now + 1.0
                    self._send_messages(sock, pending_messages)
                    readable, _, _ = select.select([sock], [], [], 0.03)
                    if readable:
                        for _ in range(256):
                            try:
                                raw, address = sock.recvfrom(65535)
                            except BlockingIOError:
                                break
                            source = address[0]
                            if self.board and self.board != "255.255.255.255" and source != self.board:
                                continue
                            arrival = time.monotonic()
                            host_utc = utc_now()
                            try:
                                if raw.startswith(MESSAGE_ACK_MAGIC):
                                    self._receive_message_ack(raw, address, pending_messages)
                                    continue
                                if raw.startswith(b"{"):
                                    sample = parse_power(raw)
                                    self._select_discovered_board(source)
                                    power_count += 1
                                    if not self._event("power", (arrival, source, sample)):
                                        ui_dropped += 1
                                    recorder = self.recorder_getter()
                                    if recorder:
                                        recorder.submit("power", source, sample, host_utc)
                                else:
                                    frame = reassembler.feed(raw, address, arrival)
                                    if frame is None:
                                        continue
                                    self._select_discovered_board(source)
                                    sequence_loss.observe(source, frame["session"], frame["seq"])
                                    if not self._event("frame", (arrival, source, frame)):
                                        ui_dropped += 1
                                    recorder = self.recorder_getter()
                                    if recorder:
                                        recorder.submit("frame", source, frame, host_utc)
                            except (ValueError, KeyError, TypeError, AttributeError,
                                    UnicodeError, struct.error):
                                invalid += 1
                    now = time.monotonic()
                    reassembler.expire(now)
                    self._expire_messages(pending_messages, now)
                    if now >= next_report:
                        complete = reassembler.stats["complete"]
                        elapsed = now - (next_report - 1.0)
                        self._event("stats", dict(depth=complete, fps=(complete-previous)/max(elapsed, 0.001),
                                                   power=power_count, invalid=invalid,
                                                   incomplete=reassembler.stats["incomplete"],
                                                   evicted=reassembler.stats["evicted"],
                                                   pending_peak=reassembler.stats["pending_peak"],
                                                   discovery_errors=discovery_errors,
                                                   ui_dropped=ui_dropped,
                                                   **sequence_loss.snapshot()))
                        previous = complete
                        next_report = now + 1.0
        except OSError as exc:
            self._event("error", f"UDP 接收失败：{exc}")
        finally:
            self.ready.clear()
            self._event("stopped", None)

    def _select_discovered_board(self, source):
        if self.auto_discover:
            self.auto_discover = False
            self.board = source
            self._event("discovered", source)
