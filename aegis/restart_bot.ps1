# restart_bot.ps1 - stop any running aegis bot and start one detached (survives the agent session dropping).
# Usage (from bash): powershell.exe -NoProfile -File "aegis/restart_bot.ps1"
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $root '.venv/Scripts/python.exe'
# wait (max 3 min) until the running bot has no queries or messages in flight (skip if no bot is running)
$running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'aegis.bot\.py' }).Count -gt 0
$deadline = (Get-Date).AddMinutes(3)
while ($running -and (Test-Path "$root/logs/bot_busy.txt") -and ((Get-Content "$root/logs/bot_busy.txt" -Raw).Trim() -ne '0') -and ((Get-Date) -lt $deadline)) {
  Start-Sleep -Seconds 2
}
if ((Get-Date) -ge $deadline) { Write-Output 'bot still busy after 3 min; restarting anyway' }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'aegis.bot\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
$stamp = Get-Date -Format 'HHmmss'
if (Test-Path "$root/logs/bot_out.log") { Copy-Item "$root/logs/bot_out.log" "$root/logs/bot_out_$stamp.log" }
if (Test-Path "$root/logs/bot_err.log") { Copy-Item "$root/logs/bot_err.log" "$root/logs/bot_err_$stamp.log" }
$env:PYTHONPATH = ''
Start-Process -FilePath $py -ArgumentList 'aegis/bot.py' -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput "$root/logs/bot_out.log" -RedirectStandardError "$root/logs/bot_err.log"
Write-Output 'bot restarted (detached)'
