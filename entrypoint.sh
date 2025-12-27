#!/bin/sh

# MTProto TLS Proxy Entrypoint Script

set -e

# Required environment variables
SECRET=${SECRET:-$(openssl rand -hex 16)}
WORKERS=${WORKERS:-4}
TAG=${TAG:-}
TLS_DOMAIN=${TLS_DOMAIN:-}
TLS_CERT_PATH=${TLS_CERT_PATH:-/etc/ssl/certs/fullchain.pem}
TLS_KEY_PATH=${TLS_KEY_PATH:-/etc/ssl/private/privkey.pem}

# Generate TLS certificate if not provided
if [ ! -f "$TLS_CERT_PATH" ] || [ ! -f "$TLS_KEY_PATH" ]; then
    echo "Generating self-signed TLS certificate for domain: $TLS_DOMAIN"
    
    # Create certificate directory
    mkdir -p $(dirname "$TLS_CERT_PATH") $(dirname "$TLS_KEY_PATH")
    
    # Generate private key
    openssl genrsa -out "$TLS_KEY_PATH" 2048
    
    # Generate certificate signing request
    openssl req -new -key "$TLS_KEY_PATH" -out /tmp/cert.csr -subj "/CN=$TLS_DOMAIN"
    
    # Generate self-signed certificate
    openssl x509 -req -days 365 -in /tmp/cert.csr -signkey "$TLS_KEY_PATH" -out "$TLS_CERT_PATH"
    
    # Clean up
    rm -f /tmp/cert.csr
fi

# Prepare the secret with TLS prefix if domain is provided
if [ -n "$TLS_DOMAIN" ]; then
    # Convert domain to hex
    DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
    SECRET="ee${SECRET}${DOMAIN_HEX}"
fi

# Prepare tag parameter
TAG_PARAM=""
if [ -n "$TAG" ]; then
    TAG_PARAM="--tag $TAG"
fi

# Start the proxy
echo "Starting MTProto TLS proxy..."
echo "Domain: $TLS_DOMAIN"
echo "Workers: $WORKERS"
echo "Secret: $SECRET"

exec ./mtproto-proxy \
    -u nobody \
    -p 8888,80,443 \
    -H 443 \
    -S $SECRET \
    --address 0.0.0.0 \
    --port 443 \
    --http-ports 80 \
    --slaves $WORKERS \
    --max-special-connections 60000 \
    --allow-skip-dh \
    --cert "$TLS_CERT_PATH" \
    --key "$TLS_KEY_PATH" \
    --dc 1,149.154.175.50,443 \
    --dc 2,149.154.167.51,443 \
    --dc 3,149.154.175.100,443 \
    --dc 4,149.154.167.91,443 \
    --dc 5,91.108.56.151,443 \
    $TAG_PARAM