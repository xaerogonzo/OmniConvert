@echo off
REM Generated from nuitka-build.bat.template
REM Launcher for build.ps1 - bypasses execution policy and keeps the window
REM open at the end so build output stays visible.
REM
REM NOTE: build.ps1 must stay pure ASCII. This launcher uses Windows
REM PowerShell 5.1, which reads BOM-less files as cp1252; a stray non-ASCII
REM character decodes into a smart quote and silently breaks parsing.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0build.ps1"
set BUILD_RC=%ERRORLEVEL%
if %BUILD_RC% neq 0 (
    echo.
    echo BUILD FAILED with exit code %BUILD_RC%.
)
pause
exit /b %BUILD_RC%
