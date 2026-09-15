@echo off
setlocal
echo ======================================================================
echo    Channel Harvest - Automated Release Build
echo ======================================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in system PATH.
    echo Please install Python 3.10+ and ensure it is added to PATH.
    pause
    exit /b 1
)

python build.py %*
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Build encountered an error.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [DONE] Build completed successfully!
pause
