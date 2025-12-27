import os
import shutil
import tarfile
import subprocess
from datetime import datetime
from app.utils.helpers import get_setting

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

    def create_backup(self):
        """
        Creates a comprehensive backup of the system.
        Returns: (file_path, filename)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"hoseinproxy_backup_{timestamp}.tar.gz"
        file_path = os.path.join(self.backup_dir, filename)
        
        # Files to backup
        # Format: (source_path, arcname)
        files_to_backup = []
        
        # 1. Database (Critical)
        db_path = os.path.join(self.app_root, 'panel.db')
        if os.path.exists(db_path):
            files_to_backup.append((db_path, 'panel.db'))
            
        # 2. Secret Key (Critical)
        key_path = os.path.join(self.app_root, 'secret.key')
        if os.path.exists(key_path):
            files_to_backup.append((key_path, 'secret.key'))
            
        # 3. Config Env (Critical)
        config_path = os.path.join(self.project_root, 'config.env')
        if os.path.exists(config_path):
            files_to_backup.append((config_path, 'config.env'))
            
        # 4. Requirements (Useful)
        req_path = os.path.join(self.app_root, 'requirements.txt')
        if os.path.exists(req_path):
            files_to_backup.append((req_path, 'requirements.txt'))

        # 5. Nginx Config (Optional but good)
        nginx_conf = "/etc/nginx/sites-available/hoseinproxy"
        if os.path.exists(nginx_conf):
            files_to_backup.append((nginx_conf, 'nginx_hoseinproxy.conf'))
            
        if not files_to_backup:
            raise Exception("No files found to backup!")

        with tarfile.open(file_path, "w:gz") as tar:
            for source, arcname in files_to_backup:
                tar.add(source, arcname=arcname)
                
        # Cleanup old backups (keep last 10)
        self._cleanup_old_backups()
        
        return file_path, filename

    def restore_backup(self, backup_file_path):
        """
        Restores the system from a backup file.
        backup_file_path: Path to the .tar.gz backup file
        """
        if not tarfile.is_tarfile(backup_file_path):
            raise Exception("Invalid backup file format (must be tar.gz)")

        # Create temp extract dir
        extract_dir = os.path.join(self.backup_dir, 'restore_temp')
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        try:
            with tarfile.open(backup_file_path, "r:gz") as tar:
                tar.extractall(path=extract_dir)
                
            # Validate
            if not os.path.exists(os.path.join(extract_dir, 'panel.db')):
                raise Exception("Backup is invalid: panel.db not found")

            # Restore Database
            src_db = os.path.join(extract_dir, 'panel.db')
            dst_db = os.path.join(self.app_root, 'panel.db')
            # Close DB connection if possible? 
            # In Flask-SQLAlchemy, connections are scoped. 
            # Ideally, we should stop the service before this, but we are running INSIDE the service.
            # SQLite allows overwriting file usually, but might corrupt if writing.
            # We will rely on restart after restore.
            shutil.copy2(src_db, dst_db)

            # Restore Secret Key
            if os.path.exists(os.path.join(extract_dir, 'secret.key')):
                shutil.copy2(os.path.join(extract_dir, 'secret.key'), os.path.join(self.app_root, 'secret.key'))

            # Restore Config
            if os.path.exists(os.path.join(extract_dir, 'config.env')):
                shutil.copy2(os.path.join(extract_dir, 'config.env'), os.path.join(self.project_root, 'config.env'))

            # Restore Nginx Config
            if os.path.exists(os.path.join(extract_dir, 'nginx_hoseinproxy.conf')):
                # Only restore if it exists on destination to avoid permission issues if not root
                # But usually we are root.
                dst_nginx = "/etc/nginx/sites-available/hoseinproxy"
                if os.path.exists(os.path.dirname(dst_nginx)):
                     try:
                         shutil.copy2(os.path.join(extract_dir, 'nginx_hoseinproxy.conf'), dst_nginx)
                         # Reload nginx
                         subprocess.run(['systemctl', 'reload', 'nginx'], check=False)
                     except Exception as e:
                         print(f"Failed to restore Nginx config: {e}")

            return True

        finally:
            # Cleanup temp
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)

    def _cleanup_old_backups(self, keep=10):
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
        # We spawn a background process to restart, so the current request can finish
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
