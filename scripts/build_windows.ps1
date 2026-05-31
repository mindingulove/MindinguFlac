$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = if (Test-Path ".venv-build\Scripts\python.exe") {
    ".venv-build\Scripts\python.exe"
} elseif (Test-Path "venv_build\Scripts\python.exe") {
    "venv_build\Scripts\python.exe"
} else {
    "python"
}

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt -r requirements-desktop.txt
& $python scripts\make_desktop_icons.py

& $python -m PyInstaller --clean --noconfirm Mindinguflac-windows.spec

$zipPath = Join-Path $root "Mindinguflac-windows.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
Compress-Archive -Path (Join-Path $root "dist\Mindinguflac.exe") -DestinationPath $zipPath

Write-Host "Built $zipPath"
