import os
import tarfile
import subprocess
import requests
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, flash, send_from_directory, redirect, url_for
from flask_login import login_required
from app.utils.helpers import get_setting, get_valid_bot_token
from app.services.backup_service import BackupService

system_bp = Blueprint('system', __name__, url_prefix='/system')

@system_bp.route('/')
@login_required
def page():
    try:
        current_version = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('utf-8').strip()
    except:
        current_version = "Unknown"
        
    # Get Backups
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    service = BackupService(app_root)
    backups = service.list_backups()
        
    return render_template('pages/admin/system.html', current_version=current_version, backups=backups)

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
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service = BackupService(app_root)
        
        file_path, filename = service.create_backup(keep=5)
        
        # Send to Telegram if requested (though we have a separate endpoint now, we can keep logic or remove)
        # User asked for "Send to telegram AND download".
        # We'll just return success and let UI handle list refresh or offer download.
        
        # We can still auto-send if configured, but let's stick to the new "Send" button in list.
        # However, for manual creation, auto-sending is nice.
        
        bot_token = get_valid_bot_token()
        chat_id = get_setting('telegram_chat_id')
        sent_to_telegram = False
        
        if bot_token and chat_id:
             success, msg = service.send_backup_to_telegram(filename, chat_id)
             sent_to_telegram = success

        msg = 'نسخه پشتیبان کامل ایجاد شد.'
        if sent_to_telegram:
            msg += ' و به تلگرام ارسال شد.'
            
        return jsonify({'status': 'success', 'path': file_path, 'filename': filename, 'message': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@system_bp.route('/download_backup/<filename>')
@login_required
def download_backup(filename):
    try:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service = BackupService(app_root)
        return send_from_directory(service.backup_dir, filename, as_attachment=True)
    except Exception as e:
        flash(f'خطا در دانلود فایل: {e}', 'danger')
        return redirect(url_for('system.page'))

@system_bp.route('/delete_backup/<filename>', methods=['POST'])
@login_required
def delete_backup(filename):
    try:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service = BackupService(app_root)
        if service.delete_backup(filename):
             return jsonify({'status': 'success', 'message': 'بکاپ حذف شد.'})
        else:
             return jsonify({'status': 'error', 'message': 'فایل یافت نشد.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@system_bp.route('/send_backup/<filename>', methods=['POST'])
@login_required
def send_backup(filename):
    try:
        app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service = BackupService(app_root)
        success, msg = service.send_backup_to_telegram(filename)
        if success:
             return jsonify({'status': 'success', 'message': 'بکاپ به تلگرام ارسال شد.'})
        else:
             return jsonify({'status': 'error', 'message': msg})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

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
        
        try:
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            service = BackupService(app_root)
            service.restore_backup(backup_path)
            
            # Restart Service
            service.restart_service()
            
            flash('بکاپ با موفقیت بازگردانی شد. سرویس در حال ریستارت است...', 'success')
            return jsonify({'status': 'success'})
            
        finally:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
