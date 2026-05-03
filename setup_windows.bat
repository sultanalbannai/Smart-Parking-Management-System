@echo off
REM Smart Parking Management System - Windows setup
REM Creates a venv, installs dependencies, and initializes the database.

echo ============================================================
echo  Smart Parking Management System - Windows Setup
echo ============================================================
echo.

REM 1. Verify Python
echo [1/4] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found.
    echo Install Python 3.10 or 3.11 from https://www.python.org/
    echo and tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)
python --version
echo.

REM 2. Virtual environment
echo [2/4] Creating virtual environment...
if exist venv (
    echo Virtual environment already exists, skipping creation.
) else (
    python -m venv venv
)
call venv\Scripts\activate.bat
echo.

REM 3. Install dependencies
echo [3/4] Installing dependencies (this may take several minutes)...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: dependency install failed.
    pause
    exit /b 1
)
echo.

REM 4. Initialize the SQLite database
echo [4/4] Initializing database...
python init_camera_db.py
if %errorlevel% neq 0 (
    echo WARNING: database init reported a non-zero exit code.
)
echo.

echo ============================================================
echo  Setup complete.
echo ============================================================
echo.
echo Next steps:
echo   1. Activate the venv:    venv\Scripts\activate.bat
echo   2. Start the demo:       python run_camera_demo.py
echo   3. Open the dashboard:   http://localhost:5000
echo   4. Calibrate cameras:    http://localhost:5000/calibrate
echo.
pause
