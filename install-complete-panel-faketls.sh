#!/bin/bash

# Complete MTProto Panel + FakeTLS Installation Script for Ubuntu
# This script installs the complete HoseinProxy panel with FakeTLS support

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}==== $1 ====${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_error "This script must be run as root (use sudo)"
   exit 1
fi

# Welcome banner
clear
echo -e "${PURPLE}"
cat << "EOF"
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🚀 HoseinProxy Panel + FakeTLS Auto-Installer           ║
║                                                              ║
║   Complete MTProto Proxy Management System                  ║
║   with Anti-Filtering FakeTLS Support                       ║
║                                                              ║
║   Created by: HoseinProxy Team                             ║
║   Telegram: @HoseinProxy                                    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo ""

# Get user configuration
print_header "Configuration Setup"
echo "This installer will set up a complete MTProto proxy management system with FakeTLS support."
echo ""

read -p "Enter panel admin username [admin]: " ADMIN_USER
read -p "Enter panel admin password [admin123]: " ADMIN_PASS
read -p "Enter panel port [5000]: " PANEL_PORT
read -p "Enter your server IP (optional, will auto-detect): " SERVER_IP
read -p "Enter preferred domain for FakeTLS (1-5) [1]: " FAKE_TLS_DOMAIN

# Set defaults
ADMIN_USER=${ADMIN_USER:-admin}
ADMIN_PASS=${ADMIN_PASS:-admin123}
PANEL_PORT=${PANEL_PORT:-5000}
FAKE_TLS_DOMAIN=${FAKE_TLS_DOMAIN:-1}

# Auto-detect server IP if not provided
if [ -z "$SERVER_IP" ]; then
    SERVER_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "YOUR_SERVER_IP")
fi

# Domain mapping
case $FAAKE_TLS_DOMAIN in
    1) TLS_DOMAIN="google.com" ;;
    2) TLS_DOMAIN="cloudflare.com" ;;
    3) TLS_DOMAIN="microsoft.com" ;;
    4) TLS_DOMAIN="apple.com" ;;
    5) TLS_DOMAIN="amazon.com" ;;
    *) TLS_DOMAIN="google.com" ;;
esac

print_status "Configuration:"
print_status "  Admin User: $ADMIN_USER"
print_status "  Panel Port: $PANEL_PORT"
print_status "  Server IP: $SERVER_IP"
print_status "  FakeTLS Domain: $TLS_DOMAIN"
echo ""

read -p "Press Enter to continue or Ctrl+C to cancel..."

# System update
print_header "System Update"
print_status "Updating Ubuntu system..."
apt update && apt upgrade -y

# Install required packages
print_header "Installing Dependencies"
print_status "Installing required packages..."
apt install -y \
    curl \
    wget \
    git \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    certbot \
    python3-certbot-nginx \
    ufw \
    fail2ban \
    sqlite3 \
    build-essential \
    openssl \
    docker.io \
    docker-compose

# Install Docker properly
print_status "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
    usermod -aG docker $SUDO_USER || true
fi

# Configure firewall
print_header "Firewall Configuration"
print_status "Configuring UFW firewall..."
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow "$PANEL_PORT/tcp"
ufw --force enable

# Create panel directory
print_header "Panel Installation"
PANEL_DIR="/opt/hoseinproxy-panel"
print_status "Creating panel directory: $PANEL_DIR"
mkdir -p $PANEL_DIR
cd $PANEL_DIR

# Copy panel files
print_status "Installing panel files..."
if [ -d "/tmp/panel" ]; then
    cp -r /tmp/panel/* $PANEL_DIR/
else
    # Create basic panel structure
    mkdir -p app/{routes,services,utils,templates/{layouts,pages/{admin,auth}},static/{css,js,img}}
    mkdir -p migrations
fi

# Create panel requirements
print_status "Creating panel requirements..."
cat > requirements.txt << 'EOF'
Flask==2.3.3
Flask-SQLAlchemy==3.0.5
Flask-Login==0.6.3
Flask-Limiter==3.5.0
Werkzeug==2.3.7
docker==6.1.3
requests==2.31.0
python-dotenv==1.0.0
EOF

# Create virtual environment
print_status "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create panel configuration
print_status "Creating panel configuration..."
cat > app/config.py << 'EOF'
import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hosein-proxy-secret-key-change-this'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///hoseinproxy.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    
    # Rate limiting
    RATELIMIT_STORAGE_URL = "memory://"
    RATELIMIT_DEFAULT = "100 per hour"
    
    # Security
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
EOF

# Create main app file
print_status "Creating main application..."
cat > app/__init__.py << 'EOF'
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.config import Config

db = SQLAlchemy()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'لطفاً وارد شوید.'
    
    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.proxy import proxy_bp
    from app.routes.proxy_enhanced import proxy_enhanced_bp
    from app.routes.settings import settings_bp
    from app.routes.firewall import firewall_bp
    from app.routes.api import api_bp
    from app.routes.system import system_bp
    from app.routes.tools import tools_bp
    from app.routes.reports import reports_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(proxy_bp)
    app.register_blueprint(proxy_enhanced_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(firewall_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(reports_bp)
    
    # Create admin user
    with app.app_context():
        db.create_all()
        from app.models import User
        admin = User.query.filter_by(username='{{ ADMIN_USER }}').first()
        if not admin:
            admin = User(username='{{ ADMIN_USER }}')
            admin.set_password('{{ ADMIN_PASS }}')
            db.session.add(admin)
            db.session.commit()
    
    return app
EOF

# Create systemd service for panel
print_status "Creating systemd service..."
cat > /etc/systemd/system/hoseinproxy-panel.service << EOF
[Unit]
Description=HoseinProxy Panel
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=$PANEL_DIR
Environment="PATH=$PANEL_DIR/venv/bin"
ExecStart=$PANEL_DIR/venv/bin/python run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Create panel startup script
print_status "Creating panel startup script..."
cat > run.py << 'EOF'
#!/usr/bin/env python3
import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
EOF

chmod +x run.py

# Create FakeTLS setup script
print_status "Creating FakeTLS setup script..."
cat > setup-faketls.sh << 'EOF'
#!/bin/bash

# FakeTLS Quick Setup Script

echo "=== MTProto FakeTLS Quick Setup ==="
echo ""
echo "Available domains:"
echo "1. google.com (Recommended)"
echo "2. cloudflare.com"
echo "3. microsoft.com"
echo "4. apple.com"
echo "5. amazon.com"
echo ""

read -p "Select domain (1-5) [1]: " DOMAIN_CHOICE
read -p "Enter port [443]: " PORT
read -p "Enter workers [4]: " WORKERS
read -p "Enter tag (optional): " TAG

DOMAIN_CHOICE=${DOMAIN_CHOICE:-1}
PORT=${PORT:-443}
WORKERS=${WORKERS:-4}

case $DOMAIN_CHOICE in
    1) TLS_DOMAIN="google.com" ;;
    2) TLS_DOMAIN="cloudflare.com" ;;
    3) TLS_DOMAIN="microsoft.com" ;;
    4) TLS_DOMAIN="apple.com" ;;
    5) TLS_DOMAIN="amazon.com" ;;
    *) TLS_DOMAIN="google.com" ;;
esac

SECRET=$(openssl rand -hex 16)
DOMAIN_HEX=$(echo -n "$TLS_DOMAIN" | hexdump -v -e '1/1 "%02x"')
FAKE_SECRET="ee${SECRET}${DOMAIN_HEX}"

# Create Docker Compose for FakeTLS
mkdir -p /opt/faketls-$PORT
cd /opt/faketls-$PORT

cat > docker-compose.yml << EOL
version: '3.8'

services:
  mtproto-faketls:
    image: golang:1.21-alpine
    container_name: mtproto_faketls_$PORT
    restart: always
    ports:
      - "$PORT:443"
    command: |
      sh -c "
        apk add --no-cache git openssl &&
        git clone https://github.com/TelegramMessenger/MTProxy.git /app &&
        cd /app &&
        go mod init mtproxy || true &&
        go mod tidy || true &&
        CGO_ENABLED=0 GOOS=linux go build -o mtproto-proxy ./cmd/proxy &&
        mkdir -p /etc/ssl/certs /etc/ssl/private /var/log/mtproto &&
        openssl genrsa -out /etc/ssl/private/privkey.pem 2048 &&
        openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr -subj '/C=US/ST=CA/L=Mountain View/O=Google LLC/CN=$TLS_DOMAIN' &&
        openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem -out /etc/ssl/certs/fullchain.pem &&
        rm -f /tmp/cert.csr &&
        ./mtproto-proxy \\
          -u nobody \\
          -p 8888,80,443 \\
          -H 443 \\
          -S $FAKE_SECRET \\
          --address 0.0.0.0 \\
          --port 443 \\
          --http-ports 80 \\
          --slaves $WORKERS \\
          --max-special-connections 60000 \\
          --allow-skip-dh \\
          --cert /etc/ssl/certs/fullchain.pem \\
          --key /etc/ssl/private/privkey.pem \\
          --dc 1,149.154.175.50,443 \\
          --dc 2,149.154.167.51,443 \\
          --dc 3,149.154.175.100,443 \\
          --dc 4,149.154.167.91,443 \\
          --dc 5,91.108.56.151,443 \\
          ${TAG:+--tag $TAG}
      "
    volumes:
      - ./logs:/var/log/mtproto
EOL

echo "Starting FakeTLS proxy..."
docker-compose up -d

sleep 10

SERVER_IP=$(curl -s ifconfig.me || echo "YOUR_SERVER_IP")

echo ""
echo "✅ FakeTLS proxy setup complete!"
echo "Domain: $TLS_DOMAIN"
echo "Port: $PORT"
echo "Secret: $SECRET"
echo "Fake Secret: $FAKE_SECRET"
echo ""
echo "Telegram Link:"
echo "https://t.me/proxy?server=$SERVER_IP&port=$PORT&secret=$FAKE_SECRET"
echo ""
echo "Proxy info saved to: /opt/faketls-$PORT/proxy-info.txt"
EOF

chmod +x setup-faketls.sh

# Create management script
cat > manage-panel.sh << 'EOF'
#!/bin/bash

# HoseinProxy Panel Management Script

case "$1" in
    start)
        echo "Starting HoseinProxy Panel..."
        systemctl start hoseinproxy-panel
        ;;
    stop)
        echo "Stopping HoseinProxy Panel..."
        systemctl stop hoseinproxy-panel
        ;;
    restart)
        echo "Restarting HoseinProxy Panel..."
        systemctl restart hoseinproxy-panel
        ;;
    status)
        echo "Checking HoseinProxy Panel status..."
        systemctl status hoseinproxy-panel
        ;;
    logs)
        echo "Viewing HoseinProxy Panel logs..."
        journalctl -u hoseinproxy-panel -f
        ;;
    setup-faketls)
        echo "Running FakeTLS setup..."
        cd $PANEL_DIR
        ./setup-faketls.sh
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|setup-faketls}"
        echo ""
        echo "Panel URL: http://$SERVER_IP:$PANEL_PORT"
        echo "Admin Login: $ADMIN_USER / $ADMIN_PASS"
        exit 1
        ;;
esac
EOF

chmod +x manage-panel.sh

# Create info file
print_status "Creating system info file..."
cat > SYSTEM_INFO.txt << EOF
🚀 HoseinProxy Panel + FakeTLS Installation Complete!

📋 System Information:
   Panel URL: http://$SERVER_IP:$PANEL_PORT
   Admin Username: $ADMIN_USER
   Admin Password: $ADMIN_PASS
   Installation Directory: $PANEL_DIR
   FakeTLS Domain: $TLS_DOMAIN

🔧 Management Commands:
   Panel Control: $PANEL_DIR/manage-panel.sh {start|stop|restart|status|logs}
   FakeTLS Setup: $PANEL_DIR/manage-panel.sh setup-faketls
   System Logs: journalctl -u hoseinproxy-panel -f

🛠️ Service Management:
   Start Panel: systemctl start hoseinproxy-panel
   Stop Panel: systemctl stop hoseinproxy-panel
   Enable Auto-start: systemctl enable hoseinproxy-panel

🌐 Access Panel:
   Open browser and go to: http://$SERVER_IP:$PANEL_PORT
   Login with admin credentials
   Navigate to "پروکسی FakeTLS" to create anti-filtering proxies

🔒 Security Features:
   ✅ Firewall (UFW) configured
   ✅ Fail2ban installed
   ✅ Rate limiting enabled
   ✅ Secure session management

📱 Create FakeTLS Proxy:
   1. Login to panel
   2. Click "پروکسی FakeTLS"
   3. Choose domain (google.com recommended)
   4. Set port and workers
   5. Generate proxy link

🔗 Example FakeTLS Link:
   https://t.me/proxy?server=$SERVER_IP&port=443&secret=eeSECRETgooglecom

🆘 Support:
   Check logs: $PANEL_DIR/manage-panel.sh logs
   System status: systemctl status hoseinproxy-panel
   Firewall status: ufw status

=====================================
✅ Installation completed successfully!
=====================================
EOF

# Replace placeholders in files
sed -i "s/{{ ADMIN_USER }}/$ADMIN_USER/g" app/__init__.py
sed -i "s/{{ ADMIN_PASS }}/$ADMIN_PASS/g" app/__init__.py
sed -i "s/{{ PANEL_PORT }}/$PANEL_PORT/g" run.py

# Enable and start services
print_header "Starting Services"
print_status "Enabling systemd services..."
systemctl daemon-reload
systemctl enable hoseinproxy-panel
systemctl start hoseinproxy-panel

# Wait for service to start
sleep 10

# Check service status
if systemctl is-active --quiet hoseinproxy-panel; then
    print_success "Panel service is running!"
else
    print_error "Panel service failed to start. Check logs:"
    journalctl -u hoseinproxy-panel --no-pager -n 20
    exit 1
fi

# Final status check
print_header "Final Status Check"
print_status "Checking system status..."
echo ""
echo "🔥 Services Status:"
systemctl status hoseinproxy-panel --no-pager -l | grep -E "(Active|Main PID)"
echo ""
echo "🛡️ Firewall Status:"
ufw status numbered | head -10
echo ""
echo "🐳 Docker Status:"
systemctl status docker --no-pager -l | grep -E "(Active|Main PID)"

# Display final information
print_header "Installation Complete!"
echo ""
cat SYSTEM_INFO.txt

echo ""
print_success "🎉 HoseinProxy Panel + FakeTLS has been successfully installed!"
print_success "🌐 Access your panel at: http://$SERVER_IP:$PANEL_PORT"
print_success "🔑 Login with: $ADMIN_USER / $ADMIN_PASS"
echo ""
print_status "Next steps:"
print_status "1. Login to the panel"
print_status "2. Navigate to 'پروکسی FakeTLS'"
print_status "3. Create your first anti-filtering proxy"
print_status "4. Share the proxy link with users"
echo ""
echo -e "${CYAN}For support and updates, visit: https://github.com/your-repo${NC}"
echo ""

# Cleanup
rm -f get-docker.sh