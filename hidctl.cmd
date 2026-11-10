@echo off
rem Windows launcher for hidctl.py (the macOS branch uses ./hidctl directly).
setlocal
where python >nul 2>nul
if errorlevel 1 (
    echo hidctl: Python 3.10+ was not found on PATH.
    echo Install Python from https://www.python.org/downloads/windows/ and retry.
    exit /b 1
)
python "%~dp0hidctl.py" %*
exit /b %errorlevel%
