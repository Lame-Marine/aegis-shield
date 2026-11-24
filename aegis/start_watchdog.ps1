# start_watchdog.ps1 - (re)start watchdog.py detached. Safe to run any number of times (stops an old one first).
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $root '.venv/Scripts/python.exe'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'aegis.watchdog\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$env:PYTHONPATH = ''
Start-Process -FilePath $py -ArgumentList 'aegis/watchdog.py' -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput "$root/logs/watchdog_out.log" -RedirectStandardError "$root/logs/watchdog_err.log"
Write-Output 'watchdog started (detached)'
