#!/bin/bash

# Build fake TLS proxy Docker image
echo "Building fake TLS proxy Docker image..."

cd "$(dirname "$0")"

# Build the Docker image
docker build -t mtproxy-faketls:latest .

# Check if build was successful
if [ $? -eq 0 ]; then
    echo "✅ Fake TLS proxy image built successfully!"
    echo "Image: mtproxy-faketls:latest"
else
    echo "❌ Failed to build fake TLS proxy image"
    exit 1
fi

# Test the image
echo "Testing the fake TLS proxy..."
docker run --rm -d -p 8443:443 \
    -e SECRET=0123456789abcdef0123456789abcdef \
    -e TLS_DOMAIN=google.com \
    -e WORKERS=2 \
    --name test-faketls \
    mtproxy-faketls:latest

sleep 3

# Check if container is running
if docker ps | grep -q test-faketls; then
    echo "✅ Fake TLS proxy is running successfully!"
    docker stop test-faketls
else
    echo "❌ Fake TLS proxy test failed"
    docker logs test-faketls
fi

echo "Build process completed!"