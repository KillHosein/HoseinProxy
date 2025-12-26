#!/bin/bash

# HoseinProxy Management Script
# Version 3.0 (Modular Edition)

# Configuration
LOG_FILE="/var/log/hoseinproxy_manager.log"
INSTALL_DIR="/root/HoseinProxy"
PANEL_DIR="$INSTALL_DIR/panel"
SERVICE_NAME="hoseinproxy"
BACKUP_DIR="/root/backups"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Helper Functions ---

log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
    log "INFO: $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    log "SUCCESS: $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    log "ERROR: $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
       error "This script must be run as root."
       exit 1
    fi
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

install_dependencies() {
    info "Installing system dependencies..."
    
    # Try to fix broken installs first
    apt-get --fix-broken install -y >> "$LOG_FILE" 2>&1
    
    # Update package lists
    if ! apt-get update -y >> "$LOG_FILE" 2>&1; then
        error "Failed to update package lists. Retrying..."
        sleep 2
        apt-get update -y >> "$LOG_FILE" 2>&1
    fi
    
    # Remove conflicting packages if present
    if dpkg -l | grep -q containerd; then
        info "Removing conflicting containerd packages..."
        apt-get remove -y containerd containerd.io >> "$LOG_FILE" 2>&1
    fi

    # Essential packages
    PACKAGES="python3 python3-pip python3-venv docker.io curl nginx git whiptail apt-transport-https ca-certificates gnupg lsb-release"
    
    if ! apt-get install -y $PACKAGES >> "$LOG_FILE" 2>&1; then
        error "Failed to install dependencies silently. Retrying with output..."
        
        # Try installing packages one by one to identify the failure
        for pkg in $PACKAGES; do
            if ! apt-get install -y $pkg >> "$LOG_FILE" 2>&1; then
                error "Failed to install $pkg. Attempting to fix..."
                apt-get --fix-broken install -y >> "$LOG_FILE" 2>&1
                apt-get install -y $pkg
            fi
        done
        
        # Final check
        if ! dpkg -s $PACKAGES >/dev/null 2>&1; then
             error "Some dependencies failed to install. Check log for details."
             # Don't exit here, let the script try to continue or fail later
        fi
    else
        success "Dependencies installed."
    fi
}

ensure_docker_running() {
    if ! command -v docker &> /dev/null; then
        info "Docker not found. Installing..."
        apt-get update -y >> "$LOG_FILE" 2>&1
        apt-get install -y docker.io >> "$LOG_FILE" 2>&1
    fi

    # Try systemd first
    if command -v systemctl &> /dev/null; then
        if ! systemctl is-active --quiet docker; then
            info "Starting Docker (systemd)..."
            systemctl unmask docker >> "$LOG_FILE" 2>&1
            systemctl enable docker >> "$LOG_FILE" 2>&1
            systemctl start docker >> "$LOG_FILE" 2>&1
            sleep 3
        fi
        if systemctl is-active --quiet docker; then
            return 0
        fi
    fi

    # Fallback to service command (SysVinit/WSL)
    if command -v service &> /dev/null; then
        if ! service docker status &> /dev/null; then
            info "Starting Docker (service)..."
            service docker start >> "$LOG_FILE" 2>&1
            sleep 3
        fi
        if service docker status &> /dev/null; then
            return 0
        fi
    fi
    
    # If we get here, Docker isn't running
    error "Docker failed to start. Please check logs."
    return 1
}

# --- 1. Installation ---

install_panel() {
    log "Starting Installation..."
    
    if (whiptail --title "HoseinProxy Installation" --yesno "Are you ready to install HoseinProxy Panel v3.0?" 10 60); then
        install_dependencies
        ensure_docker_running
        
        # Check System Resources
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        if [ $RAM_KB -lt 500000 ]; then
             whiptail --title "Warning" --msgbox "System RAM is less than 500MB. Performance may be degraded." 10 60
        fi

        # Prepare Directory
        mkdir -p "$INSTALL_DIR"
        
        # If we are running from a cloned repo, copy files if not in place
        SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
        if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
            info "Copying files to install directory..."
            cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/"
        fi
        
        # Setup Python Environment
        info "Setting up Python environment..."
        cd "$PANEL_DIR" || { error "Panel directory not found!"; exit 1; }
        
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi
        
        source venv/bin/activate
        pip install --upgrade pip >> "$LOG_FILE" 2>&1
        pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        
        if [ $? -ne 0 ]; then
            error "Failed to install Python requirements."
            exit 1
        fi
        
        # Create Admin User
        ADMIN_USER=$(whiptail --inputbox "Enter Admin Username:" 10 60 3>&1 1>&2 2>&3)
        if [ -z "$ADMIN_USER" ]; then ADMIN_USER="admin"; fi
        
        ADMIN_PASS=$(whiptail --passwordbox "Enter Admin Password:" 10 60 3>&1 1>&2 2>&3)
        if [ -z "$ADMIN_PASS" ]; then 
            error "Password cannot be empty."
            exit 1
        fi
        
        info "Creating admin user..."
        # Using run.py which imports app factory
        python3 -c "from run import create_admin; create_admin('$ADMIN_USER', '$ADMIN_PASS')" >> "$LOG_FILE" 2>&1
        
        # Setup Nginx
        info "Configuring Nginx..."
        cat > /etc/nginx/sites-available/hoseinproxy <<EOF
server {
    listen 1111 default_server;
    server_name _;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
        ln -sf /etc/nginx/sites-available/hoseinproxy /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
        nginx -t >> "$LOG_FILE" 2>&1
        systemctl restart nginx
        
        # Setup Systemd Service
        info "Creating Systemd Service..."
        cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=HoseinProxy Panel
After=network.target docker.service

[Service]
User=root
WorkingDirectory=$PANEL_DIR
Environment="PATH=$PANEL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$PANEL_DIR/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 "run:app"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable $SERVICE_NAME
        systemctl restart $SERVICE_NAME
        
        # Install Fake TLS Support
        if (whiptail --title "Fake TLS Support" --yesno "Do you want to install Fake TLS anti-filter support?" 10 60); then
            info "Installing Fake TLS support..."
            install_fake_tls
        fi
        
        # Final Check
        sleep 2
        if systemctl is-active --quiet $SERVICE_NAME; then
            IP=$(curl -s -4 ifconfig.me)
            whiptail --title "Success" --msgbox "Installation Complete!\n\nPanel URL: http://$IP:1111\nUsername: $ADMIN_USER" 12 60
            success "Installation Completed Successfully."
        else
            error "Service failed to start. Check logs."
            journalctl -u $SERVICE_NAME --no-pager | tail -n 20
        fi
    else
        log "Installation Cancelled."
    fi
}

# --- 2. Update ---

update_panel() {
    log "Checking for updates..."
    cd "$INSTALL_DIR" || exit
    git fetch
    
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ "$LOCAL" = "$REMOTE" ] && [ "$1" != "force" ]; then
        whiptail --title "Update" --msgbox "System is up to date." 10 60
    else
        if [ "$1" == "force" ] || (whiptail --title "Update Available" --yesno "New version found. Update now?" 10 60); then
            info "Updating system..."
            git reset --hard
            git pull >> "$LOG_FILE" 2>&1
            
            # Update Python Dependencies
            cd "$PANEL_DIR" || exit
            if [ -d "venv" ]; then
                source venv/bin/activate
                pip install -r requirements.txt >> "$LOG_FILE" 2>&1
            fi
            
            # Update Fake TLS if it exists
            if [ -d "$INSTALL_DIR/proxy" ] && [ -f "$INSTALL_DIR/proxy/Dockerfile" ]; then
                if (whiptail --title "Update Fake TLS" --yesno "Update Fake TLS Docker image?" 10 60); then
                    info "Updating Fake TLS image..."
                    build_fake_tls_image
                fi
            fi
            
            # Restart Service
            systemctl restart $SERVICE_NAME
            
            success "Update Complete."
            if [ "$1" != "force" ]; then
                whiptail --title "Success" --msgbox "Update Complete!" 10 60
            fi
        fi
    fi
}

# --- 3. Uninstall ---

uninstall_panel() {
    if (whiptail --title "Uninstall" --yesno "DANGER: This will remove HoseinProxy and all data. Continue?" 10 60); then
        
        if (whiptail --title "Backup" --yesno "Do you want to create a full backup before uninstalling?" 10 60); then
             backup_panel
        fi
        
        info "Uninstalling..."
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        
        rm -f /etc/nginx/sites-enabled/hoseinproxy
        rm -f /etc/nginx/sites-available/hoseinproxy
        systemctl restart nginx
        
        # Stop and remove Fake TLS containers
        if docker ps | grep -q mtproxy-faketls; then
            info "Stopping Fake TLS containers..."
            docker stop $(docker ps -q -f "ancestor=mtproxy-faketls:latest") >> "$LOG_FILE" 2>&1
            docker rm $(docker ps -aq -f "ancestor=mtproxy-faketls:latest") >> "$LOG_FILE" 2>&1
        fi
        
        # Remove Fake TLS image
        if docker images | grep -q mtproxy-faketls; then
            info "Removing Fake TLS image..."
            docker rmi mtproxy-faketls:latest >> "$LOG_FILE" 2>&1
        fi
        
        rm -rf "$INSTALL_DIR"
        
        whiptail --title "Done" --msgbox "Uninstallation Complete." 10 60
        success "Uninstallation Complete."
    fi
}

# --- 4. Backup & Restore ---

backup_panel() {
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/hoseinproxy_backup_$TIMESTAMP.tar.gz"
    
    info "Creating backup..."
    
    # Check if panel dir exists
    if [ ! -d "$PANEL_DIR" ]; then
        error "Panel directory not found!"
        return
    fi
    
    # Backup important files (DB, Config, App Code, Requirements)
    # We backup the whole panel directory but exclude venv and __pycache__ to save space
    # Also include proxy directory if it exists
    BACKUP_ITEMS="panel"
    if [ -d "$INSTALL_DIR/proxy" ]; then
        BACKUP_ITEMS="$BACKUP_ITEMS proxy"
    fi
    
    tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR" \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        $BACKUP_ITEMS
    
    if [ $? -eq 0 ]; then
        whiptail --title "Backup" --msgbox "Backup created at:\n$BACKUP_FILE" 10 60
        success "Backup created: $BACKUP_FILE"
    else
        error "Backup failed."
        whiptail --title "Error" --msgbox "Backup failed. Check logs." 10 60
    fi
}

restore_panel() {
    BACKUP_FILE=$(whiptail --title "Restore" --inputbox "Enter full path to backup file:" 10 60 "$BACKUP_DIR/" 3>&1 1>&2 2>&3)
    
    if [ -f "$BACKUP_FILE" ]; then
        info "Restoring from $BACKUP_FILE..."
        systemctl stop $SERVICE_NAME
        
        tar -xzf "$BACKUP_FILE" -C "$INSTALL_DIR"
        
        # Restore permissions/env if needed
        cd "$PANEL_DIR" || exit
        if [ ! -d "venv" ]; then
            python3 -m venv venv
            source venv/bin/activate
            pip install -r requirements.txt
        fi
        
        systemctl restart $SERVICE_NAME
        success "Restore complete."
        whiptail --title "Success" --msgbox "System restored successfully." 10 60
    else
        error "Backup file not found."
        whiptail --title "Error" --msgbox "File not found!" 10 60
    fi
}

# --- 5. Utilities ---

schedule_updates() {
    CRON_CMD="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"
    
    if (whiptail --title "Schedule Updates" --yesno "Enable daily auto-updates at 3:00 AM?" 10 60); then
        (crontab -l 2>/dev/null | grep -v "manage.sh update_silent"; echo "$CRON_CMD") | crontab -
        whiptail --title "Success" --msgbox "Auto-updates enabled." 10 60
        success "Auto-updates enabled."
    else
        crontab -l 2>/dev/null | grep -v "manage.sh update_silent" | crontab -
        whiptail --title "Disabled" --msgbox "Auto-updates disabled." 10 60
        success "Auto-updates disabled."
    fi
}

repair_panel() {
    info "Attempting repair..."
    install_dependencies
    
    # Check and rebuild Fake TLS if needed
    if [ -d "$INSTALL_DIR/proxy" ] && [ -f "$INSTALL_DIR/proxy/Dockerfile" ]; then
        if ! docker images | grep -q mtproxy-faketls; then
            info "Fake TLS image missing, rebuilding..."
            build_fake_tls_image
        fi
    fi
    
    cd "$PANEL_DIR" || exit
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -r requirements.txt >> "$LOG_FILE" 2>&1
    
    # Fix Permissions
    chown -R root:root "$INSTALL_DIR"
    
    systemctl restart $SERVICE_NAME
    whiptail --title "Repair" --msgbox "Repair completed." 10 60
}

# --- Silent Mode ---
if [ "$1" == "update_silent" ]; then
    update_panel force
    exit 0
fi

# --- Main Menu ---

show_menu() {
    OPTION=$(whiptail --title "HoseinProxy Manager v3.0" --menu "Select Operation:" 25 70 15 \
    "1" "Install Panel" \
    "2" "Update Panel" \
    "3" "Uninstall Panel" \
    "4" "Restart Service" \
    "5" "View Logs" \
    "6" "Schedule Auto-Update" \
    "7" "Backup Data" \
    "8" "Restore Data" \
    "9" "Repair / Reinstall Deps" \
    "10" "Fake TLS Management" \
    "11" "Build Fake TLS Image" \
    "12" "Install Fake TLS Support" \
    "13" "System Status Check" \
    "0" "Exit" 3>&1 1>&2 2>&3)
    
    EXITSTATUS=$?
    if [ $EXITSTATUS = 0 ]; then
        case $OPTION in
        1) install_panel ;;
        2) update_panel ;;
        3) uninstall_panel ;;
        4) 
            systemctl restart $SERVICE_NAME
            whiptail --title "Success" --msgbox "Service Restarted." 10 60
            ;;
        5) 
            # Enhanced logs view with Fake TLS status
            if docker images | grep -q mtproxy-faketls; then
                info "Fake TLS Status:"
                if docker ps | grep -q mtproxy-faketls; then
                    success "Fake TLS image: Installed and running"
                else
                    info "Fake TLS image: Installed but not running"
                fi
                echo "----------------------------------------" >> /tmp/logview
            else
                info "Fake TLS Status: Not installed"
            fi
            
            tail -n 50 "$LOG_FILE" >> /tmp/logview
            whiptail --title "System Logs" --textbox /tmp/logview 25 80
            ;;
        6) schedule_updates ;;
        7) backup_panel ;;
        8) restore_panel ;;
        9) repair_panel ;;
        10) manage_fake_tls ;;
        11) build_fake_tls_image ;;
        12) install_fake_tls ;;
        13) 
            # Quick status check
            info "System Status Check:"
            
            # Panel status
            if systemctl is-active --quiet $SERVICE_NAME; then
                success "Panel Service: Running"
            else
                error "Panel Service: Stopped"
            fi
            
            # Docker status
            if systemctl is-active --quiet docker; then
                success "Docker Service: Running"
            else
                error "Docker Service: Stopped"
            fi
            
            # Fake TLS status
            if docker images | grep -q mtproxy-faketls; then
                if docker ps | grep -q mtproxy-faketls; then
                    success "Fake TLS: Installed and running"
                else
                    info "Fake TLS: Installed but not running"
                fi
            else
                info "Fake TLS: Not installed"
            fi
            
            # Nginx status
            if systemctl is-active --quiet nginx; then
                success "Nginx Service: Running"
            else
                error "Nginx Service: Stopped"
            fi
            
            read -p "Press Enter to continue..."
            ;;
        0) exit 0 ;;
        esac
    else
        exit 0
    fi
}

# --- 6. Fake TLS Functions ---

build_fake_tls_image() {
    info "Building Fake TLS Docker image..."
    ensure_docker_running || return 1
    
    if [ ! -d "$INSTALL_DIR/proxy" ]; then
        error "Proxy directory not found. Please ensure Fake TLS files are installed."
        return 1
    fi
    
    cd "$INSTALL_DIR/proxy" || return 1
    
    if docker build -t mtproxy-faketls:latest . >> "$LOG_FILE" 2>&1; then
        success "Fake TLS Docker image built successfully!"
        
        # Test the image
        info "Testing Fake TLS image..."
        TEST_CONTAINER="test-faketls-$(date +%s)"
        if docker run -d --rm --name "$TEST_CONTAINER" -p 8443:443 \
            -e SECRET=0123456789abcdef0123456789abcdef \
            -e TLS_DOMAIN=google.com \
            -e WORKERS=2 mtproxy-faketls:latest >> "$LOG_FILE" 2>&1; then
            
            sleep 5
            if docker ps | grep -q "$TEST_CONTAINER"; then
                success "Fake TLS test passed!"
                docker stop "$TEST_CONTAINER" >> "$LOG_FILE" 2>&1
            else
                error "Fake TLS test failed. Check logs."
                docker logs "$TEST_CONTAINER" >> "$LOG_FILE" 2>&1
                docker rm -f "$TEST_CONTAINER" >> "$LOG_FILE" 2>&1
            fi
        fi
    else
        error "Failed to build Fake TLS image. Check logs."
        return 1
    fi
    
    cd - >> "$LOG_FILE" 2>&1
}

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
cat > config.py << CONFIG_EOF
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
CONFIG_EOF

# Start the proxy
exec python3 proxy_server.py
EOF

    chmod +x entrypoint.sh
    
    # Return to original directory
    cd - >> "$LOG_FILE" 2>&1
    
    # Build the Docker image
    build_fake_tls_image
}

manage_fake_tls() {
    action=$(whiptail --title "Fake TLS Management" --menu "Select operation:" 18 65 6 \
        "1" "Build Fake TLS Image" \
        "2" "Test Fake TLS Proxy" \
        "3" "View Fake TLS Logs" \
        "4" "Check Fake TLS Status" \
        "5" "Quick Setup Guide" \
        "6" "Back" 3>&1 1>&2 2>&3)
    
    case $action in
        1)
            build_fake_tls_image
            ;;
        2)
            ensure_docker_running || return
            info "Testing Fake TLS proxy..."
            TEST_CONTAINER="test-faketls-$(date +%s)"
            docker run -d --rm --name "$TEST_CONTAINER" -p 8443:443 \
                -e SECRET=0123456789abcdef0123456789abcdef \
                -e TLS_DOMAIN=google.com \
                -e WORKERS=2 mtproxy-faketls:latest >> "$LOG_FILE" 2>&1
            
            sleep 5
            if docker ps | grep -q "$TEST_CONTAINER"; then
                success "Fake TLS proxy is running! Test with: telnet localhost 8443"
                whiptail --title "Success" --msgbox "Fake TLS proxy is running on port 8443!\n\nYou can test it with:\ntelnet localhost 8443\n\nor\nopenssl s_client -connect localhost:8443 -servername google.com\n\nThen create a proxy in your panel with 'Fake TLS' type!" 18 70
                docker stop "$TEST_CONTAINER" >> "$LOG_FILE" 2>&1
            else
                error "Test failed. Check logs."
                docker logs "$TEST_CONTAINER" >> "$LOG_FILE" 2>&1
                docker rm -f "$TEST_CONTAINER" >> "$LOG_FILE" 2>&1
            fi
            ;;
        3)
            ensure_docker_running || return
            if docker ps | grep -q mtproxy-faketls; then
                CONTAINER_ID=$(docker ps | grep mtproxy-faketls | awk '{print $1}')
                docker logs "$CONTAINER_ID" | tail -50 > /tmp/faketls_logs
                whiptail --title "Fake TLS Logs" --textbox /tmp/faketls_logs 25 80
            else
                whiptail --title "Info" --msgbox "No Fake TLS container is currently running." 10 60
            fi
            ;;
        4)
            # Check Fake TLS status
            ensure_docker_running || return
            if docker images | grep -q mtproxy-faketls; then
                if docker ps | grep -q mtproxy-faketls; then
                    success "Fake TLS Status: Installed and running"
                    CONTAINER_ID=$(docker ps | grep mtproxy-faketls | awk '{print $1}')
                    docker stats "$CONTAINER_ID" --no-stream > /tmp/faketls_stats 2>/dev/null
                    whiptail --title "Fake TLS Status" --msgbox "✅ Fake TLS is running successfully!\n\nContainer ID: $CONTAINER_ID\n\nUse your panel to create Fake TLS proxies." 12 60
                else
                    info "Fake TLS Status: Installed but not running"
                    whiptail --title "Fake TLS Status" --msgbox "✅ Fake TLS image is installed.\n\nYou can now create Fake TLS proxies from your panel." 10 60
                fi
            else
                error "Fake TLS Status: Not installed"
                whiptail --title "Fake TLS Status" --msgbox "❌ Fake TLS is not installed.\n\nPlease install it first from the main menu." 10 60
            fi
            ;;
        5)
            whiptail --title "Fake TLS Quick Setup Guide" --msgbox "🛡️ Fake TLS Quick Setup:\n\n1. Install Fake TLS from main menu\n2. Build the Docker image\n3. Test the proxy\n4. Go to your panel\n5. Create new proxy\n6. Select 'Fake TLS' type\n7. Use popular domains like google.com\n8. Save and enjoy anti-filter!" 15 65
            ;;
        6)
            return 0
            ;;
    esac
}

# Entry Point
check_root
while true; do
    show_menu
done
