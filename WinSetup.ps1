Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "🚀 UnderDeck Scraper - Windows Setup" -ForegroundColor Cyan
Write-Host "========================================="
Write-Host ""

# Function to check if command exists
function Command-Exists {
    param($command)
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Stop'
    try {
        if (Get-Command $command) { return $true }
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldPreference
    }
}

# Check Python
Write-Host "🔍 Checking Python..." -ForegroundColor Yellow
if (Command-Exists "python") {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ Python: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "  ⚠ Python not found. Installing Python..." -ForegroundColor Yellow
    try {
        $url = "https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe"
        $output = "$env:TEMP\python-installer.exe"
        Write-Host "  Downloading Python installer..."
        Invoke-WebRequest -Uri $url -OutFile $output
        Write-Host "  Installing Python (this may take a minute)..."
        Start-Process -FilePath $output -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
        Remove-Item $output
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        Write-Host "  ✓ Python installed successfully" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed to install Python: $_" -ForegroundColor Red
        exit 1
    }
}

# Check Node.js
Write-Host ""
Write-Host "🔍 Checking Node.js..." -ForegroundColor Yellow
if (Command-Exists "node") {
    $nodeVersion = node --version
    Write-Host "  ✓ Node.js: $nodeVersion" -ForegroundColor Green
} else {
    Write-Host "  ⚠ Node.js not found. Installing Node.js..." -ForegroundColor Yellow
    try {
        $url = "https://nodejs.org/dist/v18.17.1/node-v18.17.1-x64.msi"
        $output = "$env:TEMP\node-installer.msi"
        Write-Host "  Downloading Node.js installer..."
        Invoke-WebRequest -Uri $url -OutFile $output
        Write-Host "  Installing Node.js..."
        Start-Process -FilePath "msiexec.exe" -ArgumentList "/i $output /quiet" -Wait
        Remove-Item $output
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        Write-Host "  ✓ Node.js installed successfully" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed to install Node.js: $_" -ForegroundColor Red
        exit 1
    }
}

# Install Python packages
Write-Host ""
Write-Host "📦 Installing Python packages..." -ForegroundColor Green
try {
    pip install flask flask-cors playwright
    Write-Host "  ✓ Python packages installed" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Failed to install Python packages: $_" -ForegroundColor Red
    exit 1
}

# Install Playwright browsers
Write-Host ""
Write-Host "🌐 Installing Playwright browsers..." -ForegroundColor Green
try {
    playwright install chromium
    Write-Host "  ✓ Playwright browsers installed" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Failed to install Playwright browsers: $_" -ForegroundColor Red
    exit 1
}

# Install frontend dependencies
if (Test-Path "frontend") {
    Write-Host ""
    Write-Host "📦 Installing frontend dependencies..." -ForegroundColor Green
    try {
        Set-Location frontend
        npm install
        Set-Location ..
        Write-Host "  ✓ Frontend dependencies installed" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed to install frontend dependencies: $_" -ForegroundColor Red
        exit 1
    }
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
Write-Host ""

# Keep window open
Read-Host "Press Enter to exit"
