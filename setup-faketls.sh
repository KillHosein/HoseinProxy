#!/bin/bash

# MTProto FakeTLS Setup Script
# This script sets up FakeTLS with popular domains like google.com, cloudflare.com, etc.

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

# Popular domains for FakeTLS
POPULAR_DOMAINS=(
    "google.com"
    "cloudflare.com"
    "microsoft.com"
    "apple.com"
    "amazon.com"
    "facebook.com"
    "twitter.com"
    "instagram.com"
    "whatsapp.com"
    "telegram.org"
    "cdn.discordapp.com"
    "cdn.cloudflare.com"
    "ajax.googleapis.com"
    "fonts.googleapis.com"
    "apis.google.com"
    "ssl.gstatic.com"
    "www.gstatic.com"
    "accounts.google.com"
    "drive.google.com"
    "docs.google.com"
)

print_header "MTProto FakeTLS Setup"
echo "Available domains for FakeTLS:"
echo ""
for i in "${!POPULAR_DOMAINS[@]}"; do
    printf "%2d. %-20s" $((i+1)) "${POPULAR_DOMAINS[$i]}"
    if (( (i+1) % 3 == 0 )); then
        echo ""
    fi
done
echo ""

# Get user input
read -p "Select domain number (1-${#POPULAR_DOMAINS[@]}): " DOMAIN_NUM
read -p "Enter port number: " PORT
read -p "Enter number of workers (default: 4): " WORKERS
read -p "Enter proxy tag (optional): " TAG
read -p "Enter proxy name (optional): " NAME

# Validate domain selection
if ! [[ "$DOMAIN_NUM" =~ ^[0-9]+$ ]] || (( DOMAIN_NUM < 1 || DOMAIN_NUM > ${#POPULAR_DOMAINS[@]} )); then
    print_error "Invalid domain selection"
    exit 1
fi

DOMAIN="${POPULAR_DOMAINS[$((DOMAIN_NUM-1))]}"
WORKERS=${WORKERS:-4}
SECRET=$(openssl rand -hex 16)

print_status "Setting up FakeTLS proxy with domain: $DOMAIN"
print_status "Port: $PORT"
print_status "Workers: $WORKERS"
print_status "Secret: $SECRET"

# Create necessary directories
mkdir -p ssl logs

# Create Docker Compose file for FakeTLS
cat > docker-compose-faketls.yml << EOF
version: '3.8'

services:
  mtproto-faketls-${PORT}:
    build:
      context: .
      dockerfile: Dockerfile.faketls
    container_name: mtproto_faketls_${PORT}
    restart: always
    ports:
      - "${PORT}:443"
    environment:
      SECRET: ${SECRET}
      TAG: ${TAG}
      WORKERS: ${WORKERS}
      TLS_DOMAIN: ${DOMAIN}
      PORT: 443
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
COPY entrypoint-faketls.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 443

ENTRYPOINT ["/entrypoint.sh"]
EOF

# Create entrypoint script
cat > entrypoint-faketls.sh << 'EOF'
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

chmod +x entrypoint-faketls.sh

# Generate FakeTLS secret
DOMAIN_HEX=$(echo -n "$DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

# Create proxy info file
cat > proxy-faketls-info.txt << EOF
MTProto FakeTLS Proxy Information
==============================
Domain: $DOMAIN
Secret: $SECRET
Fake Secret: $FAKE_SECRET
Workers: $WORKERS
Tag: ${TAG:-None}
Port: $PORT

Proxy Link: https://t.me/proxy?server=SERVER_IP&port=${PORT}&secret=${FAKE_SECRET}

Docker Commands:
- Start: docker-compose -f docker-compose-faketls.yml up -d
- View logs: docker-compose -f docker-compose-faketls.yml logs -f
- Stop: docker-compose -f docker-compose-faketls.yml down
- Restart: docker-compose -f docker-compose-faketls.yml restart
==============================
EOF

print_status "Building and starting FakeTLS proxy..."
docker-compose -f docker-compose-faketls.yml up -d

print_status "FakeTLS proxy setup completed!"
print_status "Domain: $DOMAIN"
print_status "Port: $PORT"
print_status "Secret: $SECRET"
print_status "Fake Secret: $FAKE_SECRET"
echo ""
echo "Proxy information saved to: proxy-faketls-info.txt"
echo "To test the proxy:"
echo "1. Open Telegram"
echo "2. Go to Settings > Data and Storage > Proxy Settings"
echo "3. Add proxy using the link in proxy-faketls-info.txt"
echo ""
echo "Replace SERVER_IP with your actual server IP address in the proxy link."