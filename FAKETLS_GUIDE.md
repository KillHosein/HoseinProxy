# MTProto FakeTLS Setup Guide

This guide explains how to set up FakeTLS for your MTProto proxy to make it more resistant to filtering.

## What is FakeTLS?

FakeTLS is a technique that makes MTProto proxy traffic appear as regular HTTPS traffic by using popular domain names like google.com, cloudflare.com, etc. This makes it harder to detect and block the proxy traffic.

## Quick Setup

### Linux/macOS
```bash
# Make the script executable
chmod +x setup-faketls.sh

# Run the setup script
./setup-faketls.sh
```

### Windows
```cmd
# Run the batch file
setup-faketls.bat
```

## Available Domains

The following popular domains are available for FakeTLS:

1. **google.com** - Recommended for most cases
2. **cloudflare.com** - Good for CDN-like traffic
3. **microsoft.com** - For enterprise environments
4. **apple.com** - For iOS/macOS environments
5. **amazon.com** - For e-commerce traffic
6. **facebook.com** - For social media traffic
7. **twitter.com** - For social media traffic
8. **instagram.com** - For social media traffic
9. **whatsapp.com** - For messaging traffic
10. **telegram.org** - For messaging traffic
11. **cdn.discordapp.com** - For gaming/communication
12. **cdn.cloudflare.com** - For CDN traffic
13. **ajax.googleapis.com** - For Google APIs
14. **fonts.googleapis.com** - For web fonts
15. **apis.google.com** - For Google APIs
16. **ssl.gstatic.com** - For Google static content
17. **www.gstatic.com** - For Google static content
18. **accounts.google.com** - For Google authentication
19. **drive.google.com** - For Google Drive
20. **docs.google.com** - For Google Docs

## Manual Setup

If you prefer manual setup, follow these steps:

### 1. Choose a Domain
Select a domain that fits your use case:
- **google.com** - Most versatile and recommended
- **cloudflare.com** - Good for technical environments
- **microsoft.com** - For corporate networks

### 2. Build the Docker Image
```bash
# Create the Dockerfile
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

# Create the entrypoint script
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
```

### 3. Run the Container
```bash
# Create and run the container
docker run -d \
  --name mtproto_faketls_443 \
  -p 443:443 \
  -e SECRET=$(openssl rand -hex 16) \
  -e WORKERS=4 \
  -e TLS_DOMAIN=google.com \
  -e TAG=your_tag \
  mtproto-faketls:latest
```

## Testing the Proxy

1. **Get your proxy link**:
```bash
# Generate the proxy link
SECRET="your_secret_here"
DOMAIN="google.com"
DOMAIN_HEX=$(echo -n "$DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"
echo "tg://proxy?server=YOUR_SERVER_IP&port=443&secret=$FAKE_SECRET"
```

2. **Test in Telegram**:
   - Open Telegram
   - Go to Settings → Data and Storage → Proxy Settings
   - Add proxy using the generated link
   - Or manually enter:
     - Server: Your server IP
     - Port: 443
     - Secret: The fake secret (ee + secret + domain hex)

## Security Tips

1. **Rotate domains regularly** - Don't stick to one domain for too long
2. **Use different ports** - Avoid using the default port 443
3. **Monitor traffic** - Keep an eye on unusual traffic patterns
4. **Use strong secrets** - Always use randomly generated secrets

## Troubleshooting

### Connection Issues
- Check if the container is running: `docker ps`
- Check logs: `docker logs mtproto_faketls_443`
- Verify port is open: `netstat -tlnp | grep 443`

### Certificate Issues
- Ensure the fake certificate is generated correctly
- Check certificate validity: `openssl x509 -in /etc/ssl/certs/fullchain.pem -text -noout`

### Domain Issues
- Make sure the domain is in the popular domains list
- Test domain resolution: `nslookup google.com`

## Integration with Panel

The FakeTLS functionality is integrated into the panel. You can:

1. **Create FakeTLS proxies** through the web interface
2. **Manage existing proxies** with TLS support
3. **Monitor proxy status** and performance
4. **Generate new secrets** and domains

## Best Practices

1. **Use google.com or cloudflare.com** for most reliability
2. **Avoid suspicious domains** that might be blocked
3. **Keep your server updated** with latest security patches
4. **Use firewall rules** to restrict access if needed
5. **Monitor proxy usage** to detect anomalies

## Support

For issues and questions:
- Check the logs in the panel
- Review Docker container logs
- Test connectivity with telnet/nc
- Verify domain accessibility