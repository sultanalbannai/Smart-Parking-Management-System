# SPMS Setup Script for Windows 11 (PowerShell)
# Run this after extracting the project

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Smart Parking Management System - Windows Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python installation
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ ERROR: Python not found!" -ForegroundColor Red
    Write-Host "  Please install Python 3.10 or 3.11 from https://www.python.org/" -ForegroundColor Red
    Write-Host "  Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# Create virtual environment
Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "✓ Virtual environment already exists, skipping..." -ForegroundColor Green
} else {
    python -m venv venv
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Virtual environment created successfully!" -ForegroundColor Green
    } else {
        Write-Host "✗ ERROR: Failed to create virtual environment" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Write-Host ""

# Activate virtual environment
Write-Host "[3/5] Activating virtual environment..." -ForegroundColor Yellow
try {
    & ".\venv\Scripts\Activate.ps1"
    Write-Host "✓ Virtual environment activated!" -ForegroundColor Green
} catch {
    Write-Host "⚠ WARNING: Could not activate virtual environment" -ForegroundColor Yellow
    Write-Host "  You may need to run: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
    Write-Host "  Continuing anyway..." -ForegroundColor Yellow
}
Write-Host ""

# Install dependencies
Write-Host "[4/5] Installing dependencies..." -ForegroundColor Yellow
Write-Host "  This may take a few minutes..." -ForegroundColor Gray

# Upgrade pip
pip install --upgrade pip --quiet

# Install packages
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Dependencies installed successfully!" -ForegroundColor Green
} else {
    Write-Host "⚠ WARNING: Some packages may have failed" -ForegroundColor Yellow
    Write-Host "  Trying essential packages only..." -ForegroundColor Yellow
    pip install sqlalchemy pyyaml --quiet
}
Write-Host ""

# Test core components
Write-Host "[5/5] Testing core components..." -ForegroundColor Yellow
python test_core.py
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Core components test passed!" -ForegroundColor Green
} else {
    Write-Host "✗ ERROR: Core component test failed!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# Success message
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Setup Complete! ✓" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Initialize database: python init_db.py" -ForegroundColor White
Write-Host "  2. Read PROGRESS.md for implementation status" -ForegroundColor White
Write-Host "  3. Read WINDOWS_SETUP.md for detailed guide" -ForegroundColor White
Write-Host ""
Write-Host "To activate virtual environment in the future:" -ForegroundColor Cyan
Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host ""

Read-Host "Press Enter to continue"
