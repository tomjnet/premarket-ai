#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Blocks LAN access to Ollama (TCP 11434) while WSL and localhost keep working.
.DESCRIPTION
  Ollama has no authentication and OLLAMA_HOST=0.0.0.0 makes it listen on every
  interface. These inbound BLOCK rules apply only to physical Wired and Wireless
  adapters, so other machines on your network cannot reach it. Loopback and the
  WSL virtual networking are not affected. Block rules win over any "allow
  ollama.exe" rule Windows may have created on first run.
.PARAMETER Remove
  Removes the rules again.
.EXAMPLE
  .\03_ollama-firewall.ps1
  .\03_ollama-firewall.ps1 -Remove
#>
param([switch]$Remove)
$ErrorActionPreference = 'Stop'

$prefix = 'premarket-ai: block Ollama 11434 from LAN'

Get-NetFirewallRule -DisplayName "$prefix*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) {
    Write-Host 'Removed premarket-ai Ollama firewall rules.'
    return
}

foreach ($type in 'Wired', 'Wireless') {
    New-NetFirewallRule -DisplayName "$prefix ($type)" `
        -Direction Inbound -Action Block -Protocol TCP -LocalPort 11434 `
        -InterfaceType $type -Profile Any | Out-Null
    Write-Host "Added: $prefix ($type)"
}

Write-Host ''
Write-Host 'Check from WSL (should work):   curl http://localhost:11434/api/version'
Write-Host 'Check from another device on your network (should FAIL): http://<this-PC-IP>:11434/api/version'
Write-Host 'If WSL containers cannot reach Ollama after this, run scripts/wsl/03_check-ollama.sh and'
Write-Host 'temporarily remove the rules with: .\03_ollama-firewall.ps1 -Remove'
