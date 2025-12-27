#!/bin/bash

# HoseinProxy Management Script
# Version: 5.0 (Ultimate Persian Edition)
# By: Gemini AI

# تنظیمات زبان برای نمایش صحیح کاراکترهای فارسی
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

# --- تنظیمات ---
LOG_FILE="/var/log/hoseinproxy_manager.log"
INSTALL_DIR="/root/HoseinProxy"
PANEL_DIR="$INSTALL_DIR/panel"
SERVICE_NAME="hoseinproxy"
BACKUP_DIR="/root/backups"

# --- رنگ‌ها ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- توابع کمکی ---

# نمایش لوگو به صورت گرافیکی
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
    echo -e "${PURPLE}${BOLD}       مدیریت حرفه‌ای پنل حسین‌پراکسی - نسخه ۵.۰${NC}"
    echo -e "${BLUE}       -------------------------------------------${NC}"
    echo ""
}

# ثبت لاگ
log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# نمایش نوار پیشرفت گرافیکی
show_progress() {
    local -i percent=0;
    local message="$1"
    (
        while [ $percent -le 100 ]; do
            echo $percent
            sleep 0.05
            percent=$((percent + 2))
        done
    ) | whiptail --gauge "$message" 6 60 0
}

# بررسی دسترسی روت
check_root() {
    if [[ $EUID -ne 0 ]]; then
       echo -e "${RED}[خطا] این اسکریپت باید با دسترسی کاربر ریشه‌ (Root) اجرا شود.${NC}"
       exit 1
    fi
}

# دریافت وضعیت سیستم برای نمایش در منو
get_system_status() {
    # وضعیت سرویس
    if systemctl is-active --quiet $SERVICE_NAME; then
        STATUS="${GREEN}فعال (Running)${NC}"
    else
        STATUS="${RED}غیرفعال (Stopped)${NC}"
    fi
    
    # دریافت آی‌پی و وضعیت منابع
    IP=$(curl -s -4 ifconfig.me --connect-timeout 2 || echo "نامشخص")
    
    # محاسبه مصرف رم و سی‌پی‌یو
    if command -v bc >/dev/null 2>&1; then
        RAM_USAGE=$(free -m | awk '/Mem:/ { printf("%.1f%%", $3/$2*100) }')
        CPU_LOAD=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1"%"}' || echo "N/A")
    else
        RAM_USAGE="N/A"
        CPU_LOAD="N/A"
    fi
    
    echo -e " ⚡ وضعیت سرویس: $STATUS"
    echo -e " 🌐 آی‌پی سرور:  ${YELLOW}$IP${NC}"
    echo -e " 📊 مصرف منابع:  رم: ${CYAN}$RAM_USAGE${NC} | پردازنده: ${CYAN}$CPU_LOAD${NC}"
    echo -e " -------------------------------------------"
}

# نصب پیش‌نیازها
install_dependencies() {
    echo -e "${BLUE}[INFO]${NC} در حال بروزرسانی مخازن و نصب پیش‌نیازها..."
    apt-get update -y >> "$LOG_FILE" 2>&1
    
    PACKAGES="python3 python3-pip python3-venv docker.io curl nginx git whiptail bc"
    apt-get install -y $PACKAGES >> "$LOG_FILE" 2>&1
    
    systemctl enable docker >> "$LOG_FILE" 2>&1
    systemctl start docker >> "$LOG_FILE" 2>&1
}

# --- ۱. نصب پنل ---

install_panel() {
    show_logo
    if (whiptail --title "نصب پنل" --yesno "آیا برای نصب نسخه جدید پنل آماده هستید؟" 10 60); then
        
        show_progress "در حال آماده‌سازی سیستم..."
        install_dependencies
        
        # بررسی حداقل رم
        RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        if [ $RAM_KB -lt 500000 ]; then
             whiptail --title "هشدار عملکرد" --msgbox "رم سیستم کمتر از ۵۰۰ مگابایت است. ممکن است پنل با کندی مواجه شود." 10 60
        fi

        mkdir -p "$INSTALL_DIR"
        SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
        if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
            cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/"
        fi
        
        cd "$PANEL_DIR" || { echo "Directory not found"; exit 1; }
        
        # راه‌اندازی محیط مجازی پایتون
        if [ ! -d "venv" ]; then
            python3 -m venv venv
        fi
        
        source venv/bin/activate
        pip install --upgrade pip >> "$LOG_FILE" 2>&1
        
        echo -e "${BLUE}[INFO]${NC} در حال نصب کتابخانه‌های پایتون..."
        pip install -r requirements.txt >> "$LOG_FILE" 2>&1
        
        # دریافت اطلاعات ادمین
        ADMIN_USER=$(whiptail --inputbox "نام کاربری ادمین را وارد کنید:" 10 60 3>&1 1>&2 2>&3)
        if [ -z "$ADMIN_USER" ]; then ADMIN_USER="admin"; fi
        
        ADMIN_PASS=$(whiptail --passwordbox "رمز عبور ادمین را وارد کنید:" 10 60 3>&1 1>&2 2>&3)
        
        # ساخت دیتابیس و ادمین
        python3 -c "from run import create_admin; create_admin('$ADMIN_USER', '$ADMIN_PASS')" >> "$LOG_FILE" 2>&1
        
        # تنظیمات Nginx
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
        
        # تنظیمات سرویس Systemd
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
        
        show_progress "در حال نهایی‌سازی نصب..."
        
        IP=$(curl -s -4 ifconfig.me)
        whiptail --title "نصب موفقیت‌آمیز" --msgbox "نصب با موفقیت انجام شد!\n\n🌐 آدرس پنل: http://$IP:1111\n👤 نام کاربری: $ADMIN_USER" 12 60
    else
        echo "نصب لغو شد."
    fi
}

# --- ۲. بروزرسانی ---

update_panel() {
    show_progress "در حال بررسی بروزرسانی‌ها..."
    cd "$INSTALL_DIR" || exit
    git fetch
    
    LOCAL=$(git rev-parse @)
    REMOTE=$(git rev-parse @{u})
    
    if [ "$LOCAL" = "$REMOTE" ] && [ "$1" != "force" ]; then
        whiptail --title "وضعیت بروزرسانی" --msgbox "سیستم شما بروز است و نیازی به آپدیت ندارد." 10 60
    else
        if [ "$1" == "force" ] || (whiptail --title "بروزرسانی موجود است" --yesno "نسخه جدید پیدا شد. آیا مایل به آپدیت هستید؟" 10 60); then
            git reset --hard
            git pull >> "$LOG_FILE" 2>&1
            
            cd "$PANEL_DIR" || exit
            if [ -d "venv" ]; then
                source venv/bin/activate
                pip install -r requirements.txt >> "$LOG_FILE" 2>&1
            fi
            
            systemctl restart $SERVICE_NAME
            
            if [ "$1" != "force" ]; then
                whiptail --title "موفق" --msgbox "بروزرسانی با موفقیت انجام شد." 10 60
            fi
        fi
    fi
}

# --- ۳. حذف پنل ---

uninstall_panel() {
    if (whiptail --title "حذف پنل" --yesno "هشدار مهم:\nتمام اطلاعات پنل و دیتابیس حذف خواهد شد.\n\nآیا کاملاً مطمئن هستید؟" 12 60); then
        
        if (whiptail --title "بکاپ اضطراری" --yesno "آیا می‌خواهید قبل از حذف، یک بکاپ بگیرید؟" 10 60); then
             backup_panel
        fi
        
        show_progress "در حال حذف سرویس‌ها..."
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        
        rm -f /etc/nginx/sites-enabled/hoseinproxy
        systemctl restart nginx
        
        rm -rf "$INSTALL_DIR"
        
        whiptail --title "پایان" --msgbox "پنل به طور کامل از روی سرور حذف شد." 10 60
    fi
}

# --- ۴. پشتیبان‌گیری و بازیابی ---

backup_panel() {
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/hoseinproxy_backup_$TIMESTAMP.tar.gz"
    
    show_progress "در حال فشرده‌سازی اطلاعات..."
    
    tar -czf "$BACKUP_FILE" -C "$INSTALL_DIR" \
        --exclude='venv' \
        --exclude='__pycache__' \
        panel
    
    if [ $? -eq 0 ]; then
        whiptail --title "پشتیبان‌گیری" --msgbox "بکاپ با موفقیت ساخته شد:\n\n$BACKUP_FILE" 12 60
    else
        whiptail --title "خطا" --msgbox "ساخت بکاپ با خطا مواجه شد." 10 60
    fi
}

restore_panel() {
    BACKUP_FILE=$(whiptail --title "بازیابی" --inputbox "مسیر کامل فایل بکاپ را وارد کنید:" 10 60 "$BACKUP_DIR/" 3>&1 1>&2 2>&3)
    
    if [ -f "$BACKUP_FILE" ]; then
        show_progress "در حال بازگردانی اطلاعات..."
        systemctl stop $SERVICE_NAME
        tar -xzf "$BACKUP_FILE" -C "$INSTALL_DIR"
        systemctl restart $SERVICE_NAME
        whiptail --title "موفق" --msgbox "اطلاعات با موفقیت بازیابی شد." 10 60
    else
        whiptail --title "خطا" --msgbox "فایل بکاپ پیدا نشد!" 10 60
    fi
}

# --- ۵. ابزارها ---

schedule_updates() {
    CRON_CMD="0 3 * * * /bin/bash $INSTALL_DIR/manage.sh update_silent >> $LOG_FILE 2>&1"
    
    if (whiptail --title "زمان‌بندی آپدیت" --yesno "آیا می‌خواهید آپدیت خودکار روزانه (ساعت ۳ صبح) فعال شود؟" 10 60); then
        (crontab -l 2>/dev/null | grep -v "manage.sh update_silent"; echo "$CRON_CMD") | crontab -
        whiptail --title "موفق" --msgbox "آپدیت خودکار فعال شد." 10 60
    else
        crontab -l 2>/dev/null | grep -v "manage.sh update_silent" | crontab -
        whiptail --title "غیرفعال" --msgbox "آپدیت خودکار غیرفعال شد." 10 60
    fi
}

# --- حالت خاموش (برای آپدیت خودکار) ---
if [ "$1" == "update_silent" ]; then
    update_panel force
    exit 0
fi

# --- منوی اصلی ---

show_menu() {
    show_logo
    get_system_status
    echo ""
    
    OPTION=$(whiptail --title "مدیریت پنل حسین‌پراکسی" --menu "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:" 20 70 10 \
    "1" "نصب پنل (Install)" \
    "2" "بروزرسانی پنل (Update)" \
    "3" "حذف پنل (Uninstall)" \
    "4" "پشتیبان‌گیری (Backup)" \
    "5" "بازیابی اطلاعات (Restore)" \
    "6" "تنظیم آپدیت خودکار (Auto-Update)" \
    "7" "ریستارت سرویس (Restart)" \
    "8" "مشاهده لاگ‌ها (Logs)" \
    "0" "خروج (Exit)" 3>&1 1>&2 2>&3)
    
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
            show_progress "در حال راه‌اندازی مجدد سرویس..."
            systemctl restart $SERVICE_NAME
            whiptail --title "موفق" --msgbox "سرویس با موفقیت ریستارت شد." 10 60
            ;;
        8) 
            tail -n 50 "$LOG_FILE" > /tmp/logview
            whiptail --title "آخرین گزارشات سیستم" --textbox /tmp/logview 20 80
            rm /tmp/logview
            ;;
        0) exit 0 ;;
        esac
    else
        exit 0
    fi
}

# شروع برنامه
check_root
while true; do
    show_menu
done