$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$clientScript = Join-Path $projectRoot 'core_client.py'
$serverExe = Join-Path $projectRoot 'internal\runtime\start_server.exe'
$owned = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $serverExe -or ($_.CommandLine -and $_.CommandLine.Contains($clientScript))
}
$ownedIds = @($owned | ForEach-Object { $_.ProcessId })
foreach ($process in $owned) {
    if ($process.ParentProcessId -notin $ownedIds -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
        & taskkill.exe /PID $process.ProcessId /T /F | Out-Null
    }
}
