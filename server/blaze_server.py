"""Madden 20 Blaze server (TCP, plaintext while redirector says secure=0), Fire2 framing.
Every frame is logged (header + decoded TDF) to logs/blaze_server.log, raw bytes to logs/blaze/.
Command handlers live in handlers.py, re-imported on every frame so they can be edited live."""
import importlib
import socket
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import handlers
from http_server import HOST_IP
from tdf import decode_tdf, fmt_tdf, parse_fire2

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "blaze"
LOG.mkdir(parents=True, exist_ok=True)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 10041
_lock = threading.Lock()
# MADDEN_VERBOSE=0 (release launcher): no decoded-frame lines, no raw .bin captures; connects/errors only.
VERBOSE = os.environ.get("MADDEN_VERBOSE", "1") != "0"


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with _lock:
        print(line, flush=True)
        with open(ROOT / "logs" / "blaze_server.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")


def describe(hdr, payload, direction):
    name = handlers.command_name(hdr["comp"], hdr["cmd"])
    head = (f"{direction} {name} comp={hdr['comp']:#06x} cmd={hdr['cmd']:#06x} seq={hdr['seq']} "
            f"type={hdr['type']} len={hdr['len']}")
    try:
        body = fmt_tdf(decode_tdf(payload))
    except Exception as e:  # noqa: BLE001
        body = f"(tdf decode failed: {e}) {payload[:96].hex(' ')}"
    return head + ("\n    " + body.replace("\n", "\n    ") if body else "")


def handle(conn, addr):
    log(f"connect from {addr}")
    raw = open(LOG / f"conn_{int(time.time())}_{addr[1]}.bin", "ab") if VERBOSE else None
    buf = b""
    send_lock = threading.Lock()

    def send_later(delay, frame_bytes):
        """Push a frame (e.g. a notification) after `delay` seconds on this connection."""
        def fire():
            try:
                ph = parse_fire2(frame_bytes)
                if VERBOSE:
                    log(describe(ph[0], ph[1], ">> (deferred)"))
                with send_lock:
                    conn.sendall(frame_bytes)
            except OSError as e:
                log(f"deferred send failed: {e}")
        t = threading.Timer(delay, fire)
        t.daemon = True
        t.start()

    state = {"addr": addr, "log": log, "send_later": send_later}
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            if raw:
                raw.write(data)
                raw.flush()
            buf += data
            while True:
                p = parse_fire2(buf)
                if not p:
                    break
                hdr, payload, used = p
                buf = buf[used:]
                if VERBOSE:
                    log(describe(hdr, payload, "<<"))
                try:
                    importlib.reload(handlers)
                    replies = handlers.dispatch(hdr, payload, state)
                except Exception:  # noqa: BLE001
                    log("handler crash:\n" + traceback.format_exc())
                    replies = []
                for out in replies:
                    ph = parse_fire2(out)
                    if VERBOSE:
                        log(describe(ph[0], ph[1], ">>"))
                    with send_lock:
                        conn.sendall(out)
                if not replies:
                    log(f"   (no handler for {handlers.command_name(hdr['comp'], hdr['cmd'])})")
    except OSError as e:
        log(f"conn error {e}")
    finally:
        log(f"disconnect {addr}")
        if raw:
            raw.close()
        conn.close()


def main():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST_IP, PORT))
    s.listen(8)
    log(f"blaze listening tcp {HOST_IP}:{PORT}")
    while True:
        c, a = s.accept()
        threading.Thread(target=handle, args=(c, a), daemon=True).start()


if __name__ == "__main__":
    main()
