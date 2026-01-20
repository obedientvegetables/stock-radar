#!/bin/bash
# Fix Flask installation and start the service
# Run this on the GCP VM as the ned_lindau user

set -e

echo "=== Stock Radar Flask Setup Script ==="
echo ""

# Navigate to project directory
cd /home/ned_lindau/stock-radar

# Pull latest changes (includes Flask in requirements.txt)
echo "1. Pulling latest changes from GitHub..."
git pull origin main

# Ensure venv exists
if [ ! -d "venv" ]; then
    echo "2. Creating virtual environment..."
    python3 -m venv venv
else
    echo "2. Virtual environment already exists."
fi

# Activate venv and install Flask
echo "3. Installing Flask and dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install flask
pip install -r requirements.txt

# Ensure logs directory exists
mkdir -p logs

# Test Flask import
echo "4. Testing Flask installation..."
python -c "import flask; print(f'Flask {flask.__version__} installed successfully!')"

echo ""
echo "=== Installation complete! ==="
echo ""
echo "To run manually (for testing):"
echo "  source venv/bin/activate"
echo "  python app.py"
echo ""
echo "To set up as a systemd service (for persistence):"
echo "  sudo cp deployment/stock-radar.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable stock-radar"
echo "  sudo systemctl start stock-radar"
echo ""
echo "Check service status:"
echo "  sudo systemctl status stock-radar"
echo ""
echo "View logs:"
echo "  tail -f logs/flask.log"
echo ""
echo "Access dashboard at: http://34.10.246.252:5001"
