#!/bin/bash
# Boof 30 EC2 Deployment Script
# Usage: ./deploy_boof30.sh

echo "=========================================="
echo "BOOF 30 EC2 DEPLOYMENT"
echo "=========================================="
echo ""

# Configuration
EC2_HOST="ubuntu@your-ec2-ip"
KEY_PATH="~/.ssh/your-key.pem"
REPO_URL="https://github.com/Tybrester/algorithims.git"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "Step 1: Pushing code to GitHub..."
git add BOOF30_LIVE_DEPLOY.py requirements_boof30.txt boof30.service
git commit -m "Add Boof 30 live trading bot"
git push origin main
echo -e "${GREEN}✓ Code pushed${NC}"
echo ""

echo "Step 2: Deploying to EC2..."
ssh -i $KEY_PATH $EC2_HOST << 'EOF'
    echo "  Updating system..."
    sudo apt-get update -qq
    
    echo "  Pulling latest code..."
    cd ~/algorithims || git clone $REPO_URL algorithims
    cd ~/algorithims
    git pull origin main
    
    echo "  Installing dependencies..."
    pip3 install -q -r requirements_boof30.txt
    
    echo "  Creating log directory..."
    mkdir -p ~/logs
    
    echo "  Setting up systemd service..."
    sudo cp boof30.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable boof30.service
    
    echo "  Restarting Boof 30 service..."
    sudo systemctl restart boof30.service
    
    echo "  Checking status..."
    sleep 2
    sudo systemctl status boof30.service --no-pager
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Boof 30 deployed successfully${NC}"
    echo ""
    echo "To check logs:"
    echo "  ssh -i $KEY_PATH $EC2_HOST 'tail -f ~/logs/boof30.log'"
    echo ""
    echo "To check status:"
    echo "  ssh -i $KEY_PATH $EC2_HOST 'sudo systemctl status boof30'"
else
    echo -e "${RED}✗ Deployment failed${NC}"
    exit 1
fi
