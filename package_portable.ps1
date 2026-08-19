#Requires -Version 5.1
# Build a fully portable Miku Cure package (CPU torch only, extract-and-run).
# Design reference: RAG-PRO package_release.ps1
[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [string]$LauncherPath = "",
    [string]$LauncherSha256 = "",
    [string]$DownloadProxy = $env:MIKU_DOWNLOAD_PROXY,
    [switch]$SkipMedia,
    [switch]$IncludeUserModels,
    [switch]$KeepStaging,
    [switch]$SkipLauncherBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$BuildId = $Timestamp + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$PackageName = "MikuCure-portable-$BuildId"
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $ProjectRoot "packages"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$Staging = Join-Path $OutputDirectory (".release-staging-" + $BuildId)
$PkgRoot = Join-Path $Staging "MikuCure"
$ArchivePath = Join-Path $OutputDirectory ($PackageName + ".zip")
$PythonVersion = "3.13.12"
$PythonEmbedSha256 = "76F238F606250C87C6BEAC75DCCD35EE99070A13490555936ABB6CB64ECCE3D0"
$frontendPackage = Get-Content -LiteralPath (Join-Path $ProjectRoot "frontend\package.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$AppVersion = [string]$frontendPackage.version
if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid frontend/package.json version: $AppVersion"
}

$script:Bytes = [int64]0
$script:Files = 0
$script:BuildSucceeded = $false

function Write-Step([string]$msg) {
    Write-Host ("[*] " + $msg) -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
    Write-Host ("[OK] " + $msg) -ForegroundColor Green
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Assert-Sha256([string]$Path, [string]$Expected, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description is missing: $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected) {
        throw "$Description SHA256 mismatch. Expected $Expected, got $actual"
    }
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
            foreach ($segment in $rel.Split('\')) {
                if ($segment -like $d) {
                    $skip = $true
                    break
                }
            }
            if ($skip) { break }
        }
        if (-not $skip) {
            foreach ($seg in $rel.Split('\')) {
                if ($seg -eq '__pycache__' -or $seg -eq '.pytest_cache') {
                    $skip = $true
                    break
                }
            }
        }
        if (-not $skip) {
            foreach ($pattern in $ExcludeFiles) {
                if ($item.Name -like $pattern) {
                    $skip = $true
                    break
                }
            }
        }
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
        # The source root is node_modules/electron, so locale paths begin at dist/.
        if ($rel -match '(^|\\)dist\\locales\\([^\\]+)$') {
            if ($Matches[2] -notin @('en-US.pak', 'zh-CN.pak', 'ja.pak')) { continue }
        }
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

try {
    Write-Step ("Creating staging: " + $PkgRoot)
    New-Item -ItemType Directory -Path $PkgRoot -Force | Out-Null

# -- 0) Launcher --
$launcherExe = ""
if (-not $SkipLauncherBuild) {
    if ($LauncherPath) {
        throw "-LauncherPath may only be used together with -SkipLauncherBuild"
    }
    Write-Step "Building launcher into isolated staging (PyInstaller)..."
    $launcherDir = Join-Path $ProjectRoot "launcher"
    $launcherPython = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $launcherPython -PathType Leaf)) {
        throw "Launcher build environment missing. Run install.bat first: $launcherPython"
    }
    Invoke-NativeChecked -FilePath $launcherPython `
        -Arguments @('-c', 'from importlib.metadata import version; import PySide6, PyInstaller, PIL; assert version("PySide6") == "6.10.2"; assert version("pyinstaller") == "6.19.0"; assert version("Pillow") == "12.3.0"') `
        -Description "Launcher dependency validation"
    Invoke-NativeChecked -FilePath $launcherPython -Arguments @('-m', 'pip', 'check') -Description "Python dependency consistency check"

    $launcherDist = Join-Path $Staging "launcher-dist"
    $launcherWork = Join-Path $Staging "launcher-work"
    $launcherSpec = Join-Path $Staging "launcher-spec"
    New-Item -ItemType Directory -Path $launcherDist, $launcherWork, $launcherSpec -Force | Out-Null
    Push-Location $launcherDir
    try {
        Invoke-NativeChecked -FilePath $launcherPython -Arguments @('make_icon.py') -Description "Launcher icon generation"
        $pyInstallerArgs = @(
            '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onefile',
            '--name', 'MikuCure-Launcher', '--icon', (Join-Path $launcherDir 'icon.ico'),
            '--add-data', ((Join-Path $ProjectRoot 'miku\icon.png') + ';miku'),
            '--distpath', $launcherDist, '--workpath', $launcherWork,
            '--specpath', $launcherSpec, (Join-Path $launcherDir 'main.py')
        )
        Invoke-NativeChecked -FilePath $launcherPython -Arguments $pyInstallerArgs -Description "PyInstaller launcher build"
    } finally {
        Pop-Location
    }
    $launcherExe = Join-Path $launcherDist "MikuCure-Launcher.exe"
} else {
    if (-not $LauncherPath) {
        throw "-SkipLauncherBuild requires an explicit -LauncherPath; stale launchers are never selected implicitly"
    }
    if (-not $LauncherSha256 -or $LauncherSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
        throw "-SkipLauncherBuild requires -LauncherSha256 so the selected artifact cannot change silently"
    }
    $launcherExe = if ([System.IO.Path]::IsPathRooted($LauncherPath)) {
        [System.IO.Path]::GetFullPath($LauncherPath)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $LauncherPath))
    }
    Assert-Sha256 -Path $launcherExe -Expected $LauncherSha256.ToUpperInvariant() -Description "Prebuilt launcher"
}
if (-not (Test-Path -LiteralPath $launcherExe -PathType Leaf)) {
    throw "Fresh launcher artifact not found: $launcherExe"
}
$launcherInfo = Get-Item -LiteralPath $launcherExe
if ($launcherInfo.Length -lt 1MB) {
    throw "Launcher artifact is unexpectedly small: $($launcherInfo.Length) bytes"
}
$packagedLauncher = Join-Path $PkgRoot "MikuCure-Launcher.exe"
Copy-Item -LiteralPath $launcherExe -Destination $packagedLauncher -Force
if ((Get-FileHash -LiteralPath $launcherExe -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $packagedLauncher -Algorithm SHA256).Hash) {
    throw "Packaged launcher hash does not match the selected fresh artifact"
}
Write-Ok "Fresh launcher copied and hash verified"

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
        Assert-Sha256 -Path $embCache -Expected $PythonEmbedSha256 -Description "Cached Python embeddable archive"
        Copy-Item -LiteralPath $embCache -Destination $Dest -Force
        Write-Ok ("Using cached embed zip: " + $embCache)
        return
    }
    # Prefer curl.exe (more reliable than Invoke-WebRequest on some networks)
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        Write-Step "Downloading embed zip via curl..."
        $curlArgs = @('-L', '--fail', '--retry', '5', '--retry-delay', '3', '--connect-timeout', '30', '--max-time', '900')
        if ($DownloadProxy) { $curlArgs += @('--proxy', $DownloadProxy) }
        $curlArgs += @('-o', $Dest, $embUrl)
        Invoke-NativeChecked -FilePath $curl.Source -Arguments $curlArgs -Description "Python embeddable download"
    } else {
        Write-Step "Downloading embed zip via Invoke-WebRequest..."
        $requestArgs = @{ Uri = $embUrl; OutFile = $Dest; TimeoutSec = 900 }
        if ($DownloadProxy) { $requestArgs.Proxy = $DownloadProxy }
        Invoke-WebRequest @requestArgs
    }
    Assert-Sha256 -Path $Dest -Expected $PythonEmbedSha256 -Description "Downloaded Python embeddable archive"
    Copy-Item -LiteralPath $Dest -Destination $embCache -Force
    Write-Ok ("Cached embed zip at " + $embCache)
}

Get-PythonEmbedZip -Dest $embZip
Assert-Sha256 -Path $embZip -Expected $PythonEmbedSha256 -Description "Staged Python embeddable archive"
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
import json, platform, struct, sys
from importlib.metadata import PackageNotFoundError, version
import cv2, mediapipe, numpy, openai, PIL, torch, torchvision, websockets
assert sys.version_info[:3] == (3, 13, 12), sys.version
assert struct.calcsize("P") * 8 == 64, platform.architecture()
assert torch.version.cuda is None and not torch.cuda.is_available(), torch.__version__
expected = {
    "opencv-contrib-python": "4.13.0.92", "mediapipe": "0.10.35", "numpy": "2.5.0",
    "websockets": "16.0", "openai": "2.43.0", "python-dotenv": "1.2.2",
    "Pillow": "12.3.0", "torch": "2.12.1+cpu", "torchvision": "0.27.1+cpu",
}
for distribution, wanted in expected.items():
    assert version(distribution) == wanted, (distribution, version(distribution), wanted)
for conflicting in ("opencv-python", "opencv-python-headless", "opencv-contrib-python-headless"):
    try:
        installed = version(conflicting)
    except PackageNotFoundError:
        continue
    raise AssertionError(("conflicting OpenCV distribution", conflicting, installed))
print(json.dumps({
    "status": "CORE_OK",
    "python": platform.python_version(),
    "arch": platform.machine(),
    "torch": torch.__version__,
    "opencv": cv2.__version__,
    "mediapipe": mediapipe.__version__,
    "numpy": numpy.__version__,
    "openai": openai.__version__,
    "websockets": websockets.__version__,
}, sort_keys=True))
'@ | Set-Content -LiteralPath $checkPy -Encoding UTF8
& $venvPy $checkPy
if ($LASTEXITCODE -ne 0) { throw "venv core import failed" }

Write-Step "Copying locked runtime dependency closure (this may take several minutes)..."
$rtSP = Join-Path $pythonDir "Lib\site-packages"
$runtimeCopyTool = Join-Path $ProjectRoot "build_tools\copy_runtime_packages.py"
if (-not (Test-Path -LiteralPath $runtimeCopyTool -PathType Leaf)) {
    throw "Runtime dependency copier is missing: $runtimeCopyTool"
}
$runtimeRoots = @(
    "opencv-contrib-python", "mediapipe", "numpy", "websockets", "openai",
    "python-dotenv", "Pillow", "torch", "torchvision"
)
Invoke-NativeChecked -FilePath $venvPy `
    -Arguments (@($runtimeCopyTool, '--source', $venvSP, '--destination', $rtSP, '--roots') + $runtimeRoots) `
    -Description "Locked runtime dependency copy"
if (Get-ChildItem -LiteralPath $rtSP -Filter "*.pth" -File -ErrorAction SilentlyContinue | Select-Object -First 1) {
    throw "Executable .pth files are forbidden in the portable runtime"
}
$runtimeFiles = @(Get-ChildItem -LiteralPath $rtSP -Recurse -File -Force)
$script:Files += $runtimeFiles.Count
$script:Bytes += [int64](($runtimeFiles | Measure-Object -Property Length -Sum).Sum)

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
import json, platform, struct, sys
from importlib.metadata import PackageNotFoundError, version
import cv2, mediapipe, numpy, openai, PIL, torch, torchvision, websockets
assert sys.version_info[:3] == (3, 13, 12), sys.version
assert struct.calcsize("P") * 8 == 64, platform.architecture()
assert torch.version.cuda is None and not torch.cuda.is_available(), torch.__version__
expected = {
    "opencv-contrib-python": "4.13.0.92", "mediapipe": "0.10.35", "numpy": "2.5.0",
    "websockets": "16.0", "openai": "2.43.0", "python-dotenv": "1.2.2",
    "Pillow": "12.3.0", "torch": "2.12.1+cpu", "torchvision": "0.27.1+cpu",
}
for distribution, wanted in expected.items():
    assert version(distribution) == wanted, (distribution, version(distribution), wanted)
for conflicting in ("opencv-python", "opencv-python-headless", "opencv-contrib-python-headless"):
    try:
        installed = version(conflicting)
    except PackageNotFoundError:
        continue
    raise AssertionError(("conflicting OpenCV distribution", conflicting, installed))
for unwanted in ("torchaudio", "pandas", "scikit-learn", "scipy", "fastapi", "uvicorn", "psutil", "PySide6", "PyInstaller"):
    try:
        installed = version(unwanted)
    except PackageNotFoundError:
        continue
    raise AssertionError(("non-runtime distribution reached portable package", unwanted, installed))
print(json.dumps({
    "status": "EMBED_OK",
    "python": platform.python_version(),
    "arch": platform.machine(),
    "torch": torch.__version__,
    "opencv": cv2.__version__,
    "mediapipe": mediapipe.__version__,
    "numpy": numpy.__version__,
    "openai": openai.__version__,
    "websockets": websockets.__version__,
}, sort_keys=True))
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
    -ExcludeDirs @(".venv", "venv", "__pycache__", "tests", "user", "keys", "secrets") `
    -ExcludeFiles @(
        ".env", ".env.*", "test_*.py", "*_test.py", "*.pem", "*.key",
        "api.json", "backend.pid", "ws_port.json", "pet_control.json", "backend_control.json"
    )
if (-not (Test-Path (Join-Path $backendDst "models"))) {
    throw "backend/models is missing"
}
if (-not (Get-ChildItem -LiteralPath (Join-Path $backendDst "models") -Filter "*.pth" -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    throw "No backend model weights (*.pth) were packaged"
}
Write-Ok "Backend copied"

# -- 4) Frontend + Electron --
Write-Step "Copying frontend + Electron..."
$feSrc = Join-Path $ProjectRoot "frontend"
$feDst = Join-Path $PkgRoot "frontend"
$feNames = @(
    "main.js", "preload.js", "paths.js", "security.js", "renderer.js", "3d_runtime.js", "i18n.js", "style.css",
    "index.html", "settings.html", "settings_renderer.js", "chat.html", "chat_renderer.js",
    "report.html", "report_renderer.js", "report.css", "package.json"
)
foreach ($name in $feNames) {
    $s = Join-Path $feSrc $name
    if (-not (Test-Path -LiteralPath $s -PathType Leaf)) {
        throw "Required frontend file is missing: $s"
    }
    $d = Join-Path $feDst $name
    New-Item -ItemType Directory -Path (Split-Path $d) -Force | Out-Null
    Copy-Item -LiteralPath $s -Destination $d -Force
    $script:Files++
}
if (Test-Path (Join-Path $feSrc "assets")) {
    Copy-Tree -Src (Join-Path $feSrc "assets") -Dst (Join-Path $feDst "assets")
}
$elecSrc = Join-Path $feSrc "node_modules\electron"
if (-not (Test-Path -LiteralPath $elecSrc)) {
    throw "frontend/node_modules/electron not found. Run install.bat (npm ci)"
}
$electronPackagePath = Join-Path $elecSrc "package.json"
$electronPackage = Get-Content -LiteralPath $electronPackagePath -Raw -Encoding UTF8 | ConvertFrom-Json
$declaredElectron = [string]$frontendPackage.devDependencies.electron
$installedElectron = [string]$electronPackage.version
if ($declaredElectron -notmatch '^\d+\.\d+\.\d+$' -or $installedElectron -ne $declaredElectron) {
    throw "Electron dependency drift: package.json requires $declaredElectron but node_modules contains $installedElectron. Run install.bat (npm ci)."
}
$electronDistVersionPath = Join-Path $elecSrc "dist\version"
if (Test-Path -LiteralPath $electronDistVersionPath) {
    $electronDistVersion = (Get-Content -LiteralPath $electronDistVersionPath -Raw).Trim()
    if ($electronDistVersion -ne $declaredElectron) {
        throw "Electron binary drift: expected $declaredElectron but dist/version reports $electronDistVersion"
    }
}
Copy-ElectronTree -Src $elecSrc -Dst (Join-Path $feDst "node_modules\electron")
$elecExe = Join-Path $feDst "node_modules\electron\dist\electron.exe"
if (-not (Test-Path -LiteralPath $elecExe)) {
    throw "electron.exe missing after copy"
}
$threeSrc = Join-Path $feSrc "node_modules\three"
if (-not (Test-Path -LiteralPath $threeSrc -PathType Container)) {
    throw "frontend/node_modules/three not found. Run install.bat (npm ci)"
}
Copy-Tree -Src $threeSrc -Dst (Join-Path $feDst "node_modules\three")
$live2dPackages = @(
    "pixi.js",
    "@pixi\unsafe-eval",
    "pixi-live2d-display",
    "@hazart-pkg\live2d-core"
)
foreach ($packageName in $live2dPackages) {
    $packageSrc = Join-Path $feSrc ("node_modules\" + $packageName)
    if (-not (Test-Path -LiteralPath $packageSrc -PathType Container)) {
        throw "frontend/node_modules/$packageName not found. Run install.bat (npm ci)"
    }
    Copy-Tree -Src $packageSrc -Dst (Join-Path $feDst ("node_modules\" + $packageName))
}
Write-Ok "Frontend + Electron copied"

# -- 5) Media --
if (-not $SkipMedia) {
    Write-Step "Copying miku media..."
    $mikuSrc = Join-Path $ProjectRoot "miku"
    if (Test-Path -LiteralPath $mikuSrc) {
        $modelExclusions = if ($IncludeUserModels) { @() } else { @("models") }
        Copy-Tree -Src $mikuSrc -Dst (Join-Path $PkgRoot "miku") -ExcludeDirs $modelExclusions
        if ($IncludeUserModels) {
            Write-Ok "miku/ copied, including local character models"
        } else {
            Write-Ok "miku/ copied without local character models"
            Write-Warning "Local models were skipped because they may have separate redistribution terms. Use -IncludeUserModels only when their license allows it."
        }
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
$runtimeLockPath = Join-Path $PkgRoot "RUNTIME_DEPENDENCIES.json"
$runtimeLock = & $embPy -c "import importlib.metadata,json; print(json.dumps(dict(sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions() if d.metadata['Name'])),ensure_ascii=False,indent=2))" 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    throw ("Failed to inventory embedded runtime dependencies: " + $runtimeLock)
}
[System.IO.File]::WriteAllText($runtimeLockPath, $runtimeLock.Trim() + "`n", (New-Object System.Text.UTF8Encoding($false)))
$runtimeLockSha256 = (Get-FileHash -LiteralPath $runtimeLockPath -Algorithm SHA256).Hash
$manifestObj = [ordered]@{
    name              = "MikuCure"
    version           = $AppVersion
    mode              = "portable"
    torch             = "cpu"
    preferred_ws_port = 13939
    built_at          = (Get-Date).ToString("s")
    python            = $PythonVersion
    runtime_lock      = "RUNTIME_DEPENDENCIES.json"
    runtime_lock_sha256 = $runtimeLockSha256
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
echo ERROR: MikuCure-Launcher.exe is missing or the package is incomplete.
echo Direct startup is disabled because it cannot establish the authenticated local session.
pause
exit /b 1
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

# Refuse to archive common secret-bearing files or plaintext API key literals.
$forbiddenNames = Get-ChildItem -LiteralPath $PkgRoot -Recurse -Force -File | Where-Object {
    $_.Name -like '.env*' -or $_.Extension -in @('.pem', '.key', '.p12', '.pfx') -or $_.Name -eq 'api.json'
}
if ($forbiddenNames) {
    throw ("Secret-bearing files reached staging: " + (($forbiddenNames.FullName) -join ', '))
}
$secretHit = Get-ChildItem -LiteralPath $PkgRoot -Recurse -File -Include *.py,*.js,*.json,*.html,*.txt | Select-String -Pattern 'sk-[A-Za-z0-9_-]{24,}' | Select-Object -First 1
if ($secretHit) {
    throw "Possible plaintext API key reached staging: $($secretHit.Path):$($secretHit.LineNumber)"
}
Write-Ok "Staging secret scan passed"

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
        if ($LASTEXITCODE -ne 0) { throw "7-Zip failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
} else {
    Compress-Archive -Path (Join-Path $Staging "MikuCure") -DestinationPath $ArchivePath -CompressionLevel Optimal
}

if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf) -or (Get-Item -LiteralPath $ArchivePath).Length -le 0) {
    throw "Portable archive was not created correctly: $ArchivePath"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
try {
    $entries = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    foreach ($required in @(
        'MikuCure/MikuCure-Launcher.exe', 'MikuCure/PORTABLE_MANIFEST.json',
        'MikuCure/RUNTIME_DEPENDENCIES.json',
        'MikuCure/backend/main.py', 'MikuCure/frontend/main.js',
        'MikuCure/frontend/security.js', 'MikuCure/runtime/python/python.exe'
    )) {
        if ($required -notin $entries) { throw "Required ZIP entry is missing: $required" }
    }
    $forbiddenEntry = $entries | Where-Object {
        $_ -match '(^|/)\.env([^/]*$)' -or
        $_ -match '(^|/)(test_[^/]*\.py|[^/]*_test\.py)$' -or
        $_ -match '(^|/)(api\.json|backend\.pid|ws_port\.json|pet_control\.json|backend_control\.json)$'
    } | Select-Object -First 1
    if ($forbiddenEntry) { throw "Forbidden ZIP entry found: $forbiddenEntry" }
    $badLocale = $entries | Where-Object {
        $_ -match '/frontend/node_modules/electron/dist/locales/([^/]+)$' -and
        $Matches[1] -notin @('en-US.pak', 'zh-CN.pak', 'ja.pak')
    } | Select-Object -First 1
    if ($badLocale) { throw "Unexpected Electron locale in ZIP: $badLocale" }
} finally {
    $zip.Dispose()
}
Write-Ok "ZIP contents verified"

$hash = (Get-FileHash -Algorithm SHA256 -Path $ArchivePath).Hash
$hashPath = $ArchivePath + ".sha256"
[System.IO.File]::WriteAllText($hashPath, ($hash + "  " + $PackageName + ".zip`n"))
$sizeMB = [math]::Round(((Get-Item $ArchivePath).Length / 1MB), 1)
Write-Ok ("Package: " + $ArchivePath + " (" + $sizeMB + " MB)")
Write-Ok ("SHA256: " + $hashPath)
Write-Host ("Staged files~" + $script:Files + "  bytes~" + [math]::Round($script:Bytes / 1MB, 1) + " MB") -ForegroundColor DarkGray

$script:BuildSucceeded = $true
Write-Host ""
Write-Host "Done. Extract the zip and run MikuCure-Launcher.exe" -ForegroundColor Green
} finally {
    if (-not $script:BuildSucceeded) {
        Remove-Item -LiteralPath $ArchivePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath ($ArchivePath + ".sha256") -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $Staging) {
        if ($KeepStaging) {
            Write-Step ("Staging kept: " + $Staging)
        } else {
            Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
            Write-Step "Staging cleaned"
        }
    }
}
