import os
import shutil
import tarfile
import subprocess
import re
import requests
from datetime import datetime
from app.utils.helpers import get_setting, get_valid_bot_token

class BackupService:
    def __init__(self, app_root):
        """
        app_root: The root directory of the panel application (e.g., /root/HoseinProxy/panel)
        """
        self.app_root = os.path.abspath(app_root)
        self.project_root = os.path.dirname(self.app_root) # /root/HoseinProxy
        self.backup_dir = os.path.join(self.project_root, 'backups')
        
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)

    def list_backups(self):
        """Returns a list of available backups with metadata."""
        backups = []
        if not os.path.exists(self.backup_dir):
            return backups
            
        for f in os.listdir(self.backup_dir):
            if f.endswith('.tar.gz'):
                path = os.path.join(self.backup_dir, f)
                size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
                mod_time = os.path.getmtime(path)
                dt = datetime.fromtimestamp(mod_time)
                
                backups.append({
                    'filename': f,
                    'path': path,
                    'size_mb': size_mb,
                    'date': dt.strftime('%Y-%m-%d %H:%M:%S'),
                    'timestamp': mod_time
                })
        
        # Sort by newest first
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        return backups

    def delete_backup(self, filename):
        """Deletes a specific backup file."""
        path = os.path.join(self.backup_dir, filename)
        if os.path.exists(path) and path.startswith(self.backup_dir):
            os.remove(path)
            return True
        return False

    def send_backup_to_telegram(self, filename, chat_id=None):
        """Sends a specific backup file to Telegram."""
        path = os.path.join(self.backup_dir, filename)
        if not os.path.exists(path):
            return False, "File not found"

        bot_token = get_valid_bot_token()
        if not chat_id:
            chat_id = get_setting('telegram_chat_id')

        if not bot_token or not chat_id:
            return False, "Telegram not configured"

        try:
            with open(path, 'rb') as f:
                url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                timestamp = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
                caption = f'📦 <b>Auto Backup</b>\n📄 File: {filename}\n📅 Date: {timestamp}\n💾 Size: {round(os.path.getsize(path)/1024/1024, 2)} MB'
                data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
                files = {'document': f}
                resp = requests.post(url, data=data, files=files, timeout=60)
                
                if resp.status_code == 200:
                    return True, "Sent successfully"
                else:
                    return False, f"Telegram API Error: {resp.text}"
        except Exception as e:
            return False, str(e)

    def create_backup(self, keep=5):
        """
        Creates a comprehensive backup of the entire project + dependencies.
        Returns: (file_path, filename)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hoseinproxy_backup_{timestamp}.tar.gz"
        file_path = os.path.join(self.backup_dir, filename)
        
        with tarfile.open(file_path, "w:gz") as tar:
            # 1. Backup Entire Project Directory (excluding junk)
            exclude_dirs = {'venv', '.git', 'backups', '__pycache__', 'restore_temp', 'static'} 
            
            for root, dirs, files in os.walk(self.project_root):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                
                for file in files:
                    if file.endswith('.pyc') or file.endswith('.log'):
                        continue
                        
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, self.project_root)
                    tar.add(full_path, arcname=arcname)
            
            # 2. External Configs (Nginx)
            nginx_conf = "/etc/nginx/sites-available/hoseinproxy"
            if os.path.exists(nginx_conf):
                tar.add(nginx_conf, arcname='external/nginx_hoseinproxy.conf')
                
                # 3. SSL Certs (if found in nginx config)
                ssl_files = self._find_ssl_files(nginx_conf)
                for f in ssl_files:
                    if os.path.exists(f):
                        arcname = 'external/ssl/' + f.lstrip('/')
                        tar.add(f, arcname=arcname)

        # Cleanup old backups
        self._cleanup_old_backups(keep)
        
        return file_path, filename

    def restore_backup(self, backup_file_path):
        """
        Restores the system from a full backup.
        """
        if not tarfile.is_tarfile(backup_file_path):
            raise Exception("Invalid backup file format (must be tar.gz)")

        extract_dir = os.path.join(self.backup_dir, 'restore_temp')
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        try:
            with tarfile.open(backup_file_path, "r:gz") as tar:
                tar.extractall(path=extract_dir)
                
            # 1. Restore Project Files
            for root, dirs, files in os.walk(extract_dir):
                if 'external' in root.split(os.sep):
                    continue
                
                rel_path = os.path.relpath(root, extract_dir)
                target_root = os.path.join(self.project_root, rel_path)
                
                if not os.path.exists(target_root):
                    os.makedirs(target_root)
                    
                for file in files:
                    if file == 'external': continue
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target_root, file)
                    shutil.copy2(src_file, dst_file)

            # 2. Restore External (Nginx & SSL)
            external_dir = os.path.join(extract_dir, 'external')
            if os.path.exists(external_dir):
                # Nginx
                nginx_src = os.path.join(external_dir, 'nginx_hoseinproxy.conf')
                if os.path.exists(nginx_src):
                    dst_nginx = "/etc/nginx/sites-available/hoseinproxy"
                    if os.path.exists(os.path.dirname(dst_nginx)):
                         try:
                             shutil.copy2(nginx_src, dst_nginx)
                             subprocess.run(['systemctl', 'reload', 'nginx'], check=False)
                         except: pass

                # SSL
                ssl_dir = os.path.join(external_dir, 'ssl')
                if os.path.exists(ssl_dir):
                    for root, dirs, files in os.walk(ssl_dir):
                        for file in files:
                            src_file = os.path.join(root, file)
                            rel = os.path.relpath(src_file, ssl_dir)
                            dst_file = '/' + rel 
                            
                            if os.path.exists(os.path.dirname(dst_file)):
                                try:
                                    shutil.copy2(src_file, dst_file)
                                except: pass
            
            return True

        finally:
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)

    def _find_ssl_files(self, nginx_conf_path):
        """Scans nginx config for ssl_certificate directives"""
        files = set()
        try:
            with open(nginx_conf_path, 'r') as f:
                content = f.read()
                certs = re.findall(r'ssl_certificate\s+([^;]+);', content)
                keys = re.findall(r'ssl_certificate_key\s+([^;]+);', content)
                
                files.update([c.strip() for c in certs])
                files.update([k.strip() for k in keys])
        except:
            pass
        return list(files)

    def _cleanup_old_backups(self, keep=5):
        try:
            files = sorted(
                [os.path.join(self.backup_dir, f) for f in os.listdir(self.backup_dir) if f.endswith('.tar.gz')],
                key=os.path.getmtime
            )
            while len(files) > keep:
                os.remove(files[0])
                files.pop(0)
        except Exception:
            pass

    def restart_service(self):
        """Restarts the hoseinproxy service"""
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
