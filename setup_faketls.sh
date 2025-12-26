#!/bin/bash

# Fake TLS Proxy Setup Script
echo "🚀 Setting up Fake TLS Proxy for HoseinProxy Panel"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed. Please install Docker first.${NC}"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose is not installed. Please install Docker Compose first.${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 Building Fake TLS Docker image...${NC}"

# Navigate to proxy directory
cd "$(dirname "$0")/proxy" || exit

# Build the Docker image
if docker build -t mtproxy-faketls:latest .; then
    echo -e "${GREEN}✅ Fake TLS Docker image built successfully!${NC}"
else
    echo -e "${RED}❌ Failed to build Docker image${NC}"
    exit 1
fi

# Test the image
echo -e "${YELLOW}🧪 Testing Fake TLS proxy...${NC}"

# Run a test container
TEST_CONTAINER="test-faketls-$(date +%s)"
docker run -d --rm \
    --name "$TEST_CONTAINER" \
    -p 8443:443 \
    -e SECRET=0123456789abcdef0123456789abcdef \
    -e TLS_DOMAIN=google.com \
    -e WORKERS=2 \
    mtproxy-faketls:latest

# Wait for container to start
sleep 5

# Check if container is running
if docker ps | grep -q "$TEST_CONTAINER"; then
    echo -e "${GREEN}✅ Test container is running successfully!${NC}"
    
    # Stop the test container
    docker stop "$TEST_CONTAINER" > /dev/null 2>&1
    echo -e "${GREEN}✅ Test container stopped${NC}"
else
    echo -e "${RED}❌ Test failed - container is not running${NC}"
    echo -e "${YELLOW}📋 Container logs:${NC}"
    docker logs "$TEST_CONTAINER" 2>&1 | tail -20
    docker rm -f "$TEST_CONTAINER" > /dev/null 2>&1
    exit 1
fi

echo -e "${GREEN}🎉 Fake TLS proxy setup completed successfully!${NC}"
echo ""
echo -e "${YELLOW}📋 Usage Instructions:${NC}"
echo "1. The fake TLS proxy is now ready to use"
echo "2. In your panel, select 'Fake TLS (Anti-Filter)' as proxy type"
echo "3. Use popular domains like google.com, cloudflare.com for TLS handshake"
echo "4. The proxy will automatically obfuscate traffic to bypass filters"
echo ""
echo -e "${YELLOW}🔧 Available Environment Variables:${NC}"
echo "- SECRET: 32-character hex secret key"
echo "- TLS_DOMAIN: Domain for fake TLS handshake"
echo "- TAG: Optional tag for the proxy"
echo "- WORKERS: Number of worker processes"
echo ""
echo -e "${YELLOW}🛡️ Anti-Filter Features:${NC}"
echo "- Fake TLS handshake that mimics real HTTPS"
echo "- Traffic obfuscation to avoid detection"
echo "- Connection padding with random data"
echo "- Rate limiting to prevent abuse"
echo "- Support for popular domains as camouflage"

# Return to original directory
cd - > /dev/null || exit