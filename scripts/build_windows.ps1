$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "--- Checking Environment ---"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [ScriptBlock]$Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

$requiredPython = "3.12"
$venvDir = ".venv-build"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Get-PythonMinorVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Exe,
        [string[]]$Args = @()
    )
    try {
        $version = & $Exe @Args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        if ($LASTEXITCODE -eq 0) {
            return $version.Trim()
        }
    } catch {
        return $null
    }
    return $null
}

function Resolve-Python313 {
    $candidates = @(
        [pscustomobject]@{ Exe = "py"; Args = @("-3.12") },
        [pscustomobject]@{ Exe = "python3.12"; Args = @() },
        [pscustomobject]@{ Exe = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"); Args = @() },
        [pscustomobject]@{ Exe = (Join-Path $env:ProgramFiles "Python312\python.exe"); Args = @() }
    )

    foreach ($candidate in $candidates) {
        if (($candidate.Exe -match "[\\/]") -and -not (Test-Path $candidate.Exe)) {
            continue
        }
        $version = Get-PythonMinorVersion -Exe $candidate.Exe -Args $candidate.Args
        if ($version -eq $requiredPython) {
            return $candidate
        }
    }

    return $null
}

function Install-Python313 {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python 3.12 is required, but winget is not available to install it automatically. Install Python 3.12 from python.org, then rerun this script."
    }

    Write-Host "--- Installing Python 3.12 ---"
    Invoke-Checked { winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements }
}

$python313 = Resolve-Python313
if (-not $python313) {
    Install-Python313
    $python313 = Resolve-Python313
}
if (-not $python313) {
    throw "Python 3.13 was not found after installation. Open a new PowerShell window and rerun this script."
}

if (Test-Path $venvPython) {
    $venvVersion = Get-PythonMinorVersion -Exe $venvPython
    if ($venvVersion -ne $requiredPython) {
        Write-Host "Removing $venvDir because it uses Python $venvVersion instead of Python $requiredPython."
        Remove-Item $venvDir -Recurse -Force
    }
}

if (-not (Test-Path $venvPython)) {
    Write-Host "--- Creating Python 3.13 build venv ---"
    $venvArgs = @($python313.Args) + @("-m", "venv", $venvDir)
    Invoke-Checked { & $python313.Exe @venvArgs }
}

$python = $venvPython
$pythonVersion = Get-PythonMinorVersion -Exe $python
if ($pythonVersion -ne $requiredPython) {
    throw "Build venv is using Python $pythonVersion, but Windows torrent builds require Python $requiredPython."
}

Write-Host "Using Python: $python ($pythonVersion)"

Write-Host "--- Installing Dependencies ---"
Invoke-Checked { & $python -m pip install --upgrade pip }
Invoke-Checked { & $python -m pip install --only-binary=cryptography --prefer-binary -r requirements.txt -r requirements-desktop.txt }

Write-Host "--- Preparing Assets ---"
Invoke-Checked { & $python scripts\make_desktop_icons.py }

Write-Host "--- Building Executable ---"
# Use python -m PyInstaller to bypass PATH issues
Invoke-Checked { & $python -m PyInstaller --clean --noconfirm Mindinguflac-windows.spec }

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
