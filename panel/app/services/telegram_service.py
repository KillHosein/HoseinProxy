import telebot
import time
import requests
import os
import psutil
import secrets
import docker
from datetime import datetime, timedelta
from telebot import types
from sqlalchemy import func, or_
from app.utils.helpers import (
    get_setting,
    set_setting,
    get_valid_bot_token,
    infer_proxy_type_from_secret,
    extract_tls_domain_from_ee_secret,
    parse_mtproxy_secret_input,
)
from app.models import Proxy, User, BlockedIP, Settings
from app.extensions import db
from app.services.docker_client import client as docker_client
from app.services.firewall_service import _apply_firewall_rule

_bot_instance = None
_user_states = {} # {chat_id: {'step': '...', 'data': {...}}}

def get_bot():
    global _bot_instance
    if _bot_instance:
        return _bot_instance
    token = get_valid_bot_token()
    if token:
        try:
            _bot_instance = telebot.TeleBot(token, threaded=False)
            return _bot_instance
        except:
            return None
    return None

def send_telegram_alert(message):
    try:
        bot_token = get_valid_bot_token()
        chat_id = get_setting('telegram_chat_id')
        if not bot_token or not chat_id:
            return
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

# --- Keyboards ---
def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📊 وضعیت سیستم", "🚀 مدیریت پروکسی")
    markup.add("🛡️ فایروال", "👥 مدیران")
    markup.add("⚙️ تنظیمات", "📦 بکاپ")
    markup.add("📜 لاگ سیستم")
    return markup

def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 بازگشت")
    return markup

def proxy_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 لیست پروکسی‌ها", "➕ افزودن پروکسی")
    markup.add("� جستجو", "� بازگشت")
    return markup

def firewall_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 لیست سیاه", "⛔ مسدود کردن IP")
    markup.add("🔓 آزاد کردن IP", "🔙 بازگشت")
    return markup

def users_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 لیست مدیران", "➕ افزودن مدیر")
    markup.add("🗑️ حذف مدیر", "🔙 بازگشت")
    return markup

# --- Helper Logic ---
def is_admin(chat_id, app):
    with app.app_context():
        admin_id = get_setting('telegram_chat_id')
        return str(chat_id) == str(admin_id)

def set_state(chat_id, step, data=None):
    _user_states[chat_id] = {'step': step, 'data': data or {}}

def get_state(chat_id):
    return _user_states.get(chat_id)

def clear_state(chat_id):
    if chat_id in _user_states:
        del _user_states[chat_id]

def sync_proxies(app):
    """Restores/Syncs proxy containers from DB"""
    with app.app_context():
        try:
            proxies = Proxy.query.filter_by(status='running').all()
            created_count = 0
            for p in proxies:
                try:
                    # Check if container exists
                    exists = False
                    if docker_client and p.container_id:
                        try:
                            c = docker_client.containers.get(p.container_id)
                            if c.status == 'running':
                                exists = True
                            elif c.status != 'running':
                                c.start()
                                exists = True
                        except docker.errors.NotFound:
                            pass
                        except Exception:
                            pass
                    
                    if exists: continue

                    # Recreate
                    if docker_client:
                        ports_config = {'443/tcp': p.port}
                        if p.proxy_ip:
                             ports_config = {'443/tcp': (p.proxy_ip, p.port)}

                        c = docker_client.containers.run(
                            "telegrammessenger/proxy",
                            detach=True,
                            ports=ports_config,
                            environment={
                                'SECRET': p.secret,
                                'TAG': p.tag,
                                'WORKERS': p.workers
                            },
                            restart_policy={"Name": "always"},
                            name=f"mtproto_{p.port}"
                        )
                        p.container_id = c.id
                        created_count += 1
                except Exception as e:
                    print(f"Failed to sync proxy {p.port}: {e}")
            
            if created_count > 0:
                db.session.commit()
            return created_count
        except Exception as e:
            print(f"Sync Proxies Error: {e}")
            return 0

# --- Bot Runner ---
def run_telegram_bot(app):
    # Try to acquire a lock to ensure only one instance runs (for Gunicorn)
    try:
        import fcntl
        lock_file = '/tmp/hoseinproxy_bot.lock'
        fp = open(lock_file, 'w')
        try:
            fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            # Lock is held by another process
            print("[Telegram] Bot is already running in another worker. Skipping.")
            return
    except ImportError:
        # Not on Linux/Unix, skip locking (dev mode)
        pass
    except Exception as e:
        print(f"[Telegram] Lock Error: {e}")

    with app.app_context():
        token = get_valid_bot_token()
        if not token:
            return

        bot = telebot.TeleBot(token)
        
        # --- Command Handlers ---
        @bot.message_handler(commands=['start', 'help'])
        def send_welcome(message):
            chat_id = str(message.chat.id)
            with app.app_context():
                admin_id = get_setting('telegram_chat_id')
                
                if not admin_id:
                    # First time setup
                    set_setting('telegram_chat_id', chat_id)
                    bot.reply_to(message, "✅ تبریک! شما به عنوان مدیر ربات شناخته شدید.", reply_markup=main_menu_keyboard())
                    return

                if chat_id != admin_id:
                    bot.reply_to(message, "⛔ دسترسی غیرمجاز است.")
                    return
                
            clear_state(message.chat.id)
            bot.reply_to(message, f"👋 به پنل مدیریت پیشرفته HoseinProxy خوش آمدید.", reply_markup=main_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "🔙 بازگشت")
        def go_back(message):
            clear_state(message.chat.id)
            bot.reply_to(message, "منوی اصلی:", reply_markup=main_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📜 لاگ سیستم")
        def show_logs(message):
            if not is_admin(message.chat.id, app): return
            try:
                log_path = '/var/log/hoseinproxy_manager.log'
                if not os.path.exists(log_path):
                    bot.reply_to(message, "❌ فایل لاگ یافت نشد.")
                    return
                
                # Read last 15 lines
                lines = []
                with open(log_path, 'r') as f:
                    # Simple efficient tail
                    f.seek(0, 2)
                    fsize = f.tell()
                    f.seek(max(fsize - 4096, 0), 0)
                    lines = f.readlines()[-15:]
                
                log_content = "".join(lines)
                # Escape HTML
                log_content = log_content.replace("<", "&lt;").replace(">", "&gt;")
                
                msg = f"📜 <b>System Logs (Last 15 lines):</b>\n\n<pre>{log_content}</pre>"
                bot.reply_to(message, msg, parse_mode='HTML')
            except Exception as e:
                bot.reply_to(message, f"Error: {e}")

        # --- System Status ---
        @bot.message_handler(func=lambda m: m.text == "📊 وضعیت سیستم")
        def status_handler(message):
            if not is_admin(message.chat.id, app): return
            
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage('/').percent
                boot_time = datetime.fromtimestamp(psutil.boot_time())
                uptime = datetime.now() - boot_time
                uptime_str = str(uptime).split('.')[0]

                with app.app_context():
                    proxy_count = Proxy.query.count()
                    active_count = Proxy.query.filter_by(status='running').count()
                    total_upload = db.session.query(func.sum(Proxy.upload)).scalar() or 0
                    total_download = db.session.query(func.sum(Proxy.download)).scalar() or 0
                    
                    total_active_conns = db.session.query(func.sum(Proxy.active_connections)).scalar() or 0
                    total_up_speed = db.session.query(func.sum(Proxy.upload_rate_bps)).scalar() or 0
                    total_down_speed = db.session.query(func.sum(Proxy.download_rate_bps)).scalar() or 0
                
                def format_speed(bps):
                    if bps < 1024: return f"{bps} B/s"
                    elif bps < 1024**2: return f"{round(bps/1024, 1)} KB/s"
                    else: return f"{round(bps/(1024**2), 1)} MB/s"

                msg = (
                    f"📊 <b>System Status</b>\n\n"
                    f"⏳ Uptime: <code>{uptime_str}</code>\n"
                    f"💻 CPU: <code>{cpu}%</code>\n"
                    f"🧠 RAM: <code>{ram}%</code>\n"
                    f"💾 Disk: <code>{disk}%</code>\n\n"
                    f"🚀 Proxies: <code>{active_count}/{proxy_count}</code> Active\n"
                    f"⚡ Speed: ⬆️ {format_speed(total_up_speed)} | ⬇️ {format_speed(total_down_speed)}\n\n"
                    f"⬆️ Upload: <code>{round(total_upload / (1024**3), 2)} GB</code>\n"
                    f"⬇️ Download: <code>{round(total_download / (1024**3), 2)} GB</code>"
                )
                bot.reply_to(message, msg, parse_mode='HTML')
            except Exception as e:
                bot.reply_to(message, f"Error: {e}")

        # --- Proxy Management ---
        @bot.message_handler(func=lambda m: m.text == "🚀 مدیریت پروکسی")
        def proxy_menu(message):
            if not is_admin(message.chat.id, app): return
            bot.reply_to(message, "مدیریت پروکسی:", reply_markup=proxy_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📋 لیست پروکسی‌ها")
        def list_proxies(message):
            if not is_admin(message.chat.id, app): return
            set_state(message.chat.id, 'viewing_list', {'query': None})
            show_proxy_list_page(message.chat.id, 1)

        def show_proxy_list_page(chat_id, page, message_id=None):
            state = get_state(chat_id)
            query_filter = None
            if state and state.get('step') == 'viewing_list':
                query_filter = state.get('data', {}).get('query')

            with app.app_context():
                per_page = 10
                q = Proxy.query.order_by(Proxy.id.desc())
                
                if query_filter:
                    filters = []
                    if query_filter.isdigit():
                        filters.append(Proxy.port == int(query_filter))
                    filters.append(Proxy.tag.ilike(f"%{query_filter}%"))
                    filters.append(Proxy.name.ilike(f"%{query_filter}%"))
                    q = q.filter(or_(*filters))

                proxies = q.paginate(page=page, per_page=per_page, error_out=False)
                
                if not proxies.items and page == 1:
                    msg_text = "هیچ پروکسی یافت نشد."
                    if message_id:
                        try:
                            bot.edit_message_text(msg_text, chat_id, message_id)
                        except:
                            bot.send_message(chat_id, msg_text)
                    else:
                        bot.send_message(chat_id, msg_text)
                    return

                markup = types.InlineKeyboardMarkup()
                for p in proxies.items:
                    status_icon = "🟢" if p.status == 'running' else "🔴"
                    btn_text = f"{status_icon} {p.port} | {p.name or p.tag or 'No Name'}"
                    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"p_{p.id}"))
                
                # Pagination Buttons
                nav_btns = []
                if proxies.has_prev:
                    nav_btns.append(types.InlineKeyboardButton("⬅️ قبلی", callback_data=f"list_page_{proxies.prev_num}"))
                
                nav_btns.append(types.InlineKeyboardButton(f"📄 {page}/{proxies.pages}", callback_data="noop"))
                
                if proxies.has_next:
                    nav_btns.append(types.InlineKeyboardButton("بعدی ➡️", callback_data=f"list_page_{proxies.next_num}"))
                
                markup.row(*nav_btns)
                
                text = f"📋 لیست پروکسی‌ها (صفحه {page}):"
                if query_filter:
                    text += f"\n🔍 فیلتر: {query_filter}"

                if message_id:
                    try:
                        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
                    except Exception as e:
                        # In case message content is same
                        pass
                else:
                    bot.send_message(chat_id, text, reply_markup=markup)

        @bot.message_handler(func=lambda m: m.text == "🔍 جستجو")
        def search_proxy_init(message):
            if not is_admin(message.chat.id, app): return
            set_state(message.chat.id, 'search_proxy')
            bot.reply_to(message, "🔍 لطفاً متن جستجو (پورت، نام یا تگ) را وارد کنید:", reply_markup=back_keyboard())

        @bot.message_handler(func=lambda m: m.text == "➕ افزودن پروکسی")
        def add_proxy_step1(message):
            if not is_admin(message.chat.id, app): return
            set_state(message.chat.id, 'add_proxy_port')
            bot.reply_to(message, "🔢 لطفاً <b>شماره پورت</b> را وارد کنید:\n(مثال: 443)", reply_markup=back_keyboard(), parse_mode='HTML')

        # --- Firewall Management ---
        @bot.message_handler(func=lambda m: m.text == "🛡️ فایروال")
        def firewall_menu(message):
            if not is_admin(message.chat.id, app): return
            bot.reply_to(message, "مدیریت فایروال:", reply_markup=firewall_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📋 لیست سیاه")
        def list_firewall(message):
            if not is_admin(message.chat.id, app): return
            with app.app_context():
                blocked = BlockedIP.query.all()
                if not blocked:
                    bot.reply_to(message, "هیچ آی‌پی مسدود نشده است.")
                    return
                msg = "🚫 <b>Blocked IPs:</b>\n\n"
                for b in blocked:
                    msg += f"• <code>{b.ip_address}</code> ({b.reason or '-'})\n"
                bot.reply_to(message, msg, parse_mode='HTML')

        @bot.message_handler(func=lambda m: m.text == "⛔ مسدود کردن IP")
        def block_ip_step1(message):
            if not is_admin(message.chat.id, app): return
            set_state(message.chat.id, 'block_ip_addr')
            bot.reply_to(message, "🚫 لطفاً <b>آی‌پی</b> مورد نظر برای مسدودسازی را وارد کنید:", reply_markup=back_keyboard(), parse_mode='HTML')

        @bot.message_handler(func=lambda m: m.text == "🔓 آزاد کردن IP")
        def unblock_ip_step1(message):
            if not is_admin(message.chat.id, app): return
            set_state(message.chat.id, 'unblock_ip_addr')
            bot.reply_to(message, "🔓 لطفاً <b>آی‌پی</b> مورد نظر برای آزادسازی را وارد کنید:", reply_markup=back_keyboard(), parse_mode='HTML')

        # --- User Management ---
        @bot.message_handler(func=lambda m: m.text == "👥 مدیران")
        def users_menu(message):
            if not is_admin(message.chat.id, app): return
            bot.reply_to(message, "مدیریت کاربران:", reply_markup=users_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📋 لیست مدیران")
        def list_users(message):
            if not is_admin(message.chat.id, app): return
            with app.app_context():
                users = User.query.all()
                msg = "👤 <b>Admins:</b>\n\n"
                for u in users:
                    msg += f"• {u.username}\n"
                bot.reply_to(message, msg, parse_mode='HTML')

        @bot.message_handler(func=lambda m: m.text == "➕ افزودن مدیر")
        def add_user_step1(message):
            if not is_admin(message.chat.id, app): return
            set_state(message.chat.id, 'add_user_name')
            bot.reply_to(message, "👤 نام کاربری جدید را وارد کنید:", reply_markup=back_keyboard())

        @bot.message_handler(func=lambda m: m.text == "🗑️ حذف مدیر")
        def delete_user_step1(message):
            if not is_admin(message.chat.id, app): return
            
            with app.app_context():
                users = User.query.all()
                if not users:
                    bot.reply_to(message, "❌ کاربری یافت نشد.")
                    return
                
                markup = types.InlineKeyboardMarkup()
                for u in users:
                    # Don't allow deleting self? Assuming current chat_id is mapped to a user?
                    # But telegram_chat_id is in Settings, not User model directly linked often.
                    # Just list all.
                    markup.add(types.InlineKeyboardButton(f"❌ {u.username}", callback_data=f"deluser_{u.id}"))
                
                markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_users"))
                bot.reply_to(message, "👤 کاربری که می‌خواهید حذف کنید را انتخاب نمایید:", reply_markup=markup)

        # --- Settings ---
        @bot.message_handler(func=lambda m: m.text == "⚙️ تنظیمات")
        def settings_menu(message):
            if not is_admin(message.chat.id, app): return
            msg = "⚙️ <b>تنظیمات</b>\n\nهم‌اکنون فقط از طریق پنل وب قابل دسترسی است."
            bot.reply_to(message, msg, parse_mode='HTML')

        # --- Backup & Restore ---
        @bot.message_handler(func=lambda m: m.text == "📦 بکاپ")
        def backup_menu(message):
            if not is_admin(message.chat.id, app): return
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📥 دانلود بکاپ", callback_data="backup_download"),
                       types.InlineKeyboardButton("📤 بازیابی (Restore)", callback_data="backup_restore"))
            bot.reply_to(message, "📦 <b>مدیریت پشتیبان‌گیری</b>\n\nلطفاً یک گزینه را انتخاب کنید:\n\n• <b>دانلود بکاپ:</b> دریافت فایل کامل اطلاعات.\n• <b>بازیابی:</b> آپلود فایل بکاپ جهت بازگردانی اطلاعات.", reply_markup=markup, parse_mode='HTML')

        @bot.callback_query_handler(func=lambda call: call.data == "backup_download")
        def do_backup_callback(call):
            if not is_admin(call.message.chat.id, app): return
            wait_msg = bot.send_message(call.message.chat.id, "⏳ در حال تهیه نسخه پشتیبان... لطفاً صبر کنید.")
            try:
                from app.services.backup_service import BackupService
                
                with app.app_context():
                    # Initialize Service
                    # telegram_service.py is in panel/app/services/
                    # we need panel/ (root of panel app)
                    # panel/app/services/../../ -> panel/
                    panel_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    service = BackupService(panel_dir)
                    
                    file_path, filename = service.create_backup()
                    
                    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                        bot.edit_message_text("❌ فایل بکاپ ایجاد نشد یا خالی است.", call.message.chat.id, wait_msg.message_id)
                        return
                    
                    # Send file
                    with open(file_path, 'rb') as f:
                        bot.send_document(
                            call.message.chat.id, 
                            f, 
                            caption=f"📦 <b>نسخه پشتیبان کامل</b>\n📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n🔐 شامل دیتابیس، تنظیمات و کلیدهای امنیتی",
                            parse_mode='HTML',
                            timeout=120
                        )
                    
                    bot.delete_message(call.message.chat.id, wait_msg.message_id)
                    bot.answer_callback_query(call.id, "بکاپ ارسال شد.")
                    
            except Exception as e:
                bot.edit_message_text(f"❌ خطا در تهیه بکاپ:\n{str(e)}", call.message.chat.id, wait_msg.message_id)
                print(f"Backup Error: {e}")

        @bot.callback_query_handler(func=lambda call: call.data == "backup_restore")
        def ask_restore_callback(call):
             if not is_admin(call.message.chat.id, app): return
             set_state(call.message.chat.id, 'waiting_restore_file')
             bot.send_message(call.message.chat.id, "📤 لطفاً فایل بکاپ (.tar.gz) خود را ارسال کنید:", reply_markup=back_keyboard())
             bot.answer_callback_query(call.id)

        @bot.message_handler(content_types=['document'])
        def handle_restore_file(message):
            state = get_state(message.chat.id)
            if not state or state.get('step') != 'waiting_restore_file':
                return
            
            if not is_admin(message.chat.id, app): return
            
            wait_msg = bot.reply_to(message, "⏳ در حال دانلود و بررسی فایل...")
            
            temp_path = None
            try:
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                
                # Create temp file
                temp_path = os.path.join(os.getcwd(), 'restore_upload.tar.gz')
                
                with open(temp_path, 'wb') as new_file:
                    new_file.write(downloaded_file)
                
                import tarfile
                if not tarfile.is_tarfile(temp_path):
                    bot.edit_message_text("❌ فایل ارسال شده معتبر نیست (باید tar.gz باشد).", message.chat.id, wait_msg.message_id)
                    if os.path.exists(temp_path): os.remove(temp_path)
                    return

                # Restore using Service
                from app.services.backup_service import BackupService
                
                # Close DB connections before restore
                with app.app_context():
                     db.session.remove()
                     try:
                         db.engine.dispose()
                     except: pass
                
                panel_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                service = BackupService(panel_dir)
                
                service.restore_backup(temp_path)
                
                if os.path.exists(temp_path): os.remove(temp_path)
                
                bot.edit_message_text("✅ فایل‌ها جایگزین شدند. در حال همگام‌سازی پروکسی‌ها...", message.chat.id, wait_msg.message_id)
                
                # Sync Proxies
                synced = sync_proxies(app)
                
                bot.send_message(message.chat.id, f"✅ <b>بازیابی با موفقیت انجام شد!</b>\n\n🔄 دیتابیس و تنظیمات بازیابی شدند.\n🚀 تعداد {synced} پروکسی همگام‌سازی شدند.\n\n⚠️ سرویس به زودی ریستارت می‌شود...", parse_mode='HTML')
                clear_state(message.chat.id)
                
                # Restart Service after short delay to allow message sending
                def delayed_restart():
                    time.sleep(2)
                    service.restart_service()
                
                import threading
                threading.Thread(target=delayed_restart).start()
            
            except Exception as e:
                bot.edit_message_text(f"❌ خطا در بازیابی:\n{e}", message.chat.id, wait_msg.message_id)
                if temp_path and os.path.exists(temp_path): os.remove(temp_path)

        # --- State Handlers (Wizard Logic) ---
        @bot.message_handler(func=lambda m: get_state(m.chat.id) is not None)
        def state_handler(message):
            if not is_admin(message.chat.id, app): return
            state = get_state(message.chat.id)
            step = state['step']
            data = state['data']
            
            # --- Add Proxy Wizard ---
            if step == 'search_proxy':
                query = message.text.strip()
                set_state(message.chat.id, 'viewing_list', {'query': query})
                show_proxy_list_page(message.chat.id, 1)

            elif step == 'edit_proxy_tag':
                pid = data['id']
                tag = message.text.strip()
                if tag.lower() == 'none': tag = None
                with app.app_context():
                    p = Proxy.query.get(pid)
                    if p:
                        p.tag = tag
                        db.session.commit()
                        bot.reply_to(message, "✅ تگ ویرایش شد.", reply_markup=proxy_menu_keyboard())
                    else:
                        bot.reply_to(message, "❌ پروکسی یافت نشد.")
                clear_state(message.chat.id)

            elif step == 'edit_proxy_expiry':
                pid = data['id']
                try:
                    days = int(message.text.strip())
                    with app.app_context():
                        p = Proxy.query.get(pid)
                        if p:
                            if days > 0:
                                p.expiry_date = datetime.utcnow() + timedelta(days=days)
                            else:
                                p.expiry_date = None
                            db.session.commit()
                            bot.reply_to(message, "✅ زمان انقضا ویرایش شد.", reply_markup=proxy_menu_keyboard())
                        else:
                            bot.reply_to(message, "❌ پروکسی یافت نشد.")
                except ValueError:
                    bot.reply_to(message, "❌ لطفاً عدد وارد کنید.")
                    return
                clear_state(message.chat.id)

            elif step == 'edit_proxy_quota':
                pid = data['id']
                try:
                    gb = float(message.text.strip())
                    with app.app_context():
                        p = Proxy.query.get(pid)
                        if p:
                            if gb > 0:
                                p.quota_bytes = int(gb * 1024 * 1024 * 1024)
                            else:
                                p.quota_bytes = 0
                            db.session.commit()
                            bot.reply_to(message, "✅ حجم مجاز ویرایش شد.", reply_markup=proxy_menu_keyboard())
                        else:
                            bot.reply_to(message, "❌ پروکسی یافت نشد.")
                except ValueError:
                    bot.reply_to(message, "❌ لطفاً عدد معتبر وارد کنید.")
                    return
                clear_state(message.chat.id)

            elif step == 'add_proxy_port':
                try:
                    port = int(message.text)
                    with app.app_context():
                        if Proxy.query.filter_by(port=port).first():
                            bot.reply_to(message, "❌ این پورت قبلاً استفاده شده است. پورت دیگری وارد کنید:")
                            return
                    data['port'] = port
                    set_state(message.chat.id, 'add_proxy_secret', data)
                    bot.reply_to(message, "🔑 سکرت (Secret) را وارد کنید (یا بنویسید 'random'):")
                except ValueError:
                    bot.reply_to(message, "❌ لطفاً یک عدد صحیح وارد کنید.")

            elif step == 'add_proxy_secret':
                secret = message.text.strip()
                if secret.lower() == 'random':
                    secret = secrets.token_hex(16)
                data['secret'] = secret
                set_state(message.chat.id, 'add_proxy_tag', data)
                bot.reply_to(message, "🏷️ تگ (Tag) را وارد کنید (یا بنویسید 'none'):")

            elif step == 'add_proxy_tag':
                tag = message.text.strip()
                if tag.lower() == 'none': tag = None
                data['tag'] = tag
                
                set_state(message.chat.id, 'add_proxy_expiry', data)
                bot.reply_to(message, "⏳ اعتبار (روز) را وارد کنید (0 برای نامحدود):")

            elif step == 'add_proxy_expiry':
                try:
                    days = int(message.text.strip())
                    if days > 0:
                        data['expiry_days'] = days
                    else:
                        data['expiry_days'] = 0
                    
                    set_state(message.chat.id, 'add_proxy_quota', data)
                    bot.reply_to(message, "💾 حجم مجاز (GB) را وارد کنید (0 برای نامحدود):")
                except ValueError:
                    bot.reply_to(message, "❌ لطفاً یک عدد صحیح وارد کنید.")

            elif step == 'add_proxy_quota':
                try:
                    gb = float(message.text.strip())
                    data['quota_gb'] = gb
                except ValueError:
                    bot.reply_to(message, "❌ لطفاً یک عدد معتبر وارد کنید.")
                    return

                # Finalize Creation
                try:
                    with app.app_context():
                        if docker_client:
                            parsed = parse_mtproxy_secret_input(None, data.get('secret'))
                            ptype = parsed["proxy_type"]
                            tls_domain = parsed["tls_domain"]
                            container = docker_client.containers.run(
                                'telegrammessenger/proxy',
                                detach=True,
                                ports={'443/tcp': data['port']},
                                environment={
                                    'SECRET': parsed["base_secret"],
                                    'TAG': data['tag'],
                                    'WORKERS': 1
                                },
                                restart_policy={"Name": "always"},
                                name=f"mtproto_{data['port']}"
                            )
                            
                            expiry_date = None
                            if data.get('expiry_days', 0) > 0:
                                expiry_date = datetime.utcnow() + timedelta(days=data['expiry_days'])
                            
                            quota_bytes = 0
                            if data.get('quota_gb', 0) > 0:
                                quota_bytes = int(data['quota_gb'] * 1024 * 1024 * 1024)

                            p = Proxy(
                                port=data['port'],
                                secret=parsed["base_secret"],
                                proxy_type=ptype,
                                tls_domain=tls_domain,
                                tag=data['tag'],
                                workers=1,
                                container_id=container.id,
                                status="running",
                                expiry_date=expiry_date,
                                quota_bytes=quota_bytes
                            )
                            db.session.add(p)
                            db.session.commit()
                            bot.reply_to(message, f"✅ پروکسی با پورت {data['port']} ساخته شد.\n⏳ انقضا: {data['expiry_days'] or 'نامحدود'} روز\n💾 حجم: {data['quota_gb'] or 'نامحدود'} GB", reply_markup=proxy_menu_keyboard())
                        else:
                            bot.reply_to(message, "❌ خطا: داکر متصل نیست.")
                except Exception as e:
                    bot.reply_to(message, f"❌ خطا در ساخت: {e}")
                clear_state(message.chat.id)

            # --- Firewall Wizard ---
            elif step == 'block_ip_addr':
                ip = message.text.strip()
                with app.app_context():
                    if not BlockedIP.query.filter_by(ip_address=ip).first():
                        b = BlockedIP(ip_address=ip, reason="Telegram Bot")
                        db.session.add(b)
                        db.session.commit()
                        _apply_firewall_rule(ip, 'block')
                        bot.reply_to(message, f"⛔ آی‌پی {ip} مسدود شد.", reply_markup=firewall_menu_keyboard())
                    else:
                        bot.reply_to(message, "⚠️ این آی‌پی قبلاً مسدود شده است.", reply_markup=firewall_menu_keyboard())
                clear_state(message.chat.id)

            elif step == 'unblock_ip_addr':
                ip = message.text.strip()
                with app.app_context():
                    b = BlockedIP.query.filter_by(ip_address=ip).first()
                    if b:
                        db.session.delete(b)
                        db.session.commit()
                        _apply_firewall_rule(ip, 'unblock')
                        bot.reply_to(message, f"🔓 آی‌پی {ip} آزاد شد.", reply_markup=firewall_menu_keyboard())
                    else:
                        bot.reply_to(message, "⚠️ این آی‌پی در لیست سیاه نیست.", reply_markup=firewall_menu_keyboard())
                clear_state(message.chat.id)

            # --- User Wizard ---
            elif step == 'add_user_name':
                data['username'] = message.text.strip()
                set_state(message.chat.id, 'add_user_pass', data)
                bot.reply_to(message, "🔑 رمز عبور را وارد کنید:")

            elif step == 'add_user_pass':
                data['password'] = message.text.strip()
                with app.app_context():
                    if User.query.filter_by(username=data['username']).first():
                        bot.reply_to(message, "❌ این کاربر قبلاً وجود دارد.", reply_markup=users_menu_keyboard())
                    else:
                        u = User(username=data['username'])
                        u.set_password(data['password'])
                        db.session.add(u)
                        db.session.commit()
                        bot.reply_to(message, f"✅ مدیر {data['username']} اضافه شد.", reply_markup=users_menu_keyboard())
                clear_state(message.chat.id)

        @bot.message_handler(commands=['restart_panel'])
        def restart_panel_cmd(message):
            if not is_admin(message.chat.id, app): return
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ بله، ریستارت شود", callback_data="confirm_restart_panel"),
                       types.InlineKeyboardButton("❌ خیر", callback_data="noop"))
            bot.reply_to(message, "⚠️ <b>آیا از ریستارت کردن پنل اطمینان دارید؟</b>\nربات برای لحظاتی قطع خواهد شد.", reply_markup=markup, parse_mode='HTML')

        @bot.callback_query_handler(func=lambda call: call.data == "confirm_restart_panel")
        def do_restart_panel(call):
            if not is_admin(call.message.chat.id, app): return
            bot.edit_message_text("🔄 در حال ریستارت سرویس...", call.message.chat.id, call.message.message_id)
            import subprocess
            try:
                subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ خطا: {e}")

        # --- Callbacks ---
        @bot.callback_query_handler(func=lambda call: call.data.startswith('list_page_'))
        def list_page_callback(call):
            if not is_admin(call.message.chat.id, app): return
            try:
                page = int(call.data.split('_')[2])
                show_proxy_list_page(call.message.chat.id, page, call.message.message_id)
                bot.answer_callback_query(call.id)
            except Exception as e:
                print(f"Pagination error: {e}")

        @bot.callback_query_handler(func=lambda call: call.data == 'noop')
        def noop_callback(call):
            bot.answer_callback_query(call.id)

        @bot.callback_query_handler(func=lambda call: call.data.startswith('edit_'))
        def edit_proxy_menu(call):
            if not is_admin(call.message.chat.id, app): return
            try:
                pid = int(call.data.split('_')[1])
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🏷️ تگ", callback_data=f"edittag_{pid}"),
                           types.InlineKeyboardButton("⏳ انقضا", callback_data=f"editexp_{pid}"))
                markup.add(types.InlineKeyboardButton("💾 حجم", callback_data=f"editquota_{pid}"),
                           types.InlineKeyboardButton("🔑 سکرت", callback_data=f"newsec_{pid}"))
                markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"p_{pid}"))
                
                bot.edit_message_text("✏️ چه چیزی را می‌خواهید ویرایش کنید؟", call.message.chat.id, call.message.message_id, reply_markup=markup)
            except Exception as e:
                print(f"Edit Menu Error: {e}")

        @bot.callback_query_handler(func=lambda call: call.data.startswith(('edittag_', 'editexp_', 'editquota_', 'newsec_')))
        def edit_proxy_field(call):
            if not is_admin(call.message.chat.id, app): return
            action, pid = call.data.split('_')
            pid = int(pid)
            
            if action == 'newsec':
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ بله، تغییر سکرت", callback_data=f"confirmsec_{pid}"),
                           types.InlineKeyboardButton("❌ خیر", callback_data=f"edit_{pid}"))
                bot.edit_message_text("⚠️ <b>آیا از تغییر سکرت اطمینان دارید؟</b>\nکاربران فعلی قطع خواهند شد.", 
                                      call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
                return

            if action == 'edittag':
                set_state(call.message.chat.id, 'edit_proxy_tag', {'id': pid})
                bot.send_message(call.message.chat.id, "🏷️ تگ جدید را وارد کنید (یا 'none' برای حذف):", reply_markup=back_keyboard())
            elif action == 'editexp':
                set_state(call.message.chat.id, 'edit_proxy_expiry', {'id': pid})
                bot.send_message(call.message.chat.id, "⏳ تعداد روز اعتبار جدید را وارد کنید (0 برای نامحدود):", reply_markup=back_keyboard())
            elif action == 'editquota':
                set_state(call.message.chat.id, 'edit_proxy_quota', {'id': pid})
                bot.send_message(call.message.chat.id, "💾 حجم جدید (GB) را وارد کنید (0 برای نامحدود):", reply_markup=back_keyboard())
            
            bot.answer_callback_query(call.id)

        @bot.callback_query_handler(func=lambda call: call.data.startswith('confirmsec_'))
        def confirm_new_secret(call):
            if not is_admin(call.message.chat.id, app): return
            pid = int(call.data.split('_')[1])
            with app.app_context():
                p = Proxy.query.get(pid)
                if p:
                    new_secret = secrets.token_hex(16)
                    p.secret = new_secret
                    db.session.commit()
                    
                    # Restart container
                    try:
                        if docker_client and p.container_id:
                            container = docker_client.containers.get(p.container_id)
                            # Update env var - Docker API doesn't support update env easily without recreation or some tricks
                            # Easier: Just show new secret, but for it to apply, container needs recreation with new env.
                            # Standard proxy containers use SECRET env.
                            # Recreating is best.
                            
                            # Stop & Remove old
                            container.stop()
                            container.remove()
                            
                            # Recreate
                            parsed = parse_mtproxy_secret_input(None, new_secret)
                            new_container = docker_client.containers.run(
                                'telegrammessenger/proxy',
                                detach=True,
                                ports={'443/tcp': p.port},
                                environment={
                                    'SECRET': parsed["base_secret"],
                                    'TAG': p.tag,
                                    'WORKERS': p.workers
                                },
                                restart_policy={"Name": "always"},
                                name=f"mtproto_{p.port}"
                            )
                            p.container_id = new_container.id
                            p.status = 'running'
                            db.session.commit()
                            
                            bot.answer_callback_query(call.id, "سکرت جدید اعمال شد.")
                            bot.delete_message(call.message.chat.id, call.message.message_id)
                            # Go back to proxy detail
                            # Re-call detail logic? Or just done.
                        else:
                            bot.answer_callback_query(call.id, "خطا: داکر متصل نیست.")
                    except Exception as e:
                        bot.answer_callback_query(call.id, f"خطا در اعمال تغییرات: {e}")
                else:
                    bot.answer_callback_query(call.id, "پروکسی یافت نشد.")

        @bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
        def proxy_detail_callback(call):
            if not is_admin(call.message.chat.id, app): return
            try:
                proxy_id = int(call.data.split('_')[1])
                with app.app_context():
                    p = Proxy.query.get(proxy_id)
                    if not p:
                        bot.answer_callback_query(call.id, "پروکسی یافت نشد.")
                        return
                    
                    status_icon = "🟢" if p.status == 'running' else "🔴"
                    
                    expiry_str = "Unlimited"
                    if p.expiry_date:
                        remaining = (p.expiry_date - datetime.utcnow()).days
                        expiry_str = f"{remaining} days" if remaining > 0 else "Expired"
                        
                    # Usage calculation (Download only as requested)
                    used_gb = round(p.download / (1024**3), 2)
                    
                    quota_str = "Unlimited"
                    if p.quota_bytes and p.quota_bytes > 0:
                        limit_gb = round(p.quota_bytes / (1024**3), 2)
                        quota_str = f"{used_gb}/{limit_gb} GB"

                    msg = (
                        f"⚙️ <b>Proxy #{p.port}</b>\n"
                        f"Name: {p.name or '-'}\n"
                        f"Tag: {p.tag or '-'}\n"
                        f"Status: {status_icon} {p.status}\n"
                        f"⏳ Expiry: {expiry_str}\n"
                        f"💾 Usage: {quota_str}\n"
                        f"⬇️ Download: {round(p.download / (1024**2), 2)} MB\n"
                    )
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    if p.status == 'running':
                        markup.add(types.InlineKeyboardButton("🔴 توقف", callback_data=f"stop_{p.id}"),
                                   types.InlineKeyboardButton("🔄 ریستارت", callback_data=f"restart_{p.id}"))
                    else:
                        markup.add(types.InlineKeyboardButton("🟢 شروع", callback_data=f"start_{p.id}"))
                    
                    markup.add(types.InlineKeyboardButton("🔗 لینک اتصال", callback_data=f"link_{p.id}"),
                               types.InlineKeyboardButton("♻️ ریست مصرف", callback_data=f"reset_{p.id}"))
                    
                    markup.add(types.InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_{p.id}"),
                               types.InlineKeyboardButton("🗑️ حذف", callback_data=f"del_{p.id}"))

                    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_list"))
                    
                    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
            except Exception as e:
                print(f"Bot Callback Error: {e}")

        @bot.callback_query_handler(func=lambda call: call.data == "back_list")
        def back_list_callback(call):
            bot.delete_message(call.message.chat.id, call.message.message_id)
            # Re-send list (since editing to text from inline requires logic change in previous handler if we want to reuse)
            # Or just send text "Select from list" and re-call list_proxies logic logic
            # Simpler: just acknowledge
            bot.answer_callback_query(call.id, "منو را از کیبورد انتخاب کنید.")

        @bot.callback_query_handler(func=lambda call: call.data == "back_users")
        def back_users_callback(call):
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "منوی مدیریت کاربران")

        @bot.callback_query_handler(func=lambda call: call.data.startswith('deluser_'))
        def delete_user_callback(call):
            if not is_admin(call.message.chat.id, app): return
            uid = int(call.data.split('_')[1])
            with app.app_context():
                u = User.query.get(uid)
                if u:
                    if u.username == 'admin': # Protect main admin if named 'admin'
                         bot.answer_callback_query(call.id, "❌ امکان حذف کاربر اصلی وجود ندارد.")
                         return
                    db.session.delete(u)
                    db.session.commit()
                    bot.answer_callback_query(call.id, f"کاربر {u.username} حذف شد.")
                    # Refresh list
                    users = User.query.all()
                    markup = types.InlineKeyboardMarkup()
                    for u in users:
                        markup.add(types.InlineKeyboardButton(f"❌ {u.username}", callback_data=f"deluser_{u.id}"))
                    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_users"))
                    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
                else:
                    bot.answer_callback_query(call.id, "کاربر یافت نشد.")

        @bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
        def confirm_delete_proxy(call):
            if not is_admin(call.message.chat.id, app): return
            pid = int(call.data.split('_')[1])
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"confirmdel_{pid}"),
                       types.InlineKeyboardButton("❌ خیر، لغو", callback_data=f"p_{pid}"))
            bot.edit_message_text("⚠️ <b>آیا از حذف این پروکسی اطمینان دارید؟</b>\nاین عملیات غیرقابل بازگشت است.", 
                                  call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

        @bot.callback_query_handler(func=lambda call: call.data.startswith('confirmdel_'))
        def delete_proxy_confirmed(call):
            if not is_admin(call.message.chat.id, app): return
            pid = int(call.data.split('_')[1])
            with app.app_context():
                p = Proxy.query.get(pid)
                if p:
                    try:
                        if docker_client and p.container_id:
                            try:
                                container = docker_client.containers.get(p.container_id)
                                container.stop()
                                container.remove()
                            except: pass
                        db.session.delete(p)
                        db.session.commit()
                        bot.answer_callback_query(call.id, "پروکسی با موفقیت حذف شد.")
                        bot.delete_message(call.message.chat.id, call.message.message_id)
                        # Optional: Go back to list
                        show_proxy_list_page(call.message.chat.id, 1)
                    except Exception as e:
                        bot.answer_callback_query(call.id, f"خطا: {e}")
                else:
                    bot.answer_callback_query(call.id, "پروکسی یافت نشد.")

        @bot.callback_query_handler(func=lambda call: call.data.startswith(('stop_', 'start_', 'restart_', 'link_', 'reset_')))
        def action_callback(call):
            if not is_admin(call.message.chat.id, app): return
            action, pid = call.data.split('_')
            pid = int(pid)
            
            with app.app_context():
                p = Proxy.query.get(pid)
                if not p:
                    bot.answer_callback_query(call.id, "پروکسی یافت نشد.")
                    return

                if action == 'link':
                    server_ip = get_setting('server_ip') or 'YOUR_IP'
                    secret = p.secret
                    if p.tls_domain:
                        secret = f"ee{p.secret}{p.tls_domain.encode().hex()}"
                    link = f"https://t.me/proxy?server={server_ip}&port={p.port}&secret={secret}"
                    
                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={link}"
                    bot.send_photo(call.message.chat.id, qr_url, caption=f"🔗 <b>لینک اتصال:</b>\n\n<code>{link}</code>", parse_mode='HTML')
                    
                    bot.answer_callback_query(call.id, "لینک ارسال شد.")
                    return
                
                if action == 'reset':
                    p.upload = 0
                    p.download = 0
                    db.session.commit()
                    bot.answer_callback_query(call.id, "میزان مصرف ریست شد.")
                    # Refresh view
                    status_icon = "🟢" if p.status == 'running' else "🔴"
                    
                    expiry_str = "Unlimited"
                    if p.expiry_date:
                        remaining = (p.expiry_date - datetime.utcnow()).days
                        expiry_str = f"{remaining} days" if remaining > 0 else "Expired"
                        
                    # Usage calculation (Download only as requested)
                    used_gb = round(p.download / (1024**3), 2)
                    
                    quota_str = "Unlimited"
                    if p.quota_bytes and p.quota_bytes > 0:
                        limit_gb = round(p.quota_bytes / (1024**3), 2)
                        quota_str = f"{used_gb}/{limit_gb} GB"

                    msg = (
                        f"⚙️ <b>Proxy #{p.port}</b>\n"
                        f"Name: {p.name or '-'}\n"
                        f"Tag: {p.tag or '-'}\n"
                        f"Status: {status_icon} {p.status}\n"
                        f"⏳ Expiry: {expiry_str}\n"
                        f"💾 Usage: {quota_str}\n"
                        f"⬇️ Download: 0.0 MB\n"
                    )
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    if p.status == 'running':
                        markup.add(types.InlineKeyboardButton("🔴 توقف", callback_data=f"stop_{p.id}"),
                                   types.InlineKeyboardButton("🔄 ریستارت", callback_data=f"restart_{p.id}"))
                    else:
                        markup.add(types.InlineKeyboardButton("🟢 شروع", callback_data=f"start_{p.id}"))
                    
                    markup.add(types.InlineKeyboardButton("🔗 لینک اتصال", callback_data=f"link_{p.id}"),
                               types.InlineKeyboardButton("♻️ ریست مصرف", callback_data=f"reset_{p.id}"))
                    
                    markup.add(types.InlineKeyboardButton("🗑️ حذف", callback_data=f"del_{p.id}"),
                               types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_list"))
                    
                    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
                    return
                
                if action == 'del':
                    # Legacy fallback, though new handler catches confirmdel
                    try:
                        if docker_client and p.container_id:
                            try:
                                container = docker_client.containers.get(p.container_id)
                                container.stop()
                                container.remove()
                            except: pass
                        db.session.delete(p)
                        db.session.commit()
                        bot.answer_callback_query(call.id, "پروکسی حذف شد.")
                        bot.delete_message(call.message.chat.id, call.message.message_id)
                    except Exception as e:
                        bot.answer_callback_query(call.id, f"خطا: {e}")
                    return

                try:
                    if docker_client and p.container_id:
                        container = docker_client.containers.get(p.container_id)
                        if action == 'stop':
                            container.stop()
                            p.status = 'stopped'
                            bot.answer_callback_query(call.id, "پروکسی متوقف شد.")
                        elif action == 'start':
                            container.start()
                            p.status = 'running'
                            bot.answer_callback_query(call.id, "پروکسی روشن شد.")
                        elif action == 'restart':
                            container.restart()
                            p.status = 'running'
                            bot.answer_callback_query(call.id, "پروکسی ریستارت شد.")
                        
                        db.session.commit()
                        # Update the view
                        status_icon = "🟢" if p.status == 'running' else "🔴"
                        
                        expiry_str = "Unlimited"
                        if p.expiry_date:
                            remaining = (p.expiry_date - datetime.utcnow()).days
                            expiry_str = f"{remaining} days" if remaining > 0 else "Expired"
                            
                        # Usage calculation (Download only as requested)
                        used_gb = round(p.download / (1024**3), 2)

                        quota_str = "Unlimited"
                        if p.quota_bytes and p.quota_bytes > 0:
                            limit_gb = round(p.quota_bytes / (1024**3), 2)
                            quota_str = f"{used_gb}/{limit_gb} GB"

                        msg = (
                            f"⚙️ <b>Proxy #{p.port}</b>\n"
                            f"Name: {p.name or '-'}\n"
                            f"Tag: {p.tag or '-'}\n"
                            f"Status: {status_icon} {p.status}\n"
                            f"⏳ Expiry: {expiry_str}\n"
                            f"💾 Usage: {quota_str}\n"
                            f"⬇️ Download: {round(p.download / (1024**2), 2)} MB\n"
                        )
                        
                        markup = types.InlineKeyboardMarkup(row_width=2)
                        if p.status == 'running':
                            markup.add(types.InlineKeyboardButton("🔴 توقف", callback_data=f"stop_{p.id}"),
                                    types.InlineKeyboardButton("🔄 ریستارت", callback_data=f"restart_{p.id}"))
                        else:
                            markup.add(types.InlineKeyboardButton("🟢 شروع", callback_data=f"start_{p.id}"))
                        
                        markup.add(types.InlineKeyboardButton("🔗 لینک اتصال", callback_data=f"link_{p.id}"),
                                   types.InlineKeyboardButton("♻️ ریست مصرف", callback_data=f"reset_{p.id}"))
                        
                        markup.add(types.InlineKeyboardButton("🗑️ حذف", callback_data=f"del_{p.id}"),
                                   types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_list"))
                        
                        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

                    else:
                        bot.answer_callback_query(call.id, "خطا در ارتباط با داکر.")
                except Exception as e:
                    bot.answer_callback_query(call.id, f"خطا: {e}")

        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Bot Polling Error: {e}")
