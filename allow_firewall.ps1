# allow_firewall.ps1 - open inbound TCP 8080 so the target phone can reach the listener.
# MUST be run from an ELEVATED PowerShell (Run as Administrator).
#
#   Right-click PowerShell -> Run as administrator, then:
#       cd D:\cyber\fishproject
#       powershell -ExecutionPolicy Bypass -File .\allow_firewall.ps1
#
# Undo later with:
#       Remove-NetFirewallRule -DisplayName "fishproject-8080"

$ruleName = "fishproject-8080"

if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Rule '$ruleName' already exists." -ForegroundColor Yellow
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 8080 `
        -Action Allow `
        -Profile Public,Private,Domain | Out-Null
    Write-Host "Created '$ruleName' (TCP 8080 inbound, Public/Private/Domain)." -ForegroundColor Green
}

Get-NetFirewallRule -DisplayName $ruleName |
    Select-Object DisplayName, Enabled, Direction, Action, Profile |
    Format-List
