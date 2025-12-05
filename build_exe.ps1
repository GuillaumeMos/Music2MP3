# build_exe.ps1
param(
  [string]$Python = "python",
  [string]$Spec = "Music2MP3-Windows.spec"
)

$ErrorActionPreference = "Stop"

function Ensure-Tool($exe) {
  if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
    throw "Outil introuvable: $exe"
  }
}

# 1) Vérifs de base
Ensure-Tool $Python

# 2) Venv
if (-not (Test-Path ".venv")) {
  & $Python -m venv .venv
}
$env:VIRTUAL_ENV = (Resolve-Path ".venv").Path
$env:PATH = "$($env:VIRTUAL_ENV)\Scripts;$env:PATH"

# 3) Deps (always via the chosen interpreter)
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt pyinstaller

# 4) Vérif binaires embarqués
if (-not (Test-Path "yt-dlp/yt-dlp.exe")) { Write-Warning "Manque yt-dlp/yt-dlp.exe" }
if (-not (Test-Path "ffmpeg/ffmpeg.exe") -and -not (Test-Path "ffmpeg/bin/ffmpeg.exe")) {
  Write-Warning "Manque ffmpeg/ffmpeg.exe ou ffmpeg/bin/ffmpeg.exe"
}

# 5) Build
& $Python -m PyInstaller $Spec

Write-Host "`nBuild terminé. Exe dans dist/Music2MP3/Music2MP3.exe"
