#!/bin/bash
set -e

echo "========================================="
echo "   HoseinProxy Panel Installer           "
echo "========================================="

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

echo "[*] Updating system..."
apt-get update

echo "[*] Installing dependencies..."
apt-get install -y python3 python3-pip python3-venv docker.io curl

echo "[*] Setting up Docker..."
systemctl enable docker
systemctl start docker

# Create venv
echo "[*] Setting up Python Environment..."
# Ensure we are in the correct directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/panel"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

echo "[*] Installing Python requirements..."
pip install -r requirements.txt

echo "[*] Creating Admin User..."
echo "Please enter credentials for the admin panel:"
read -p "Username: " ADMIN_USER
while true; do
    read -s -p "Password: " ADMIN_PASS
    echo
    read -s -p "Confirm Password: " ADMIN_PASS_CONFIRM
    echo
    [ "$ADMIN_PASS" = "$ADMIN_PASS_CONFIRM" ] && break
    echo "Passwords do not match. Please try again."
done

python3 -c "from app import create_admin; create_admin('$ADMIN_USER', '$ADMIN_PASS')"

# Create Systemd Service
echo "[*] Creating Systemd Service..."
SERVICE_FILE="/etc/systemd/system/hoseinproxy.service"
cat > $SERVICE_FILE <<EOF
[Unit]
Description=HoseinProxy Management Panel
After=network.target docker.service
Requires=docker.service

[Service]
User=root
WorkingDirectory=$SCRIPT_DIR/panel
Environment="PATH=$SCRIPT_DIR/panel/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$SCRIPT_DIR/panel/venv/bin/gunicorn -w 2 -b 0.0.0.0:80 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hoseinproxy
systemctl restart hoseinproxy

echo "========================================="
echo "   Installation Complete!                "
echo "   Panel is running at http://$(curl -s ifconfig.me):80 "
echo "========================================="
