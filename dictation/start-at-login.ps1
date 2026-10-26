$ErrorActionPreference = 'Stop'
# A client-only install (no speech server here) uses another PC's server over Tailscale.
if (Test-Path (Join-Path $PSScriptRoot 'internal\runtime\start_server.exe')) {
    & "$PSScriptRoot\start-dictation.ps1"
} else {
    & "$PSScriptRoot\start-client.ps1"
}
