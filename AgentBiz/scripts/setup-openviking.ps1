# setup-openviking.ps1
# Instala OpenViking server (uv) y genera ~/.openviking/ov.conf con NVIDIA NIM.
# No imprime claves. Requiere NVIDIA_API_KEY en el .env de AgentBiz.
$ErrorActionPreference = "Stop"

$envFileAgent = Join-Path $PSScriptRoot "..\.env"           # AgentBiz/.env
$envFileRoot = Join-Path $PSScriptRoot "..\..\.env"          # raiz del repo (Segundo-Cerebro/.env)
$envFile = if (Test-Path $envFileAgent) { $envFileAgent } elseif (Test-Path $envFileRoot) { $envFileRoot } else { $envFileAgent }
$confDir = Join-Path $env:USERPROFILE ".openviking"
$conf = Join-Path $confDir "ov.conf"

function Get-EnvValue([string]$name) {
    foreach ($file in @($envFileAgent, $envFileRoot)) {
        if (-not (Test-Path $file)) { continue }
        foreach ($line in Get-Content $file) {
            if ($line -match "^$name=(.+)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
        }
    }
    return $null
}

# 1. uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando uv..."
    $uvLocal = Join-Path $env:USERPROFILE ".local\bin"
    if (Test-Path (Join-Path $uvLocal "uv.exe")) {
        $env:Path = "$uvLocal;$env:Path"
    } else {
        irm https://astral.sh/uv/install.ps1 | iex
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv no disponible. Reinstala con: irm https://astral.sh/uv/install.ps1 | iex"
}

# 2. paquete openviking
Write-Host "Instalando openviking..."
uv tool install openviking --upgrade

# 3. claves (sin imprimirlas)
$nvidiaKey = Get-EnvValue "NVIDIA_API_KEY"
if (-not $nvidiaKey) { throw "Falta NVIDIA_API_KEY en $envFile" }
$ovKey = Get-EnvValue "OPENVIKING_API_KEY"
if (-not $ovKey) {
    $ovKey = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    Add-Content -Path $envFile -Value "OPENVIKING_API_KEY=$ovKey"
    Write-Host "OPENVIKING_API_KEY generada en .env (no se muestra)."
}
if (-not (Get-EnvValue "OPENVIKING_URL")) {
    Add-Content -Path $envFile -Value "OPENVIKING_URL=http://127.0.0.1:1933"
}

# 3.5. asegurar que ~/.local/bin (uv tools) esta en PATH de esta sesion
$uvLocal = Join-Path $env:USERPROFILE ".local\bin"
if ((Test-Path (Join-Path $uvLocal "uv.exe")) -and ($env:Path -notlike "*$uvLocal*")) {
    $env:Path = "$uvLocal;$env:Path"
}

# 4. ov.conf
New-Item -ItemType Directory -Force -Path $confDir | Out-Null
$confObj = @{
    storage = @{
        workspace = (Join-Path $confDir "data")
        vectordb  = @{ name = "context"; backend = "local" }
        agfs      = @{ backend = "local" }
    }
    embedding = @{
        dense = @{
            api_base  = "https://integrate.api.nvidia.com/v1"
            api_key   = $nvidiaKey
            provider  = "openai"
            model     = "nvidia/nemotron-3-embed-1b"
            dimension = 2048
        }
    }
    vlm = @{
        api_base = "https://integrate.api.nvidia.com/v1"
        api_key  = $nvidiaKey
        provider = "openai"
        model    = "meta/llama-3.2-11b-vision-instruct"
    }
    server = @{
        host         = "127.0.0.1"
        port         = 1933
        auth_mode    = "api_key"
        root_api_key = $ovKey
    }
}
$confJson = $confObj | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($conf, $confJson, (New-Object System.Text.UTF8Encoding $false))
Write-Host "ov.conf escrito en $conf (claves no mostradas)."

# 5. verificacion del embedding en NIM
Write-Host "Verificando embedding en NIM..."
$probe = @{ model = "nvidia/nemotron-3-embed-1b"; input = "prueba" } | ConvertTo-Json
try {
    $r = Invoke-RestMethod -Uri "https://integrate.api.nvidia.com/v1/embeddings" `
        -Method Post -Headers @{ Authorization = "Bearer $nvidiaKey"; "Content-Type" = "application/json" } `
        -Body $probe -TimeoutSec 30
    Write-Host "Embedding OK (dimension: $($r.data[0].embedding.Count))."
} catch {
    Write-Warning "El embedding no respondio ($($_.Exception.Message)). Ajusta 'model'/'dimension' en $conf y vuelve a correr."
}

# 6. doctor (ejecutable instalado por uv tool, no paquete)
Write-Host "Ejecutando doctor..."
& (Join-Path $uvLocal "openviking-server.exe") doctor
if ($LASTEXITCODE -ne 0) { Write-Warning "doctor reporto problemas (revisa arriba)." }
Write-Host "Setup listo. Arranca con: .\start-openviking.ps1"
