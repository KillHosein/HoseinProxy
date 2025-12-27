#!/bin/bash

# Quick FakeTLS Setup Script for Ubuntu
# Run this to quickly set up FakeTLS proxy

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== MTProto FakeTLS Quick Setup ===${NC}"

# Check root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Please run as root${NC}"
   exit 1
fi

# Get user input
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

echo -e "${GREEN}Setting up FakeTLS with domain: $TLS_DOMAIN${NC}"
echo -e "${GREEN}Port: $PORT${NC}"
echo -e "${GREEN}Workers: $WORKERS${NC}"

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Installing Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl start docker
    systemctl enable docker
fi

# Generate secret
SECRET=$(openssl rand -hex 16)
DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

# Create directories
mkdir -p /opt/mtproto-faketls
cd /opt/mtproto-faketls

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

# Get server IP
SERVER_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "YOUR_SERVER_IP")

# Start the proxy
echo -e "${YELLOW}Starting FakeTLS proxy...${NC}"
docker-compose up -d

# Wait for startup
sleep 10

# Check status
if docker-compose ps | grep -q "Up"; then
    echo -e "${GREEN}✅ FakeTLS proxy is running!${NC}"
    echo ""
    echo -e "${GREEN}=== Connection Information ===${NC}"
    echo "Domain: $TLS_DOMAIN"
    echo "Port: $PORT"
    echo "Secret: $SECRET"
    echo "Fake Secret: $FAKE_SECRET"
    echo ""
    echo -e "${GREEN}=== Proxy Links ===${NC}"
    echo "Telegram: https://t.me/proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
    echo "Direct: tg://proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
    echo ""
    echo -e "${YELLOW}To check logs: docker-compose logs -f${NC}"
    echo -e "${YELLOW}To stop: docker-compose down${NC}"
    echo -e "${YELLOW}To restart: docker-compose restart${NC}"
else
    echo -e "${RED}❌ Failed to start proxy. Check logs with: docker-compose logs${NC}"
    exit 1
fi

# Save info to file
cat > proxy-info.txt << EOF
MTProto FakeTLS Proxy Information
==============================
Domain: $TLS_DOMAIN
Port: $PORT
Secret: $SECRET
Fake Secret: $FAKE_SECRET
Workers: $WORKERS
Tag: ${TAG:-None}

Server IP: $SERVER_IP

Telegram Link:
https://t.me/proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET

Direct Link:
tg://proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET

Docker Commands:
- View logs: docker-compose logs -f
- Stop: docker-compose down
- Restart: docker-compose restart
- Check status: docker-compose ps
==============================
EOF

echo -e "${GREEN}Information saved to: /opt/mtproto-faketls/proxy-info.txt${NC}"