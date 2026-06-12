#!/bin/bash
# Boof 30 EC2 Deployment Script

EC2_HOST="ubuntu@YOUR-EC2-IP"
KEY_PATH="~/.ssh/YOUR-KEY.pem"
REPO_URL="https://github.com/Tybrester/algorithims.git"

echo "=========================================="
echo "BOOF 30 EC2 DEPLOYMENT"
echo "=========================================="
echo ""

echo "Step 1: Pushing code to GitHub..."
git add BOOF30_LIVE_DEPLOY.py requirements_boof30.txt boof30.service 2>/dev/null || true
git commit -m "Add Boof 30 live trading bot" 2>/dev/null || echo "Nothing to commit"
git push origin main
echo "✓ Code pushed"
echo ""

echo "Step 2: Deploying to EC2..."
echo "Update EC2_HOST and KEY_PATH in this script first!"
echo ""
echo "Manual steps:"
echo "1. SSH into EC2: ssh -i \$KEY_PATH \$EC2_HOST"
echo "2. Pull code: cd ~/algorithims && git pull origin main"
echo "3. Install: pip3 install -r requirements_boof30.txt"
echo "4. Copy service: sudo cp boof30.service /etc/systemd/system/"
echo "5. Start: sudo systemctl start boof30"
