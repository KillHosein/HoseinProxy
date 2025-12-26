install_fake_tls() {
    info "Installing Fake TLS support..."
    
    # Check if Docker is running
    if ! systemctl is-active --quiet docker; then
        error "Docker is not running. Please start Docker first."
        return 1
    fi
    
    # Create proxy directory if it doesn't exist
    mkdir -p "$INSTALL_DIR/proxy"
    
    # Change to proxy directory for file creation
    cd "$INSTALL_DIR/proxy" || return 1
    
    # Create Dockerfile
    cat > Dockerfile << 'EOF'
FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    gcc \
    git \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Clone and build the fake TLS proxy
RUN git clone https://github.com/alexbers/mtprotoproxy.git .

# Copy our custom configuration
COPY config.py ./
COPY entrypoint.sh ./
COPY proxy_server.py ./

RUN chmod +x entrypoint.sh

EXPOSE 443

CMD ["./entrypoint.sh"]
EOF

    # Create proxy_server.py
    cat > proxy_server.py << 'EOF'
import asyncio
import logging
import struct
import hashlib
import secrets
import time
import socket
import ssl
from urllib.parse import urlparse

# Configuration
PORT = 443
SECRET = "your_secret_here"
TLS_DOMAIN = "google.com"
WORKERS = 2
ENABLE_FAKE_TLS = True
TLS_ONLY = True
FALLBACK_DOMAIN = "google.com"
ENABLE_ANTIFILTER = True
OBFUSCATION_LEVEL = 2
PADDING_ENABLED = True

class FakeTLSProxy:
    def __init__(self):
        self.secret = bytes.fromhex(SECRET)
        self.tls_domain = TLS_DOMAIN
        self.workers = WORKERS
        self.port = PORT
        
    async def handle_connection(self, reader, writer):
        """Handle incoming connection with fake TLS"""
        client_addr = writer.get_extra_info('peername')
        print(f"New connection from {client_addr}")
        
        try:
            # Perform fake TLS handshake
            await self._perform_fake_tls_handshake(reader, writer)
            # Handle the actual proxy protocol
            await self._handle_proxy_protocol(reader, writer)
        except Exception as e:
            print(f"Error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _perform_fake_tls_handshake(self, reader, writer):
        """Perform fake TLS handshake"""
        # Send fake ServerHello
        server_hello = self._create_server_hello()
        writer.write(server_hello)
        await writer.drain()
        
        # Wait for ClientHello
        client_hello = await reader.read(1024)
        if not self._validate_client_hello(client_hello):
            raise Exception("Invalid ClientHello")
        
        print("Fake TLS handshake completed")
    
    def _create_server_hello(self):
        """Create fake ServerHello"""
        version = b'\x03\x03'  # TLS 1.2
        random = secrets.token_bytes(32)
        session_id = b'\x20' + secrets.token_bytes(32)
        
        # Selected cipher suite
        cipher_suite = b'\x00\x9f'
        compression = b'\x00'
        
        handshake = version + random + session_id + cipher_suite + compression
        
        # TLS record header
        record_header = b'\x16\x03\x03'
        record_length = len(handshake).to_bytes(2, 'big')
        
        return record_header + record_length + handshake
    
    def _validate_client_hello(self, data):
        """Validate incoming ClientHello"""
        if len(data) < 43:
            return False
        
        # Check TLS record header
        if data[0] != 0x16 or data[1:3] != b'\x03\x03':
            return False
        
        return True
    
    async def _handle_proxy_protocol(self, reader, writer):
        """Handle the actual MTProxy protocol"""
        # Simple relay implementation
        data = await reader.read(1024)
        if data:
            # Connect to Telegram servers (simplified)
            telegram_reader, telegram_writer = await asyncio.open_connection(
                '149.154.175.50', 443
            )
            
            # Start relaying data
            await asyncio.gather(
                self._relay_data(reader, telegram_writer),
                self._relay_data(telegram_reader, writer)
            )
    
    async def _relay_data(self, reader, writer):
        """Relay data between client and Telegram"""
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception as e:
            print(f"Relay error: {e}")
        finally:
            writer.close()
    
    async def start_server(self):
        """Start the fake TLS proxy server"""
        server = await asyncio.start_server(
            self.handle_connection,
            '0.0.0.0',
            self.port
        )
        
        print(f"Fake TLS proxy started on port {self.port}")
        print(f"Secret: {SECRET}")
        print(f"TLS Domain: {self.tls_domain}")
        
        async with server:
            await server.serve_forever()

if __name__ == '__main__':
    proxy = FakeTLSProxy()
    asyncio.run(proxy.start_server())
EOF

    # Create entrypoint.sh
    cat > entrypoint.sh << 'EOF'
#!/bin/bash

# Generate secret if not provided
if [ -z "$SECRET" ]; then
    SECRET=$(openssl rand -hex 16)
    echo "Generated secret: $SECRET"
fi

# Create config file
cat > config.py << EOF
PORT = 443
SECRET = "$SECRET"
TLS_DOMAIN = "$TLS_DOMAIN"
TAG = "$TAG"
WORKERS = $WORKERS
ENABLE_FAKE_TLS = True
TLS_ONLY = True
FALLBACK_DOMAIN = "$TLS_DOMAIN"
ENABLE_ANTIFILTER = True
OBFUSCATION_LEVEL = 2
PADDING_ENABLED = True
EOF

# Start the proxy
exec python3 proxy_server.py
EOF

    chmod +x entrypoint.sh
    
    # Return to original directory
    cd - >> "$LOG_FILE" 2>&1
    
    # Build the Docker image
    build_fake_tls_image
}