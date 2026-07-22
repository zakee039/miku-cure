#Requires -Version 5.1
# Build a fully portable Miku Cure package (CPU torch only, extract-and-run).
# Design reference: RAG-PRO package_release.ps1
[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [switch]$SkipMedia,
    [switch]$KeepStaging,
    [switch]$SkipLauncherBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$PackageName = "MikuCure-portable-$Timestamp"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ProjectRoot "packages"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$Staging = Join-Path $OutputDirectory (".release-staging-" + $Timestamp)
$PkgRoot = Join-Path $Staging "MikuCure"
$ArchivePath = Join-Path $OutputDirectory ($PackageName + ".zip")
$PythonVersion = "3.13.12"

$script:Bytes = [int64]0
$script:Files = 0

function Write-Step([string]$msg) {
    Write-Host ("[*] " + $msg) -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
    Write-Host ("[OK] " + $msg) -ForegroundColor Green
}

function Copy-Tree {
    param(
        [string]$Src,
        [string]$Dst,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )
    if (-not (Test-Path -LiteralPath $Src)) { return }
    $srcFull = (Resolve-Path -LiteralPath $Src).Path
    foreach ($item in Get-ChildItem -LiteralPath $srcFull -Recurse -Force -File -ErrorAction Stop) {
        $rel = $item.FullName.Substring($srcFull.Length).TrimStart('\')
        $skip = $false
        foreach ($d in $ExcludeDirs) {
            if ($rel -eq $d -or $rel.StartsWith($d + '\') -or $rel.Contains('\' + $d + '\') -or $rel.EndsWith('\' + $d)) {
                $skip = $true
                break
            }
        }
        if (-not $skip) {
            foreach ($seg in $rel.Split('\')) {
                if ($seg -eq '__pycache__' -or $seg -eq '.pytest_cache') {
                    $skip = $true
                    break
                }
            }
        }
        if (-not $skip -and ($ExcludeFiles -contains $item.Name)) { $skip = $true }
        if (-not $skip -and $item.Extension -in @('.pyc', '.pyo', '.log')) { $skip = $true }
        if ($skip) { continue }

        $dest = Join-Path $Dst $rel
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
        $script:Files++
        $script:Bytes += [int64]$item.Length
    }
}

function Copy-ElectronTree {
    param([string]$Src, [string]$Dst)
    if (-not (Test-Path -LiteralPath $Src)) { return }
    $srcFull = (Resolve-Path -LiteralPath $Src).Path
    foreach ($item in Get-ChildItem -LiteralPath $srcFull -Recurse -Force -File -ErrorAction SilentlyContinue) {
        $rel = $item.FullName.Substring($srcFull.Length).TrimStart('\')
        if ($rel -match '\\__pycache__\\') { continue }
        if ($item.Extension -in @('.pyc', '.pyo', '.map', '.log')) { continue }
        # keep en-US and zh-CN locales only
        if ($rel -match '\\electron\\dist\\locales\\' -and $rel -notmatch 'en-US|zh-CN') { continue }
        $dest = Join-Path $Dst $rel
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
        $script:Files++
        $script:Bytes += [int64]$item.Length
    }
}

Write-Step ("Creating staging: " + $PkgRoot)
New-Item -ItemType Directory -Path $PkgRoot -Force | Out-Null

# -- 0) Launcher --
$launcherExe = Join-Path $ProjectRoot "MikuCure-Launcher.exe"
if (-not $SkipLauncherBuild) {
    Write-Step "Building launcher (PyInstaller)..."
    $launcherDir = Join-Path $ProjectRoot "launcher"
    Push-Location $launcherDir
    try {
        python -m pip install -r requirements.txt pyinstaller pillow -q
        python make_icon.py
        python -m PyInstaller --noconfirm --clean --windowed --onefile `
            --name "MikuCure-Launcher" `
            --icon icon.ico `
            --add-data "..\miku\icon.png;miku" `
            --add-data "..\miku\icon.ico;miku" `
            --distpath ".." `
            main.py
    } finally {
        Pop-Location
    }
}
if (Test-Path -LiteralPath $launcherExe) {
    Copy-Item -LiteralPath $launcherExe -Destination (Join-Path $PkgRoot "MikuCure-Launcher.exe") -Force
    Write-Ok "Launcher copied"
} else {
    Write-Warning "MikuCure-Launcher.exe not found. Package will use start.bat fallback only."
}

# -- 1) Embeddable Python --
Write-Step ("Preparing Python " + $PythonVersion + " embeddable...")
$embZipName = "python-$PythonVersion-embed-amd64.zip"
$embZip = Join-Path $Staging "python-embed.zip"
$pythonDir = Join-Path $PkgRoot "runtime\python"
New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null
$embUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
# Cache location so re-packs do not re-download
$embCache = Join-Path $OutputDirectory $embZipName
$ProgressPreference = "SilentlyContinue"

function Get-PythonEmbedZip([string]$Dest) {
    if (Test-Path -LiteralPath $embCache) {
        Copy-Item -LiteralPath $embCache -Destination $Dest -Force
        Write-Ok ("Using cached embed zip: " + $embCache)
        return
    }
    # Prefer curl.exe (more reliable than Invoke-WebRequest on some networks)
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        Write-Step "Downloading embed zip via curl..."
        & curl.exe -L --retry 5 --retry-delay 3 --connect-timeout 30 --max-time 900 -o $Dest $embUrl
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Dest)) {
            throw "curl download failed for Python embeddable"
        }
    } else {
        Write-Step "Downloading embed zip via Invoke-WebRequest..."
        Invoke-WebRequest -Uri $embUrl -OutFile $Dest -TimeoutSec 900
    }
    Copy-Item -LiteralPath $Dest -Destination $embCache -Force
    Write-Ok ("Cached embed zip at " + $embCache)
}

Get-PythonEmbedZip -Dest $embZip
Expand-Archive -Path $embZip -DestinationPath $pythonDir -Force
Write-Ok "Python runtime extracted"

# -- 2) site-packages from venv (CPU torch) --
$venvSP = Join-Path $ProjectRoot "backend\.venv\Lib\site-packages"
$venvPy = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvSP)) {
    throw "backend\.venv not found. Run install.bat first (CPU torch)."
}
Write-Step "Validating venv imports (CPU)..."
$checkPy = Join-Path $Staging "check_core.py"
@'
import torch, cv2, numpy, websockets
print("CORE_OK", torch.__version__)
'@ | Set-Content -LiteralPath $checkPy -Encoding UTF8
& $venvPy $checkPy
if ($LASTEXITCODE -ne 0) { throw "venv core import failed" }

Write-Step "Copying site-packages (this may take several minutes)..."
$rtSP = Join-Path $pythonDir "Lib\site-packages"
Copy-Tree -Src $venvSP -Dst $rtSP `
    -ExcludeDirs @("__pycache__", "pip", "setuptools", "pkg_resources", "_distutils_hack", "tests", "test", "deepface", "tensorflow", "keras", "tensorboard", "tf_keras") `
    -ExcludeFiles @("distutils-precedence.pth", "_virtualenv.pth")

Get-ChildItem -LiteralPath $rtSP -Filter "*.pth" -File -ErrorAction SilentlyContinue | ForEach-Object {
    $txt = ""
    try { $txt = [System.IO.File]::ReadAllText($_.FullName) } catch {}
    if ($_.Name -in @("distutils-precedence.pth", "_virtualenv.pth") -or $txt -match "_distutils_hack") {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

$pthFile = Get-ChildItem -LiteralPath $pythonDir -Filter "*._pth" | Select-Object -First 1
if (-not $pthFile) { throw "python embeddable ._pth not found" }
$pyZip = Get-ChildItem -LiteralPath $pythonDir -Filter "python*.zip" | Select-Object -First 1
$zipName = if ($pyZip) { $pyZip.Name } else { "python313.zip" }
$pthContent = $zipName + "`n.`nLib\site-packages`nimport site`n"
[System.IO.File]::WriteAllText($pthFile.FullName, $pthContent, (New-Object System.Text.UTF8Encoding($false)))

$embPy = Join-Path $pythonDir "python.exe"
Write-Step "Validating embedded runtime..."
$checkEmbedPy = Join-Path $Staging "check_embed.py"
@'
import torch, cv2, numpy, websockets
print("EMBED_OK", torch.__version__)
'@ | Set-Content -LiteralPath $checkEmbedPy -Encoding UTF8
$embOut = & $embPy $checkEmbedPy 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $embOut -notmatch "EMBED_OK") {
    throw ("Embedded runtime import failed: " + $embOut)
}
Write-Ok ("Embedded Python OK: " + $embOut.Trim())

# -- 3) Backend source --
Write-Step "Copying backend..."
$backendSrc = Join-Path $ProjectRoot "backend"
$backendDst = Join-Path $PkgRoot "backend"
Copy-Tree -Src $backendSrc -Dst $backendDst `
    -ExcludeDirs @(".venv", "venv", "__pycache__", "tests") `
    -ExcludeFiles @()
if (-not (Test-Path (Join-Path $backendDst "models"))) {
    Write-Warning "backend/models missing"
}
Write-Ok "Backend copied"

# -- 4) Frontend + Electron --
Write-Step "Copying frontend + Electron..."
$feSrc = Join-Path $ProjectRoot "frontend"
$feDst = Join-Path $PkgRoot "frontend"
$feNames = @(
    "main.js", "preload.js", "paths.js", "renderer.js", "i18n.js", "style.css",
    "index.html", "settings.html", "settings_renderer.js", "chat.html", "chat_renderer.js",
    "report.html", "report_renderer.js", "report.css", "package.json"
)
foreach ($name in $feNames) {
    $s = Join-Path $feSrc $name
    if (Test-Path -LiteralPath $s) {
        $d = Join-Path $feDst $name
        New-Item -ItemType Directory -Path (Split-Path $d) -Force | Out-Null
        Copy-Item -LiteralPath $s -Destination $d -Force
        $script:Files++
    }
}
if (Test-Path (Join-Path $feSrc "assets")) {
    Copy-Tree -Src (Join-Path $feSrc "assets") -Dst (Join-Path $feDst "assets")
}
$elecSrc = Join-Path $feSrc "node_modules\electron"
if (-not (Test-Path -LiteralPath $elecSrc)) {
    throw "frontend/node_modules/electron not found. Run: cd frontend; npm install"
}
Copy-ElectronTree -Src $elecSrc -Dst (Join-Path $feDst "node_modules\electron")
$elecExe = Join-Path $feDst "node_modules\electron\dist\electron.exe"
if (-not (Test-Path -LiteralPath $elecExe)) {
    throw "electron.exe missing after copy"
}
Write-Ok "Frontend + Electron copied"

# -- 5) Media --
if (-not $SkipMedia) {
    Write-Step "Copying miku media..."
    $mikuSrc = Join-Path $ProjectRoot "miku"
    if (Test-Path -LiteralPath $mikuSrc) {
        Copy-Tree -Src $mikuSrc -Dst (Join-Path $PkgRoot "miku")
        Write-Ok "miku/ copied"
    } else {
        Write-Warning "miku/ not found"
    }
} else {
    Write-Warning "Media skipped (-SkipMedia)"
}

# -- 6) user template --
foreach ($d in @("user\keys", "user\lora", "user\memorize", "user\others", "logs")) {
    $p = Join-Path $PkgRoot $d
    New-Item -ItemType Directory -Path $p -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $p ".gitkeep"), "")
}

# -- 7) Manifest + start scripts --
Write-Step "Writing manifest and start scripts..."
$manifestObj = [ordered]@{
    name              = "MikuCure"
    version           = "1.1.1"
    mode              = "portable"
    torch             = "cpu"
    preferred_ws_port = 13939
    built_at          = (Get-Date).ToString("s")
    python            = $PythonVersion
    notes             = "Extract and run MikuCure-Launcher.exe. No system Python/Node/CUDA required."
}
$manifest = $manifestObj | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $PkgRoot "PORTABLE_MANIFEST.json"), $manifest)

$startBat = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "MIKU_PROJECT_ROOT=%~dp0"
set "MIKU_RESOURCES=%~dp0"
set "MIKU_USER_DIR=%~dp0user"
set "CUDA_VISIBLE_DEVICES="
if exist "MikuCure-Launcher.exe" (
  start "" "MikuCure-Launcher.exe"
  exit /b 0
)
echo Launcher exe missing. Starting backend + electron...
start "Miku Backend" "%~dp0runtime\python\python.exe" "%~dp0backend\main.py"
timeout /t 2 >nul
start "Miku Pet" "%~dp0frontend\node_modules\electron\dist\electron.exe" "%~dp0frontend"
"@
[System.IO.File]::WriteAllText((Join-Path $PkgRoot "start.bat"), $startBat)

$readmeLines = @(
    "Miku Cure Portable (CPU)",
    "",
    "1. Extract the MikuCure folder anywhere (need ~3GB free).",
    "2. Double-click MikuCure-Launcher.exe (or start.bat).",
    "3. Click One-Click Start in the launcher.",
    "",
    "Includes:",
    "  - runtime/python  (embedded Python + CPU PyTorch / OpenCV / MediaPipe)",
    "  - frontend Electron runtime",
    "  - backend models",
    "  - WebSocket default port 13939 (auto fallback if busy)",
    "",
    "No system Python / Node / CUDA required.",
    "User data is stored under user/."
)
$readmeText = ($readmeLines -join "`r`n") + "`r`n"
$utf8bom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText((Join-Path $PkgRoot "README-PORTABLE.txt"), $readmeText, $utf8bom)
Write-Ok "Manifest and scripts written"

# -- 8) Zip --
Write-Step ("Compressing to " + $ArchivePath + " ...")
if (Test-Path -LiteralPath $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}

$seven = @(
    "${env:ProgramFiles}\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($seven) {
    Push-Location $Staging
    try {
        & $seven a -tzip -mx=5 $ArchivePath "MikuCure\*" | Out-Null
    } finally {
        Pop-Location
    }
} else {
    Compress-Archive -Path (Join-Path $Staging "MikuCure") -DestinationPath $ArchivePath -CompressionLevel Optimal
}

$hash = (Get-FileHash -Algorithm SHA256 -Path $ArchivePath).Hash
$hashPath = $ArchivePath + ".sha256"
[System.IO.File]::WriteAllText($hashPath, ($hash + "  " + $PackageName + ".zip`n"))
$sizeMB = [math]::Round(((Get-Item $ArchivePath).Length / 1MB), 1)
Write-Ok ("Package: " + $ArchivePath + " (" + $sizeMB + " MB)")
Write-Ok ("SHA256: " + $hashPath)
Write-Host ("Staged files~" + $script:Files + "  bytes~" + [math]::Round($script:Bytes / 1MB, 1) + " MB") -ForegroundColor DarkGray

if (-not $KeepStaging) {
    Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
    Write-Step "Staging cleaned"
} else {
    Write-Step ("Staging kept: " + $Staging)
}

Write-Host ""
Write-Host "Done. Extract the zip and run MikuCure-Launcher.exe" -ForegroundColor Green
