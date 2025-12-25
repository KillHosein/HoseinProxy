#!/bin/bash
set -e

echo "========================================="
echo "   HoseinProxy Panel Installer           "
echo "========================================="

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

# Function to wait for apt locks
wait_for_apt_locks() {
    echo "[*] Checking for background updates..."
    # Check for running package manager processes
    while pgrep -x "apt" >/dev/null || pgrep -x "apt-get" >/dev/null || pgrep -x "dpkg" >/dev/null || pgrep -f "unattended-upgr" >/dev/null; do
        echo "   Waiting for other package managers to finish (apt/dpkg)..."
        sleep 5
    done
}

# Robust update function
run_apt_update() {
    echo "[*] Updating system..."
    local MAX_RETRIES=5
    local COUNT=0
    while [ $COUNT -lt $MAX_RETRIES ]; do
        wait_for_apt_locks
        if apt-get update; then
            return 0
        fi
        echo "   Update failed. Retrying in 10 seconds..."
        sleep 10
        COUNT=$((COUNT+1))
    done
    echo "Error: Failed to update system after multiple attempts."
    exit 1
}

# Robust install function
run_apt_install() {
    echo "[*] Installing dependencies..."
    local MAX_RETRIES=5
    local COUNT=0
    while [ $COUNT -lt $MAX_RETRIES ]; do
        wait_for_apt_locks
        if apt-get install -y "$@"; then
            return 0
        fi
        echo "   Install failed. Retrying in 10 seconds..."
        sleep 10
        COUNT=$((COUNT+1))
    done
    echo "Error: Failed to install dependencies."
    exit 1
}

run_apt_update
run_apt_install python3 python3-pip python3-venv docker.io curl nginx

echo "[*] Setting up Docker..."
systemctl enable docker
systemctl start docker

# Configure Nginx
echo "[*] Configuring Nginx Reverse Proxy..."
# Remove default Nginx config if it exists
if [ -f /etc/nginx/sites-enabled/default ]; then
    echo "   Removing default Nginx site..."
    rm -f /etc/nginx/sites-enabled/default
fi

cat > /etc/nginx/sites-available/hoseinproxy <<EOF
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/hoseinproxy /etc/nginx/sites-enabled/

echo "[*] Verifying Nginx configuration..."
nginx -t

echo "[*] Restarting Nginx..."
systemctl restart nginx


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
ExecStart=$SCRIPT_DIR/panel/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
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
