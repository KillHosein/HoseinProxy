#!/bin/bash

# HoseinProxy Management Script
# Version 2.0

LOG_FILE="/var/log/hoseinproxy_manager.log"
INSTALL_DIR="/root/HoseinProxy"
PANEL_DIR="$INSTALL_DIR/panel"
SERVICE_NAME="hoseinproxy"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper Functions
log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo -e "${RED}Error: This script must be run as root.${NC}"
       exit 1
    fi
}

install_dependencies() {
    log "Installing system dependencies..."
    apt-get update -y >> "$LOG_FILE" 2>&1
    apt-get install -y python3 python3-pip python3-venv docker.io curl nginx git whiptail >> "$LOG_FILE" 2>&1
}

# --- 1. Installation Section ---
install_panel() {
    log "Starting Installation..."
    
    if (whiptail --title "HoseinProxy Installation" --yesno "Are you ready to install HoseinProxy Panel?" 10 60); then
        install_dependencies
        
        # Check requirements
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        if [ $RAM_KB -lt 500000 ]; then
             whiptail --title "Warning" --msgbox "System RAM is less than 500MB. Performance may be degraded." 10 60
        fi

        # Clone/Copy logic handled by git clone usually, but here we assume we are in the repo or downloading it.
        # Ensure we are in the correct place
        mkdir -p "$INSTALL_DIR"
        
        # Configure Docker
        systemctl enable docker
        systemctl start docker
        
        # Setup Python
        cd "$PANEL_DIR" || exit
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        
        # Get Credentials
        ADMIN_USER=$(whiptail --inputbox "Enter Admin Username:" 10 60 3>&1 1>&2 2>&3)
        ADMIN_PASS=$(whiptail --passwordbox "Enter Admin Password:" 10 60 3>&1 1>&2 2>&3)
        
        python3 -c "from app import create_admin; create_admin('$ADMIN_USER', '$ADMIN_PASS')"
        
        # Setup Nginx
        cat > /etc/nginx/sites-available/hoseinproxy <<EOF
server {
    listen 80 default_server;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
        ln -sf /etc/nginx/sites-available/hoseinproxy /etc/nginx/sites-enabled/
        rm -f /etc/nginx/sites-enabled/default
        systemctl restart nginx

        # Setup Systemd
        cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=HoseinProxy Panel
After=network.target docker.service

[Service]
User=root
WorkingDirectory=$PANEL_DIR
ExecStart=$PANEL_DIR/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable $SERVICE_NAME
        systemctl restart $SERVICE_NAME
        
        IP=$(curl -s ifconfig.me)
        whiptail --title "Success" --msgbox "Installation Complete!\nPanel URL: http://$IP" 10 60
        log "Installation Completed Successfully."
    else
        log "Installation Cancelled."
    fi
}

# --- 2. Update Section ---
update_panel() {
    log "Checking for updates..."
    cd "$INSTALL_DIR" || exit
    git fetch
    
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ $LOCAL = $REMOTE ]; then
        whiptail --title "Update" --msgbox "System is up to date." 10 60
    else
        if (whiptail --title "Update Available" --yesno "New version found. Update now?" 10 60); then
            log "Updating system..."
            git pull >> "$LOG_FILE" 2>&1
            
            # Re-install requirements
            cd "$PANEL_DIR" || exit
            source venv/bin/activate
            pip install -r requirements.txt >> "$LOG_FILE" 2>&1
            
            # Restart Service
            systemctl restart $SERVICE_NAME
            
            whiptail --title "Success" --msgbox "Update Complete!" 10 60
            log "Update Completed."
        fi
    fi
}

# --- 3. Uninstall Section ---
uninstall_panel() {
    if (whiptail --title "Uninstall" --yesno "DANGER: This will remove HoseinProxy and all data. Continue?" 10 60); then
        
        # Show files to be deleted
        FILES_LIST=$(find "$INSTALL_DIR" -maxdepth 2)
        whiptail --title "Files to be Deleted" --msgbox "The following files/directories will be deleted:\n\n$FILES_LIST\n\nAnd system services: $SERVICE_NAME" 20 70

        # Backup
        if (whiptail --title "Backup" --yesno "Do you want to create a full backup before uninstalling?" 10 60); then
             backup_panel
        fi
        
        log "Uninstalling..."
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME
        rm /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        
        rm /etc/nginx/sites-enabled/hoseinproxy
        rm /etc/nginx/sites-available/hoseinproxy
        systemctl restart nginx
        
        # Optional: Remove dependencies? No, safer to keep system libs.
        
        rm -rf "$INSTALL_DIR"
        
        whiptail --title "Done" --msgbox "Uninstallation Complete." 10 60
        log "Uninstallation Complete."
    fi
}

# --- 4. Additional Features ---
schedule_updates() {
    CRON_CMD="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"
    
    if (whiptail --title "Schedule Updates" --yesno "Enable daily auto-updates at 3:00 AM?" 10 60); then
        (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
        whiptail --title "Success" --msgbox "Auto-updates enabled." 10 60
        log "Auto-updates enabled."
    else
        # Remove cron job
        crontab -l | grep -v "manage.sh update_silent" | crontab -
        whiptail --title "Disabled" --msgbox "Auto-updates disabled." 10 60
        log "Auto-updates disabled."
    fi
}

backup_panel() {
    BACKUP_DIR="/root/backups"
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/hoseinproxy_backup_$TIMESTAMP.tar.gz"
    
    log "Starting backup..."
    
    # Backup DB and Config
    tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR" panel/panel.db panel/app.py panel/requirements.txt
    
    whiptail --title "Backup" --msgbox "Backup created at:\n$BACKUP_FILE" 10 60
    log "Backup created: $BACKUP_FILE"
}

rollback_panel() {
    if (whiptail --title "Rollback" --yesno "Revert to previous version? Service will restart." 10 60); then
        log "Rolling back..."
        cd "$INSTALL_DIR" || exit
        
        # Reset to previous commit
        git reset --hard HEAD^ >> "$LOG_FILE" 2>&1
        
        # Restart Service
        systemctl restart $SERVICE_NAME
        
        whiptail --title "Success" --msgbox "Rolled back to previous version." 10 60
        log "Rolled back successfully."
    fi
}

update_silent() {
    # Silent update for cron
    log "Starting silent update..."
    cd "$INSTALL_DIR" || exit
    git fetch
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ $LOCAL != $REMOTE ]; then
        git pull >> "$LOG_FILE" 2>&1
        cd "$PANEL_DIR" || exit
        source venv/bin/activate
        pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        systemctl restart $SERVICE_NAME
        log "Silent update completed."
    else
        log "No updates found."
    fi
}

# --- Main Menu ---
show_menu() {
    OPTION=$(whiptail --title "HoseinProxy Manager" --menu "Choose an option:" 20 60 10 \
    "1" "Install Panel" \
    "2" "Update Panel" \
    "3" "Uninstall Panel" \
    "4" "Restart Service" \
    "5" "View Logs" \
    "6" "Schedule Updates" \
    "7" "Backup Data" \
    "8" "Rollback Version" \
    "9" "Exit" 3>&1 1>&2 2>&3)
    
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
            tail -n 20 "$LOG_FILE" > /tmp/logview
            whiptail --title "Logs" --textbox /tmp/logview 20 80
            ;;
        6) schedule_updates ;;
        7) backup_panel ;;
        8) rollback_panel ;;
        9) exit 0 ;;
        esac
    else
        exit 0
    fi
}

# Handle silent update argument
if [ "$1" == "update_silent" ]; then
    update_silent
    exit 0
fi


# Entry Point
check_root
while true; do
    show_menu
done
