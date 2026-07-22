<#
.SYNOPSIS
    Registers a Windows Scheduled Task that runs bookmark_bridge.py on an
    interval (and at logon) to keep Edge and Brave bookmarks in sync.

.DESCRIPTION
    This is for the FALLBACK, fully-local bridge (see README.md). It assumes
    Python 3 is installed and on PATH. The task runs whether or not you are
    interactive, but remember: the bridge only WRITES to a browser that is
    currently closed. So changes flow into Brave/Edge the next time that
    browser is shut while the task fires.

.PARAMETER IntervalMinutes
    How often to run the sync. Default: 15.

.PARAMETER TaskName
    Scheduled Task name. Default: "BraveEdgeBookmarkBridge".

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Install-BridgeTask.ps1
    powershell -ExecutionPolicy Bypass -File .\Install-BridgeTask.ps1 -IntervalMinutes 10

.NOTES
    To remove:  Unregister-ScheduledTask -TaskName "BraveEdgeBookmarkBridge" -Confirm:$false
#>
[CmdletBinding()]
param(
    [int]$IntervalMinutes = 15,
    [string]$TaskName = "BraveEdgeBookmarkBridge"
)

$ErrorActionPreference = "Stop"

# Locate python and the bridge script (assumed to sit next to this file).
$python = (Get-Command python -ErrorAction SilentlyContinue) `
          ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $python) {
    Write-Error "Python was not found on PATH. Install it (e.g. 'winget install Python.Python.3.12') and re-run."
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridge    = Join-Path $scriptDir "bookmark_bridge.py"
if (-not (Test-Path $bridge)) {
    Write-Error "Could not find bookmark_bridge.py next to this script ($bridge)."
    exit 1
}

Write-Host "Python : $($python.Source)"
Write-Host "Bridge : $bridge"
Write-Host "Every  : $IntervalMinutes minute(s), plus at logon"

$action = New-ScheduledTaskAction -Execute $python.Source `
          -Argument "`"$bridge`"" -WorkingDirectory $scriptDir

# Repeat forever at the chosen interval, starting shortly after registration,
# and also once at logon.
$repeat  = (New-TimeSpan -Minutes $IntervalMinutes)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
           -RepetitionInterval $repeat -RepetitionDuration ([TimeSpan]::MaxValue)
$logon   = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
            -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
            -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($trigger, $logon) -Settings $settings `
    -Description "Two-way Edge<->Brave bookmark sync (fully local)." -Force | Out-Null

Write-Host ""
Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "Run it once now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Watch what it does with a manual dry run:"
Write-Host "  & `"$($python.Source)`" `"$bridge`" --dry-run"
