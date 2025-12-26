# Fake TLS Proxy Configuration

This directory contains the fake TLS proxy implementation for anti-filtering capabilities.

## Features

- **Fake TLS Handshake**: Mimics real TLS connections to avoid detection
- **Anti-Filtering**: Uses obfuscation techniques to bypass filters
- **Custom Domain**: Can use any domain for TLS handshake (google.com, cloudflare.com, etc.)
- **Rate Limiting**: Built-in connection limits per IP
- **Logging**: Comprehensive logging for monitoring

## Building

```bash
# Build the Docker image
./build.sh

# Or manually:
docker build -t mtproxy-faketls:latest .
```

## Usage

### Environment Variables

- `SECRET`: 32-character hex secret key
- `TLS_DOMAIN`: Domain for fake TLS handshake (e.g., google.com)
- `TAG`: Optional tag for the proxy
- `WORKERS`: Number of worker processes (default: 2)

### Docker Run Example

```bash
docker run -d -p 443:443 \
    -e SECRET=your_secret_key_here \
    -e TLS_DOMAIN=google.com \
    -e WORKERS=2 \
    --name faketls-proxy \
    mtproxy-faketls:latest
```

### Docker Compose

```bash
docker-compose up -d
```

## Client Configuration

For fake TLS proxies, use the secret format: `ee` + 32-char hex + domain hex

Example: `ee0123456789abcdef0123456789abcdef676f6f676c652e636f6d`

Where `676f6f676c652e636f6d` is "google.com" in hex.

## Anti-Filter Features

1. **TLS Obfuscation**: Traffic looks like regular HTTPS
2. **Domain Camouflage**: Uses popular domains for handshake
3. **Connection Padding**: Adds random padding to connections
4. **Rate Limiting**: Prevents abuse and detection
5. **IP Rotation**: Can work with multiple Telegram DCs

## Monitoring

Check logs:
```bash
docker logs faketls-proxy
```

View stats:
```bash
docker exec faketls-proxy python3 -c "import proxy_server; print(proxy_server.stats)"
```