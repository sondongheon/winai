param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

& $PythonExe -m pip install pyinstaller
& $PythonExe -m PyInstaller --noconfirm --clean --windowed --name WinAI main.py

Write-Host "Build complete: .\dist\WinAI\WinAI.exe"