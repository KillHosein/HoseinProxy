#!/bin/bash

# HoseinProxy Fake TLS Integration Script
echo "🔧 Integrating Fake TLS with HoseinProxy Panel"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   echo -e "${RED}❌ This script should not be run as root${NC}"
   exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

echo -e "${BLUE}🚀 HoseinProxy Fake TLS Integration${NC}"
echo "=================================="

# Build the fake TLS proxy
echo -e "${YELLOW}📦 Building Fake TLS proxy...${NC}"
chmod +x setup_faketls.sh
./setup_faketls.sh

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to build Fake TLS proxy${NC}"
    exit 1
fi

# Update panel requirements if needed
echo -e "${YELLOW}🔧 Checking panel requirements...${NC}"
cd panel || exit

# Check if we need to install additional Python packages
if ! pip list | grep -q "cryptography"; then
    echo -e "${YELLOW}📦 Installing cryptography package for enhanced security...${NC}"
    pip install cryptography
fi

echo -e "${GREEN}✅ Panel requirements checked${NC}"

# Create systemd service for automatic startup (optional)
echo -e "${YELLOW}🔧 Creating systemd service...${NC}"
cat > ~/.config/systemd/user/hoseinproxy-faketls.service << EOF
[Unit]
Description=HoseinProxy Fake TLS Service
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/docker run -d --rm --name hoseinproxy-faketls -p 8443:443 -e SECRET=auto -e TLS_DOMAIN=google.com -e WORKERS=2 mtproxy-faketls:latest
ExecStop=/usr/bin/docker stop hoseinproxy-faketls
TimeoutStartSec=0

[Install]
WantedBy=default.target
EOF

# Enable the service (optional - user can enable it if needed)
# systemctl --user enable hoseinproxy-faketls.service

echo -e "${GREEN}✅ Systemd service created (optional)${NC}"

# Create management script
echo -e "${YELLOW}📝 Creating management script...${NC}"
cat > manage_faketls.sh << 'EOF'
#!/bin/bash

# HoseinProxy Fake TLS Management Script

case "$1" in
    start)
        echo "Starting Fake TLS proxy..."
        docker run -d --rm --name hoseinproxy-faketls -p 8443:443 -e SECRET=auto -e TLS_DOMAIN=google.com -e WORKERS=2 mtproxy-faketls:latest
        ;;
    stop)
        echo "Stopping Fake TLS proxy..."
        docker stop hoseinproxy-faketls
        ;;
    restart)
        echo "Restarting Fake TLS proxy..."
        docker stop hoseinproxy-faketls 2>/dev/null
        docker run -d --rm --name hoseinproxy-faketls -p 8443:443 -e SECRET=auto -e TLS_DOMAIN=google.com -e WORKERS=2 mtproxy-faketls:latest
        ;;
    status)
        if docker ps | grep -q hoseinproxy-faketls; then
            echo "Fake TLS proxy is running"
            docker stats hoseinproxy-faketls --no-stream
        else
            echo "Fake TLS proxy is not running"
        fi
        ;;
    logs)
        docker logs hoseinproxy-faketls
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
EOF

chmod +x manage_faketls.sh

echo -e "${GREEN}✅ Management script created${NC}"

# Create integration documentation
echo -e "${YELLOW}📖 Creating integration documentation...${NC}"
cat > INTEGRATION_GUIDE.md << 'EOF'
# HoseinProxy Fake TLS Integration Guide

## Overview
Your HoseinProxy panel now supports Fake TLS anti-filtering technology. This allows your proxies to bypass internet filters by mimicking legitimate HTTPS traffic.

## Features
- ✅ Fake TLS handshake that looks like real HTTPS
- ✅ Anti-filtering capabilities
- ✅ Custom domain selection for camouflage
- ✅ Integration with your existing panel
- ✅ Easy management through web interface

## How to Use

### 1. Create Fake TLS Proxy
1. Log into your HoseinProxy panel
2. Click "پروکسی جدید" (New Proxy)
3. Select "Fake TLS (Anti-Filter)" as proxy type
4. Choose a popular domain like:
   - `google.com`
   - `cloudflare.com`
   - `microsoft.com`
   - `amazon.com`
5. Set other parameters as usual
6. Click "ایجاد پروکسی" (Create Proxy)

### 2. Client Configuration
For Fake TLS proxies, the secret format is:
```
ee + 32_char_hex + domain_hex
```

Example: `ee0123456789abcdef0123456789abcdef676f6f676c652e636f6d`
Where `676f6f676c652e636f6d` is "google.com" in hex.

### 3. Management Commands
```bash
# Start Fake TLS proxy
./manage_faketls.sh start

# Stop Fake TLS proxy
./manage_faketls.sh stop

# Check status
./manage_faketls.sh status

# View logs
./manage_faketls.sh logs
```

## Anti-Filter Features
- **TLS Obfuscation**: Traffic looks like regular HTTPS
- **Domain Camouflage**: Uses popular domains for handshake
- **Connection Padding**: Adds random padding to connections
- **Rate Limiting**: Prevents abuse and detection
- **IP Rotation**: Works with multiple Telegram DCs

## Troubleshooting

### Proxy not connecting?
- Check if Docker is running: `docker ps`
- Check logs: `./manage_faketls.sh logs`
- Verify port is not blocked: `netstat -tlnp | grep 8443`

### Still getting filtered?
- Try different popular domains
- Change the proxy port
- Use different secret keys
- Check if your IP is blocked

### Performance issues?
- Increase worker count in panel
- Check server resources
- Monitor connection limits

## Security Notes
- Always use strong, random secrets
- Rotate secrets regularly
- Monitor proxy usage
- Keep Docker images updated
- Use firewall rules to restrict access

## Support
For issues and questions:
- Check the logs first
- Verify Docker is running
- Test with different domains
- Check network connectivity
EOF

echo -e "${GREEN}✅ Integration documentation created${NC}"

# Final summary
echo ""
echo -e "${BLUE}🎉 HoseinProxy Fake TLS Integration Complete!${NC}"
echo "=============================================="
echo ""
echo -e "${GREEN}✅ What's been installed:${NC}"
echo "• Fake TLS Docker image (mtproxy-faketls:latest)"
echo "• Management script (manage_faketls.sh)"
echo "• Systemd service (optional)"
echo "• Integration documentation"
echo ""
echo -e "${GREEN}✅ What's been updated:${NC}"
echo "• Panel now supports Fake TLS proxy type"
echo "• Web interface updated with TLS options"
echo "• Backend logic for TLS proxy management"
echo ""
echo -e "${YELLOW}📋 Next Steps:${NC}"
echo "1. Test the Fake TLS proxy from your panel"
echo "2. Create a new proxy with 'Fake TLS' type"
echo "3. Use popular domains like google.com"
echo "4. Test the anti-filtering capabilities"
echo "5. Monitor performance and usage"
echo ""
echo -e "${YELLOW}📖 Documentation:${NC}"
echo "See INTEGRATION_GUIDE.md for detailed instructions"
echo ""
echo -e "${BLUE}🔒 Your proxy is now anti-filter ready!${NC}"

# Return to original directory
cd - > /dev/null || exit