#!/usr/bin/env bash
# HoseinProxy Smart Manager
# Version: 7.1 (Advanced Professional Edition)
# Author: Hosein (refined)

set -Eeuo pipefail
IFS=$'\n\t'

# ----------------------------
# Environment
# ----------------------------
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ----------------------------
# Configuration
# ----------------------------
# Default Configuration
APP_TITLE="HoseinProxy Smart Manager"
INSTALL_DIR="/root/HoseinProxy"
PANEL_DIR="$INSTALL_DIR/panel"
SERVICE_NAME="hoseinproxy"
BACKUP_DIR="/root/backups"
LOG_FILE="/var/log/hoseinproxy_manager.log"

NGINX_SITE_NAME="hoseinproxy"
NGINX_PORT="1111"
GUNICORN_BIND="127.0.0.1:5000"
GUNICORN_WORKERS="2"

# Load External Configuration
CONFIG_FILE="$INSTALL_DIR/config.env"
if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

# Ensure derived variables are set correctly if not in config
PANEL_DIR="${PANEL_DIR:-$INSTALL_DIR/panel}"

# ----------------------------
# Colors
# ----------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ----------------------------
# Logging & UX helpers
# ----------------------------
timestamp() { date +"%Y-%m-%d %H:%M:%S"; }

log() {
  local level="$1"; shift
  local msg="$*"
  printf "[%s] [%s] %s\n" "$(timestamp)" "$level" "$msg" | tee -a "$LOG_FILE" >/dev/null
}

info() { echo -e "${BLUE}[INFO]${NC} $*"; log "INFO" "$*"; }
ok()   { echo -e "${GREEN}[ OK ]${NC} $*"; log "OK"   "$*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; log "WARN" "$*"; }
err()  { echo -e "${RED}[ERR ]${NC} $*"; log "ERR"  "$*"; }

die() { err "$*"; exit 1; }

on_error() {
  local exit_code=$?
  local line_no=${BASH_LINENO[0]:-?}
  err "Unexpected error at line ${line_no}. (exit code: ${exit_code})"
  err "Check log: $LOG_FILE"
  exit "$exit_code"
}
trap on_error ERR

# Spinner (safe PID check)
spinner() {
  local pid="$1"
  local delay=0.1
  local spin='|/-\'
  while kill -0 "$pid" >/dev/null 2>&1; do
    for c in $(echo -n "$spin" | fold -w1); do
      printf " [%c]  " "$c"
      sleep "$delay"
      printf "\b\b\b\b\b\b"
      kill -0 "$pid" >/dev/null 2>&1 || break
    done
  done
  printf "      \b\b\b\b\b\b"
}

# Text-based progress wrapper
show_progress() {
  local message="$1"
  echo -e "${BLUE}➤ ${message}${NC}"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || return 1
}

# ----------------------------
# Input Helpers
# ----------------------------
pause() {
  read -rp "Press [Enter] to continue..."
}

ask_yesno() {
  local prompt="$1"
  local default="${2:-N}"
  local reply
  
  if [ "${default,,}" = "y" ]; then
    prompt="$prompt [Y/n]"
  else
    prompt="$prompt [y/N]"
  fi
  
  read -rp "$prompt " reply
  if [ -z "$reply" ]; then
    reply="$default"
  fi
  
  if [[ "${reply,,}" =~ ^(y|yes)$ ]]; then
    return 0
  else
    return 1
  fi
}

ask_input() {
  local prompt="$1"
  local default="${2:-}"
  local var_name="$3"
  local reply
  
  local p_text="$prompt"
  [ -n "$default" ] && p_text="$p_text [$default]"
  
  read -rp "$p_text: " reply
  
  if [ -z "$reply" ]; then
    eval "$var_name='$default'"
  else
    eval "$var_name='$reply'"
  fi
}

ask_password() {
  local prompt="$1"
  local var_name="$2"
  local reply
  
  echo -n "$prompt: "
  read -rs reply
  echo
  eval "$var_name='$reply'"
}

# ----------------------------
# UI
# ----------------------------
show_header() {
  clear
  echo -e "${RED}"
  echo " ██╗  ██╗██╗██╗     ██╗     ██╗  ██╗ ██████╗ ███████╗███████╗██╗███╗   ██╗"
  echo " ██║ ██╔╝██║██║     ██║     ██║  ██║██╔═══██╗██╔════╝██╔════╝██║████╗  ██║"
  echo " █████╔╝ ██║██║     ██║     ███████║██║   ██║███████╗█████╗  ██║██╔██╗ ██║"
  echo " ██╔═██╗ ██║██║     ██║     ██╔══██║██║   ██║╚════██║██╔══╝  ██║██║╚██╗██║"
  echo " ██║  ██╗██║███████╗███████╗██║  ██║╚██████╔╝███████║███████╗██║██║ ╚████║"
  echo " ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝"
  echo -e "${NC}"
  echo -e "${CYAN}${BOLD}        ☠  KillHosein Control Panel  ☠${NC}"
  echo -e "${BLUE}        ======================================================${NC}"
  echo ""
}

# ----------------------------
# System Info
# ----------------------------
get_public_ip() {
  # fastest + fallback
  local ip="N/A"
  if require_cmd curl; then
    ip="$(curl -s -4 --connect-timeout 2 ifconfig.me 2>/dev/null || true)"
    [ -n "$ip" ] || ip="N/A"
  fi
  echo "$ip"
}

get_system_stats() {
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    STATUS="${GREEN}✅ Active${NC}"
    STATUS_PLAIN="Active (Running)"
  else
    STATUS="${RED}⛔ Inactive${NC}"
    STATUS_PLAIN="Stopped"
  fi

  IP="$(get_public_ip)"

  if require_cmd bc; then
    RAM="$(free -m | awk '/Mem:/ { printf("%.1f%%", $3/$2*100) }')"
    CPU="$(top -bn1 | awk -F',' '/Cpu\(s\)/ {gsub(/.*id/,"",$4); gsub(/[^0-9.]/,"",$4); printf("%.1f%%", 100-$4)}' 2>/dev/null || echo "N/A")"
  else
    RAM="N/A"
    CPU="N/A"
  fi

  DISK="$(df -h / | awk 'NR==2 {print $5}')"
  UPTIME="$(uptime -p | sed 's/^up //')"
  
  # Check if BBR is enabled for display
  if grep -q "net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf 2>/dev/null; then
    BBR_STATUS="ON"
  else
    BBR_STATUS="OFF"
  fi
}

# ----------------------------
# Safety
# ----------------------------
check_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "Permission denied. Please run as root."
}

ensure_whiptail() {
  require_cmd whiptail || die "whiptail not found. Install it: apt-get install -y whiptail"
}

# basic shell escaping for python string literal injection prevention
py_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\'/\\\'}"
  echo "$s"
}

# ----------------------------
# Dependencies
# ----------------------------
install_deps() {
  info "Updating apt repositories..."
  apt-get update -qq >/dev/null 2>&1 &
  spinner $!

  local packages=(python3 python3-pip python3-venv docker.io curl nginx git whiptail bc)
  info "Installing dependencies: ${packages[*]}"
  apt-get install -y "${packages[@]}" >>"$LOG_FILE" 2>&1 &
  spinner $!

  systemctl enable docker >/dev/null 2>&1 || true
  systemctl start docker  >/dev/null 2>&1 || true
  ok "Dependencies installed."
}

# ----------------------------
# Optimization & Advanced Tools
# ----------------------------
enable_bbr() {
  show_progress "🚀 Enabling TCP BBR..."
  
  if grep -q "net.core.default_qdisc=fq" /etc/sysctl.conf && grep -q "net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf; then
    echo -e "${GREEN}✅ TCP BBR is already enabled.${NC}"
    pause
    ok "TCP BBR already enabled."
    return 0
  fi

  echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
  echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
  sysctl -p >>"$LOG_FILE" 2>&1
  
  echo -e "${GREEN}✅ TCP BBR enabled successfully.${NC}"
  pause
  ok "TCP BBR enabled."
}

configure_firewall() {
  if ! require_cmd ufw; then
    if ask_yesno "UFW is not installed. Install it?" "Y"; then
      apt-get install -y ufw >>"$LOG_FILE" 2>&1
    else
      return 1
    fi
  fi

  show_progress "🛡️ Configuring Firewall..."
  
  ufw allow ssh >/dev/null 2>&1
  ufw allow http >/dev/null 2>&1
  ufw allow https >/dev/null 2>&1
  ufw allow "${NGINX_PORT}/tcp" >/dev/null 2>&1
  
  # Allow proxy ports if known, otherwise warn
  # For now just basic ports
  
  if ! ufw status | grep -q "Status: active"; then
    echo "y" | ufw enable >>"$LOG_FILE" 2>&1
  fi
  
  echo -e "${GREEN}✅ Firewall configured (SSH, HTTP, HTTPS, Panel Port).${NC}"
  pause
  ok "Firewall configured."
}

configure_ssl() {
  if ! require_cmd certbot; then
    warn "Certbot not found. Installing..."
    apt-get install -y certbot python3-certbot-nginx >>"$LOG_FILE" 2>&1
  fi

  local domain
  echo -e "\n${MAGENTA}🔐 SSL Configuration (Let's Encrypt)${NC}"
  echo "-------------------------------------"
  ask_input "Enter your domain name (e.g., panel.example.com)" "" domain
  
  if [ -z "$domain" ]; then
    err "Domain name is required."
    return 1
  fi

  show_progress "Obtaining SSL certificate for $domain..."
  
  # Ensure Nginx is running
  systemctl start nginx || true
  
  # Run certbot
  if certbot --nginx -d "$domain" --non-interactive --agree-tos --register-unsafely-without-email --redirect; then
    ok "SSL Certificate installed successfully for $domain"
    echo -e "${GREEN}✅ HTTPS enabled! Access your panel at https://$domain${NC}"
  else
    err "Certbot failed. Check logs."
    echo "Check /var/log/letsencrypt/letsencrypt.log for details."
    return 1
  fi
}

advanced_tools() {
  local tool_opt
  
  echo -e "\n${MAGENTA}🛠️  Advanced Tools${NC}"
  echo "1) 🚀 Enable TCP BBR"
  echo "2) 🛡️  Configure UFW Firewall"
  echo "3) 🔐 Configure SSL (Certbot)"
  echo "4) 🧹 Clean System Logs & Cache"
  echo "5) 🔙 Back to Main Menu"
  
  ask_input "Select a tool" "5" tool_opt
    
  case "${tool_opt:-}" in
    1) enable_bbr ;;
    2) configure_firewall ;;
    3) configure_ssl ;;
    4) 
       show_progress "🧹 Cleaning up..."
       apt-get clean >/dev/null 2>&1
       journalctl --vacuum-time=3d >/dev/null 2>&1
       rm -f /var/log/*.gz
       echo -e "${GREEN}✅ System cleaned.${NC}"
       pause
       ;;
    5|"") return 0 ;;
  esac
}

# ----------------------------
# Operations
# ----------------------------
install_panel() {
  show_header
  if ! ask_yesno "Ready to install the latest panel version?" "Y"; then
    return 0
  fi

  install_deps
  show_progress "Configuring system..."

  local ram_kb
  ram_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo || echo 0)"
  if [ "${ram_kb:-0}" -lt 500000 ]; then
    echo -e "${YELLOW}⚠️  Resource Warning: System RAM is below 500MB.${NC}"
    warn "RAM below 500MB."
    pause
  fi

  mkdir -p "$INSTALL_DIR"

  # Copy files to install dir if run elsewhere
  local script_dir
  script_dir="$(dirname "$(readlink -f "$0")")"
  if [ "$script_dir" != "$INSTALL_DIR" ]; then
    info "Copying files to $INSTALL_DIR"
    cp -r "$script_dir/"* "$INSTALL_DIR/" 2>/dev/null || true
  fi

  mkdir -p "$PANEL_DIR"
  cd "$PANEL_DIR"

  info "Setting up Python virtual environment..."
  if [ ! -d "venv" ]; then
    python3 -m venv venv >>"$LOG_FILE" 2>&1
  fi

  # shellcheck disable=SC1091
  source venv/bin/activate

  pip install --upgrade pip >>"$LOG_FILE" 2>&1
  if [ -f requirements.txt ]; then
    pip install -r requirements.txt >>"$LOG_FILE" 2>&1
  else
    warn "requirements.txt not found in $PANEL_DIR"
  fi

  local admin_user admin_pass
  ask_input "👤 Admin Username" "admin" admin_user
  ask_password "🔑 Admin Password" admin_pass

  [ -n "${admin_user:-}" ] || die "Admin username cannot be empty."
  [ -n "${admin_pass:-}" ] || die "Admin password cannot be empty."

  local admin_user_esc admin_pass_esc
  admin_user_esc="$(py_escape "$admin_user")"
  admin_pass_esc="$(py_escape "$admin_pass")"

  info "Creating admin user..."
  python3 -c "from run import create_admin; create_admin('${admin_user_esc}', '${admin_pass_esc}')" >>"$LOG_FILE" 2>&1

  info "Configuring Nginx (port ${NGINX_PORT})..."
  cat >"/etc/nginx/sites-available/${NGINX_SITE_NAME}" <<EOF
server {
    listen ${NGINX_PORT} default_server;
    server_name _;
    location / {
        proxy_pass http://${GUNICORN_BIND};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
EOF

  ln -sf "/etc/nginx/sites-available/${NGINX_SITE_NAME}" "/etc/nginx/sites-enabled/${NGINX_SITE_NAME}"
  rm -f /etc/nginx/sites-enabled/default || true
  nginx -t >>"$LOG_FILE" 2>&1 || die "Nginx config test failed. Check $LOG_FILE"
  systemctl restart nginx
  ok "Nginx configured."

  info "Creating systemd service: ${SERVICE_NAME}"
  cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=HoseinProxy Panel
After=network.target docker.service

[Service]
User=root
WorkingDirectory=${PANEL_DIR}
Environment="PATH=${PANEL_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${PANEL_DIR}/venv/bin/gunicorn -w ${GUNICORN_WORKERS} -b ${GUNICORN_BIND} "run:app"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}" >/dev/null 2>&1
  systemctl restart "${SERVICE_NAME}"

  info "Setting up Log Rotation..."
  cat >"/etc/logrotate.d/${SERVICE_NAME}" <<EOF
$LOG_FILE {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 root root
}
EOF
  ok "Log rotation configured."

  local ip
  ip="$(get_public_ip)"
  
  echo -e "\n${GREEN}✅ Installation Complete!${NC}"
  echo "-------------------------------------"
  echo -e "🌐 Panel URL: http://${ip}:${NGINX_PORT}"
  echo -e "👤 Username: ${admin_user}"
  echo -e "📄 Logs: ${LOG_FILE}"
  
  if ask_yesno "Do you want to configure SSL (HTTPS) now?" "Y"; then
    configure_ssl
  fi
  
  pause
  ok "Installation finished."
}

update_panel() {
  show_progress "♻️ Checking Git repository..."
  cd "$INSTALL_DIR" || die "Install dir not found: $INSTALL_DIR"

  require_cmd git || die "git not installed."

  git fetch >>"$LOG_FILE" 2>&1

  local local_rev remote_rev
  local_rev="$(git rev-parse @)"
  remote_rev="$(git rev-parse @{u} 2>/dev/null || true)"

  if [ -z "$remote_rev" ]; then
    warn "No upstream branch configured. Running git pull anyway."
    git pull >>"$LOG_FILE" 2>&1 || die "git pull failed."
    systemctl restart "$SERVICE_NAME" || true
    ok "Updated."
    return 0
  fi

  if [ "$local_rev" = "$remote_rev" ] && [ "${1:-}" != "force" ]; then
    echo -e "${GREEN}✅ Your system is already up to date.${NC}"
    pause
    ok "Already up to date."
    return 0
  fi

  if [ "${1:-}" = "force" ] || ask_yesno "A new version is available. Update now?" "Y"; then
    info "Updating..."
    git reset --hard >>"$LOG_FILE" 2>&1
    git pull >>"$LOG_FILE" 2>&1
    systemctl restart "$SERVICE_NAME" || true
    if [ "${1:-}" != "force" ]; then
        echo -e "${GREEN}✅ Update completed successfully.${NC}"
        pause
    fi
    ok "Update completed."
  fi
}

uninstall_panel() {
  echo -e "${RED}${BOLD}⚠️  DANGER ZONE ⚠️${NC}"
  echo -e "You are about to perform a ${RED}FULL UNINSTALLATION${NC}."
  echo "This action will:"
  echo " 1. Stop and delete the Control Panel service."
  echo " 2. Stop and remove ALL created Proxy containers (Docker)."
  echo " 3. Delete Nginx configurations and SSL certificates."
  echo " 4. WIPE the installation directory ($INSTALL_DIR) and logs."
  echo ""
  
  if ! ask_yesno "Are you absolutely sure you want to proceed?" "N"; then
    return 0
  fi

  show_progress "Stopping services..."
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
  
  # Docker Cleanup
  if command -v docker >/dev/null 2>&1; then
    show_progress "Removing proxies (Docker)..."
    # Stop and remove containers created by proxy.sh (mtproto_PORT)
    # Using specific filter to avoid deleting other unrelated containers
    docker ps -a --filter "name=mtproto_" -q | xargs -r docker rm -f >/dev/null 2>&1 || true
    
    # If there is a compose file in install dir
    if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
       docker compose -f "$INSTALL_DIR/docker-compose.yml" down >/dev/null 2>&1 || true
    fi
  fi

  show_progress "Removing system configurations..."
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  rm -f "/etc/logrotate.d/${SERVICE_NAME}"
  systemctl daemon-reload

  rm -f "/etc/nginx/sites-enabled/${NGINX_SITE_NAME}" || true
  rm -f "/etc/nginx/sites-available/${NGINX_SITE_NAME}" || true
  systemctl restart nginx || true

  show_progress "Cleaning up files..."
  rm -f "$LOG_FILE"
  rm -f "${LOG_FILE}.*" 2>/dev/null || true

  # Change directory to home before deleting INSTALL_DIR to avoid "No such file or directory" errors
  cd "$HOME" || cd /

  if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
  fi

  echo -e "${GREEN}✅ Full uninstallation completed.${NC}"
  echo -e "${YELLOW}ℹ️  Returned to: $(pwd)${NC}"
  
  # Exit script since it might be deleted
  exit 0
}

backup_panel() {
  mkdir -p "$BACKUP_DIR"
  local file
  file="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M).tar.gz"

  show_progress "💾 Creating backup..."
  tar -czf "$file" -C "$INSTALL_DIR" --exclude='venv' --exclude='__pycache__' panel >>"$LOG_FILE" 2>&1

  echo -e "${GREEN}✅ Backup created: ${file}${NC}"
  pause
  ok "Backup: $file"
}

restore_panel() {
  local file
  ask_input "Backup file path" "$BACKUP_DIR/" file

  if [ ! -f "${file:-}" ]; then
    echo -e "${RED}❌ File not found.${NC}"
    pause
    return 1
  fi

  show_progress "📦 Restoring backup..."
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  tar -xzf "$file" -C "$INSTALL_DIR" >>"$LOG_FILE" 2>&1
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true

  echo -e "${GREEN}✅ Backup restored successfully.${NC}"
  pause
  ok "Restored from $file"
}

schedule_updates() {
  local cmd
  cmd="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"

  if ask_yesno "Enable daily auto-update at 03:00?" "Y"; then
    (crontab -l 2>/dev/null | grep -v "update_silent" || true; echo "$cmd") | crontab -
    echo -e "${GREEN}✅ Auto-update enabled.${NC}"
    pause
    ok "Auto-update enabled."
  else
    (crontab -l 2>/dev/null | grep -v "update_silent" || true) | crontab -
    echo -e "${YELLOW}⛔ Auto-update disabled.${NC}"
    pause
    ok "Auto-update disabled."
  fi
}

restart_service() {
  show_progress "🔄 Restarting service..."
  systemctl restart "$SERVICE_NAME" >>"$LOG_FILE" 2>&1 || true
  echo -e "${GREEN}✅ Service restarted.${NC}"
  pause
  ok "Service restarted."
}

view_logs() {
  clear
  echo -e "${CYAN}📜 Latest Logs (Press q to exit)${NC}"
  tail -n 100 "$LOG_FILE" | less +G
}

# ----------------------------
# Menu
# ----------------------------
show_menu() {
  show_header
  get_system_stats

  echo -e "📊 ${BOLD}Server Dashboard${NC}"
  echo "──────────────────────────────────────────────────────"
  echo -e "▫️ Service:    ${STATUS_PLAIN}"
  echo -e "▫️ IP Address: ${IP}"
  echo -e "▫️ Resources:  CPU: ${CPU} | RAM: ${RAM}"
  echo -e "▫️ Disk:       ${DISK} | Uptime: ${UPTIME}"
  echo -e "▫️ TCP BBR:    ${BBR_STATUS}"
  echo "──────────────────────────────────────────────────────"
  
  echo -e "👇 Select an operation:"
  echo " 1) 🚀 Install Panel"
  echo " 2) ♻️  Update Panel"
  echo " 3) 🗑️  Uninstall Panel"
  echo " 4) 💾 Backup Data"
  echo " 5) 📦 Restore Data"
  echo " 6) ⏰ Auto-Update Config"
  echo " 7) 🔄 Restart Service"
  echo " 8) 📜 View Logs"
  echo " 9) 🛠️  Advanced Tools"
  echo " 0) 🚪 Exit"
  echo ""

  local option
  ask_input "Choose an option" "" option

  case "${option:-}" in
    1) install_panel ;;
    2) update_panel ;;
    3) uninstall_panel ;;
    4) backup_panel ;;
    5) restore_panel ;;
    6) schedule_updates ;;
    7) restart_service ;;
    8) view_logs ;;
    9) advanced_tools ;;
    0|"") exit 0 ;;
    *) echo -e "${RED}Invalid option.${NC}"; sleep 1 ;;
  esac
}

# ----------------------------
# Entry Point
# ----------------------------
check_root

if [ "${1:-}" = "update_silent" ]; then
  update_panel force
  exit 0
fi

while true; do
  show_menu
done
