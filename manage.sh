#!/bin/bash

# ==============================================================================
# HoseinProxy Management Script
# Version: 5.0.0 (Enterprise Edition)
# Author: Gemini AI
# Description: Advanced management tool for HoseinProxy panel.
# ==============================================================================

# --- Environment Setup ---
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# --- Configuration ---
readonly APP_NAME="HoseinProxy"
readonly APP_VERSION="5.0.0"
readonly BASE_DIR="/root/HoseinProxy"
readonly PANEL_DIR="${BASE_DIR}/panel"
readonly LOG_FILE="/var/log/hoseinproxy_manager.log"
readonly BACKUP_DIR="/root/backups"
readonly SERVICE_NAME="hoseinproxy"
readonly NGINX_CONF="/etc/nginx/sites-available/hoseinproxy"

# --- Colors (for terminal output outside whiptail) ---
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# --- Logging Functions ---
log() {
    local level="$1"
    local message="$2"
    local timestamp=$(date +'%Y-%m-%d %H:%M:%S')
    echo -e "[${timestamp}] [${level}] ${message}" >> "$LOG_FILE"
}

log_info() { log "INFO" "$1"; }
log_warn() { log "WARN" "$1"; }
log_error() { log "ERROR" "$1"; }

# --- Error Handling ---
cleanup() {
    rm -f /tmp/hp_temp_*
}
trap cleanup EXIT

handle_error() {
    log_error "Script error at line $1"
}
# trap 'handle_error $LINENO' ERR

# --- System Checks ---
check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[CRITICAL] This script must be run as root.${NC}"
        exit 1
    fi
}

check_dependencies() {
    local deps=("curl" "git" "whiptail" "bc" "openssl" "tar")
    local missing=()
    
    for cmd in "${deps[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done
    
    if [ ${#missing[@]} -ne 0 ]; then
        echo -e "${YELLOW}[INIT] Installing missing dependencies: ${missing[*]}...${NC}"
        apt-get update -qq >/dev/null 2>&1
        apt-get install -y "${missing[@]}" >> "$LOG_FILE" 2>&1
    fi
}

get_system_metrics() {
    # Network
    SERVER_IP=$(curl -s -4 --connect-timeout 2 ifconfig.me || echo "N/A")
    
    # Resources
    RAM_USAGE=$(free -m | awk '/Mem:/ { printf("%.1f%%", $3/$2*100) }')
    CPU_LOAD=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1"%"}')
    
    # Service
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        SERVICE_STATUS="Active (Running)"
    else
        SERVICE_STATUS="Inactive (Stopped)"
    fi
}

show_progress() {
    local message="$1"
    local sleep_time=${2:-0.1}
    {
        for ((i = 0 ; i <= 100 ; i+=2)); do
            echo $i
            sleep "$sleep_time"
        done
    } | whiptail --gauge "$message" 6 60 0
}

# --- Core Operations ---

install_panel() {
    if ! (whiptail --title "Installation" --yesno "Install ${APP_NAME} v${APP_VERSION}?" 10 60); then
        return
    fi

    log_info "Starting installation process."
    
    # Resource Check
    local ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    if [ "$ram_kb" -lt 500000 ]; then
        whiptail --title "Resource Warning" --msgbox "Low RAM detected (<500MB). Performance may be limited." 10 60
    fi

    show_progress "Installing system packages..." 0.05
    apt-get update -y >> "$LOG_FILE" 2>&1
    apt-get install -y python3 python3-pip python3-venv docker.io curl nginx git >> "$LOG_FILE" 2>&1
    
    systemctl enable docker >> "$LOG_FILE" 2>&1
    systemctl start docker >> "$LOG_FILE" 2>&1

    # Setup Files
    mkdir -p "$BASE_DIR"
    local script_dir=$(dirname "$(readlink -f "$0")")
    if [ "$script_dir" != "$BASE_DIR" ]; then
        cp -r "$script_dir/"* "$BASE_DIR/" 2>/dev/null || true
    fi

    cd "$PANEL_DIR" || {
        whiptail --title "Error" --msgbox "Panel directory missing!" 10 60
        log_error "Panel directory not found."
        return
    }

    # Python Env
    show_progress "Configuring Python environment..." 0.05
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    pip install --upgrade pip >> "$LOG_FILE" 2>&1
    pip install -r requirements.txt >> "$LOG_FILE" 2>&1

    # User Config
    local admin_user=$(whiptail --inputbox "Admin Username:" 10 60 "admin" 3>&1 1>&2 2>&3)
    [ -z "$admin_user" ] && admin_user="admin"
    
    local admin_pass
    while [[ -z "$admin_pass" ]]; do
        admin_pass=$(whiptail --passwordbox "Admin Password:" 10 60 3>&1 1>&2 2>&3)
        if [[ -z "$admin_pass" ]]; then
            whiptail --msgbox "Password is required." 8 40
        fi
    done

    # Initialize DB
    if python3 -c "from run import create_admin; create_admin('$admin_user', '$admin_pass')" >> "$LOG_FILE" 2>&1; then
        log_info "Admin user created."
    else
        log_error "Failed to create admin user."
        whiptail --title "Error" --msgbox "Failed to initialize database. Check logs." 10 60
    fi

    # Nginx
    cat > "$NGINX_CONF" <<EOF
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
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    nginx -t >> "$LOG_FILE" 2>&1 && systemctl restart nginx

    # Systemd
    cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=${APP_NAME} Panel
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
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"

    log_info "Installation completed."
    whiptail --title "Installation Success" --msgbox "Panel Installed Successfully!\n\nURL: http://${SERVER_IP}:1111\nUsername: ${admin_user}" 12 60
}

update_panel() {
    local force=$1
    
    show_progress "Checking for updates..."
    cd "$BASE_DIR" || return
    git fetch
    
    local local_hash=$(git rev-parse @)
    local remote_hash=$(git rev-parse @{u})
    
    if [ "$local_hash" = "$remote_hash" ] && [ "$force" != "force" ]; then
        whiptail --title "Update" --msgbox "System is already up to date." 10 60
        return
    fi
    
    if [ "$force" == "force" ] || (whiptail --title "Update Available" --yesno "New version found. Update now?" 10 60); then
        log_info "Updating panel..."
        git reset --hard
        git pull >> "$LOG_FILE" 2>&1
        
        cd "$PANEL_DIR" || return
        if [ -d "venv" ]; then
            source venv/bin/activate
            pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        fi
        
        systemctl restart "$SERVICE_NAME"
        
        if [ "$force" != "force" ]; then
            whiptail --title "Success" --msgbox "Update completed successfully." 10 60
        fi
        log_info "Update completed."
    fi
}

uninstall_panel() {
    if ! (whiptail --title "Uninstall" --yesno "WARNING: This will DELETE all data. Continue?" 10 60); then
        return
    fi
    
    if (whiptail --title "Backup" --yesno "Create a backup before uninstalling?" 10 60); then
        backup_panel
    fi
    
    show_progress "Uninstalling..."
    systemctl stop "$SERVICE_NAME"
    systemctl disable "$SERVICE_NAME"
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
    
    rm -f "/etc/nginx/sites-enabled/hoseinproxy"
    systemctl restart nginx
    
    rm -rf "$BASE_DIR"
    
    log_info "Panel uninstalled."
    whiptail --title "Done" --msgbox "Panel has been removed." 10 60
}

backup_panel() {
    mkdir -p "$BACKUP_DIR"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/hoseinproxy_backup_$timestamp.tar.gz"
    
    show_progress "Creating backup..."
    
    if tar -czf "$backup_file" -C "$BASE_DIR" --exclude='venv' --exclude='__pycache__' panel >> "$LOG_FILE" 2>&1; then
        log_info "Backup created: $backup_file"
        whiptail --title "Backup Success" --msgbox "Backup saved to:\n$backup_file" 10 60
    else
        log_error "Backup failed."
        whiptail --title "Backup Failed" --msgbox "Check logs for details." 10 60
    fi
}

restore_panel() {
    local backup_file=$(whiptail --title "Restore" --inputbox "Backup File Path:" 10 60 "$BACKUP_DIR/" 3>&1 1>&2 2>&3)
    
    if [ -f "$backup_file" ]; then
        show_progress "Restoring data..."
        systemctl stop "$SERVICE_NAME"
        tar -xzf "$backup_file" -C "$BASE_DIR" >> "$LOG_FILE" 2>&1
        systemctl restart "$SERVICE_NAME"
        log_info "Restored from $backup_file"
        whiptail --title "Success" --msgbox "Data restored successfully." 10 60
    else
        whiptail --title "Error" --msgbox "File not found." 10 60
    fi
}

# --- Utilities ---

view_logs() {
    local temp_log="/tmp/hp_view.log"
    tail -n 100 "$LOG_FILE" > "$temp_log"
    whiptail --title "System Logs (Last 100 lines)" --textbox "$temp_log" 20 80
    rm -f "$temp_log"
}

restart_service() {
    show_progress "Restarting Service..."
    systemctl restart "$SERVICE_NAME"
    whiptail --title "Success" --msgbox "Service restarted." 10 60
}

schedule_updates() {
    local cron_cmd="0 3 * * * /bin/bash $BASE_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"
    
    if (whiptail --title "Auto-Update" --yesno "Enable daily auto-updates (3:00 AM)?" 10 60); then
        (crontab -l 2>/dev/null | grep -v "manage.sh update_silent"; echo "$cron_cmd") | crontab -
        whiptail --title "Enabled" --msgbox "Auto-updates enabled." 10 60
    else
        crontab -l 2>/dev/null | grep -v "manage.sh update_silent" | crontab -
        whiptail --title "Disabled" --msgbox "Auto-updates disabled." 10 60
    fi
}

# --- Main Menu ---

show_menu() {
    get_system_metrics
    
    local menu_info="User: $USER | Host: $HOSTNAME\n"
    menu_info+="IP: ${SERVER_IP} | Status: ${SERVICE_STATUS}\n"
    menu_info+="Load: ${CPU_LOAD} | RAM: ${RAM_USAGE}\n"
    menu_info+="------------------------------------------------"
    
    local choice
    choice=$(whiptail --title "${APP_NAME} Manager v${APP_VERSION}" \
             --menu "$menu_info" 20 75 10 \
        "1" "Install Panel" \
        "2" "Update Panel" \
        "3" "Uninstall Panel" \
        "4" "Backup Data" \
        "5" "Restore Data" \
        "6" "Auto-Update Config" \
        "7" "Restart Service" \
        "8" "View Logs" \
        "0" "Exit" 3>&1 1>&2 2>&3)
        
    local status=$?
    if [ $status -ne 0 ]; then exit 0; fi
    
    case $choice in
        1) install_panel ;;
        2) update_panel ;;
        3) uninstall_panel ;;
        4) backup_panel ;;
        5) restore_panel ;;
        6) schedule_updates ;;
        7) restart_service ;;
        8) view_logs ;;
        0) exit 0 ;;
    esac
}

# --- Entry Point ---

# Silent update mode check
if [ "$1" == "update_silent" ]; then
    update_panel force
    exit 0
fi

# Interactive mode
check_root
check_dependencies

while true; do
    show_menu
done
