$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$projectRoot = $PSScriptRoot
$runtime = Join-Path $projectRoot 'internal\runtime'
$serverExe = Join-Path $runtime 'start_server.exe'
New-Item -ItemType Directory -Force (Join-Path $projectRoot 'logs') | Out-Null
$existing = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $serverExe }
if (-not $existing) {
    Start-Process -FilePath $serverExe -WorkingDirectory $runtime -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\logs\server-console.log" -RedirectStandardError "$projectRoot\logs\server-error.log"
}
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $ready = [bool](Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 6016 -State Listen -ErrorAction SilentlyContinue)
    if ($ready) { break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'Speech server did not start. Check logs\server-error.log.' }
& "$projectRoot\start-client.ps1"
