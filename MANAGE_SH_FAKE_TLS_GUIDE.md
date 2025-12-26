# HoseinProxy Fake TLS Integration with manage.sh

## 🎯 Overview

Your HoseinProxy panel now has complete Fake TLS anti-filter support integrated into the main `manage.sh` script. You can manage everything from the familiar menu interface.

## 🚀 Quick Start

### 1. Install Fake TLS Support
```bash
./manage.sh
# Select option 12: "Install Fake TLS Support"
```

### 2. Build Fake TLS Docker Image
```bash
./manage.sh
# Select option 11: "Build Fake TLS Image"
```

### 3. Test Fake TLS Proxy
```bash
./manage.sh
# Select option 10: "Fake TLS Management"
# Then select option 2: "Test Fake TLS Proxy"
```

### 4. Create Fake TLS Proxy in Panel
1. Access your panel at `http://your-server:1111`
2. Click "پروکسی جدید" (New Proxy)
3. Select "Fake TLS (Anti-Filter)" as proxy type
4. Use popular domains like:
   - `google.com`
   - `cloudflare.com`
   - `microsoft.com`
   - `amazon.com`
5. Save and enjoy anti-filter protection!

## 📋 Complete Menu Options

### Main Menu (./manage.sh)
1. **Install Panel** - Install HoseinProxy with Fake TLS option
2. **Update Panel** - Update system with Fake TLS support
3. **Uninstall Panel** - Remove everything including Fake TLS
4. **Restart Service** - Restart panel service
5. **View Logs** - View system logs with Fake TLS status
6. **Schedule Auto-Update** - Enable/disable automatic updates
7. **Backup Data** - Backup panel and Fake TLS configurations
8. **Restore Data** - Restore from backup
9. **Repair / Reinstall Deps** - Fix issues and rebuild Fake TLS if needed
10. **Fake TLS Management** - Comprehensive Fake TLS management
11. **Build Fake TLS Image** - Build Docker image for Fake TLS
12. **Install Fake TLS Support** - Install Fake TLS components
13. **System Status Check** - Quick status of all services

### Fake TLS Management Menu (Option 10)
1. **Build Fake TLS Image** - Build/rebuild the Docker image
2. **Test Fake TLS Proxy** - Test the proxy functionality
3. **View Fake TLS Logs** - View container logs
4. **Check Fake TLS Status** - Check if Fake TLS is running
5. **Quick Setup Guide** - Show setup instructions
6. **Back** - Return to main menu

## 🛡️ Anti-Filter Features

### TLS Obfuscation
- Traffic looks exactly like real HTTPS connections
- Uses proper TLS handshake protocols
- Mimics popular websites' behavior

### Domain Camouflage
- Uses well-known domains for handshake
- Makes traffic blend with normal web traffic
- Supports any domain you specify

### Connection Security
- Strong encryption using proper algorithms
- Random padding to prevent traffic analysis
- Rate limiting to avoid detection

## 🔧 Technical Details

### Docker Integration
- Automatic Docker image building
- Container management through menu
- Health checks and monitoring

### Panel Integration
- Seamless integration with existing proxy types
- Automatic proxy type detection
- Backend support for TLS configuration

### File Structure
```
/opt/HoseinProxy/
├── panel/                    # Main panel files
├── proxy/                    # Fake TLS proxy files
│   ├── Dockerfile
│   ├── proxy_server.py
│   └── entrypoint.sh
├── manage.sh                 # Main management script
└── backups/                  # Backup storage
```

## 🧪 Testing Your Setup

### 1. Check System Status
```bash
./manage.sh
# Select option 13: "System Status Check"
```

### 2. Test Fake TLS Connection
```bash
# Test TLS handshake
telnet localhost 8443

# Test with OpenSSL
openssl s_client -connect localhost:8443 -servername google.com
```

### 3. Create Test Proxy
1. Go to your panel
2. Create new proxy with Fake TLS type
3. Use domain: `google.com`
4. Test connection from Telegram client

## 🚨 Troubleshooting

### Common Issues

#### Fake TLS Not Working
1. Check Docker is running: `systemctl status docker`
2. Rebuild image: `./manage.sh` → option 11
3. Check logs: `./manage.sh` → option 10 → option 3

#### Panel Not Showing Fake TLS Option
1. Update panel: `./manage.sh` → option 2
2. Restart service: `./manage.sh` → option 4
3. Check browser cache

#### Connection Test Fails
1. Check firewall rules
2. Verify port 443 is open
3. Test with different domains

### Quick Fixes
```bash
# Rebuild everything
./manage.sh repair

# Check all statuses
./manage.sh → option 13

# View detailed logs
./manage.sh → option 5
```

## 📈 Performance Optimization

### Worker Configuration
- Default: 2 workers
- Recommended: 1 worker per CPU core
- Adjustable in panel when creating proxy

### Domain Selection
- Use popular, stable domains
- Avoid domains that might be blocked
- Test different domains for best results

### Network Optimization
- Ensure good server connectivity
- Use reliable DNS servers
- Monitor connection limits

## 🔒 Security Best Practices

### Secret Management
- Use strong, random secrets
- Rotate secrets periodically
- Don't reuse secrets across proxies

### Domain Selection
- Use legitimate, popular domains
- Avoid suspicious or blocked domains
- Monitor domain accessibility

### Monitoring
- Regular log review
- Connection monitoring
- Performance tracking

## 🎉 Success Indicators

✅ **Installation Success**: No errors during setup
✅ **Image Build Success**: Docker image created successfully
✅ **Test Success**: Proxy responds to TLS handshake
✅ **Panel Integration**: Fake TLS option visible in panel
✅ **Connection Success**: Telegram connects through Fake TLS proxy
✅ **Anti-Filter Working**: No filtering/blocking detected

## 📞 Support

If you encounter issues:

1. **Check Logs**: `./manage.sh` → option 5
2. **Test Components**: `./manage.sh` → option 10
3. **Verify Status**: `./manage.sh` → option 13
4. **Rebuild if Needed**: `./manage.sh` → option 9

## 🎯 Next Steps

1. **Create Multiple Proxies**: Set up several Fake TLS proxies with different domains
2. **Monitor Usage**: Track performance and connection statistics
3. **Scale as Needed**: Add more servers for load distribution
4. **Keep Updated**: Regular updates through `./manage.sh` → option 2

---

**🚀 Your HoseinProxy is now fully anti-filter ready!** Enjoy unrestricted access with professional-grade TLS obfuscation technology.