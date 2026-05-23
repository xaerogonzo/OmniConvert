@echo off
python "%~dp0main.py"
if %ERRORLEVEL% neq 0 (
    echo.
    echo OmniConvert exited with an error. See above for details.
    pause
)
