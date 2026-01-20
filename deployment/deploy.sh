#!/bin/bash
# Stock Radar - Deploy to Google Cloud VM
# Run this from your LOCAL machine to push code to the server
#
# Usage:
#   ./deploy.sh <VM_EXTERNAL_IP> [username]
#
# Examples:
#   ./deploy.sh 35.192.123.456
#   ./deploy.sh 35.192.123.456 john

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Error: VM IP address required${NC}"
    echo ""
    echo "Usage: ./deploy.sh <VM_EXTERNAL_IP> [username]"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh 35.192.123.456"
    echo "  ./deploy.sh 35.192.123.456 myuser"
    echo ""
    echo "Get your VM's external IP from:"
    echo "  Google Cloud Console > Compute Engine > VM instances"
    exit 1
fi

VM_IP=$1
VM_USER=${2:-$USER}  # Default to current username
LOCAL_DIR=~/stock_radar
REMOTE_DIR="~/stock_radar"

echo "=============================================="
echo "       Stock Radar Deployment"
echo "=============================================="
echo ""
echo "Target:  ${VM_USER}@${VM_IP}"
echo "Source:  ${LOCAL_DIR}"
echo ""

# Check if local directory exists
if [ ! -d "$LOCAL_DIR" ]; then
    echo -e "${RED}Error: Local directory not found: ${LOCAL_DIR}${NC}"
    exit 1
fi

# Check if rsync is available
if ! command -v rsync &> /dev/null; then
    echo -e "${RED}Error: rsync is required but not installed${NC}"
    echo "Install with: brew install rsync"
    exit 1
fi

# Test SSH connection
echo -e "${YELLOW}Testing SSH connection...${NC}"
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes ${VM_USER}@${VM_IP} "echo 'SSH OK'" 2>/dev/null; then
    echo -e "${RED}Error: Cannot connect to ${VM_USER}@${VM_IP}${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "1. Verify the IP address is correct"
    echo "2. Make sure you've connected via gcloud ssh first:"
    echo "   gcloud compute ssh stock-radar-vm --zone=us-central1-a"
    echo "3. Check your SSH keys are set up"
    exit 1
fi
echo -e "${GREEN}SSH connection successful${NC}"
echo ""

# Sync code
echo -e "${YELLOW}Syncing code to server...${NC}"
rsync -avz --progress \
    --exclude 'venv/' \
    --exclude 'data/*.db' \
    --exclude 'data/*.db-journal' \
    --exclude 'logs/' \
    --exclude 'output/*.png' \
    --exclude 'output/*.json' \
    --exclude 'output/*.txt' \
    --exclude '__pycache__/' \
    --exclude '.env' \
    --exclude '.git/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    --exclude '.vscode/' \
    --exclude '.idea/' \
    ${LOCAL_DIR}/ ${VM_USER}@${VM_IP}:${REMOTE_DIR}/

echo ""
echo -e "${GREEN}=============================================="
echo "       Deployment Complete!"
echo "==============================================${NC}"
echo ""
echo "Files synced to ${VM_USER}@${VM_IP}:${REMOTE_DIR}/"
echo ""
echo -e "${YELLOW}Excluded (not synced):${NC}"
echo "  - venv/           (recreate on server)"
echo "  - data/*.db       (your local database)"
echo "  - logs/           (local logs)"
echo "  - output/         (local reports)"
echo "  - .env            (contains secrets)"
echo "  - __pycache__/    (Python cache)"
echo ""
echo -e "${YELLOW}Next steps on the server:${NC}"
echo ""
echo "1. SSH in:"
echo "   ssh ${VM_USER}@${VM_IP}"
echo "   # or"
echo "   gcloud compute ssh stock-radar-vm --zone=us-central1-a"
echo ""
echo "2. Install/update dependencies:"
echo "   cd ~/stock_radar"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "3. If first deployment, create .env:"
echo "   cp deployment/env_template.txt .env"
echo "   nano .env  # Edit with your settings"
echo ""
echo "4. If first deployment, initialize database:"
echo "   python3 daily_run.py init"
echo ""
echo "5. Test it works:"
echo "   python3 daily_run.py status"
echo ""
