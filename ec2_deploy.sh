#!/bin/bash
# Boof 23 + Boof 29 EC2 Deploy Script
# Run on Amazon Linux 2023 EC2 instance

set -e
echo "=== Installing dependencies ==="
sudo dnf install -y python3 python3-pip git

echo "=== Installing Python packages ==="
pip3 install alpaca-py pandas numpy pytz requests

echo "=== Creating bot directory ==="
mkdir -p ~/boof_bots
cd ~/boof_bots

echo "=== Writing boof23_analysis.py ==="
cat > ~/boof_bots/boof23_analysis.py << 'PYEOF'
BOOF23_ANALYSIS_PLACEHOLDER
PYEOF

echo "=== Writing boof23_paper.py ==="
cat > ~/boof_bots/boof23_paper.py << 'PYEOF'
BOOF23_PAPER_PLACEHOLDER
PYEOF

echo "=== Writing boof29_paper.py ==="
cat > ~/boof_bots/boof29_paper.py << 'PYEOF'
BOOF29_PAPER_PLACEHOLDER
PYEOF

echo "=== Creating systemd service: boof23 ==="
sudo tee /etc/systemd/system/boof23.service > /dev/null << 'EOF'
[Unit]
Description=Boof 23 Paper Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/boof_bots
ExecStart=/usr/bin/python3 /home/ec2-user/boof_bots/boof23_paper.py
Restart=always
RestartSec=30
StandardOutput=append:/home/ec2-user/boof_bots/boof23_paper.log
StandardError=append:/home/ec2-user/boof_bots/boof23_paper.log

[Install]
WantedBy=multi-user.target
EOF

echo "=== Creating systemd service: boof29 ==="
sudo tee /etc/systemd/system/boof29.service > /dev/null << 'EOF'
[Unit]
Description=Boof 29 Paper Trading Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/boof_bots
ExecStart=/usr/bin/python3 /home/ec2-user/boof_bots/boof29_paper.py
Restart=always
RestartSec=30
StandardOutput=append:/home/ec2-user/boof_bots/boof29_paper.log
StandardError=append:/home/ec2-user/boof_bots/boof29_paper.log

[Install]
WantedBy=multi-user.target
EOF

echo "=== Enabling and starting services ==="
sudo systemctl daemon-reload
sudo systemctl enable boof23 boof29
sudo systemctl start boof23 boof29

echo ""
echo "=== STATUS ==="
sudo systemctl status boof23 --no-pager | tail -5
sudo systemctl status boof29 --no-pager | tail -5
echo ""
echo "=== DONE — Both bots running. Logs:"
echo "  tail -f ~/boof_bots/boof23_paper.log"
echo "  tail -f ~/boof_bots/boof29_paper.log"
