#!/bin/bash

# MTProto FakeTLS Auto-Installer for Ubuntu
# This script automatically installs and configures FakeTLS proxy

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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
   print_error "This script must be run as root"
   exit 1
fi

# Check if Ubuntu
if ! grep -qi ubuntu /etc/os-release; then
    print_warning "This script is optimized for Ubuntu, but continuing..."
fi

print_header "MTProto FakeTLS Auto-Installer"
print_status "Starting installation on Ubuntu..."

# Update system
print_status "Updating system packages..."
apt update && apt upgrade -y

# Install required packages
print_status "Installing required packages..."
apt install -y \
    curl \
    wget \
    git \
    openssl \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
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
    usermod -aG docker $SUDO_USER || true
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
ufw --force enable

# Create project directory
print_status "Creating project directory..."
PROJECT_DIR="/opt/mtproto-faketls"
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR

# Create Docker Compose for FakeTLS
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  mtproto-faketls:
    build:
      context: .
      dockerfile: Dockerfile.faketls
    container_name: mtproto_faketls
    restart: always
    ports:
      - "443:443"
      - "8443:8443"
      - "8843:8843"
    environment:
      SECRET: ${SECRET}
      TAG: ${TAG}
      WORKERS: ${WORKERS}
      TLS_DOMAIN: ${TLS_DOMAIN}
      PORT: ${PORT}
    volumes:
      - ./ssl:/etc/ssl/certs:ro
      - ./logs:/var/log/mtproto
    networks:
      - mtproto_network

networks:
  mtproto_network:
    driver: bridge
EOF

# Create Dockerfile for FakeTLS
cat > Dockerfile.faketls << 'EOF'
FROM golang:1.21-alpine AS builder

RUN apk add --no-cache git openssl

WORKDIR /app

# Clone MTProxy source
RUN git clone https://github.com/TelegramMessenger/MTProxy.git . && \
    go mod init mtproxy || true && \
    go mod tidy || true

# Build the proxy
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o mtproto-proxy ./cmd/proxy

FROM alpine:latest

RUN apk --no-cache add ca-certificates openssl

WORKDIR /root/

COPY --from=builder /app/mtproto-proxy .

# Create directories
RUN mkdir -p /var/log/mtproto /etc/ssl/certs /etc/ssl/private

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443

ENTRYPOINT ["/entrypoint.sh"]
EOF

# Create entrypoint script
cat > entrypoint.sh << 'EOF'
#!/bin/sh
set -e

SECRET=${SECRET:-$(openssl rand -hex 16)}
WORKERS=${WORKERS:-4}
TAG=${TAG:-}
TLS_DOMAIN=${TLS_DOMAIN:-google.com}
PORT=${PORT:-443}

echo "Setting up FakeTLS proxy..."
echo "Domain: $TLS_DOMAIN"
echo "Port: $PORT"
echo "Workers: $WORKERS"

# Generate certificate for fake domain
mkdir -p /etc/ssl/certs /etc/ssl/private

# Generate private key
openssl genrsa -out /etc/ssl/private/privkey.pem 2048

# Generate certificate signing request
openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr \
    -subj "/C=US/ST=CA/L=Mountain View/O=Google LLC/CN=$TLS_DOMAIN"

# Generate self-signed certificate
openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem \
    -out /etc/ssl/certs/fullchain.pem

# Clean up
rm -f /tmp/cert.csr

# Prepare FakeTLS secret
echo "Preparing FakeTLS secret for domain: $TLS_DOMAIN"
DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

echo "Fake Secret: $FAKE_SECRET"

TAG_PARAM=""
if [ -n "$TAG" ]; then
    TAG_PARAM="--tag $TAG"
fi

# Start the proxy
exec ./mtproto-proxy \
    -u nobody \
    -p 8888,80,$PORT \
    -H $PORT \
    -S $FAKE_SECRET \
    --address 0.0.0.0 \
    --port $PORT \
    --http-ports 80 \
    --slaves $WORKERS \
    --max-special-connections 60000 \
    --allow-skip-dh \
    --cert /etc/ssl/certs/fullchain.pem \
    --key /etc/ssl/private/privkey.pem \
    --dc 1,149.154.175.50,443 \
    --dc 2,149.154.167.51,443 \
    --dc 3,149.154.175.100,443 \
    --dc 4,149.154.167.91,443 \
    --dc 5,91.108.56.151,443 \
    $TAG_PARAM
EOF

chmod +x entrypoint.sh

# Create management script
cat > manage-faketls.sh << 'EOF'
#!/bin/bash

# MTProto FakeTLS Management Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd $SCRIPT_DIR

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
    build)
        echo "Building Docker image..."
        docker-compose build
        ;;
    info)
        echo "Proxy Information:"
        echo "=================="
        if [ -f .env ]; then
            source .env
            DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
            FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"
            echo "Domain: $TLS_DOMAIN"
            echo "Port: $PORT"
            echo "Secret: $SECRET"
            echo "Fake Secret: $FAKE_SECRET"
            echo "Workers: $WORKERS"
            echo "Tag: $TAG"
            echo ""
            echo "Proxy Link:"
            echo "tg://proxy?server=YOUR_SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
            echo ""
            echo "Telegram Link:"
            echo "https://t.me/proxy?server=YOUR_SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
        else
            echo "No configuration found. Run setup first."
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|status|build|info}"
        exit 1
        ;;
esac
EOF

chmod +x manage-faketls.sh

# Create setup script for easy configuration
cat > setup-proxy.sh << 'EOF'
#!/bin/bash

# Interactive setup script

echo "=== MTProto FakeTLS Proxy Setup ==="
echo ""
echo "Available domains for FakeTLS:"
echo "1. google.com (Recommended)"
echo "2. cloudflare.com"
echo "3. microsoft.com"
echo "4. apple.com"
echo "5. amazon.com"
echo "6. facebook.com"
echo "7. twitter.com"
echo "8. instagram.com"
echo "9. whatsapp.com"
echo "10. telegram.org"
echo ""

read -p "Select domain (1-10) [1]: " DOMAIN_CHOICE
read -p "Enter port number [443]: " PORT
read -p "Enter number of workers [4]: " WORKERS
read -p "Enter proxy tag (optional): " TAG
read -p "Enter proxy name (optional): " NAME

# Set defaults
DOMAIN_CHOICE=${DOMAIN_CHOICE:-1}
PORT=${PORT:-443}
WORKERS=${WORKERS:-4}

# Map domain choice to domain name
case $DOMAIN_CHOICE in
    1) TLS_DOMAIN="google.com" ;;
    2) TLS_DOMAIN="cloudflare.com" ;;
    3) TLS_DOMAIN="microsoft.com" ;;
    4) TLS_DOMAIN="apple.com" ;;
    5) TLS_DOMAIN="amazon.com" ;;
    6) TLS_DOMAIN="facebook.com" ;;
    7) TLS_DOMAIN="twitter.com" ;;
    8) TLS_DOMAIN="instagram.com" ;;
    9) TLS_DOMAIN="whatsapp.com" ;;
    10) TLS_DOMAIN="telegram.org" ;;
    *) TLS_DOMAIN="google.com" ;;
esac

# Generate secret
SECRET=$(openssl rand -hex 16)

# Create environment file
cat > .env << EOF
SECRET=$SECRET
TAG=$TAG
WORKERS=$WORKERS
TLS_DOMAIN=$TLS_DOMAIN
PORT=$PORT
NAME=$NAME
EOF

echo ""
echo "Configuration created:"
echo "Domain: $TLS_DOMAIN"
echo "Port: $PORT"
echo "Workers: $WORKERS"
echo "Secret: $SECRET"
echo ""

# Generate proxy link
DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

# Get server IP
SERVER_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "YOUR_SERVER_IP")

echo "Proxy Links:"
echo "Telegram: https://t.me/proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
echo "Direct: tg://proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
echo ""
echo "Save this information!"
EOF

chmod +x setup-proxy.sh

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
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Create initial setup
print_status "Running initial setup..."
./setup-proxy.sh

# Build Docker image
print_status "Building Docker image..."
docker-compose build

# Start the service
print_status "Starting FakeTLS proxy..."
./manage-faketls.sh start

# Wait for service to start
sleep 10

# Check status
print_status "Checking service status..."
./manage-faketls.sh status

# Create proxy info
./manage-faketls.sh info > proxy-info.txt

# Enable auto-start
systemctl enable mtproto-faketls

print_header "Installation Complete!"
print_status "FakeTLS proxy has been installed and started."
print_status "Management script: $PROJECT_DIR/manage-faketls.sh"
print_status "Setup script: $PROJECT_DIR/setup-proxy.sh"
print_status "Proxy info: $PROJECT_DIR/proxy-info.txt"
print_status ""
print_status "To manage the proxy:"
print_status "  cd $PROJECT_DIR"
print_status "  ./manage-faketls.sh {start|stop|restart|logs|status|info}"
print_status ""
print_status "To reconfigure:"
print_status "  ./setup-proxy.sh"
print_status ""
echo "Check proxy-info.txt for your connection details."