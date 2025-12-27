import threading
import time
import os
from app.services.backup_service import BackupService

class BackupScheduler(threading.Thread):
    def __init__(self, app_root, interval_hours=3):
        super().__init__()
        self.app_root = app_root
        self.interval_seconds = interval_hours * 3600
        self.stop_event = threading.Event()
        self.daemon = True # Daemon thread exits when main program exits

    def run(self):
        print("[Scheduler] Backup scheduler started.")
        # Initial wait? No, let's wait first to avoid immediate backup on restart loop
        while not self.stop_event.is_set():
            # Sleep in chunks to allow faster stopping
            for _ in range(self.interval_seconds):
                if self.stop_event.is_set():
                    return
                time.sleep(1)
            
            self.perform_backup()

    def perform_backup(self):
        try:
            print("[Scheduler] Starting automatic backup...")
            service = BackupService(self.app_root)
            file_path, filename = service.create_backup(keep=5)
            
            # Optional: Send to Telegram if configured
            # We don't have 'app' context here easily, but BackupService handles logic mostly.
            # However, helpers.get_setting needs app context if using Flask-SQLAlchemy directly without context?
            # BackupService methods use helpers.get_setting.
            # get_setting uses Settings.query... which needs app context.
            
            # We need to pass 'app' to the scheduler or use a context manager if possible.
            # But we are in a thread.
            # We should pass 'app' to __init__ and use app.app_context().
            pass
        except Exception as e:
            print(f"[Scheduler] Backup failed: {e}")

    def stop(self):
        self.stop_event.set()

_scheduler_instance = None

def start_scheduler(app):
    global _scheduler_instance
    if _scheduler_instance is None:
        # We need to wrap the run logic to use app context
        class AppContextBackupScheduler(BackupScheduler):
            def __init__(self, app, interval_hours=3):
                app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # panel/app/services/../../ -> panel/
                super().__init__(app_root, interval_hours)
                self.app = app

            def perform_backup(self):
                with self.app.app_context():
                    super().perform_backup()
                    # Also try to send to telegram
                    try:
                        service = BackupService(self.app_root)
                        # We assume the last created backup is the one we want, 
                        # but create_backup returns the path.
                        # Wait, create_backup was called in super().perform_backup() ? 
                        # No, super().perform_backup calls create_backup.
                        # We should override perform_backup entirely here.
                        
                        print("[Scheduler] Starting automatic backup...")
                        file_path, filename = service.create_backup(keep=5)
                        print(f"[Scheduler] Backup created: {filename}")
                        
                        success, msg = service.send_backup_to_telegram(filename)
                        if success:
                            print("[Scheduler] Backup sent to Telegram.")
                        else:
                            print(f"[Scheduler] Failed to send to Telegram: {msg}")
                            
                    except Exception as e:
                        print(f"[Scheduler] Error: {e}")

        _scheduler_instance = AppContextBackupScheduler(app)
        _scheduler_instance.start()
