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
$venvDir = if ($env:MINDINGUFLAC_VENV_DIR) { $env:MINDINGUFLAC_VENV_DIR } else { Join-Path $root "venv-windows" }
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Get-PythonMinorVersion {
    param([string]$Exe, [string[]]$Args = @())
    try {
        $versionOutput = & $Exe @Args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
        $version = $versionOutput | ForEach-Object { "$_".Trim() } | Where-Object { $_ -match '^\d+\.\d+$' } | Select-Object -Last 1
        if ($version) {
            return $version.Trim()
        }
        if (($LASTEXITCODE -ne 0) -and $versionOutput) {
            Write-Host "  -> Version probe output: $($versionOutput -join ' | ')" -ForegroundColor DarkYellow
        }
        if (($Args.Count -eq 0) -and ($Exe -match "[\\/]") -and (Test-Path $Exe)) {
            $fileVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Exe)
            foreach ($candidateVersion in @($fileVersion.ProductVersion, $fileVersion.FileVersion)) {
                if ($candidateVersion -and $candidateVersion -match '^(\d+)\.(\d+)') {
                    return "$($Matches[1]).$($Matches[2])"
                }
            }
        }
    } catch {
        if (($Args.Count -eq 0) -and ($Exe -match "[\\/]") -and (Test-Path $Exe)) {
            try {
                $fileVersion = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Exe)
                foreach ($candidateVersion in @($fileVersion.ProductVersion, $fileVersion.FileVersion)) {
                    if ($candidateVersion -and $candidateVersion -match '^(\d+)\.(\d+)') {
                        return "$($Matches[1]).$($Matches[2])"
                    }
                }
            } catch {}
        }
        return $null
    }
    return $null
}

function Get-PEMachineArch {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path $Exe)) { return $null }
    try {
        $fs = [System.IO.File]::OpenRead($Exe)
        try {
            $reader = New-Object System.IO.BinaryReader($fs)
            $fs.Seek(0x3c, [System.IO.SeekOrigin]::Begin) | Out-Null
            $peOffset = $reader.ReadInt32()
            if ($peOffset -le 0) { return $null }
            $fs.Seek($peOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
            $signature = $reader.ReadUInt32()
            if ($signature -ne 0x00004550) { return $null }
            $machine = $reader.ReadUInt16()
            switch ($machine) {
                0x8664 { return "AMD64" }
                0xAA64 { return "ARM64" }
                0x01C4 { return "ARM" }
                0x014C { return "X86" }
                default { return $null }
            }
        } finally {
            $fs.Close()
        }
    } catch {
        return $null
    }
}

function Get-PythonArch {
    param([string]$Exe, [string[]]$Args = @())
    # The PE header machine field is ground truth for the binary's real
    # architecture. platform.machine() is UNRELIABLE under Windows-on-ARM
    # (Parallels): an AMD64 python.exe running via x64 emulation reports
    # "ARM64" there, because PROCESSOR_ARCHITEW6432 exposes the native host
    # arch. Read the PE bytes first for any real exe path; only fall back to
    # platform.machine() for launcher-style candidates ("py -3.12").
    if (($Args.Count -eq 0) -and ($Exe -match "[\\/]")) {
        $peArch = Get-PEMachineArch -Exe $Exe
        if ($peArch) { return $peArch }
    }
    try {
        $archOutput = & $Exe @Args -c "import platform; print(platform.machine())" 2>&1
        $arch = $archOutput | ForEach-Object { "$_".Trim().ToUpper() } | Where-Object { $_ -match '^(AMD64|X86_64|ARM64|AARCH64|X86|I386)$' } | Select-Object -Last 1
        if ($arch) {
            $val = $arch.Trim().ToUpper()
            if ($val -eq "X86_64") { return "AMD64" }
            if ($val -eq "AARCH64") { return "ARM64" }
            return $val
        }
        if (($LASTEXITCODE -ne 0) -and $archOutput) {
            Write-Host "  -> Arch probe output: $($archOutput -join ' | ')" -ForegroundColor DarkYellow
        }
        if (($Args.Count -eq 0) -and ($Exe -match "[\\/]")) {
            return Get-PEMachineArch -Exe $Exe
        }
    } catch {
        if (($Args.Count -eq 0) -and ($Exe -match "[\\/]")) {
            return Get-PEMachineArch -Exe $Exe
        }
        return $null
    }
    return $null
}

function Test-PythonCanCreateVenv {
    param([string]$Exe, [string[]]$Args = @())
    try {
        $probeOutput = & $Exe @Args -c "import sys, venv; print('venv-ok')" 2>&1
        $ok = $probeOutput | ForEach-Object { "$_".Trim() } | Where-Object { $_ -eq "venv-ok" } | Select-Object -Last 1
        if ($ok) { return $true }
        if ($probeOutput) {
            Write-Host "  -> Venv probe output: $($probeOutput -join ' | ')" -ForegroundColor DarkYellow
        }
    } catch {}
    return $false
}

$amd64PythonDir = Join-Path $env:LOCALAPPDATA "mindinguflac\python312-amd64"
$amd64PythonExe = Join-Path $amd64PythonDir "python.exe"
$nugetPythonDir = Join-Path $env:LOCALAPPDATA "mindinguflac\python312-amd64-nuget"
$nugetPythonExe = Join-Path $nugetPythonDir "tools\python.exe"
$hardcodedPython312Exe = "C:\Users\jaymeeduardo\AppData\Local\Programs\Python\Python312\python.exe"

function Add-PythonCandidate {
    param(
        [System.Collections.ArrayList]$Candidates,
        [string]$Exe,
        [string[]]$Args = @()
    )
    if (-not $Exe) { return }
    $key = "$Exe $($Args -join ' ')"
    foreach ($candidate in $Candidates) {
        if ($candidate.Key -ceq $key) { return }
    }
    [void]$Candidates.Add([pscustomobject]@{ Key = $key; Exe = $Exe; Args = $Args })
}

function Get-CandidateDisplayName {
    param($Candidate)
    $suffix = if ($Candidate.Args -and $Candidate.Args.Count -gt 0) { " $($Candidate.Args -join ' ')" } else { "" }
    return "$($Candidate.Exe)$suffix"
}

function Resolve-Python312Amd64 {
    $candidates = [System.Collections.ArrayList]::new()
    if ($env:MINDINGUFLAC_PYTHON) {
        Add-PythonCandidate -Candidates $candidates -Exe $env:MINDINGUFLAC_PYTHON
    }
    Add-PythonCandidate -Candidates $candidates -Exe $hardcodedPython312Exe
    # Installer targets, kept so the auto-install fallback below can be found
    # after Install-Python312Amd64 runs.
    Add-PythonCandidate -Candidates $candidates -Exe $amd64PythonExe
    Add-PythonCandidate -Candidates $candidates -Exe $nugetPythonExe

    $foundRejected = $false
    foreach ($candidate in $candidates) {
        $display = Get-CandidateDisplayName -Candidate $candidate
        if (($candidate.Exe -match "[\\/]") -and -not (Test-Path $candidate.Exe)) {
            Write-Host "Checking candidate: $display"
            Write-Host "  -> Not found on disk."
            continue
        }
        Write-Host "Checking candidate: $display"
        $v = Get-PythonMinorVersion -Exe $candidate.Exe -Args $candidate.Args
        if (-not $v) {
            Write-Host "  -> Version: Failed"
            $foundRejected = $true
            continue
        }
        Write-Host "  -> Version: $v"
        if ($v -ne $requiredPython) {
            Write-Host "  -> Ignoring: Python $requiredPython is required." -ForegroundColor Yellow
            $foundRejected = $true
            continue
        }
        $a = Get-PythonArch -Exe $candidate.Exe -Args $candidate.Args
        Write-Host "  -> Arch: $a"
        if ($a -ne "AMD64") {
            Write-Host "  -> Ignoring: Windows builds must use AMD64/x64 Python, never ARM64." -ForegroundColor Yellow
            $foundRejected = $true
            continue
        }
        if (-not (Test-PythonCanCreateVenv -Exe $candidate.Exe -Args $candidate.Args)) {
            Write-Host "  -> Ignoring: Python cannot import venv; install may be incomplete." -ForegroundColor Yellow
            $foundRejected = $true
            continue
        }
        return $candidate
    }
    if ($foundRejected) {
        Write-Host "No existing Python candidate was accepted; only now trying the AMD64 installer." -ForegroundColor Yellow
    }
    return $null
}

function Install-Python312Amd64 {
    $pyVersion = "3.12.8"
    $url = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-amd64.exe"
    $installer = Join-Path $env:TEMP "python-$pyVersion-amd64.exe"

    Write-Host "--- Downloading x64 Python $pyVersion from python.org ---"
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing

    Write-Host "--- Installing AMD64 Python $pyVersion to $amd64PythonDir ---"
    New-Item -ItemType Directory -Path $amd64PythonDir -Force | Out-Null
    $logFile = Join-Path $env:TEMP "mindinguflac-python-$pyVersion-amd64-install.log"
    $procArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "TargetDir=$amd64PythonDir",
        "/log",
        $logFile
    )
    $proc = Start-Process -FilePath $installer -ArgumentList $procArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "AMD64 Python installer failed with code $($proc.ExitCode). Installer log: $logFile"
    }
    if (Test-Path $amd64PythonExe) {
        return
    }

    Write-Host "--- Python.org installer did not create $amd64PythonExe; using AMD64 NuGet Python fallback ---" -ForegroundColor Yellow
    $nugetUrl = "https://www.nuget.org/api/v2/package/pythonx64/$pyVersion"
    $nugetZip = Join-Path $env:TEMP "pythonx64-$pyVersion.zip"
    if (Test-Path $nugetPythonDir) {
        Remove-Item $nugetPythonDir -Recurse -Force
    }
    Invoke-WebRequest -Uri $nugetUrl -OutFile $nugetZip -UseBasicParsing
    New-Item -ItemType Directory -Path $nugetPythonDir -Force | Out-Null
    Expand-Archive -Path $nugetZip -DestinationPath $nugetPythonDir -Force
    if (-not (Test-Path $nugetPythonExe)) {
        throw "AMD64 NuGet Python fallback did not create $nugetPythonExe"
    }
}

function Ensure-VCRedistX64 {
    # The packaged app runs x64 (emulated on Windows-on-ARM) and libtorrent's
    # win_amd64 wheel needs the x64 VC++ 2015-2022 runtime. A fresh
    # Windows-on-ARM box ships only the ARM64 runtime, so the app fails with
    # "DLL load failed while importing libtorrent: The specified module could
    # not be found." Install the x64 runtime here so the build machine works.
    foreach ($k in @(
        "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    )) {
        try {
            $v = Get-ItemProperty -Path $k -ErrorAction Stop
            if ($v.Installed -eq 1) {
                Write-Host "x64 VC++ runtime already installed (v$($v.Version))."
                return
            }
        } catch {}
    }
    Write-Host "--- Installing x64 VC++ runtime (required by libtorrent) ---"
    $url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    $installer = Join-Path $env:TEMP "vc_redist.x64.exe"
    try {
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        $proc = Start-Process -FilePath $installer -ArgumentList @("/install", "/passive", "/norestart") -Wait -PassThru
        if ($proc.ExitCode -in 0, 3010, 1638) {
            Write-Host "x64 VC++ runtime installed (exit $($proc.ExitCode))."
        } else {
            Write-Host "VC++ runtime installer exit code $($proc.ExitCode); install manually from $url if libtorrent fails to load." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Could not auto-install the x64 VC++ runtime: $_" -ForegroundColor Yellow
        Write-Host "If the app fails with 'DLL load failed while importing libtorrent', install it manually from $url (x64, not arm64)." -ForegroundColor Yellow
    }
}

$usingExistingVenv = $false
if (Test-Path $venvPython) {
    Write-Host "Checking existing build venv: $venvPython"
    $venvVersion = Get-PythonMinorVersion -Exe $venvPython
    $venvArch = Get-PythonArch -Exe $venvPython
    Write-Host "  -> Version: $venvVersion"
    Write-Host "  -> Arch: $venvArch"
    if (($venvVersion -eq $requiredPython) -and ($venvArch -eq "AMD64")) {
        $usingExistingVenv = $true
    } else {
        Write-Host "Removing non-AMD64 or wrong-version venv at $venvDir" -ForegroundColor Yellow
        Remove-Item $venvDir -Recurse -Force
    }
}

if (-not $usingExistingVenv) {
    $python312 = Resolve-Python312Amd64
    if (-not $python312) {
        Install-Python312Amd64
        $python312 = Resolve-Python312Amd64
    }

    if (-not $python312) {
        throw @"
An AMD64/x64 Python 3.12 could not be found or installed automatically.

Windows builds must use AMD64 Python even on Windows-on-ARM/Parallels. ARM64
Python is intentionally rejected because PyInstaller and libtorrent must produce
the same x64 artifact as GitHub Actions.

Install the AMD64 build manually if needed:
  1. Download: https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe
  2. Install it for the current user.
  3. Rerun this script, or point it at the AMD64 interpreter:
       `$env:MINDINGUFLAC_PYTHON = "C:\path\to\python.exe"
       powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1

Verify the interpreter with:
  & "C:\path\to\python.exe" -c "import platform; print(platform.machine())"

It must print AMD64 or X86_64. If it prints ARM64, do not use it.
"@
    }

    Write-Host "--- Creating AMD64 Build Venv ---"
    Invoke-Checked { & $python312.Exe @($python312.Args) -m venv $venvDir }
}

$python = $venvPython
Write-Host "Using Python: $python"
Invoke-Checked { & $python -m pip install --upgrade pip }
Invoke-Checked { & $python -m pip install --only-binary=cryptography --prefer-binary -r requirements.txt -r requirements-desktop.txt }
Invoke-Checked { & $python -m pip install --only-binary=libtorrent libtorrent }
# libtorrent's win_amd64 wheel links OpenSSL 1.1 (libssl-1_1-x64.dll /
# libcrypto-1_1-x64.dll), which Python 3.12 (OpenSSL 3, libcrypto-3.dll) does
# NOT provide. Without these the .pyd fails with "DLL load failed ... The
# specified module could not be found." This package drops the OpenSSL 1.1 DLLs
# into the libtorrent package dir so the .pyd loads and PyInstaller bundles them.
Invoke-Checked { & $python -m pip install libtorrent-windows-dll }
# Install the x64 VC++ runtime BEFORE importing libtorrent (it also needs it).
Ensure-VCRedistX64
# Fail fast if libtorrent still can't load, instead of shipping a broken app
# (PyInstaller silently skips an un-importable libtorrent in collect_all).
Invoke-Checked { & $python -c "import libtorrent; print('libtorrent OK', libtorrent.version)" }
Invoke-Checked { & $python scripts\make_desktop_icons.py }
Invoke-Checked { & $python -m PyInstaller --clean --noconfirm Mindinguflac-windows.spec }

Write-Host "--- Packaging ---"
$zipPath = Join-Path $root "/dist/Mindinguflac-windows.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

$exePath = Join-Path $root "dist\Mindinguflac.exe"
if (-not (Test-Path $exePath)) {
    throw "Build failed: $exePath not found."
}

Compress-Archive -Path $exePath -DestinationPath $zipPath

Write-Host "--- Success ---"
Write-Host "Built: $zipPath"
