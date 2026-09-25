#Requires -Version 5.1
<#
.SYNOPSIS
  Configures Ollama on Windows for premarket-ai and restarts it.
.DESCRIPTION
  Sets the Ollama variables as *user* environment variables (persistent), then
  restarts the Ollama tray app so the server picks them up.
  OLLAMA_HOST=0.0.0.0 lets WSL containers reach Ollama. Run 03_ollama-firewall.ps1
  (as admin) afterwards so your LAN cannot reach it - Ollama has no authentication.
#>
$ErrorActionPreference = 'Stop'

$vars = [ordered]@{
    OLLAMA_HOST              = '0.0.0.0:11434'  # reachable from WSL, not only Windows localhost
    OLLAMA_MAX_LOADED_MODELS = '1'              # one model on the 4 GB GPU at a time
    OLLAMA_NUM_PARALLEL      = '2'              # two requests in parallel per model
    OLLAMA_KEEP_ALIVE        = '30m'            # keep the model loaded during a run
}

foreach ($k in $vars.Keys) {
    [Environment]::SetEnvironmentVariable($k, $vars[$k], 'User')
    # Also set it for this process, so the Ollama app started below inherits it.
    Set-Item -Path "Env:$k" -Value $vars[$k]
    Write-Host ('{0,-26} = {1}' -f $k, $vars[$k])
}

Write-Host ''
Write-Host 'Restarting Ollama...'
Get-Process -Name 'ollama app', 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

$app = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
if (-not (Test-Path $app)) {
    throw "Ollama app not found at $app - start Ollama manually."
}
Start-Process -FilePath $app

# Wait for the API to come up.
$ok = $false
foreach ($i in 1..15) {
    try {
        $v = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
        Write-Host "Ollama $($v.version) is up on 0.0.0.0:11434"
        $ok = $true
        break
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { Write-Warning 'Ollama did not answer on 127.0.0.1:11434 within 15 s.' }

Write-Host ''
Write-Host 'Next: run 03_ollama-firewall.ps1 in an *elevated* PowerShell to block LAN access.'
