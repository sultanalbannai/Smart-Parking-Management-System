@echo off
REM SPMS Setup Script for Windows 11
REM Run this after extracting the project

echo ============================================================
echo  Smart Parking Management System - Windows Setup
echo ============================================================
echo.

REM Check Python installation
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found!
    echo Please install Python 3.10 or 3.11 from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)

python --version
echo.

REM Create virtual environment
echo [2/5] Creating virtual environment...
if exist venv (
    echo Virtual environment already exists, skipping...
) else (
    python -m venv venv
    echo Virtual environment created successfully!
)
echo.

REM Activate virtual environment
echo [3/5] Activating virtual environment...
call venv\Scripts\activate.bat
echo.

REM Install dependencies
echo [4/5] Installing dependencies...
echo This may take a few minutes...
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo WARNING: Some packages failed to install
    echo Trying alternative installation method...
    pip install sqlalchemy pyyaml --quiet
)
echo Dependencies installed!
echo.

REM Test core components
echo [5/5] Testing core components...
python test_core.py
if %errorlevel% neq 0 (
    echo ERROR: Core component test failed!
    pause
    exit /b 1
)
echo.

echo ============================================================
echo  Setup Complete!
echo ============================================================
echo.
echo Next steps:
echo   1. Initialize database: python init_db.py
echo   2. Read PROGRESS.md for implementation status
echo   3. Read WINDOWS_SETUP.md for detailed Windows guide
echo.
echo To activate virtual environment in the future:
echo   venv\Scripts\activate.bat
echo.
pause
