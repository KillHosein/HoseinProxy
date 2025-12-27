#!/usr/bin/env bash
# HoseinProxy Smart Manager
# Version: 7.0 (Professional Edition)
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

# Whiptail gauge wrapper
show_progress() {
  local message="$1"
  (
    local p=0
    while [ "$p" -le 100 ]; do
      echo "$p"
      sleep 0.03
      p=$((p + 2))
    done
  ) | whiptail --gauge "$message" 6 70 0
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || return 1
}

# ----------------------------
# UI
# ----------------------------
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
  echo -e "${CYAN}${BOLD}       💎 ${APP_TITLE} - v7.0 (Professional) 💎${NC}"
  echo -e "${BLUE}       ==================================================${NC}"
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
# Operations
# ----------------------------
install_panel() {
  show_header
  if ! whiptail --title "🚀 Install Panel" --yesno "Ready to install the latest panel version?" 10 70; then
    return 0
  fi

  install_deps
  show_progress "Configuring system..."

  local ram_kb
  ram_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo || echo 0)"
  if [ "${ram_kb:-0}" -lt 500000 ]; then
    whiptail --title "⚠️ Resource Warning" --msgbox "System RAM is below 500MB.\nPanel may run slowly." 10 70
    warn "RAM below 500MB."
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
  admin_user="$(whiptail --inputbox "👤 Admin Username:" 10 70 "admin" 3>&1 1>&2 2>&3 || true)"
  admin_pass="$(whiptail --passwordbox "🔑 Admin Password:" 10 70 3>&1 1>&2 2>&3 || true)"

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

  local ip
  ip="$(get_public_ip)"
  whiptail --title "✅ Installation Complete" --msgbox \
"Panel installed successfully!

🌐 Panel URL: http://${ip}:${NGINX_PORT}
👤 Username: ${admin_user}

Logs: ${LOG_FILE}" 13 72

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
    whiptail --title "✅ Up to date" --msgbox "Your system is already up to date." 10 70
    ok "Already up to date."
    return 0
  fi

  if [ "${1:-}" = "force" ] || whiptail --title "♻️ Update Available" --yesno "A new version is available. Update now?" 10 70; then
    info "Updating..."
    git reset --hard >>"$LOG_FILE" 2>&1
    git pull >>"$LOG_FILE" 2>&1
    systemctl restart "$SERVICE_NAME" || true
    [ "${1:-}" = "force" ] || whiptail --title "✅ Success" --msgbox "Update completed successfully." 10 70
    ok "Update completed."
  fi
}

uninstall_panel() {
  if ! whiptail --title "🗑️ Uninstall Panel" --yesno "WARNING: All panel data will be deleted.\nContinue?" 10 70; then
    return 0
  fi

  show_progress "Removing components..."
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload

  rm -f "/etc/nginx/sites-enabled/${NGINX_SITE_NAME}" || true
  rm -f "/etc/nginx/sites-available/${NGINX_SITE_NAME}" || true
  systemctl restart nginx || true

  rm -rf "$INSTALL_DIR"
  whiptail --title "✅ Done" --msgbox "Panel has been removed." 10 70
  ok "Uninstalled."
}

backup_panel() {
  mkdir -p "$BACKUP_DIR"
  local file
  file="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M).tar.gz"

  show_progress "💾 Creating backup..."
  tar -czf "$file" -C "$INSTALL_DIR" --exclude='venv' --exclude='__pycache__' panel >>"$LOG_FILE" 2>&1

  whiptail --title "✅ Backup Created" --msgbox "Backup saved to:\n${file}" 10 70
  ok "Backup: $file"
}

restore_panel() {
  local file
  file="$(whiptail --inputbox "Backup file path:" 10 70 "$BACKUP_DIR/" 3>&1 1>&2 2>&3 || true)"

  if [ ! -f "${file:-}" ]; then
    whiptail --title "❌ Error" --msgbox "File not found." 10 70
    return 1
  fi

  show_progress "📦 Restoring backup..."
  systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  tar -xzf "$file" -C "$INSTALL_DIR" >>"$LOG_FILE" 2>&1
  systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true

  whiptail --title "✅ Restore Complete" --msgbox "Backup restored successfully." 10 70
  ok "Restored from $file"
}

schedule_updates() {
  local cmd
  cmd="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"

  if whiptail --title "⏰ Auto-Update" --yesno "Enable daily auto-update at 03:00?" 10 70; then
    (crontab -l 2>/dev/null | grep -v "update_silent" || true; echo "$cmd") | crontab -
    whiptail --msgbox "✅ Auto-update enabled." 10 70
    ok "Auto-update enabled."
  else
    (crontab -l 2>/dev/null | grep -v "update_silent" || true) | crontab -
    whiptail --msgbox "⛔ Auto-update disabled." 10 70
    ok "Auto-update disabled."
  fi
}

restart_service() {
  show_progress "🔄 Restarting service..."
  systemctl restart "$SERVICE_NAME" >>"$LOG_FILE" 2>&1 || true
  whiptail --msgbox "✅ Service restarted." 10 70
  ok "Service restarted."
}

view_logs() {
  tail -n 80 "$LOG_FILE" > /tmp/hoseinproxy_manager_tail.log 2>/dev/null || true
  whiptail --title "📜 Latest Logs" --textbox /tmp/hoseinproxy_manager_tail.log 22 90
}

# ----------------------------
# Menu
# ----------------------------
show_menu() {
  show_header
  get_system_stats

  local menu_text
  menu_text="📊 Server Dashboard\n"
  menu_text+="──────────────────────────────\n"
  menu_text+="▫️ Service:    ${STATUS_PLAIN}\n"
  menu_text+="▫️ IP Address: ${IP}\n"
  menu_text+="▫️ Resources:  CPU: ${CPU} | RAM: ${RAM}\n"
  menu_text+="▫️ Disk:       ${DISK} | Uptime: ${UPTIME}\n"
  menu_text+="\n👇 Select an operation:"

  local option
  option="$(whiptail --title "$APP_TITLE" --menu "$menu_text" 22 80 10 \
    "1" "🚀 Install Panel" \
    "2" "♻️  Update Panel" \
    "3" "🗑️  Uninstall Panel" \
    "4" "💾 Backup Data" \
    "5" "📦 Restore Data" \
    "6" "⏰ Auto-Update Config" \
    "7" "🔄 Restart Service" \
    "8" "📜 View Logs" \
    "0" "🚪 Exit" 3>&1 1>&2 2>&3 || true)"

  case "${option:-}" in
    1) install_panel ;;
    2) update_panel ;;
    3) uninstall_panel ;;
    4) backup_panel ;;
    5) restore_panel ;;
    6) schedule_updates ;;
    7) restart_service ;;
    8) view_logs ;;
    0|"") exit 0 ;;
  esac
}

# ----------------------------
# Entry Point
# ----------------------------
check_root
ensure_whiptail

if [ "${1:-}" = "update_silent" ]; then
  update_panel force
  exit 0
fi

while true; do
  show_menu
done
