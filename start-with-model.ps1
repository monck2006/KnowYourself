param(
    [string]$BaseUrl = 'https://api.deepseek.com',
    [string]$Model = 'deepseek-v4-flash',
    [string]$BindAddress = '127.0.0.1',
    [int]$Port = 8788,
    [switch]$NoLocal
)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw '请先按照 README 创建 .venv 并安装 Python 依赖。' }

# Opt-in model explanations. Keep the user-specified model name; do not substitute.
$env:ZHIJI_LLM_ENABLED = 'true'
$env:ZHIJI_LLM_BASE_URL = $BaseUrl
$env:ZHIJI_LLM_MODEL = $Model

# Load a project-local, git-ignored env file if present (see root .gitignore).
# Put DEEPSEEK_API_KEY=... here once to persist the key for this project.
$localEnv = Join-Path $PSScriptRoot '.env.local'
if (Test-Path -LiteralPath $localEnv) {
    foreach ($line in Get-Content -LiteralPath $localEnv -Encoding UTF8) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
        $pair = $trimmed -split '=', 2
        if ($pair.Count -eq 2) {
            $name = $pair[0].Trim()
            $value = $pair[1].Trim().Trim('"').Trim("'")
            if ($name -and [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
}

# Read the key from the environment (or the local env file above) if present; otherwise prompt with masked input.
# The key stays in the environment only: never written to source, examples, tests, Git or the browser.
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY) -and [string]::IsNullOrWhiteSpace($env:ZHIJI_LLM_API_KEY)) {
    $secret = Read-Host 'DeepSeek API Key' -AsSecureString
    $plainKey = [System.Net.NetworkCredential]::new('', $secret).Password
    if ([string]::IsNullOrWhiteSpace($plainKey)) { throw '未输入密钥，已取消。' }
    $env:DEEPSEEK_API_KEY = $plainKey
    Remove-Variable secret, plainKey
} else {
    Write-Host '使用已配置的环境变量中的模型密钥（不再提示输入）。'
}

Write-Host ('模型已启用：{0}（{1}）' -f $Model, $BaseUrl)
$arguments = @('-Port', $Port, '-BindAddress', $BindAddress)
if (!$NoLocal) { $arguments += '-Local' }
& (Join-Path $PSScriptRoot 'start.ps1') @arguments
