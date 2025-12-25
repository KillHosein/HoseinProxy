import telebot
import time
import requests
import os
import psutil
import secrets
from datetime import datetime, timedelta
from telebot import types
from sqlalchemy import func
from app.utils.helpers import get_setting, set_setting
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
    token = get_setting('telegram_bot_token')
    if token:
        try:
            _bot_instance = telebot.TeleBot(token, threaded=False)
            return _bot_instance
        except:
            return None
    return None

def send_telegram_alert(message):
    try:
        bot_token = get_setting('telegram_bot_token')
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
    return markup

def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 بازگشت")
    return markup

def proxy_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 لیست پروکسی‌ها", "➕ افزودن پروکسی")
    markup.add("🔙 بازگشت")
    return markup

def firewall_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 لیست سیاه", "⛔ مسدود کردن IP")
    markup.add("🔓 آزاد کردن IP", "🔙 بازگشت")
    return markup

def users_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 لیست مدیران", "➕ افزودن مدیر")
    markup.add("🔙 بازگشت")
    return markup

# --- Helper Logic ---
def is_admin(chat_id):
    admin_id = get_setting('telegram_chat_id')
    return str(chat_id) == str(admin_id)

def set_state(chat_id, step, data=None):
    _user_states[chat_id] = {'step': step, 'data': data or {}}

def get_state(chat_id):
    return _user_states.get(chat_id)

def clear_state(chat_id):
    if chat_id in _user_states:
        del _user_states[chat_id]

# --- Bot Runner ---
def run_telegram_bot(app):
    with app.app_context():
        token = get_setting('telegram_bot_token')
        if not token:
            return

        bot = telebot.TeleBot(token)
        
        # --- Command Handlers ---
        @bot.message_handler(commands=['start', 'help'])
        def send_welcome(message):
            chat_id = str(message.chat.id)
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

        # --- System Status ---
        @bot.message_handler(func=lambda m: m.text == "📊 وضعیت سیستم")
        def status_handler(message):
            if not is_admin(message.chat.id): return
            
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                disk = psutil.disk_usage('/').percent
                
                with app.app_context():
                    proxy_count = Proxy.query.count()
                    active_count = Proxy.query.filter_by(status='running').count()
                    total_upload = db.session.query(func.sum(Proxy.upload)).scalar() or 0
                    total_download = db.session.query(func.sum(Proxy.download)).scalar() or 0
                
                msg = (
                    f"📊 <b>System Status</b>\n\n"
                    f"💻 CPU: <code>{cpu}%</code>\n"
                    f"🧠 RAM: <code>{ram}%</code>\n"
                    f"💾 Disk: <code>{disk}%</code>\n\n"
                    f"🚀 Proxies: <code>{active_count}/{proxy_count}</code> Active\n"
                    f"⬆️ Upload: <code>{round(total_upload / (1024**3), 2)} GB</code>\n"
                    f"⬇️ Download: <code>{round(total_download / (1024**3), 2)} GB</code>"
                )
                bot.reply_to(message, msg, parse_mode='HTML')
            except Exception as e:
                bot.reply_to(message, f"Error: {e}")

        # --- Proxy Management ---
        @bot.message_handler(func=lambda m: m.text == "🚀 مدیریت پروکسی")
        def proxy_menu(message):
            if not is_admin(message.chat.id): return
            bot.reply_to(message, "مدیریت پروکسی:", reply_markup=proxy_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📋 لیست پروکسی‌ها")
        def list_proxies(message):
            if not is_admin(message.chat.id): return
            with app.app_context():
                proxies = Proxy.query.all()
                if not proxies:
                    bot.reply_to(message, "هیچ پروکسی وجود ندارد.")
                    return
                
                # Chunk list to avoid message too long
                chunk_size = 10
                for i in range(0, len(proxies), chunk_size):
                    chunk = proxies[i:i + chunk_size]
                    markup = types.InlineKeyboardMarkup()
                    for p in chunk:
                        status_icon = "🟢" if p.status == 'running' else "🔴"
                        btn_text = f"{status_icon} {p.port} | {p.name or p.tag or 'No Name'}"
                        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"p_{p.id}"))
                    
                    bot.reply_to(message, f"لیست پروکسی‌ها (صفحه {i//chunk_size + 1}):", reply_markup=markup)

        @bot.message_handler(func=lambda m: m.text == "➕ افزودن پروکسی")
        def add_proxy_step1(message):
            if not is_admin(message.chat.id): return
            set_state(message.chat.id, 'add_proxy_port')
            bot.reply_to(message, "🔢 لطفاً <b>شماره پورت</b> را وارد کنید:\n(مثال: 443)", reply_markup=back_keyboard(), parse_mode='HTML')

        # --- Firewall Management ---
        @bot.message_handler(func=lambda m: m.text == "🛡️ فایروال")
        def firewall_menu(message):
            if not is_admin(message.chat.id): return
            bot.reply_to(message, "مدیریت فایروال:", reply_markup=firewall_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📋 لیست سیاه")
        def list_firewall(message):
            if not is_admin(message.chat.id): return
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
            if not is_admin(message.chat.id): return
            set_state(message.chat.id, 'block_ip_addr')
            bot.reply_to(message, "🚫 لطفاً <b>آی‌پی</b> مورد نظر برای مسدودسازی را وارد کنید:", reply_markup=back_keyboard(), parse_mode='HTML')

        @bot.message_handler(func=lambda m: m.text == "🔓 آزاد کردن IP")
        def unblock_ip_step1(message):
            if not is_admin(message.chat.id): return
            set_state(message.chat.id, 'unblock_ip_addr')
            bot.reply_to(message, "🔓 لطفاً <b>آی‌پی</b> مورد نظر برای آزادسازی را وارد کنید:", reply_markup=back_keyboard(), parse_mode='HTML')

        # --- User Management ---
        @bot.message_handler(func=lambda m: m.text == "👥 مدیران")
        def users_menu(message):
            if not is_admin(message.chat.id): return
            bot.reply_to(message, "مدیریت کاربران:", reply_markup=users_menu_keyboard())

        @bot.message_handler(func=lambda m: m.text == "📋 لیست مدیران")
        def list_users(message):
            if not is_admin(message.chat.id): return
            with app.app_context():
                users = User.query.all()
                msg = "👤 <b>Admins:</b>\n\n"
                for u in users:
                    msg += f"• {u.username}\n"
                bot.reply_to(message, msg, parse_mode='HTML')

        @bot.message_handler(func=lambda m: m.text == "➕ افزودن مدیر")
        def add_user_step1(message):
            if not is_admin(message.chat.id): return
            set_state(message.chat.id, 'add_user_name')
            bot.reply_to(message, "👤 نام کاربری جدید را وارد کنید:", reply_markup=back_keyboard())

        # --- Settings ---
        @bot.message_handler(func=lambda m: m.text == "⚙️ تنظیمات")
        def settings_menu(message):
            if not is_admin(message.chat.id): return
            msg = "⚙️ <b>تنظیمات</b>\n\nهم‌اکنون فقط از طریق پنل وب قابل دسترسی است."
            bot.reply_to(message, msg, parse_mode='HTML')

        # --- Backup ---
        @bot.message_handler(func=lambda m: m.text == "📦 دریافت بکاپ")
        def backup_handler(message):
            if not is_admin(message.chat.id): return
            bot.reply_to(message, "⏳ در حال تهیه بکاپ...")
            try:
                with app.app_context():
                    backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'backups')
                    if not os.path.exists(backup_dir): os.makedirs(backup_dir)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"hoseinproxy_backup_{timestamp}.tar.gz"
                    backup_file = os.path.join(backup_dir, filename)
                    
                    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    
                    with tarfile.open(backup_file, "w:gz") as tar:
                        if os.path.exists(os.path.join(base_dir, 'panel.db')): tar.add(os.path.join(base_dir, 'panel.db'), arcname='panel.db')
                        if os.path.exists(os.path.join(base_dir, 'requirements.txt')): tar.add(os.path.join(base_dir, 'requirements.txt'), arcname='requirements.txt')
                        if os.path.exists(os.path.join(base_dir, 'secret.key')): tar.add(os.path.join(base_dir, 'secret.key'), arcname='secret.key')
                    
                    with open(backup_file, 'rb') as f:
                        bot.send_document(message.chat.id, f, caption=f"📦 Backup: {filename}")
            except Exception as e:
                bot.reply_to(message, f"Error: {e}")

        # --- State Handlers (Wizard Logic) ---
        @bot.message_handler(func=lambda m: get_state(m.chat.id) is not None)
        def state_handler(message):
            if not is_admin(message.chat.id): return
            state = get_state(message.chat.id)
            step = state['step']
            data = state['data']
            
            # --- Add Proxy Wizard ---
            if step == 'add_proxy_port':
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
                            container = docker_client.containers.run(
                                'alexbers/mtprotoproxy',
                                detach=True,
                                ports={'443/tcp': data['port']},
                                environment={
                                    'SECRET': data['secret'],
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
                                secret=data['secret'],
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

        # --- Callbacks ---
        @bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
        def proxy_detail_callback(call):
            if not is_admin(call.message.chat.id): return
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
                        
                    quota_str = "Unlimited"
                    if p.quota_bytes and p.quota_bytes > 0:
                        used_gb = round((p.upload + p.download) / (1024**3), 2)
                        limit_gb = round(p.quota_bytes / (1024**3), 2)
                        quota_str = f"{used_gb}/{limit_gb} GB"

                    msg = (
                        f"⚙️ <b>Proxy #{p.port}</b>\n"
                        f"Name: {p.name or '-'}\n"
                        f"Tag: {p.tag or '-'}\n"
                        f"Status: {status_icon} {p.status}\n"
                        f"⏳ Expiry: {expiry_str}\n"
                        f"💾 Quota: {quota_str}\n"
                        f"👥 Users: {p.active_connections}\n"
                        f"⬆️ UP: {round(p.upload / (1024**2), 2)} MB\n"
                        f"⬇️ DL: {round(p.download / (1024**2), 2)} MB\n"
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
            except Exception as e:
                print(f"Bot Callback Error: {e}")

        @bot.callback_query_handler(func=lambda call: call.data == "back_list")
        def back_list_callback(call):
            bot.delete_message(call.message.chat.id, call.message.message_id)
            # Re-send list (since editing to text from inline requires logic change in previous handler if we want to reuse)
            # Or just send text "Select from list" and re-call list_proxies logic logic
            # Simpler: just acknowledge
            bot.answer_callback_query(call.id, "منو را از کیبورد انتخاب کنید.")

        @bot.callback_query_handler(func=lambda call: call.data.startswith(('stop_', 'start_', 'restart_', 'link_', 'del_', 'reset_')))
        def action_callback(call):
            if not is_admin(call.message.chat.id): return
            action, pid = call.data.split('_')
            pid = int(pid)
            
            with app.app_context():
                p = Proxy.query.get(pid)
                if not p:
                    bot.answer_callback_query(call.id, "پروکسی یافت نشد.")
                    return

                if action == 'link':
                    server_ip = get_setting('server_ip') or 'YOUR_IP'
                    link = f"https://t.me/proxy?server={server_ip}&port={p.port}&secret={p.secret}"
                    bot.send_message(call.message.chat.id, f"🔗 <b>لینک اتصال:</b>\n\n<code>{link}</code>", parse_mode='HTML')
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
                        
                    quota_str = "Unlimited"
                    if p.quota_bytes and p.quota_bytes > 0:
                        used_gb = round((p.upload + p.download) / (1024**3), 2)
                        limit_gb = round(p.quota_bytes / (1024**3), 2)
                        quota_str = f"{used_gb}/{limit_gb} GB"

                    msg = (
                        f"⚙️ <b>Proxy #{p.port}</b>\n"
                        f"Name: {p.name or '-'}\n"
                        f"Tag: {p.tag or '-'}\n"
                        f"Status: {status_icon} {p.status}\n"
                        f"⏳ Expiry: {expiry_str}\n"
                        f"💾 Quota: {quota_str}\n"
                        f"👥 Users: {p.active_connections}\n"
                        f"⬆️ UP: 0.0 MB\n"
                        f"⬇️ DL: 0.0 MB\n"
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
                            
                        quota_str = "Unlimited"
                        if p.quota_bytes and p.quota_bytes > 0:
                            used_gb = round((p.upload + p.download) / (1024**3), 2)
                            limit_gb = round(p.quota_bytes / (1024**3), 2)
                            quota_str = f"{used_gb}/{limit_gb} GB"

                        msg = (
                            f"⚙️ <b>Proxy #{p.port}</b>\n"
                            f"Name: {p.name or '-'}\n"
                            f"Tag: {p.tag or '-'}\n"
                            f"Status: {status_icon} {p.status}\n"
                            f"⏳ Expiry: {expiry_str}\n"
                            f"💾 Quota: {quota_str}\n"
                            f"👥 Users: {p.active_connections}\n"
                            f"⬆️ UP: {round(p.upload / (1024**2), 2)} MB\n"
                            f"⬇️ DL: {round(p.download / (1024**2), 2)} MB\n"
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
