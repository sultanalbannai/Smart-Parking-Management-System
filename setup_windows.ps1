# Smart Parking Management System - Windows setup (PowerShell)
# Creates a venv, installs dependencies, and initializes the database.

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Smart Parking Management System - Windows Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verify Python
Write-Host "[1/4] Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    Write-Host "  Install Python 3.10 or 3.11 from https://www.python.org/" -ForegroundColor Red
    Write-Host "  and tick 'Add Python to PATH' during installation." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# 2. Virtual environment
Write-Host "[2/4] Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "Virtual environment already exists, skipping creation." -ForegroundColor Green
} else {
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "Virtual environment created." -ForegroundColor Green
}

try {
    & ".\venv\Scripts\Activate.ps1"
} catch {
    Write-Host "WARNING: Could not activate virtual environment." -ForegroundColor Yellow
    Write-Host "  You may need to run:" -ForegroundColor Yellow
    Write-Host "    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
}
Write-Host ""

# 3. Install dependencies
Write-Host "[3/4] Installing dependencies (this may take several minutes)..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: dependency install failed" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# 4. Initialize the SQLite database
Write-Host "[4/4] Initializing database..." -ForegroundColor Yellow
python init_camera_db.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: database init reported a non-zero exit code." -ForegroundColor Yellow
}
Write-Host ""

Write-Host "============================================================" -ForegroundColor Green
Write-Host " Setup complete." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Activate the venv:    .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  2. Start the demo:       python run_camera_demo.py" -ForegroundColor White
Write-Host "  3. Open the dashboard:   http://localhost:5000" -ForegroundColor White
Write-Host "  4. Calibrate cameras:    http://localhost:5000/calibrate" -ForegroundColor White
Write-Host ""

Read-Host "Press Enter to continue"
