#!/bin/bash

# Cloudflare Bot Installer
# Installs dependencies, sets up environment variables, and creates a systemd service.

SERVICE_NAME="cfbot"
INSTALL_DIR=$(pwd)
PYTHON_EXEC="/usr/bin/python3"

echo "--------------------------------------------------"
echo "   Cloudflare DNS Telegram Bot - Installer"
echo "--------------------------------------------------"

# 1. Check Root
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (sudo bash install.sh)"
  exit
fi

# 2. Install System Dependencies
echo "[+] Installing system dependencies..."
apt-get update -y
apt-get install python3-pip python3-venv -y

# 3. Install Python Dependencies
echo "[+] Installing Python libraries..."
pip3 install -r requirements.txt

# 4. Configure Environment Variables
echo "--------------------------------------------------"
echo "Please enter your configuration details:"
echo "--------------------------------------------------"

read -p "Enter Telegram Bot Token: " TG_TOKEN
read -p "Enter Cloudflare API Token (Edit Zone DNS permission): " CF_TOKEN
read -p "Enter your Telegram Admin Numeric ID: " ADMIN_ID

# Create .env file
cat <<EOF > .env
TELEGRAM_BOT_TOKEN=$TG_TOKEN
CLOUDFLARE_API_TOKEN=$CF_TOKEN
ADMIN_ID=$ADMIN_ID
EOF

echo "[+] Configuration saved to .env"

# 5. Create Systemd Service
echo "[+] Creating Systemd Service..."

cat <<EOF > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=Cloudflare DNS Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_EXEC $INSTALL_DIR/bot.py
Restart=always
RestartSec=5
EnvironmentFile=$INSTALL_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable and Start Service
echo "[+] Starting Service..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

echo "--------------------------------------------------"
echo "✅ Installation Complete!"
echo "Bot status: systemctl status $SERVICE_NAME"
echo "Stop bot: systemctl stop $SERVICE_NAME"
echo "--------------------------------------------------"
