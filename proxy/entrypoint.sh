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

# Fake TLS configuration
ENABLE_FAKE_TLS = True
TLS_ONLY = True
FALLBACK_DOMAIN = "$TLS_DOMAIN"

# Anti-filter settings
ENABLE_ANTIFILTER = True
OBFUSCATION_LEVEL = 2
PADDING_ENABLED = True

# Connection settings
MAX_CONNECTIONS = 60000
TIMEOUT = 300
BUFFER_SIZE = 65536

# Rate limiting
ENABLE_RATE_LIMIT = True
MAX_CONNECTIONS_PER_IP = 10
RATE_LIMIT_WINDOW = 60

# Logging
LOG_LEVEL = "INFO"
LOG_FILE = "/logs/proxy.log"
EOF

# Start the proxy
exec python3 proxy_server.py