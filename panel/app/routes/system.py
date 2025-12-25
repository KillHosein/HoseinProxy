import os
import tarfile
import subprocess
import requests
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, send_from_directory, redirect, url_for
from flask_login import login_required
from app.utils.helpers import get_setting

system_bp = Blueprint('system', __name__, url_prefix='/system')

@system_bp.route('/')
@login_required
def page():
    try:
        current_version = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('utf-8').strip()
    except:
        current_version = "Unknown"
        
    return render_template('pages/admin/system.html', current_version=current_version)

@system_bp.route('/check_update', methods=['POST'])
@login_required
def check_update():
    try:
        subprocess.check_call(['git', 'fetch'])
        local = subprocess.check_output(['git', 'rev-parse', '@']).decode('utf-8').strip()
        remote = subprocess.check_output(['git', 'rev-parse', '@{u}']).decode('utf-8').strip()
        
        if local == remote:
            return jsonify({'status': 'up_to_date'})
        else:
            return jsonify({'status': 'update_available'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@system_bp.route('/do_update', methods=['POST'])
@login_required
def do_update():
    try:
        subprocess.check_call(['git', 'pull'])
        subprocess.check_call(['pip', 'install', '-r', 'requirements.txt'])
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
        
        flash('سیستم به‌روزرسانی شد و در حال ریستارت است. لطفاً چند لحظه صبر کنید...', 'success')
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@system_bp.route('/restart_service', methods=['POST'])
@login_required
def restart_service():
    try:
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
        flash('سرویس در حال ریستارت است...', 'info')
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@system_bp.route('/logs')
@login_required
def logs():
    try:
        with open('/var/log/hoseinproxy_manager.log', 'r') as f:
            content = f.read()
        return jsonify({'content': content})
    except:
        return jsonify({'content': 'Log file not found.'})

@system_bp.route('/backup', methods=['POST'])
@login_required
def backup():
    try:
        # Assuming app is in panel/app/.. so we go up two levels to find root panel dir?
        # Current file is panel/app/routes/system.py
        # Root is panel/
        
        # Or better, use app.root_path or __file__ relative.
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # panel/
        
        backup_dir = os.path.join(base_dir, 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hoseinproxy_backup_{timestamp}.tar.gz"
        backup_file = os.path.join(backup_dir, filename)
        
        with tarfile.open(backup_file, "w:gz") as tar:
            # Critical files
            if os.path.exists(os.path.join(base_dir, 'panel.db')):
                tar.add(os.path.join(base_dir, 'panel.db'), arcname='panel.db')
            if os.path.exists(os.path.join(base_dir, 'app.py')): # Old app.py, maybe should backup run.py too
                tar.add(os.path.join(base_dir, 'app.py'), arcname='app.py')
            if os.path.exists(os.path.join(base_dir, 'requirements.txt')):
                tar.add(os.path.join(base_dir, 'requirements.txt'), arcname='requirements.txt')
            if os.path.exists(os.path.join(base_dir, 'secret.key')):
                tar.add(os.path.join(base_dir, 'secret.key'), arcname='secret.key')
                
        # Send to Telegram
        bot_token = get_setting('telegram_bot_token')
        chat_id = get_setting('telegram_chat_id')
        sent_to_telegram = False
        
        if bot_token and chat_id:
            try:
                with open(backup_file, 'rb') as f:
                    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                    data = {'chat_id': chat_id, 'caption': f'📦 Backup: {filename}\n📅 {timestamp}'}
                    files = {'document': f}
                    resp = requests.post(url, data=data, files=files, timeout=30)
                    if resp.status_code == 200:
                        sent_to_telegram = True
            except Exception as e:
                print(f"Telegram Upload Error: {e}")

        # Cleanup old backups
        try:
            files = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.tar.gz')], key=os.path.getmtime)
            while len(files) > 5:
                os.remove(files[0])
                files.pop(0)
        except:
            pass
            
        msg = 'نسخه پشتیبان ایجاد شد.'
        if sent_to_telegram:
            msg += ' و به تلگرام ارسال شد.'
            
        return jsonify({'status': 'success', 'path': backup_file, 'filename': filename, 'message': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@system_bp.route('/download_backup/<filename>')
@login_required
def download_backup(filename):
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        backup_dir = os.path.join(base_dir, 'backups')
        return send_from_directory(backup_dir, filename, as_attachment=True)
    except Exception as e:
        flash(f'خطا در دانلود فایل: {e}', 'danger')
        return redirect(url_for('system.page'))

@system_bp.route('/restore', methods=['POST'])
@login_required
def restore():
    try:
        if 'backup_file' not in request.files:
            return jsonify({'status': 'error', 'message': 'فایلی ارسال نشده است.'})
            
        file = request.files['backup_file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'نام فایل خالی است.'})
            
        if not file.filename.endswith('.tar.gz'):
            return jsonify({'status': 'error', 'message': 'فرمت فایل باید tar.gz باشد.'})
            
        backup_path = f"/tmp/{file.filename}"
        file.save(backup_path)
        
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        with tarfile.open(backup_path, "r:gz") as tar:
            names = tar.getnames()
            if 'panel.db' not in names and './panel.db' not in names:
                 return jsonify({'status': 'error', 'message': 'فایل بکاپ معتبر نیست (panel.db یافت نشد).'})
            
            tar.extract('panel.db', path=base_dir)
            
        os.remove(backup_path)
        
        # Restart Service
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
        
        flash('بکاپ با موفقیت بازگردانی شد. سرویس در حال ریستارت است...', 'success')
        return jsonify({'status': 'success'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
