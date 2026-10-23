# Сборка установщика Nexora.
#   powershell -ExecutionPolicy Bypass -File installer\rust\build.ps1 -Version 1.5.0 [-App <папка dist\NexoraLauncher>] [-Out <exe>]
# Сначала нужно собрать сам лаунчер: python scripts/build.py (появится dist\NexoraLauncher).
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$App = "",
    [string]$Out = "",
    [int]$Preset = 9
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$repoDist = Join-Path $root "..\..\dist"
if (-not $App) { $App = Join-Path $repoDist "NexoraLauncher" }
if (-not $Out) { $Out = Join-Path $repoDist "NexoraLauncher-$Version-setup.exe" }
if (-not (Test-Path (Join-Path $App "NexoraLauncher.exe"))) {
    throw "Нет собранного лаунчера в $App — сначала python scripts/build.py"
}

# Rust (rustup ставит в ~/.cargo/bin)
$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path $cargoBin) { $env:Path = "$cargoBin;$env:Path" }

# MinGW нужен только тулчейну GNU (dlltool без ассемблера as не работает); с MSVC, как на CI, — не нужен
$gnu = ((rustc -vV | Select-String "^host:").ToString()) -match "gnu"
if ($gnu) {
    $mingw = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -Filter "BrechtSanders.WinLibs*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "mingw64\bin" } | Where-Object { Test-Path (Join-Path $_ "as.exe") } | Select-Object -First 1
    if ($mingw) { $env:Path = "$mingw;$env:Path" }
    elseif (-not (Get-Command as.exe -ErrorAction SilentlyContinue)) {
        throw "Не найден MinGW (as.exe). Установите: winget install BrechtSanders.WinLibs.POSIX.UCRT --source winget"
    }
}

Push-Location $root
try {
    cargo build --release --locked
    if ($LASTEXITCODE -ne 0) { throw "cargo build завершился с ошибкой" }
    & (Join-Path $root "target\release\nexora-pack.exe") --app $App --version $Version --preset $Preset --out $Out
    if ($LASTEXITCODE -ne 0) { throw "упаковка завершилась с ошибкой" }
}
finally { Pop-Location }
