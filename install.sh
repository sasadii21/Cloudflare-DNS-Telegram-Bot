#!/usr/bin/env bash
set -euo pipefail

echo "=== Cloudflare DNS Telegram Bot Installer ==="

read -p "Enter Telegram Bot Token: " TG_TOKEN
read -p "Enter Cloudflare API Token: " CF_TOKEN
read -p "Enter Telegram Admin Numeric ID(s) (comma-separated): " ADMIN_IDS

# Create .env
cat <<EOF > .env
TELEGRAM_BOT_TOKEN=$TG_TOKEN
CLOUDFLARE_API_TOKEN=$CF_TOKEN
ADMIN_IDS=$ADMIN_IDS
EOF

echo "[+] .env created."

# Install deps
if command -v apt >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y python3 python3-pip python3-venv
fi

# venv
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo "[+] Installed successfully."
echo "Run:"
echo "  source venv/bin/activate"
echo "  python3 bot.py"
