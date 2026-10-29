param(
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'),
    [int]$Port = 5000
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw '找不到 Python 环境，请通过 -PythonPath 指定已安装依赖的 python.exe。'
    }
    if (-not $env:FLASK_SECRET_KEY) {
        $randomBytes = New-Object byte[] 32
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
        $env:FLASK_SECRET_KEY = ([BitConverter]::ToString($randomBytes)).Replace('-', '').ToLowerInvariant()
    }
    $env:PORT = "$Port"
    $env:PYTHONIOENCODING = 'utf-8'
    & $PythonPath -B init_schema.py
    if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败，请检查 MongoDB 连接和上方错误。' }
    Write-Host "网页地址：http://127.0.0.1:$Port"
    & $PythonPath -B app.py
} finally {
    Pop-Location
}
