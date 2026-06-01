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
# folder. A venv created on a \\psf\ (Parallels) share is broken - its
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

function Get-PythonArch {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Exe,
        [string[]]$Args = @()
    )
    try {
        $arch = & $Exe @Args -c "import platform; print(platform.machine())"
        if ($LASTEXITCODE -eq 0) {
            return $arch.Trim().ToUpper()
        }
    } catch {
        return $null
    }
    return $null
}

# We require an x64 (AMD64) Python on Windows. On Windows-on-ARM (e.g. Parallels)
# the native interpreter is ARM64, but many dependencies (multidict, libtorrent,
# yarl, frozenlist, ...) ship no win_arm64 wheels and would try to compile from
# source. An x64 interpreter resolves every dependency to a win_amd64 wheel and
# runs fine under Windows' x64 emulation.
# Dedicated location for the x64 build we install ourselves (kept separate from
# any ARM64 Python the system may already have).
$x64PythonDir = Join-Path $env:LOCALAPPDATA "mindinguflac\python312-x64"
$x64PythonExe = Join-Path $x64PythonDir "python.exe"

function Resolve-Python313 {
    $candidates = @(
        [pscustomobject]@{ Exe = $x64PythonExe; Args = @() }
    )

    # Most reliable: read the Windows registry for installed Python 3.12. The
    # python.org x64 build is tagged "3.12" (ARM64 would be "3.12-arm64", which
    # we ignore). This finds the install regardless of its folder.
    foreach ($hive in @("HKCU:", "HKLM:")) {
        foreach ($sub in @("Software\Python\PythonCore\3.12\InstallPath",
                           "Software\WOW6432Node\Python\PythonCore\3.12\InstallPath")) {
            try {
                $key = Get-ItemProperty -Path "$hive\$sub" -ErrorAction Stop
                $exe = $key.ExecutablePath
                if (-not $exe -and $key.'(default)') {
                    $exe = Join-Path $key.'(default)' "python.exe"
                }
                if ($exe -and (Test-Path $exe)) {
                    $candidates += [pscustomobject]@{ Exe = $exe; Args = @() }
                }
            } catch {}
        }
    }

    $candidates += @(
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

    $arm64Fallback = $null
    foreach ($candidate in $candidates) {
        if (($candidate.Exe -match "[\\/]") -and -not (Test-Path $candidate.Exe)) {
            continue
        }
        $version = Get-PythonMinorVersion -Exe $candidate.Exe -Args $candidate.Args
        if ($version -ne $requiredPython) {
            continue
        }
        $arch = Get-PythonArch -Exe $candidate.Exe -Args $candidate.Args
        if ($arch -eq "AMD64") {
            return $candidate
        }
        if (-not $arm64Fallback) { $arm64Fallback = $candidate }
    }

    # No AMD64 3.12 found. Return $null so the installer fetches the x64 build.
    # (The ARM64 interpreter is intentionally not used.)
    return $null
}

function Install-Python313 {
    # winget keys on package ID, not architecture: if an ARM64 Python 3.12 is
    # already installed it reports "already installed" and refuses to add the
    # x64 build. So we download the official x64 installer from python.org and
    # install it (per-user, embedded, no PATH change) into our own directory.
    $pyVersion = "3.12.8"
    $url = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-amd64.exe"
    $installer = Join-Path $env:TEMP "python-$pyVersion-amd64.exe"

    Write-Host "--- Downloading x64 Python $pyVersion from python.org ---"
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    } catch {
        throw "Failed to download x64 Python from $url : $_"
    }

    Write-Host "--- Installing x64 Python $pyVersion to $x64PythonDir ---"
    $procArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "TargetDir=$x64PythonDir"
    )
    $proc = Start-Process -FilePath $installer -ArgumentList $procArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and -not (Test-Path $x64PythonExe)) {
        throw "Python installer exited with code $($proc.ExitCode) and $x64PythonExe was not created."
    }
}

$python313 = Resolve-Python313
if (-not $python313) {
    Install-Python313
    $python313 = Resolve-Python313
}
if (-not $python313) {
    throw "An x64 Python 3.12 was not found after installation. Open a new PowerShell window and rerun this script, or install the 64-bit Python 3.12 from python.org."
}

# Recreate the venv if it is the wrong version OR the wrong architecture
# (e.g. an old ARM64 venv from before the x64 switch).
if (Test-Path $venvPython) {
    $venvVersion = Get-PythonMinorVersion -Exe $venvPython
    $venvArch = Get-PythonArch -Exe $venvPython
    if ($venvVersion -ne $requiredPython -or $venvArch -ne "AMD64") {
        Write-Host "Removing $venvDir (Python '$venvVersion' arch '$venvArch'; need $requiredPython AMD64)."
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

Write-Host "--- Installing libtorrent ---"
# The venv is x64, so the normal win_amd64 wheel installs directly.
$ltInstalled = $false
try {
    & $python -m pip install --only-binary=libtorrent libtorrent 2>&1 | Out-Host
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
