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
# Windows uses its own venv so it never collides with the macOS venv (venv-macos)
# when the project folder is shared (e.g. Parallels).
#
# IMPORTANT: the venv must live on the LOCAL Windows disk, not on the shared
# folder. A venv created on a \\psf\ (Parallels) share is broken — its
# python.exe reports an empty version and cannot reliably execute. We therefore
# place it under %LOCALAPPDATA% by default (override with MINDINGUFLAC_VENV_DIR).
if ($env:MINDINGUFLAC_VENV_DIR) {
    $venvDir = $env:MINDINGUFLAC_VENV_DIR
} else {
    $venvDir = Join-Path $env:LOCALAPPDATA "mindinguflac\venv-windows"
}
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
        [pscustomobject]@{ Exe = "python"; Args = @() },
        [pscustomobject]@{ Exe = "python3"; Args = @() },
        [pscustomobject]@{ Exe = (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"); Args = @() },
        [pscustomobject]@{ Exe = (Join-Path $env:ProgramFiles "Python312\python.exe"); Args = @() }
    )

    # Discover any 3.12 interpreter registered with the py launcher.
    try {
        $pyList = & py -0p 2>$null
        if ($LASTEXITCODE -eq 0 -and $pyList) {
            foreach ($line in $pyList) {
                if ($line -match "3\.12" -and $line -match "([A-Za-z]:\\[^\s].*python\.exe)") {
                    $candidates += [pscustomobject]@{ Exe = $Matches[1]; Args = @() }
                }
            }
        }
    } catch {}

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
    & winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    $code = $LASTEXITCODE
    # winget returns non-zero "no upgrade / already installed" codes when 3.12
    # is already present; treat those as success.
    $okCodes = @(0, -1978335189, -1978335135, -1978335212)
    if ($okCodes -notcontains $code) {
        throw "winget failed to install Python 3.12 (exit code $code)."
    }

    # Refresh PATH so a freshly installed interpreter is discoverable this session.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

$python313 = Resolve-Python313
if (-not $python313) {
    Install-Python313
    $python313 = Resolve-Python313
}
if (-not $python313) {
    throw "Python 3.12 was not found after installation. Open a new PowerShell window and rerun this script."
}

if (Test-Path $venvPython) {
    $venvVersion = Get-PythonMinorVersion -Exe $venvPython
    if ($venvVersion -ne $requiredPython) {
        Write-Host "Removing $venvDir because it uses Python $venvVersion instead of Python $requiredPython."
        Remove-Item $venvDir -Recurse -Force
    }
}

if (-not (Test-Path $venvPython)) {
    Write-Host "--- Creating Python 3.12 build venv ---"
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

Write-Host "--- Installing libtorrent (win_amd64 wheel via x64 emulation) ---"
$ltInstalled = $false
try {
    & $python -m pip install --only-binary=libtorrent `
        --platform win_amd64 --python-version 312 --implementation cp --abi cp312 `
        --target (Join-Path $venvDir "Lib\site-packages") libtorrent 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) { $ltInstalled = $true }
} catch {}
if (-not $ltInstalled) {
    Write-Warning "libtorrent could not be installed - torrent downloads will be unavailable."
}

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
