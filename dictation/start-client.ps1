$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$projectRoot = $PSScriptRoot
$clientScript = Join-Path $projectRoot 'core_client.py'
# One Python environment for the whole repo: ..\.venv
$pythonw = Join-Path (Split-Path $projectRoot -Parent) '.venv\Scripts\pythonw.exe'
New-Item -ItemType Directory -Force (Join-Path $projectRoot 'logs') | Out-Null
$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($clientScript)
}
if (-not $existing) {
    $client = Start-Process -PassThru -FilePath $pythonw -ArgumentList @("`"$clientScript`"") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$projectRoot\logs\client-console.log" -RedirectStandardError "$projectRoot\logs\client-error.log"
    if ($client.WaitForExit(4000)) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show('Dictation could not start. Details are in dictation\logs\client-error.log.', 'Utter') | Out-Null
        throw 'The dictation client exited during startup.'
    }
}
