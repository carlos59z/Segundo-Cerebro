# start-openviking.ps1
# Arranca OpenViking server en segundo plano y espera health.
$ErrorActionPreference = "Stop"
$port = 1933

# uv puede haberse instalado en ~/.local/bin sin estar en PATH de esta sesion
$uvLocal = Join-Path $env:USERPROFILE ".local\bin"
if ((Test-Path (Join-Path $uvLocal "uv.exe")) -and (-not (Get-Command uv -ErrorAction SilentlyContinue))) {
    $env:Path = "$uvLocal;$env:Path"
}

$alive = $false
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
    $alive = $true
} catch { }

if ($alive) { Write-Host "OpenViking ya corre en :$port"; exit 0 }

$serverExe = Join-Path $uvLocal "openviking-server.exe"
if (-not (Test-Path $serverExe)) {
    Write-Warning "No encontre $serverExe. Corre primero setup-openviking.ps1."
    exit 1
}

Start-Process -FilePath $serverExe -WindowStyle Hidden `
    -RedirectStandardOutput "$PSScriptRoot\..\ov_out.log" `
    -RedirectStandardError "$PSScriptRoot\..\ov_err.log"

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
        Write-Host "OpenViking OK en :$port"
        exit 0
    } catch { }
}
Write-Warning "OpenViking no respondio en 60s. Revisa ov_err.log."
exit 1
