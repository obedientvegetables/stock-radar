#!/bin/bash
# Stock Radar - Server Setup Script
# Run this once after creating the VM
#
# Usage:
#   chmod +x server_setup.sh
#   ./server_setup.sh

set -e  # Exit on error

echo "=============================================="
echo "       Stock Radar Server Setup"
echo "=============================================="
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please run as regular user, not root"
    exit 1
fi

# Update system
echo "[1/6] Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
echo ""
echo "[2/6] Installing Python and system dependencies..."
sudo apt install -y python3 python3-pip python3-venv git sqlite3 curl

# Verify Python version
PYTHON_VERSION=$(python3 --version)
echo "      Installed: $PYTHON_VERSION"

# Create app directory
echo ""
echo "[3/6] Creating application directory..."
mkdir -p ~/stock_radar
cd ~/stock_radar

# Create virtual environment
echo ""
echo "[4/6] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Create necessary directories
echo ""
echo "[5/6] Creating data directories..."
mkdir -p data logs output

# Set up log rotation (optional but recommended)
echo ""
echo "[6/6] Setting up log rotation..."
cat << 'EOF' | sudo tee /etc/logrotate.d/stock-radar > /dev/null
/home/*/stock_radar/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644
}
EOF

echo ""
echo "=============================================="
echo "       Server Setup Complete!"
echo "=============================================="
echo ""
echo "Directory structure created:"
echo "  ~/stock_radar/"
echo "  ├── data/       (database files)"
echo "  ├── logs/       (cron and app logs)"
echo "  ├── output/     (reports and charts)"
echo "  └── venv/       (Python environment)"
echo ""
echo "Next steps:"
echo ""
echo "1. On your LOCAL Mac, run the deploy script:"
echo "   cd ~/stock_radar/deployment"
echo "   ./deploy.sh YOUR_VM_EXTERNAL_IP"
echo ""
echo "2. Back on this server, install dependencies:"
echo "   cd ~/stock_radar"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "3. Create your .env file:"
echo "   cp env_template.txt .env"
echo "   nano .env"
echo ""
echo "4. Initialize the database:"
echo "   python3 daily_run.py init"
echo ""
echo "5. Test the system:"
echo "   python3 daily_run.py status"
echo "   python3 daily_run.py insider-collect --count 5"
echo ""
echo "6. Set up cron jobs:"
echo "   crontab -e"
echo "   # Add the lines from GOOGLE_CLOUD_SETUP.md Part 9"
echo ""
