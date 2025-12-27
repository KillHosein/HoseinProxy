#!/bin/bash

# Complete MTProto FakeTLS Installation for Ubuntu
# Run this script to automatically install and configure FakeTLS

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}==== $1 ====${NC}"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_error "This script must be run as root (use sudo)"
   exit 1
fi

# Welcome message
print_header "MTProto FakeTLS Auto-Installer"
echo "This script will install and configure FakeTLS proxy on your Ubuntu server."
echo ""

# Get user preferences
echo "Select domain for FakeTLS:"
echo "1. google.com (Recommended - Most Reliable)"
echo "2. cloudflare.com (Good for Technical Environments)"
echo "3. microsoft.com (Good for Corporate Networks)"
echo "4. apple.com (Good for iOS/macOS Users)"
echo "5. amazon.com (E-commerce Traffic)"
read -p "Enter your choice (1-5) [1]: " DOMAIN_CHOICE

read -p "Enter port number [443]: " PORT
read -p "Enter number of workers [4]: " WORKERS
read -p "Enter proxy tag (optional): " TAG
read -p "Enter your server IP (optional, will auto-detect): " SERVER_IP

# Set defaults
DOMAIN_CHOICE=${DOMAIN_CHOICE:-1}
PORT=${PORT:-443}
WORKERS=${WORKERS:-4}

# Map domain choice
case $DOMAIN_CHOICE in
    1) TLS_DOMAIN="google.com" ;;
    2) TLS_DOMAIN="cloudflare.com" ;;
    3) TLS_DOMAIN="microsoft.com" ;;
    4) TLS_DOMAIN="apple.com" ;;
    5) TLS_DOMAIN="amazon.com" ;;
    *) TLS_DOMAIN="google.com" ;;
esac

# Auto-detect server IP if not provided
if [ -z "$SERVER_IP" ]; then
    SERVER_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "YOUR_SERVER_IP")
fi

print_status "Starting installation with domain: $TLS_DOMAIN"
print_status "Port: $PORT"
print_status "Workers: $WORKERS"
print_status "Server IP: $SERVER_IP"

# Update system
print_status "Updating system packages..."
apt update && apt upgrade -y

# Install dependencies
print_status "Installing dependencies..."
apt install -y \
    curl \
    wget \
    git \
    openssl \
    python3 \
    python3-pip \
    nginx \
    certbot \
    python3-certbot-nginx \
    ufw \
    fail2ban

# Install Docker
print_status "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
fi

# Install Docker Compose
print_status "Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Configure firewall
print_status "Configuring firewall..."
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow "$PORT/tcp"
ufw --force enable

# Create project directory
PROJECT_DIR="/opt/mtproto-faketls"
print_status "Creating project directory: $PROJECT_DIR"
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# Generate secret
SECRET=$(openssl rand -hex 16)
DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

# Create Docker Compose
cat > docker-compose.yml << EOF
version: '3.8'

services:
  mtproto-faketls:
    image: golang:1.21-alpine
    container_name: mtproto_faketls_${PORT}
    restart: always
    ports:
      - "${PORT}:443"
    command: |
      sh -c "
        apk add --no-cache git openssl &&
        git clone https://github.com/TelegramMessenger/MTProxy.git /app &&
        cd /app &&
        go mod init mtproxy || true &&
        go mod tidy || true &&
        CGO_ENABLED=0 GOOS=linux go build -o mtproto-proxy ./cmd/proxy &&
        mkdir -p /etc/ssl/certs /etc/ssl/private /var/log/mtproto &&
        openssl genrsa -out /etc/ssl/private/privkey.pem 2048 &&
        openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr -subj '/C=US/ST=CA/L=Mountain View/O=Google LLC/CN=$TLS_DOMAIN' &&
        openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem -out /etc/ssl/certs/fullchain.pem &&
        rm -f /tmp/cert.csr &&
        ./mtproto-proxy \\
          -u nobody \\
          -p 8888,80,443 \\
          -H 443 \\
          -S $FAKE_SECRET \\
          --address 0.0.0.0 \\
          --port 443 \\
          --http-ports 80 \\
          --slaves $WORKERS \\
          --max-special-connections 60000 \\
          --allow-skip-dh \\
          --cert /etc/ssl/certs/fullchain.pem \\
          --key /etc/ssl/private/privkey.pem \\
          --dc 1,149.154.175.50,443 \\
          --dc 2,149.154.167.51,443 \\
          --dc 3,149.154.175.100,443 \\
          --dc 4,149.154.167.91,443 \\
          --dc 5,91.108.56.151,443 \\
          ${TAG:+--tag $TAG}
      "
    volumes:
      - ./logs:/var/log/mtproto
EOF

# Create management script
cat > manage-proxy.sh << 'EOF'
#!/bin/bash

# MTProto FakeTLS Management Script

cd /opt/mtproto-faketls

case "$1" in
    start)
        echo "Starting FakeTLS proxy..."
        docker-compose up -d
        ;;
    stop)
        echo "Stopping FakeTLS proxy..."
        docker-compose down
        ;;
    restart)
        echo "Restarting FakeTLS proxy..."
        docker-compose restart
        ;;
    logs)
        echo "Viewing logs..."
        docker-compose logs -f
        ;;
    status)
        echo "Checking status..."
        docker-compose ps
        ;;
    info)
        echo "Proxy Information:"
        echo "=================="
        if [ -f .env ]; then
            source .env
            echo "Domain: $TLS_DOMAIN"
            echo "Port: $PORT"
            echo "Secret: $SECRET"
            echo "Fake Secret: $FAKE_SECRET"
            echo "Workers: $WORKERS"
            echo "Tag: $TAG"
            echo ""
            echo "Telegram Link:"
            echo "tg://proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
        else
            echo "No configuration found."
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|status|info}"
        exit 1
        ;;
esac
EOF

chmod +x manage-proxy.sh

# Create environment file
cat > .env << EOF
SECRET=$SECRET
TAG=$TAG
WORKERS=$WORKERS
TLS_DOMAIN=$TLS_DOMAIN
PORT=$PORT
SERVER_IP=$SERVER_IP
FAKE_SECRET=$FAKE_SECRET
EOF

# Start the proxy
print_status "Starting FakeTLS proxy..."
docker-compose up -d

# Wait for startup
sleep 15

# Check if running
if docker-compose ps | grep -q "Up"; then
    print_status "✅ FakeTLS proxy is running successfully!"
else
    print_error "❌ Failed to start proxy. Check logs with: docker-compose logs"
    exit 1
fi

# Create systemd service
cat > /etc/systemd/system/mtproto-faketls.service << EOF
[Unit]
Description=MTProto FakeTLS Proxy
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mtproto-faketls

# Create proxy info file
cat > proxy-info.txt << EOF
🚀 MTProto FakeTLS Proxy Information
=====================================

📡 Connection Details:
   Domain: $TLS_DOMAIN
   Port: $PORT
   Server IP: $SERVER_IP
   Workers: $WORKERS
   Tag: ${TAG:-None}

🔑 Secrets:
   Base Secret: $SECRET
   Fake Secret: $FAKE_SECRET

🔗 Quick Links:
   Telegram: https://t.me/proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET
   Direct: tg://proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET

⚙️  Management Commands:
   cd $PROJECT_DIR
   ./manage-proxy.sh {start|stop|restart|logs|status|info}

📊 Monitor:
   docker-compose logs -f
   docker-compose ps

🔒 Security:
   - Firewall: Active (UFW)
   - Fail2ban: Installed
   - Auto-start: Enabled

=====================================
🎉 Installation completed successfully!
=====================================
EOF

# Final status check
print_header "Installation Complete!"
print_status "FakeTLS proxy has been installed and is running."
print_status "Domain: $TLS_DOMAIN"
print_status "Port: $PORT"
print_status "Server IP: $SERVER_IP"
print_status ""
print_status "📋 Information saved to: $PROJECT_DIR/proxy-info.txt"
print_status "🛠️  Management script: $PROJECT_DIR/manage-proxy.sh"
print_status ""
echo -e "${BLUE}=== Proxy Links ===${NC}"
echo "Telegram: https://t.me/proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
echo "Direct: tg://proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
echo ""
echo -e "${YELLOW}To test:${NC}"
echo "1. Open Telegram"
echo "2. Settings → Data and Storage → Proxy Settings"
echo "3. Add proxy using the link above"
echo ""
echo -e "${GREEN}✅ Your FakeTLS proxy is ready to use!${NC}"