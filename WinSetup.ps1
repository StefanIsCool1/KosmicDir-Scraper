Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "🚀 UnderDeck Scraper - Windows Setup" -ForegroundColor Cyan
Write-Host "========================================="
Write-Host ""

# Check Python
Write-Host "Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python not found! Please install Python from python.org" -ForegroundColor Red
    Write-Host "Download: https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "Make sure to check 'Add Python to PATH' during installation"
    Read-Host "Press Enter to exit"
    exit
}

# Check pip
Write-Host ""
Write-Host "Checking pip..." -ForegroundColor Yellow
try {
    $pipVersion = pip --version 2>&1
    Write-Host "✓ pip is installed" -ForegroundColor Green
} catch {
    Write-Host "⚠ pip not found, but continuing..."
}

# Check Node.js
Write-Host ""
Write-Host "Checking Node.js..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version 2>&1
    Write-Host "✓ Node.js: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Node.js not found! Please install Node.js from nodejs.org" -ForegroundColor Red
    Write-Host "Download: https://nodejs.org/"
    Read-Host "Press Enter to exit"
    exit
}

# Install Python packages
Write-Host ""
Write-Host "Installing Python packages..." -ForegroundColor Green
pip install flask flask-cors playwright

# Install Playwright browsers
Write-Host ""
Write-Host "Installing Playwright browsers..." -ForegroundColor Green
python -m playwright install chromium

# Install frontend dependencies
if (Test-Path "frontend") {
    Write-Host ""
    Write-Host "Installing frontend dependencies..." -ForegroundColor Green
    Set-Location frontend
    npm install
    Set-Location ..
    Write-Host "✓ Frontend dependencies installed" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Frontend folder not found, skipping frontend install" -ForegroundColor Yellow
}

# Done
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "✅ Setup Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run the app:"
Write-Host ""
Write-Host "1. Start the backend:"
Write-Host "   python app.py"
Write-Host ""
Write-Host "2. In a new terminal, start the frontend:"
Write-Host "   cd frontend"
Write-Host "   npm start"
Write-Host ""
Write-Host "3. Open http://localhost:3000 in Chrome/Firefox"
Write-Host ""

Read-Host "Press Enter to exit"
