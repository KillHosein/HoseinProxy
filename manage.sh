#!/bin/bash

# HoseinProxy Management Script
# Version: 4.0 (Pro Edition - English)
# By: Gemini AI

# Locale settings
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

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
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# --- Helper Functions ---

# Display ASCII Logo
show_logo() {
    clear
    echo -e "${CYAN}"
    echo "  _   _            _       ______                       "
    echo " | | | |          (_)      | ___ \                      "
    echo " | |_| | ___  ___  _ _ __  | |_/ / __ _____  ___   _    "
    echo " |  _  |/ _ \/ __|| | '_ \ |  __/ '__/ _ \ \/ / | | |   "
    echo " | | | | (_) \__ \| | | | || |  | | | (_) >  <| |_| |   "
    echo " \_| |_/\___/|___/|_|_| |_|\_|  |_|  \___/_/\_\\__, |   "
    echo "                                                __/ |   "
    echo "                                               |___/    "
    echo -e "${NC}"
    echo -e "${PURPLE}  HoseinProxy Advanced Manager - v4.0${NC}"
    echo -e "${BLUE}  -------------------------------------------${NC}"
    echo ""
}

log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Fake progress bar for visual feedback
show_progress() {
    local -i percent=0;
    local message="$1"
    (
        while [ $percent -le 100 ]; do
            echo $percent
            sleep 0.1
            percent=$((percent + 2))
        done
    ) | whiptail --gauge "$message" 6 60 0
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo -e "${RED}[ERROR] This script must be run as root.${NC}"
       exit 1
    fi
}

get_system_status() {
    # Service Status
    if systemctl is-active --quiet $SERVICE_NAME; then
        STATUS="${GREEN}Running${NC}"
    else
        STATUS="${RED}Stopped${NC}"
    fi
    
    # System Info
    IP=$(curl -s -4 ifconfig.me --connect-timeout 2 || echo "N/A")
    RAM_USAGE=$(free -m | awk '/Mem:/ { printf("%3.1f%%", $3/$2*100) }')
    CPU_LOAD=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1"%"}')
    
    echo -e "Service Status: $STATUS"
    echo -e "Server IP:      ${YELLOW}$IP${NC}"
    echo -e "RAM Usage:      ${CYAN}$RAM_USAGE${NC} | CPU Load: ${CYAN}$CPU_LOAD${NC}"
}

install_dependencies() {
    echo -e "${BLUE}[INFO]${NC} Updating repositories and installing dependencies..."
    apt-get update -y >> "$LOG_FILE" 2>&1
    
    PACKAGES="python3 python3-pip python3-venv docker.io curl nginx git whiptail bc"
    apt-get install -y $PACKAGES >> "$LOG_FILE" 2>&1
    
    systemctl enable docker >> "$LOG_FILE" 2>&1
    systemctl start docker >> "$LOG_FILE" 2>&1
}

# --- 1. Installation ---

install_panel() {
    show_logo
    if (whiptail --title "Install Panel" --yesno "Are you ready to install the new panel version?" 10 60); then
        
        show_progress "Preparing system..."
        install_dependencies
        
        # Check Resources
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        if [ $RAM_KB -lt 500000 ]; then
             whiptail --title "Warning" --msgbox "System RAM is less than 500MB. Performance might be degraded." 10 60
        fi

        mkdir -p "$INSTALL_DIR"
        SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
        if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
            cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/"
        fi
        
        cd "$PANEL_DIR" || { echo "Directory not found"; exit 1; }
        
        # Python Environment
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi
        
        source venv/bin/activate
        pip install --upgrade pip >> "$LOG_FILE" 2>&1
        
        echo -e "${BLUE}[INFO]${NC} Installing Python libraries..."
        pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        
        # Admin Credentials
        ADMIN_USER=$(whiptail --inputbox "Enter Admin Username:" 10 60 3>&1 1>&2 2>&3)
        if [ -z "$ADMIN_USER" ]; then ADMIN_USER="admin"; fi
        
        ADMIN_PASS=$(whiptail --passwordbox "Enter Admin Password:" 10 60 3>&1 1>&2 2>&3)
        
        # Create Database
        python3 -c "from run import create_admin; create_admin('$ADMIN_USER', '$ADMIN_PASS')" >> "$LOG_FILE" 2>&1
        
        # Nginx Config
        cat > /etc/nginx/sites-available/hoseinproxy <<EOF
server {
    listen 1111 default_server;
    server_name _;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF
        ln -sf /etc/nginx/sites-available/hoseinproxy /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
        systemctl restart nginx
        
        # Systemd Service
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
        
        show_progress "Finalizing installation..."
        
        IP=$(curl -s -4 ifconfig.me)
        whiptail --title "Installation Successful" --msgbox "Installation completed successfully!\n\nPanel URL: http://$IP:1111\nUsername: $ADMIN_USER" 12 60
    else
        echo "Installation cancelled."
    fi
}

# --- 2. Update ---

update_panel() {
    show_progress "Checking for updates..."
    cd "$INSTALL_DIR" || exit
    git fetch
    
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ "$LOCAL" = "$REMOTE" ] && [ "$1" != "force" ]; then
        whiptail --title "Update" --msgbox "System is up to date." 10 60
    else
        if [ "$1" == "force" ] || (whiptail --title "Update Available" --yesno "New version found. Do you want to update?" 10 60); then
            git reset --hard
            git pull >> "$LOG_FILE" 2>&1
            
            cd "$PANEL_DIR" || exit
            if [ -d "venv" ]; then
                source venv/bin/activate
                pip install -r requirements.txt >> "$LOG_FILE" 2>&1
            fi
            
            systemctl restart $SERVICE_NAME
            
            if [ "$1" != "force" ]; then
                whiptail --title "Success" --msgbox "Update completed successfully." 10 60
            fi
        fi
    fi
}

# --- 3. Uninstall ---

uninstall_panel() {
    if (whiptail --title "Uninstall Panel" --yesno "WARNING: All panel data will be deleted. Are you sure?" 10 60); then
        
        if (whiptail --title "Backup" --yesno "Do you want to create a backup before uninstalling?" 10 60); then
             backup_panel
        fi
        
        show_progress "Removing services..."
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        
        rm -f /etc/nginx/sites-enabled/hoseinproxy
        systemctl restart nginx
        
        rm -rf "$INSTALL_DIR"
        
        whiptail --title "Finished" --msgbox "Panel has been completely removed." 10 60
    fi
}

# --- 4. Backup & Restore ---

backup_panel() {
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/hoseinproxy_backup_$TIMESTAMP.tar.gz"
    
    show_progress "Compressing data..."
    
    tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR" \
        --exclude='venv' \
        --exclude='__pycache__' \
        panel
    
    if [ $? -eq 0 ]; then
        whiptail --title "Backup" --msgbox "Backup created successfully:\n$BACKUP_FILE" 10 60
    else
        whiptail --title "Error" --msgbox "Backup failed." 10 60
    fi
}

restore_panel() {
    BACKUP_FILE=$(whiptail --title "Restore" --inputbox "Enter full path to backup file:" 10 60 "$BACKUP_DIR/" 3>&1 1>&2 2>&3)
    
    if [ -f "$BACKUP_FILE" ]; then
        show_progress "Restoring data..."
        systemctl stop $SERVICE_NAME
        tar -xzf "$BACKUP_FILE" -C "$INSTALL_DIR"
        systemctl restart $SERVICE_NAME
        whiptail --title "Success" --msgbox "Data restored successfully." 10 60
    else
        whiptail --title "Error" --msgbox "File not found!" 10 60
    fi
}

# --- 5. Utilities ---

schedule_updates() {
    CRON_CMD="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"
    
    if (whiptail --title "Schedule Updates" --yesno "Do you want to enable daily auto-updates (at 3:00 AM)?" 10 60); then
        (crontab -l 2>/dev/null | grep -v "manage.sh update_silent"; echo "$CRON_CMD") | crontab -
        whiptail --title "Success" --msgbox "Auto-updates enabled." 10 60
    else
        crontab -l 2>/dev/null | grep -v "manage.sh update_silent" | crontab -
        whiptail --title "Disabled" --msgbox "Auto-updates disabled." 10 60
    fi
}

# --- Silent Mode ---
if [ "$1" == "update_silent" ]; then
    update_panel force
    exit 0
fi

# --- Main Menu ---

show_menu() {
    show_logo
    
    # Get info for header
    get_system_status
    echo ""
    echo "  [ Main Menu ]"
    echo ""
    
    OPTION=$(whiptail --title "HoseinProxy Manager Pro" --menu "Select an option:" 20 70 11 \
    "1" "Install Panel" \
    "2" "Update Panel" \
    "3" "Uninstall Panel" \
    "4" "Backup Data" \
    "5" "Restore Data" \
    "6" "Schedule Auto-Update" \
    "7" "Restart Service" \
    "8" "View Logs" \
    "9" "Help / Support" \
    "0" "Exit" 3>&1 1>&2 2>&3)
    
    EXITSTATUS=$?
    if [ $EXITSTATUS = 0 ]; then
        case $OPTION in
        1) install_panel ;;
        2) update_panel ;;
        3) uninstall_panel ;;
        4) backup_panel ;;
        5) restore_panel ;;
        6) schedule_updates ;;
        7) 
            show_progress "Restarting Service..."
            systemctl restart $SERVICE_NAME
            whiptail --title "Success" --msgbox "Service Restarted." 10 60
            ;;
        8) 
            tail -n 50 "$LOG_FILE" > /tmp/logview
            whiptail --title "System Logs" --textbox /tmp/logview 20 80
            rm /tmp/logview
            ;;
        9)
            whiptail --title "Support" --msgbox "For support, visit our GitHub repository or contact the admin." 10 60
            ;;
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