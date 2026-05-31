$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "--- Checking Environment ---"

# Check for Git (Required for SpotiFLAC module)
try {
    git version
} catch {
    Write-Error "Git not found! Please install Git for Windows (https://git-scm.com/download/win) and restart your terminal."
    exit 1
}

$python = if (Test-Path ".venv-build\Scripts\python.exe") {
    ".venv-build\Scripts\python.exe"
} elseif (Test-Path "venv_build\Scripts\python.exe") {
    "venv_build\Scripts\python.exe"
} else {
    "python"
}

Write-Host "Using Python: $python"

Write-Host "--- Installing Dependencies ---"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt -r requirements-desktop.txt

Write-Host "--- Preparing Assets ---"
& $python scripts\make_desktop_icons.py

Write-Host "--- Building Executable ---"
# Use python -m PyInstaller to bypass PATH issues
& $python -m PyInstaller --clean --noconfirm Mindinguflac-windows.spec

Write-Host "--- Packaging ---"
$zipPath = Join-Path $root "Mindinguflac-windows.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

$exePath = Join-Path $root "dist\Mindinguflac.exe"
if (-not (Test-Path $exePath)) {
    Write-Error "Build failed: $exePath not found."
    exit 1
}

Compress-Archive -Path $exePath -DestinationPath $zipPath

Write-Host "--- Success ---"
Write-Host "Built: $zipPath"
