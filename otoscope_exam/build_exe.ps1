$ErrorActionPreference = "Stop"

$Python = "C:\Users\haolu\AppData\Local\anaconda3\envs\otoscope_exam\python.exe"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name otoscope_exam `
    app.py

New-Item -ItemType Directory -Path ".\result" -Force | Out-Null

Write-Host "Build complete: .\dist\otoscope_exam.exe"
