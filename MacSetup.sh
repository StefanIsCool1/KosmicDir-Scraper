#!/bin/bash

echo "========================================="
echo "THE UnderDeck Scraper, i hope you have a good day - stefa 
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
else
    echo -e "${RED}Unsupported OS. Please use Linux or macOS.${NC}"
    exit 1
fi

echo -e "${GREEN}Detected OS: $OS${NC}"
echo ""

# ========================================
# INSTALL PYTHON if missing
# ========================================
if ! command_exists python3; then
    echo -e "${YELLOW}Python not found. Installing Python 3...${NC}"
    
    if [ "$OS" = "mac" ]; then
        # Install on macOS
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        brew install python3
    elif [ "$OS" = "linux" ]; then
        # Install on Linux
        sudo apt update
        sudo apt install -y python3 python3-pip
    fi
else
    echo -e "${GREEN}✓ Python already installed: $(python3 --version)${NC}"
fi

# ========================================
# INSTALL NODE/NPM if missing
# ========================================
if ! command_exists node; then
    echo -e "${YELLOW}Node.js not found. Installing Node.js...${NC}"
    
    if [ "$OS" = "mac" ]; then
        # Install on macOS
        if ! command_exists brew; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install node
    elif [ "$OS" = "linux" ]; then
        # Install on Linux
        curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
        sudo apt install -y nodejs
    fi
else
    echo -e "${GREEN}✓ Node.js already installed: $(node --version)${NC}"
fi

# ========================================
# INSTALL BACKEND DEPENDENCIES
# ========================================
echo ""
echo -e "${GREEN}Installing Python packages...${NC}"
pip3 install flask flask-cors playwright

echo ""
echo -e "${GREEN}Installing Playwright browsers...${NC}"
python3 -m playwright install chromium

# ========================================
# INSTALL FRONTEND DEPENDENCIES
# ========================================
if [ -d "frontend" ]; then
    echo ""
    echo -e "${GREEN}Installing frontend dependencies...${NC}"
    cd frontend
    npm install
    cd ..
else
    echo -e "${YELLOW}Frontend folder not found. Skipping frontend install.${NC}"
fi

# ========================================
# DONE
# ========================================
echo ""
echo "========================================="
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo "========================================="
echo ""
echo "To run the app:"
echo ""
echo "1. Start the backend:"
echo "   python3 app.py"
echo ""
echo "2. In a new terminal, start the frontend:"
echo "   cd frontend"
echo "   npm start"
echo ""
echo "3. Open http://localhost:3000 in Chrome/Firefox"
echo ""