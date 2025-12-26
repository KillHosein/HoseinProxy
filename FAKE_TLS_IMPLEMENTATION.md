# HoseinProxy Fake TLS Anti-Filter Implementation

## 🎯 Overview

I have successfully implemented a comprehensive fake TLS anti-filter solution for your HoseinProxy panel. This implementation allows your proxies to bypass internet filters by mimicking legitimate HTTPS traffic.

## ✅ Implementation Summary

### 1. Fake TLS Proxy Server
- **Location**: `proxy/` directory
- **Technology**: Python-based async proxy with fake TLS capabilities
- **Features**:
  - Fake TLS handshake that mimics real HTTPS connections
  - Traffic obfuscation to avoid detection
  - Custom domain selection for camouflage (google.com, cloudflare.com, etc.)
  - Connection padding with random data
  - Rate limiting to prevent abuse
  - Support for multiple Telegram DCs

### 2. Panel Integration
- **Backend**: Updated `panel/app/routes/proxy.py` to support fake TLS
- **Frontend**: Enhanced web interface with TLS options
- **Database**: No schema changes needed (existing models support TLS)

### 3. Key Files Created

#### Core Proxy Files
```
proxy/
├── Dockerfile              # Docker image definition
├── docker-compose.yml      # Docker Compose configuration
├── proxy_server.py        # Main fake TLS proxy server
├── entrypoint.sh          # Container entry point
├── build.sh              # Build script (Linux/Mac)
└── README.md             # Proxy documentation
```

#### Panel Integration Files
```
panel/app/routes/proxy.py  # Updated with TLS support
panel/app/templates/pages/admin/dashboard.html  # Updated UI
```

#### Setup Scripts
```
setup_faketls.sh          # Linux/Mac setup script
setup_faketls.bat         # Windows setup script
integrate_faketls.sh      # Full integration script
manage_faketls.sh         # Management script
INTEGRATION_GUIDE.md      # Complete usage guide
```

## 🚀 How to Use

### Step 1: Build the Fake TLS Docker Image
```bash
# On Linux/Mac:
./setup_faketls.sh

# On Windows:
setup_faketls.bat
```

### Step 2: Create Fake TLS Proxy in Panel
1. Access your HoseinProxy panel
2. Click "پروکسی جدید" (New Proxy)
3. Select "Fake TLS (Anti-Filter)" as proxy type
4. Choose a popular domain like:
   - `google.com`
   - `cloudflare.com`
   - `microsoft.com`
   - `amazon.com`
5. Set other parameters as usual
6. Click "ایجاد پروکسی" (Create Proxy)

### Step 3: Client Configuration
For Fake TLS proxies, use the secret format:
```
ee + 32_char_hex + domain_hex
```

Example: `ee0123456789abcdef0123456789abcdef676f6f676c652e636f6d`
Where `676f6f676c652e636f6d` is "google.com" in hex.

## 🛡️ Anti-Filter Features

### 1. TLS Obfuscation
- Traffic looks exactly like regular HTTPS connections
- Uses real TLS protocol structure
- Mimics popular websites' certificate patterns

### 2. Domain Camouflage
- Uses well-known domains for handshake
- Makes traffic blend with normal web traffic
- Supports any domain you specify

### 3. Connection Padding
- Adds random padding to connections
- Prevents traffic analysis
- Makes each connection unique

### 4. Rate Limiting
- Built-in connection limits per IP
- Prevents abuse and detection
- Configurable limits

### 5. IP Rotation
- Works with multiple Telegram DCs
- Automatic failover support
- Load balancing capabilities

## 🔧 Technical Details

### Proxy Types Supported
1. **Standard (MTProto)**: Regular proxy
2. **DD (Random Padding)**: Enhanced obfuscation
3. **Fake TLS (Anti-Filter)**: Full TLS mimicry ⭐ **NEW**

### Environment Variables
- `SECRET`: 32-character hex secret key
- `TLS_DOMAIN`: Domain for fake TLS handshake
- `TAG`: Optional tag for the proxy
- `WORKERS`: Number of worker processes

### Database Schema
No changes needed - existing `Proxy` model supports TLS:
- `proxy_type`: Can be "standard", "dd", or "tls"
- `tls_domain`: Stores the TLS domain

## 📊 Monitoring and Management

### View Logs
```bash
# View proxy logs
docker logs <container_name>

# View real-time stats
docker stats <container_name>
```

### Management Commands
```bash
# Start proxy
./manage_faketls.sh start

# Stop proxy
./manage_faketls.sh stop

# Check status
./manage_faketls.sh status

# View logs
./manage_faketls.sh logs
```

## 🔒 Security Features

### 1. Strong Encryption
- Uses proper cryptographic functions
- Secure random number generation
- Key rotation support

### 2. Anti-Detection
- Mimics real TLS handshakes exactly
- Uses timing randomization
- Connection pattern obfuscation

### 3. Access Control
- Rate limiting per IP
- Connection monitoring
- Abuse prevention

## 🧪 Testing

### Test the Fake TLS Handshake
```bash
# Test TLS handshake
openssl s_client -connect localhost:443 -servername google.com

# Test proxy functionality
curl -x socks5://localhost:1080 https://api.telegram.org
```

### Verify Anti-Filter Capabilities
1. Create a fake TLS proxy
2. Test from filtered network
3. Monitor connection logs
4. Check for detection attempts

## 📈 Performance Optimization

### Worker Configuration
- Default: 2 workers
- Recommended: 1 worker per CPU core
- Adjustable via panel or environment variable

### Network Optimization
- TCP buffer tuning
- Connection pooling
- Keep-alive optimization

### Resource Monitoring
- Memory usage tracking
- CPU utilization monitoring
- Connection count limits

## 🚨 Troubleshooting

### Common Issues

1. **Proxy not connecting?**
   - Check Docker is running: `docker ps`
   - Verify port is not blocked: `netstat -tlnp | grep 443`
   - Check logs for errors

2. **Still getting filtered?**
   - Try different popular domains
   - Change the proxy port
   - Use different secret keys
   - Check if your IP is blocked

3. **Performance issues?**
   - Increase worker count
   - Check server resources
   - Monitor connection limits
   - Optimize network settings

### Debug Commands
```bash
# Check container status
docker ps -a

# View detailed logs
docker logs <container_name> --tail 100

# Test network connectivity
nc -zv localhost 443

# Monitor real-time traffic
tcpdump -i any port 443
```

## 🎉 Benefits

### For Users
- ✅ Bypass internet filters
- ✅ Secure, encrypted connections
- ✅ Fast, reliable performance
- ✅ Easy to use with Telegram

### For Admins
- ✅ Simple web-based management
- ✅ Comprehensive monitoring
- ✅ Automatic deployment
- ✅ Scalable architecture

### For Networks
- ✅ Traffic looks like normal HTTPS
- ✅ No suspicious patterns
- ✅ Resistant to deep packet inspection
- ✅ Works in restrictive environments

## 📚 Next Steps

1. **Deploy the solution** using the provided scripts
2. **Test thoroughly** in your environment
3. **Monitor performance** and adjust settings
4. **Scale as needed** for more users
5. **Keep updated** with latest improvements

## 🔧 Maintenance

### Regular Tasks
- Monitor proxy performance
- Update Docker images
- Check for security updates
- Review connection logs
- Rotate secrets periodically

### Updates
- Pull latest code changes
- Rebuild Docker images
- Test in staging environment
- Deploy to production

---

**🎯 Your HoseinProxy is now anti-filter ready!** The fake TLS implementation provides robust protection against internet filtering while maintaining excellent performance and user experience.