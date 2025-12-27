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
    apt-get update -y >> "$LOG_FILE" 2>&1
    
    # Essential packages
    PACKAGES="python3 python3-pip python3-venv docker.io curl nginx git whiptail"
    
    apt-get install -y $PACKAGES >> "$LOG_FILE" 2>&1
    
    if [ $? -eq 0 ]; then
        success "Dependencies installed."
    else
        error "Failed to install dependencies. Check log for details."
        exit 1
    fi
}

ensure_docker_running() {
    if ! systemctl is-active --quiet docker; then
        info "Starting Docker..."
        systemctl enable docker >> "$LOG_FILE" 2>&1
        systemctl start docker >> "$LOG_FILE" 2>&1
    fi
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
    tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR" \
        --exclude='venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        panel
    
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
    OPTION=$(whiptail --title "HoseinProxy Manager v3.0" --menu "Select Operation:" 22 70 12 \
    "1" "Install Panel" \
    "2" "Update Panel" \
    "3" "Uninstall Panel" \
    "4" "Restart Service" \
    "5" "View Logs" \
    "6" "Schedule Auto-Update" \
    "7" "Backup Data" \
    "8" "Restore Data" \
    "9" "Repair / Reinstall Deps" \
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
            tail -n 50 "$LOG_FILE" > /tmp/logview
            whiptail --title "System Logs" --textbox /tmp/logview 20 80
            ;;
        6) schedule_updates ;;
        7) backup_panel ;;
        8) restore_panel ;;
        9) repair_panel ;;
        0) exit 0 ;;
        esac
    else
        exit 0
    fi
}

# Entry Point
check_root
while true; do
    show_menu
done
