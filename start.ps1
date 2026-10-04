param([int]$Port = 8788, [string]$BindAddress = '127.0.0.1')
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw '请先按照 README 创建 .venv 并安装 Python 依赖。' }
if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend/dist/index.html'))) { throw '请先在 frontend 运行 pnpm build。' }
Push-Location (Join-Path $PSScriptRoot 'backend')
try { & $pythonPath -m uvicorn app.main:app --host $BindAddress --port $Port }
finally { Pop-Location }
