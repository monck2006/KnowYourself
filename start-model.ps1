# Starts the local server with the DeepSeek model enabled for THIS PowerShell session.
# The key is read with masked input and is never written to disk, the repo, or logs.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not $env:ZHIJI_LLM_BASE_URL) { $env:ZHIJI_LLM_BASE_URL = 'https://api.deepseek.com' }
if (-not $env:ZHIJI_LLM_MODEL)    { $env:ZHIJI_LLM_MODEL = 'deepseek-v4-flash' }
$env:ZHIJI_LLM_ENABLED = 'true'

$secure = Read-Host 'DeepSeek API Key' -AsSecureString
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', $secure).Password
if (-not $env:DEEPSEEK_API_KEY) { throw 'No key entered; nothing started.' }

Write-Host 'Model enabled for this session. Key stays in memory only.'
& (Join-Path $PSScriptRoot 'start.ps1') -Local
