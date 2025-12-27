#!/bin/bash

# HoseinProxy Management Script
# Version: 6.0 (Luxury English Edition)
# By: Gemini AI

# Environment Settings
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# --- Main Configuration ---
APP_TITLE="HoseinProxy Smart Manager"
INSTALL_DIR="/root/HoseinProxy"
PANEL_DIR="$INSTALL_DIR/panel"
SERVICE_NAME="hoseinproxy"
BACKUP_DIR="/root/backups"
LOG_FILE="/var/log/hoseinproxy_manager.log"

# --- Color Palette ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Graphics & Helper Functions ---

# Spinner Animation
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# Advanced ASCII Header
show_header() {
    clear
    echo -e "${MAGENTA}"
    echo " █   █           █            █▀▀▀▀█                          "
    echo " █   █           █            █    █                          "
    echo " █▀▀▀█  ▄▀▀▄  ▄▀▀█   ▄▀▀▄     █▀▀▀▀▄  █▄ ▄█  ▄▀▀▄  ▀▄  ▄▀  ▀▄ ▄▀ "
    echo " █   █  █  █  ▀▄▄█   █▄▄▀     █     █  █▀ ▀█  █  █   ▀▄▀    █   "
    echo " █   █  ▀▄▄▀  ▀▄▄█▄  ▀▄▄▀     █▄▄▄▄█   █    █  ▀▄▄▀   ▄▀▄     █   "
    echo "                                                      ▀  ▀    ▀   "
    echo -e "${NC}"
    echo -e "${CYAN}${BOLD}       💎 $APP_TITLE - v6.0 (Luxury) 💎${NC}"
    echo -e "${BLUE}       =============================================${NC}"
    echo ""
}

# Modern Progress Bar
show_progress() {
    local -i percent=0;
    local message="$1"
    (
        while [ $percent -le 100 ]; do
            echo $percent
            sleep 0.03
            percent=$((percent + 2))
        done
    ) | whiptail --gauge "$message" 6 60 0
}

# Get System Statistics
get_system_stats() {
    # Service Status
    if systemctl is-active --quiet $SERVICE_NAME; then
        STATUS="${GREEN}✅ Active${NC}"
        STATUS_PLAIN="Active (Running)"
    else
        STATUS="${RED}⛔ Inactive${NC}"
        STATUS_PLAIN="Stopped"
    fi
    
    # Server IP
    IP=$(curl -s -4 --connect-timeout 2 ifconfig.me || echo "N/A")
    
    # Resources
    if command -v bc >/dev/null 2>&1; then
        RAM=$(free -m | awk '/Mem:/ { printf("%.1f%%", $3/$2*100) }')
        CPU=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1"%"}')
    else
        RAM="N/A"
        CPU="N/A"
    fi
    
    # Disk Usage
    DISK=$(df -h / | awk '/\// {print $5}')
    
    # System Uptime
    UPTIME=$(uptime -p | sed 's/up //')
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo -e "${RED}❌ Permission Denied: Please run as root.${NC}"
       exit 1
    fi
}

install_deps() {
    echo -e "${BLUE}[INFO]${NC} Preparing repositories..."
    apt-get update -qq >/dev/null 2>&1 &
    spinner $!
    
    PACKAGES="python3 python3-pip python3-venv docker.io curl nginx git whiptail bc"
    echo -e "${BLUE}[INFO]${NC} Installing necessary tools..."
    apt-get install -y $PACKAGES >> "$LOG_FILE" 2>&1 &
    spinner $!
    
    systemctl enable docker >/dev/null 2>&1
    systemctl start docker >/dev/null 2>&1
}

# --- Main Operations ---

install_panel() {
    show_header
    if (whiptail --title "🚀 Install Panel" --yesno "Are you ready to install the new version?" 10 60); then
        
        install_deps
        show_progress "Configuring system..."
        
        # Check RAM
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        if [ $RAM_KB -lt 500000 ]; then
             whiptail --title "⚠️ Resource Warning" --msgbox "System RAM is less than 500MB." 10 60
        fi

        mkdir -p "$INSTALL_DIR"
        
        # Copy Files
        SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
        if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
            cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/" 2>/dev/null
        fi
        
        cd "$PANEL_DIR" || mkdir -p "$PANEL_DIR"
        
        # Install Python Env
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi
        source venv/bin/activate
        pip install --upgrade pip >> "$LOG_FILE" 2>&1
        pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        
        # User Credentials
        ADMIN_USER=$(whiptail --inputbox "👤 Admin Username:" 10 60 "admin" 3>&1 1>&2 2>&3)
        ADMIN_PASS=$(whiptail --passwordbox "🔑 Admin Password:" 10 60 3>&1 1>&2 2>&3)
        
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
        
        # System Service
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
        
        IP=$(curl -s -4 ifconfig.me)
        whiptail --title "✅ Installation Success" --msgbox "Installation Complete!\n\n🌐 Panel URL: http://$IP:1111\n👤 Username: $ADMIN_USER" 12 60
    fi
}

update_panel() {
    show_progress "♻️ Checking Git repositories..."
    cd "$INSTALL_DIR" || exit
    git fetch
    
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ "$LOCAL" = "$REMOTE" ] && [ "$1" != "force" ]; then
        whiptail --title "✅ Status" --msgbox "Your system is up to date." 10 60
    else
        if [ "$1" == "force" ] || (whiptail --title "♻️ Update Available" --yesno "New version found. Update now?" 10 60); then
            git reset --hard
            git pull >> "$LOG_FILE" 2>&1
            systemctl restart $SERVICE_NAME
            if [ "$1" != "force" ]; then
                whiptail --title "Success" --msgbox "Update completed successfully." 10 60
            fi
        fi
    fi
}

uninstall_panel() {
    if (whiptail --title "🗑️ Uninstall Panel" --yesno "WARNING: All data will be deleted. Continue?" 10 60); then
        show_progress "Removing components..."
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        rm -f /etc/nginx/sites-enabled/hoseinproxy
        systemctl restart nginx
        rm -rf "$INSTALL_DIR"
        whiptail --title "Done" --msgbox "Panel has been removed." 10 60
    fi
}

backup_panel() {
    mkdir -p "$BACKUP_DIR"
    FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M).tar.gz"
    show_progress "💾 Backing up data..."
    tar -czf "$FILE" -C "$INSTALL_DIR" --exclude='venv' --exclude='__pycache__' panel
    whiptail --title "✅ Backup" --msgbox "Backup saved to:\n$FILE" 10 60
}

restore_panel() {
    FILE=$(whiptail --inputbox "Backup File Path:" 10 60 "$BACKUP_DIR/" 3>&1 1>&2 2>&3)
    if [ -f "$FILE" ]; then
        show_progress "📦 Restoring data..."
        systemctl stop $SERVICE_NAME
        tar -xzf "$FILE" -C "$INSTALL_DIR"
        systemctl restart $SERVICE_NAME
        whiptail --msgbox "✅ Restore Complete." 10 60
    else
        whiptail --msgbox "❌ File not found." 10 60
    fi
}

schedule_updates() {
    CMD="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"
    if (whiptail --title "⏰ Auto-Update" --yesno "Enable daily auto-update (at 3 AM)?" 10 60); then
        (crontab -l 2>/dev/null | grep -v "update_silent"; echo "$CMD") | crontab -
        whiptail --msgbox "✅ Enabled." 10 60
    else
        crontab -l 2>/dev/null | grep -v "update_silent" | crontab -
        whiptail --msgbox "⛔ Disabled." 10 60
    fi
}

# --- Main Menu ---

show_menu() {
    show_header
    get_system_stats
    
    # Dashboard Text
    MENU_TEXT="📊 Server Status:\n"
    MENU_TEXT+="   ▫️ Service:    $STATUS_PLAIN\n"
    MENU_TEXT+="   ▫️ IP Address: $IP\n"
    MENU_TEXT+="   ▫️ Resources:  CPU: $CPU | RAM: $RAM\n"
    MENU_TEXT+="   ▫️ Disk Space: $DISK | Uptime: $UPTIME\n\n"
    MENU_TEXT+="👇 Select an operation:"

    OPTION=$(whiptail --title "$APP_TITLE" --menu "$MENU_TEXT" 22 75 10 \
    "1" "🚀 Install Panel" \
    "2" "♻️  Update Panel" \
    "3" "🗑️  Uninstall Panel" \
    "4" "💾 Backup Data" \
    "5" "📦 Restore Data" \
    "6" "⏰ Auto-Update Config" \
    "7" "🔄 Restart Service" \
    "8" "📜 View Logs" \
    "0" "🚪 Exit" 3>&1 1>&2 2>&3)
    
    if [ $? -eq 0 ]; then
        case $OPTION in
            1) install_panel ;;
            2) update_panel ;;
            3) uninstall_panel ;;
            4) backup_panel ;;
            5) restore_panel ;;
            6) schedule_updates ;;
            7) 
               show_progress "🔄 Restarting Service..."
               systemctl restart $SERVICE_NAME
               whiptail --msgbox "✅ Service Restarted." 10 60 
               ;;
            8) 
               tail -n 50 "$LOG_FILE" > /tmp/log
               whiptail --textbox /tmp/log 20 80
               ;;
            0) exit 0 ;;
        esac
    else
        exit 0
    fi
}

# --- Entry Point ---
if [ "$1" == "update_silent" ]; then
    update_panel force
    exit 0
fi

check_root
while true; do
    show_menu
done