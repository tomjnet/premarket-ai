#Requires -Version 5.1
<#
.SYNOPSIS
  Pulls the gpu4gb model set into Windows Ollama (GTX 1650, 4 GB VRAM).
.DESCRIPTION
  Benchmark candidates for the main LLM (the increment 3 benchmark picks one), plus the
  guard and embedding models. Roughly 12 GB of disk under %UserProfile%\.ollama\models.
.PARAMETER Models
  Override the list, e.g. -Models qwen3:4b,nomic-embed-text
#>
param(
    [string[]]$Models = @(
        'qwen3:4b-instruct', # benchmark candidate (Qwen3 4B 2507, no thinking)
        'llama3.2:3b',       # benchmark candidate
        'phi4-mini',         # benchmark candidate
        'gemma3:4b',         # benchmark candidate
        'llama-guard3:1b',   # guardrail (input/output safety)
        'nomic-embed-text'   # embeddings (RAG + dedup L3)
    )
)
$ErrorActionPreference = 'Stop'

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw 'ollama CLI not found in PATH.'
}

foreach ($m in $Models) {
    Write-Host "==> ollama pull $m"
    ollama pull $m
    if ($LASTEXITCODE -ne 0) { throw "Pull failed: $m" }
}

Write-Host ''
ollama list
