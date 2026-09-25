#Requires -Version 5.1
<#
.SYNOPSIS
  Installs the premarket-ai global WSL2 config to C:\Users\<you>\.wslconfig.
.DESCRIPTION
  Backs up any existing .wslconfig, copies wslconfig.example over it, and tells you
  how to apply it. Does NOT shut WSL down for you (that would stop running work).
#>
$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot 'wslconfig.example'
$dst = Join-Path $env:UserProfile '.wslconfig'

if (Test-Path $dst) {
    $backup = "$dst.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item $dst $backup
    Write-Host "Backed up existing .wslconfig to $backup"
}

Copy-Item $src $dst -Force
Write-Host "Installed $dst"
Write-Host ''
Write-Host 'Apply it (stops all WSL distros):'
Write-Host '  wsl --shutdown'
Write-Host 'Wait ~8 seconds, open Ubuntu, then check:'
Write-Host '  free -h          # ~16 GB'
Write-Host '  nproc            # 6'
Write-Host '  wslinfo --networking-mode   # mirrored'
