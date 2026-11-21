<#
.SYNOPSIS
  Builds the PKOS Windows installer: stages every runtime into build\stage and runs electron-builder.

.DESCRIPTION
  Steps (each can be skipped):
    1. web      frontend production build              -> build\stage\web
    2. backend  PyInstaller onedir (packaging\pkos-api.spec) -> build\stage\pkos-api
    3. pgsql    PostgreSQL bin/lib/share + pgvector + MSVC runtime DLLs -> build\stage\pgsql
    4. ollama   ollama.exe + CPU, CUDA 13 and Vulkan libraries -> build\stage\ollama
    5. models   bge-small-en-v1.5 embedding model           -> build\stage\models
    6. licenses third-party notices                          -> build\stage\licenses
    7. package  electron-builder (NSIS installer, or -Unpacked for a plain folder) -> build\installer

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Unpacked -Skip backend
#>
param(
  # Steps to skip: web, backend, pgsql, ollama, models, licenses, package
  [string[]]$Skip = @(),
  # Build only the unpacked app folder (build\installer\win-unpacked), no installer
  [switch]$Unpacked,
  # PostgreSQL 16 install to copy from (needs include\ to compile pgvector)
  [string]$PgSource = "C:\Program Files\PostgreSQL\16",
  # Folder with a pgvector build already installed into a copy of PgSource (bin/lib/share); compiled when missing
  [string]$PgvectorStage = "",
  [string]$PgvectorVersion = "0.8.1",
  # Ollama install to copy the runtime from
  [string]$OllamaSource = "$env:LOCALAPPDATA\Programs\Ollama",
  # Hugging Face cache that already holds BAAI/bge-small-en-v1.5
  [string]$HfCache = "$env:USERPROFILE\.cache\huggingface\hub"
)
$ErrorActionPreference = "Stop"
# `powershell -File build.ps1 -Skip a,b` passes one string "a,b"; accept both forms.
$Skip = @($Skip | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$Root = Split-Path -Parent $PSScriptRoot
$Stage = Join-Path $Root "build\stage"
$Python = Join-Path $Root "venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $Stage | Out-Null

function Step($name, [scriptblock]$body) {
  if ($Skip -contains $name) { Write-Host "== skip $name" -ForegroundColor DarkGray; return }
  Write-Host "== $name" -ForegroundColor Cyan
  $t = Get-Date
  & $body
  Write-Host ("   done in {0:N0} s" -f ((Get-Date) - $t).TotalSeconds) -ForegroundColor DarkGray
}

function Copy-Tree($from, $to, [string[]]$exclude = @()) {
  if (Test-Path $to) { Remove-Item -Recurse -Force $to }
  New-Item -ItemType Directory -Force $to | Out-Null
  $xf = @(); foreach ($e in $exclude) { $xf += $e }
  $args = @($from, $to, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
  if ($xf.Count) { $args += "/XF"; $args += $xf }
  robocopy @args | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy $from -> $to failed ($LASTEXITCODE)" }
}

function Get-SizeMB($path) {
  "{0:N0} MB" -f ((Get-ChildItem $path -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
}

# ------------------------------------------------------------------------------------------------- 1. web
Step "web" {
  Push-Location (Join-Path $Root "frontend")
  try {
    if (-not (Test-Path node_modules)) { npm ci --no-fund --no-audit; if ($LASTEXITCODE) { throw "npm ci failed" } }
    npm run build; if ($LASTEXITCODE) { throw "frontend build failed" }
  } finally { Pop-Location }
  Copy-Tree (Join-Path $Root "frontend\dist") (Join-Path $Stage "web")
  Write-Host "   web: $(Get-SizeMB (Join-Path $Stage 'web'))"
}

# ------------------------------------------------------------------------------------------------- 2. backend
Step "backend" {
  & $Python -m PyInstaller --version | Out-Null
  if ($LASTEXITCODE) { throw "PyInstaller is not installed in the venv (pip install pyinstaller)" }
  & $Python -m PyInstaller (Join-Path $PSScriptRoot "pkos-api.spec") --noconfirm --log-level WARN `
    --distpath (Join-Path $Root "build\pyinstaller\dist") --workpath (Join-Path $Root "build\pyinstaller\work")
  if ($LASTEXITCODE) { throw "PyInstaller failed" }
  Copy-Tree (Join-Path $Root "build\pyinstaller\dist\pkos-api") (Join-Path $Stage "pkos-api")
  # Smoke test: the frozen app must import (catches missing hidden imports / data files).
  $env:PKOS_SECRET_KEY = "build-smoke-test-" + [guid]::NewGuid().ToString("N")
  $out = & (Join-Path $Stage "pkos-api\pkos-api.exe") --smoke-test 2>&1
  Remove-Item Env:PKOS_SECRET_KEY
  if ($LASTEXITCODE) { throw "frozen backend smoke test failed:`n$out" }
  Write-Host "   $($out | Select-Object -Last 1)"
  Write-Host "   pkos-api: $(Get-SizeMB (Join-Path $Stage 'pkos-api'))"
}

# ------------------------------------------------------------------------------------------------- 3. pgsql
function Build-Pgvector($pgCopy) {
  $vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -products * -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  if (-not $vs) { throw "MSVC C++ tools not found (Visual Studio Build Tools with 'Desktop development with C++')" }
  $src = Join-Path $Root "build\pgvector-src"
  $zip = Join-Path $src "pgvector-$PgvectorVersion.zip"
  New-Item -ItemType Directory -Force $src | Out-Null
  if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://github.com/pgvector/pgvector/archive/refs/tags/v$PgvectorVersion.zip" -OutFile $zip -UseBasicParsing
  }
  Expand-Archive $zip -DestinationPath $src -Force
  $vc = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
  cmd /c "`"$vc`" >nul && cd /d `"$src\pgvector-$PgvectorVersion`" && set `"PGROOT=$pgCopy`" && nmake /NOLOGO /F Makefile.win clean >nul 2>&1 & nmake /NOLOGO /F Makefile.win && nmake /NOLOGO /F Makefile.win install"
  if (-not (Test-Path (Join-Path $pgCopy "lib\vector.dll"))) { throw "pgvector build failed" }
}

Step "pgsql" {
  $out = Join-Path $Stage "pgsql"
  $work = if ($PgvectorStage) { $PgvectorStage } else { Join-Path $Root "build\pgsql-work" }
  if (-not (Test-Path (Join-Path $work "lib\vector.dll"))) {
    Write-Host "   compiling pgvector $PgvectorVersion against $PgSource"
    foreach ($d in "bin", "lib", "share", "include") { Copy-Tree (Join-Path $PgSource $d) (Join-Path $work $d) }
    Build-Pgvector $work
  }
  New-Item -ItemType Directory -Force $out | Out-Null
  # Not needed at runtime: debug symbols, import libraries, EDB's StackBuilder/pgAdmin helpers, and the PL/Perl,
  # PL/Python and PL/Tcl language plugins (they need Perl/Python/Tcl installed; PKOS never loads them).
  $plugins = @("plperl.dll", "plpython3.dll", "pltcl.dll", "*_plperl.dll", "*_plpython3.dll",
               "plperl*.control", "plperl*--*.sql", "plpython3u*", "pltcl*", "*_plperl*", "*_plpython3u*")
  foreach ($d in "bin", "lib", "share") {
    Copy-Tree (Join-Path $work $d) (Join-Path $out $d) (@("*.pdb", "*.lib", "stackbuilder.exe", "pgAdmin*") + $plugins)
  }
  # The EDB binaries rely on a system-wide Visual C++ runtime; ship it next to them (app-local deployment).
  foreach ($dll in "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll") {
    $from = Join-Path $env:WINDIR "System32\$dll"
    if (Test-Path $from) { Copy-Item $from (Join-Path $out "bin") -Force } else { Write-Warning "$dll not found" }
  }
  if (-not (Test-Path (Join-Path $out "share\extension\vector.control"))) { throw "pgvector missing from staged pgsql" }
  Write-Host "   pgsql: $(Get-SizeMB $out)"
}

# ------------------------------------------------------------------------------------------------- 4. ollama
Step "ollama" {
  $out = Join-Path $Stage "ollama"
  if (-not (Test-Path (Join-Path $OllamaSource "ollama.exe"))) { throw "ollama.exe not found in $OllamaSource" }
  if (Test-Path $out) { Remove-Item -Recurse -Force $out }
  New-Item -ItemType Directory -Force (Join-Path $out "lib\ollama") | Out-Null
  Copy-Item (Join-Path $OllamaSource "ollama.exe") $out
  Get-ChildItem (Join-Path $OllamaSource "lib\ollama") -File | Copy-Item -Destination (Join-Path $out "lib\ollama")
  # CPU backends are the loose DLLs above; add NVIDIA (CUDA 13) and Vulkan. ROCm and CUDA 12 are left out (size).
  foreach ($gpu in "cuda_v13", "vulkan") {
    $from = Join-Path $OllamaSource "lib\ollama\$gpu"
    if (Test-Path $from) { Copy-Tree $from (Join-Path $out "lib\ollama\$gpu") } else { Write-Warning "$gpu libraries not found" }
  }
  $version = (& (Join-Path $out "ollama.exe") --version 2>&1 | Select-String -Pattern '\d+\.\d+\.\d+').Matches.Value | Select-Object -Last 1
  Set-Content (Join-Path $out "VERSION") $version
  Write-Host "   ollama $version`: $(Get-SizeMB $out)"
}

# ------------------------------------------------------------------------------------------------- 5. models
Step "models" {
  $snapshots = Join-Path $HfCache "models--BAAI--bge-small-en-v1.5\snapshots"
  $snap = Get-ChildItem $snapshots -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
  if (-not $snap) { throw "BAAI/bge-small-en-v1.5 not in $HfCache (run the backend once, or set -HfCache)" }
  $out = Join-Path $Stage "models\bge-small-en-v1.5"
  # Copy-Item resolves the cache's symlinks (if any) into real files.
  if (Test-Path $out) { Remove-Item -Recurse -Force $out }
  Copy-Item $snap.FullName $out -Recurse
  Remove-Item (Join-Path $out "README.md") -ErrorAction SilentlyContinue
  if (-not (Test-Path (Join-Path $out "model.safetensors"))) { throw "model.safetensors missing" }
  Write-Host "   model: $(Get-SizeMB $out)"
}

# ------------------------------------------------------------------------------------------------- 6. licenses
Step "licenses" {
  $out = Join-Path $Stage "licenses"
  New-Item -ItemType Directory -Force $out | Out-Null
  Copy-Item (Join-Path $PSScriptRoot "THIRD_PARTY_NOTICES.txt") $out -Force
}

# ------------------------------------------------------------------------------------------------- 7. package
Step "package" {
  foreach ($d in "web", "pkos-api", "pgsql", "ollama", "models", "licenses") {
    if (-not (Test-Path (Join-Path $Stage $d))) { throw "build\stage\$d is missing; run that step first" }
  }
  Push-Location (Join-Path $Root "desktop")
  try {
    $target = if ($Unpacked) { "dir" } else { "nsis" }
    npx electron-builder --win $target --x64 --publish never
    if ($LASTEXITCODE) { throw "electron-builder failed" }
  } finally { Pop-Location }
  Get-ChildItem (Join-Path $Root "build\installer") -File -Filter "*.exe" -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("   {0}: {1:N0} MB" -f $_.Name, ($_.Length / 1MB)) }
}

Write-Host "== finished; staged runtime: $(Get-SizeMB $Stage)" -ForegroundColor Green
