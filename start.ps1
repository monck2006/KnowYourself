param(
    [ValidateRange(0, 65535)][int]$Port = 8788,
    [ValidateNotNullOrEmpty()][string]$BindAddress = '127.0.0.1',
    [switch]$Local
)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw '请先按照 README 创建 .venv 并安装 Python 依赖。' }
if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend/dist/index.html'))) { throw '请先在 frontend 运行 pnpm build。' }

function Get-UsablePort([System.Net.IPAddress]$Address, [int]$RequestedPort) {
    $listener = [System.Net.Sockets.TcpListener]::new($Address, $RequestedPort)
    $listener.Server.ExclusiveAddressUse = $true
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally { $listener.Stop() }
}

$bindIp = [System.Net.IPAddress]::None
if (![System.Net.IPAddress]::TryParse($BindAddress, [ref]$bindIp)) {
    $addresses = @([System.Net.Dns]::GetHostAddresses($BindAddress))
    $bindIp = $addresses | Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } | Select-Object -First 1
    if (!$bindIp) { $bindIp = $addresses | Select-Object -First 1 }
    if (!$bindIp) { throw '无法解析服务绑定地址。' }
}
try { $actualPort = Get-UsablePort $bindIp $Port }
catch {
    $fault = $_.Exception
    while ($fault.InnerException) { $fault = $fault.InnerException }
    if ($fault -is [System.Net.Sockets.SocketException] -and $fault.NativeErrorCode -in @(10013, 10048)) {
        $actualPort = Get-UsablePort $bindIp 0
        Write-Host ('端口 {0} 被占用或属于 Windows 保留范围，改用可用端口 {1}。' -f $Port, $actualPort)
    }
    else { throw }
}

$displayAddress = $bindIp.ToString()
if ($bindIp.Equals([System.Net.IPAddress]::Any)) { $displayAddress = '127.0.0.1' }
elseif ($bindIp.Equals([System.Net.IPAddress]::IPv6Any)) { $displayAddress = '::1' }
if ($displayAddress.Contains(':')) { $displayAddress = '[' + $displayAddress + ']' }
$variables = @('ZHIJI_DATABASE_URL', 'ZHIJI_DATABASE_PATH', 'ZHIJI_KNOWLEDGE_DATABASE_PATH', 'ZHIJI_COOKIE_SECURE')
$previousEnvironment = @{}
$locationChanged = $false
try {
    if ($Local) {
        foreach ($name in $variables) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
        Remove-Item Env:ZHIJI_DATABASE_URL -ErrorAction SilentlyContinue
        $env:ZHIJI_DATABASE_PATH = Join-Path $PSScriptRoot 'backend/data/zhiji.sqlite3'
        $env:ZHIJI_KNOWLEDGE_DATABASE_PATH = Join-Path $PSScriptRoot 'backend/data/zhiji.knowledge.sqlite3'
        $env:ZHIJI_COOKIE_SECURE = 'false'
        Write-Host ('本地 SQLite：{0}' -f $env:ZHIJI_DATABASE_PATH)
        Write-Host ('本地知识库：{0}' -f $env:ZHIJI_KNOWLEDGE_DATABASE_PATH)
    }
    Write-Host ('打开 http://{0}:{1}；接口文档 http://{0}:{1}/docs' -f $displayAddress, $actualPort)
    Push-Location (Join-Path $PSScriptRoot 'backend')
    $locationChanged = $true
    & $pythonPath -m uvicorn app.main:app --host $BindAddress --port $actualPort
    if ($LASTEXITCODE -ne 0) { throw ('服务退出，错误码 {0}。' -f $LASTEXITCODE) }
}
finally {
    if ($locationChanged) { Pop-Location }
    if ($Local) {
        foreach ($name in $variables) {
            if ($null -eq $previousEnvironment[$name]) { Remove-Item ('Env:' + $name) -ErrorAction SilentlyContinue }
            else { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
        }
    }
}
