"""Madden 20 local EA HTTP(S) endpoints.
- :42230 HTTPS  Blaze redirector  POST /redirector/getServerInstance  (XML)
- :443   HTTPS  catch-all (telemetry pin-river / rl.data bugsentry) -> 200 {}
- --plain PORT  plain HTTP side server (PC: platform_cfg.HTTP_BASE): DP tuning/LCU, telemetry, card art (netres.py)
    python http_server.py 42230 443 --plain 42240
TLS cert: certs/pc_server.crt (issued by our stand-in "GOS 2015 CA", tools/pc/make_gos_ca.py) when present,
else the old self-signed certs/ea.crt (shadPS4 never verified).
Every request is logged to logs/http/<n>_<port>_<path>.txt (headers + body) and to stdout.
Response for getServerInstance comes from redirector_response.xml if present, so it can be edited live."""
import http.server
import itertools
import socket
import socketserver
import ssl
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "http"
LOG.mkdir(parents=True, exist_ok=True)
COUNTER = itertools.count(1)


def lan_ip():
    """The address shadPS4's netctl reports (DirtySDK binds its sockets to it before connecting)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    finally:
        s.close()


def ip_u32(ip):
    a, b, c, d = (int(x) for x in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


HOST_IP = lan_ip()
# MADDEN_VERBOSE=0 (release launcher): no per-request dump files / request lines.
VERBOSE = os.environ.get("MADDEN_VERBOSE", "1") != "0"


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(ROOT / "logs" / "http_server.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _dump(self, body):
        n = next(COUNTER)
        port = self.server.server_address[1]
        safe = self.path.split("?")[0].strip("/").replace("/", "_")[:60] or "root"
        p = LOG / f"{n:04d}_{port}_{self.command}_{safe}.txt"
        if not VERBOSE:
            return p
        with open(p, "wb") as f:
            f.write(f"{self.command} {self.path} {self.request_version}\n".encode())
            f.write(str(self.headers).encode())
            f.write(b"\n")
            f.write(body)
        log(f"[{port}] {self.command} {self.headers.get('Host')} {self.path} body={len(body)} -> {p.name}")
        return p

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            if k.lower() != "content-type":
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _nucleus(self, body):
        """Route accounts.ea.com / gateway.ea.com paths through nucleus.py (reloaded per request)."""
        import importlib
        import urllib.parse
        import nucleus
        importlib.reload(nucleus)
        u = urllib.parse.urlsplit(self.path)
        r = nucleus.handle(self.command, u.path, urllib.parse.parse_qs(u.query), self.headers, body)
        if r is None:
            return False
        code, hdrs, out = r
        log(f"  -> nucleus {code} {hdrs.get('Location', '')} {out[:120]!r}")
        self._send(code, out, hdrs.get("Content-Type", "application/json"), hdrs)
        return True

    def do_POST(self):
        body = self._body()
        self._dump(body)
        if self._nucleus(body):
            return
        if self.path.startswith("/redirector/getServerInstance"):
            resp = ROOT / "redirector_response.xml"
            if resp.exists():
                data = resp.read_bytes().replace(b"{HOST_IP}", HOST_IP.encode()).replace(
                    b"{HOST_IP_U32}", str(ip_u32(HOST_IP)).encode())
                log(f"  -> redirector_response.xml ({len(data)} bytes)")
                self._send(200, data, "application/xml")
            else:
                log("  -> no redirector_response.xml yet: 503")
                self._send(503, b"", "application/xml")
            return
        self._send(200, b"{}", "application/json")

    def _netres(self):
        import importlib
        import netres
        importlib.reload(netres)
        r = netres.handle(self.path, log)
        if r is None:
            return False
        code, hdrs, out = r
        self._send(code, out, hdrs["Content-Type"])
        return True

    def do_GET(self):
        self._dump(b"")
        if self._netres():
            return
        if self._nucleus(b""):
            return
        self._send(200, b"{}", "application/json")

    do_PUT = do_POST


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port, tls=True):
    srv = Server(("127.0.0.1", port), Handler)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("ALL:@SECLEVEL=0")
        pc = ROOT / "certs" / "pc_server.crt"
        if pc.exists():
            ctx.load_cert_chain(pc, ROOT / "certs" / "pc_server.key")
        else:
            ctx.load_cert_chain(ROOT / "certs" / "ea.crt", ROOT / "certs" / "ea.key")
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    log(f"listening {'https' if tls else 'http'} 127.0.0.1:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    args = sys.argv[1:]
    plain = []
    while "--plain" in args:
        i = args.index("--plain")
        plain.append(int(args[i + 1]))
        del args[i:i + 2]
    ports = [int(p) for p in args] or [42230, 443]
    for p in ports:
        threading.Thread(target=serve, args=(p,), daemon=True).start()
    for p in plain:
        threading.Thread(target=serve, args=(p, False), daemon=True).start()
    while True:
        time.sleep(3600)
