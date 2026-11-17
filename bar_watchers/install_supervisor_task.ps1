# Registers a Windows Scheduled Task that runs the supervisor at logon,
# hidden, and restarts it on failure. Runs as current user — no admin needed.
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { Write-Host "Python not found on PATH." -ForegroundColor Red; exit 1 }

$taskName = "BAR-watchers-supervisor"
$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$here\supervisor.py`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5) `
                                         -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
                       -Settings $settings -Principal $principal -Description "BAR watcher supervisor" | Out-Null

Write-Host "Registered scheduled task: $taskName" -ForegroundColor Green
Write-Host "It will start supervisor.py at your next logon, and every 5 min if it fails."
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $taskName"
