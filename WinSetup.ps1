Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Hi win users u suck but here is the UnderDeck Scraper - Complete Setup" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python already installed: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Python not found. Installing Python..." -ForegroundColor Yellow
    # Download Python installer
    $url = "https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe"
    $output = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri $url -OutFile $output
    
    # Install Python (silent mode)
    Start-Process -FilePath $output -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine")
    
    Write-Host "✓ Python installed" -ForegroundColor Green
}

# Check if Node.js is installed
try {
    $nodeVersion = node --version
    Write-Host "✓ Node.js already installed: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "Node.js not found. Installing Node.js..." -ForegroundColor Yellow
    # Download Node.js installer
    $url = "https://nodejs.org/dist/v18.17.1/node-v18.17.1-x64.msi"
    $output = "$env:TEMP\node-installer.msi"
    Invoke-WebRequest -Uri $url -OutFile $output
    
    # Install Node.js
    Start-Process -FilePath "msiexec.exe" -ArgumentList "/i $output /quiet" -Wait
    
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine")
    
    Write-Host "✓ Node.js installed" -ForegroundColor Green
}

# Install Python packages
Write-Host ""
Write-Host "Installing Python packages..." -ForegroundColor Green
pip install flask flask-cors playwright

Write-Host ""
Write-Host "Installing Playwright browsers..." -ForegroundColor Green
playwright install chromium

# Install frontend dependencies
if (Test-Path "frontend") {
    Write-Host ""
    Write-Host "Installing frontend dependencies..." -ForegroundColor Green
    Set-Location frontend
    npm install
    Set-Location ..
} else {
    Write-Host "Frontend folder not found. Skipping frontend install." -ForegroundColor Yellow
}

# Done
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "✅ Setup Complete!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run the app:" -ForegroundColor White
Write-Host ""
Write-Host "1. Start the backend:" -ForegroundColor Yellow
Write-Host "   python app.py" -ForegroundColor Gray
Write-Host ""
Write-Host "2. In a new terminal, start the frontend:" -ForegroundColor Yellow
Write-Host "   cd frontend" -ForegroundColor Gray
Write-Host "   npm start" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Open http://localhost:3000 in Chrome/Firefox" -ForegroundColor Cyan