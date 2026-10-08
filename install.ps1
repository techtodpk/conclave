# Conclave installer for Windows.
#
# Run this in PowerShell (no administrator rights needed):
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/techtodpk/conclave/main/install.ps1 | iex"
#
# It installs uv (a small tool that downloads its own private Python), installs Conclave
# with it, puts a Conclave shortcut on your desktop and in the Start menu, and opens the
# app. Nothing is installed system-wide. To remove Conclave later, see the setup guide.

$ErrorActionPreference = "Stop"
$Source = if ($env:CONCLAVE_SOURCE) { $env:CONCLAVE_SOURCE } else { "https://github.com/techtodpk/conclave/archive/refs/heads/main.zip" }

function Refresh-Path {
    # Pick up PATH changes the uv installer made, without opening a new window.
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = (@((Join-Path $HOME ".local\bin"), $user, $machine, $env:Path) | Where-Object { $_ }) -join ";"
}

function Say($text) { Write-Host ""; Write-Host $text -ForegroundColor Cyan }

Say "Installing Conclave. This takes one or two minutes the first time."

Say "Step 1 of 3: getting uv, which keeps a private copy of Python for Conclave"
Refresh-Path
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv could not be installed. Check your internet connection and run the installer again."
}

Say "Step 2 of 3: installing Conclave"
uv tool install --force --python 3.13 "conclave-council[app,mcp] @ $Source"
if ($LASTEXITCODE -ne 0) { throw "Conclave could not be installed (uv exited with $LASTEXITCODE)." }
uv tool update-shell | Out-Null

Say "Step 3 of 3: adding a Conclave shortcut to your desktop and Start menu"
$Bin = (uv tool dir --bin | Select-Object -Last 1).Trim()
$Conclave = Join-Path $Bin "conclave.exe"
if (-not (Test-Path $Conclave)) { throw "Conclave was installed, but conclave.exe was not found in $Bin." }
& $Conclave shortcut
if ($LASTEXITCODE -ne 0) { Write-Host "No shortcut was made. You can start Conclave with: conclave app" }

Say "Done. Conclave is opening in your browser."
Write-Host "Next time, start it from the Conclave shortcut on your desktop."
Write-Host "Keep the black Conclave window open while you use it; close it to stop Conclave."
Start-Process -FilePath $Conclave -ArgumentList "app"
