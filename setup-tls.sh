#!/bin/bash

# MTProto TLS Setup Script
# This script sets up TLS for MTProto proxy with Let's Encrypt certificates

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_error "This script must be run as root"
   exit 1
fi

# Get user input
read -p "Enter your domain name (e.g., proxy.yourdomain.com): " DOMAIN
read -p "Enter your email for Let's Encrypt: " EMAIL
read -p "Enter proxy secret (leave empty to generate): " SECRET
read -p "Enter number of workers (default: 4): " WORKERS
read -p "Enter proxy tag (optional): " TAG

# Set defaults
SECRET=${SECRET:-$(openssl rand -hex 16)}
WORKERS=${WORKERS:-4}

print_status "Setting up MTProto TLS proxy for domain: $DOMAIN"

# Create necessary directories
mkdir -p nginx/ssl nginx/logs ssl logs

# Create environment file
cat > .env << EOF
DOMAIN=$DOMAIN
SECRET=$SECRET
WORKERS=$WORKERS
TAG=$TAG
TLS_DOMAIN=$DOMAIN
EOF

# Create initial self-signed certificate for nginx
print_status "Creating initial self-signed certificate..."
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout nginx/ssl/privkey.pem \
    -out nginx/ssl/fullchain.pem \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=$DOMAIN"

# Update nginx configuration with the domain
sed -i "s/your-domain.com/$DOMAIN/g" nginx/conf.d/mtproto-tls.conf

# Start services in detached mode
print_status "Starting Docker services..."
docker-compose up -d

# Wait for services to start
sleep 10

# Test if nginx is running
if curl -f http://localhost/health > /dev/null 2>&1; then
    print_status "Nginx is running successfully"
else
    print_warning "Nginx health check failed, but this might be normal during initial setup"
fi

# Get Let's Encrypt certificate
print_status "Obtaining Let's Encrypt certificate..."
docker run --rm \
    -p 80:80 \
    -v certbot_data:/etc/letsencrypt \
    -v certbot_www:/var/www/certbot \
    certbot/certbot certonly \
    --standalone \
    --non-interactive \
    --agree-tos \
    -m $EMAIL \
    -d $DOMAIN

# Update nginx configuration to use Let's Encrypt certificate
sed -i "s|/etc/letsencrypt/live/your-domain.com/fullchain.pem|/etc/letsencrypt/live/$DOMAIN/fullchain.pem|g" nginx/conf.d/mtproto-tls.conf
sed -i "s|/etc/letsencrypt/live/your-domain.com/privkey.pem|/etc/letsencrypt/live/$DOMAIN/privkey.pem|g" nginx/conf.d/mtproto-tls.conf

# Reload nginx
print_status "Reloading nginx with Let's Encrypt certificate..."
docker-compose exec nginx nginx -s reload

# Create proxy link
PROXY_LINK="https://t.me/proxy?server=$DOMAIN&port=443&secret=ee$SECRET$(echo -n $DOMAIN | hexdump -v -e '1/1 "%02x"')"

# Save proxy information
cat > proxy_info.txt << EOF
MTProto TLS Proxy Information
==============================
Domain: $DOMAIN
Secret: $SECRET
Workers: $WORKERS
Tag: $TAG
Proxy Link: $PROXY_LINK

Docker Commands:
- View logs: docker-compose logs -f
- Stop services: docker-compose down
- Restart services: docker-compose restart
- Update certificates: docker-compose exec certbot certbot renew
EOF

print_status "Setup completed successfully!"
print_status "Proxy information saved to proxy_info.txt"
print_status "Proxy link: $PROXY_LINK"

# Display proxy information
echo ""
echo "=============================="
echo "MTProto TLS Proxy Information"
echo "=============================="
echo "Domain: $DOMAIN"
echo "Secret: $SECRET"
echo "Workers: $WORKERS"
echo "Tag: $TAG"
echo "Proxy Link: $PROXY_LINK"
echo "=============================="
echo ""
echo "To test the proxy:"
echo "1. Open Telegram"
echo "2. Go to Settings > Data and Storage > Proxy Settings"
echo "3. Add proxy using the link above"
echo ""
echo "For support and updates, check the documentation."