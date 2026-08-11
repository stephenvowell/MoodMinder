# Mood Minder Windows installer
# Checks for Python, creates a virtual environment, installs requirements,
# and adds Desktop + Start Menu shortcuts.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Find-Python {
    # Prefer the py launcher, then python on PATH
    $candidates = @()

    foreach ($cmd in @("py", "python", "python3")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        try {
            if ($cmd -eq "py") {
                $ver = & py -3 -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
                $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
            } else {
                $ver = & $cmd -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
                $exe = & $cmd -c "import sys; print(sys.executable)" 2>$null
            }
            if ($LASTEXITCODE -ne 0 -or -not $ver -or -not $exe) { continue }
            $parts = $ver.Trim().Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) { continue }
            # Skip Windows Store stub that fails for real work
            if ($exe -match "WindowsApps\\python") { continue }
            $candidates += [pscustomobject]@{ Exe = $exe.Trim(); Version = $ver.Trim(); Cmd = $cmd }
        } catch {
            continue
        }
    }

    if ($candidates.Count -eq 0) { return $null }
    return $candidates[0]
}

function Test-Tkinter($pythonExe) {
    & $pythonExe -c "import tkinter" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function New-Shortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Description
    )
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($ShortcutPath)
    $sc.TargetPath = $TargetPath
    $sc.Arguments = $Arguments
    $sc.WorkingDirectory = $WorkingDirectory
    $sc.Description = $Description
    $sc.Save()
}

Write-Host "Mood Minder installer" -ForegroundColor White
Write-Host "Folder: $Root"

# --- Required files ---
Write-Step "Checking app files"
foreach ($name in @("app.py", "mood_engine.py", "pdf_export.py", "requirements.txt", "run.bat")) {
    if (-not (Test-Path (Join-Path $Root $name))) {
        throw "Missing required file: $name"
    }
}
Write-Host "App files OK."

# --- Python ---
Write-Step "Checking for Python 3.10+"
$py = Find-Python
if (-not $py) {
    Write-Host ""
    Write-Host "Python 3.10+ was not found on this PC." -ForegroundColor Yellow
    Write-Host "The installer will open the official download page."
    Write-Host "Install Python, enable 'Add python.exe to PATH', then run install.bat again."
    Write-Host ""
    Start-Process "https://www.python.org/downloads/windows/"
    Read-Host "Press Enter to close"
    exit 1
}
Write-Host ("Found Python {0} at {1}" -f $py.Version, $py.Exe)

Write-Step "Checking tkinter (GUI support)"
if (-not (Test-Tkinter $py.Exe)) {
    Write-Host "tkinter is missing from this Python install." -ForegroundColor Red
    Write-Host "Reinstall Python from python.org and keep Tcl/Tk enabled."
    Start-Process "https://www.python.org/downloads/windows/"
    Read-Host "Press Enter to close"
    exit 1
}
Write-Host "tkinter OK."

# --- Virtual environment ---
Write-Step "Creating virtual environment (.venv)"
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $py.Exe -m venv (Join-Path $Root ".venv")
}
if (-not (Test-Path $venvPython)) {
    throw "Failed to create .venv"
}
Write-Host "Virtual environment ready."

# --- Requirements ---
Write-Step "Installing requirements"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $Root "requirements.txt")
Write-Host "Requirements installed (stdlib app — no extra packages needed)."

# --- Smoke test ---
Write-Step "Verifying app imports"
& $venvPython -c "import app; import mood_engine; print('import ok')"
if ($LASTEXITCODE -ne 0) {
    throw "App import check failed."
}

# --- Shortcuts ---
Write-Step "Creating shortcuts"
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Mood Minder"
New-Item -ItemType Directory -Force -Path $programs | Out-Null

$runBat = Join-Path $Root "run.bat"
$desktopLnk = Join-Path $desktop "Mood Minder.lnk"
$startLnk = Join-Path $programs "Mood Minder.lnk"

New-Shortcut -ShortcutPath $desktopLnk -TargetPath $runBat -Arguments "" `
    -WorkingDirectory $Root -Description "Mood Minder — personal mood journal"
New-Shortcut -ShortcutPath $startLnk -TargetPath $runBat -Arguments "" `
    -WorkingDirectory $Root -Description "Mood Minder — personal mood journal"

Write-Host "Desktop shortcut: $desktopLnk"
Write-Host "Start Menu shortcut: $startLnk"

# --- Marker file ---
$info = @{
    installed_at = (Get-Date).ToString("s")
    python = $py.Exe
    python_version = $py.Version
    root = $Root
}
$info | ConvertTo-Json | Set-Content -Path (Join-Path $Root "install-info.json") -Encoding UTF8

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host "Launch with: Desktop shortcut 'Mood Minder'  or  run.bat"
Write-Host ""
$launch = Read-Host "Launch Mood Minder now? (Y/N)"
if ($launch -match '^[Yy]') {
    Start-Process -FilePath $runBat -WorkingDirectory $Root
}
