@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  Scraping Tool - Installer
echo ============================================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download it from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo [OK] Found %PY_VER%
echo.

:: Upgrade pip silently first
echo [*] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo.

:: Install required packages
echo [*] Installing required packages:
echo       - playwright
echo       - beautifulsoup4
echo       - requests
echo       - lxml
echo.
python -m pip install playwright beautifulsoup4 requests lxml
if errorlevel 1 (
    echo.
    echo [ERROR] Package installation failed.
    echo         Try running this script as Administrator, or check your internet connection.
    pause
    exit /b 1
)
echo.

:: Install Playwright Chromium browser
echo [*] Installing Playwright Chromium browser...
echo     (This downloads ~150 MB - may take a minute)
echo.
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo [ERROR] Playwright Chromium install failed.
    echo         Try running: python -m playwright install chromium
    pause
    exit /b 1
)
echo.

echo ============================================================
echo  Installation complete!
echo ============================================================
echo.
echo  Usage examples:
echo.
echo    python scraper.py "frizerji Ljubljana"
echo    python scraper.py "zobozdravniki Maribor" --max 30
echo    python scraper.py "avtomehaniki Celje" --zadeva "Ponudba" --output draft.txt
echo    python scraper.py "kozmetični saloni Kranj" --sporocilo sporocilo.txt
echo.
echo  Run tests:
echo    python test_scraper.py
echo.
echo ============================================================
pause
