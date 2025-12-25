import threading
from flask import Flask
from sqlalchemy import inspect, text
from app.config import Config
from app.extensions import db, login_manager, limiter
from app.models import User
from app.utils.helpers import get_setting

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize Extensions
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    # Register Blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.users import users_bp
    from app.routes.proxy import proxy_bp
    from app.routes.settings import settings_bp
    from app.routes.firewall import firewall_bp
    from app.routes.api import api_bp
    from app.routes.system import system_bp
    from app.routes.tools import tools_bp
    from app.routes.reports import reports_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(proxy_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(firewall_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(reports_bp)

    # Global Context Processor
    from datetime import datetime
    @app.context_processor
    def inject_globals():
        return {
            'now': datetime.utcnow(),
            'server_ip': get_setting('server_ip', 'YOUR_IP'), # Default if not set, or get from request
            'server_domain': get_setting('server_domain', '')
        }
    
    # Initialize DB
    with app.app_context():
        _ensure_db_initialized(app)

    # Start Background Threads
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        # Stats Thread
        from app.services.monitor import update_docker_stats
        import os
        if os.environ.get("HOSEINPROXY_DISABLE_STATS_THREAD", "0") != "1":
            stats_thread = threading.Thread(target=update_docker_stats, args=(app,), daemon=True)
            stats_thread.start()
            
        # Telegram Bot
        from app.services.telegram_service import run_telegram_bot
        bot_thread = threading.Thread(target=run_telegram_bot, args=(app,), daemon=True)
        bot_thread.start()

    return app

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def _ensure_db_initialized(app):
    db.create_all()
    inspector = inspect(db.engine)
    
    # Migrations Logic (Simplified)
    if inspector.has_table('proxy'):
        columns = {c['name'] for c in inspector.get_columns('proxy')}
        migrations = [
            ('active_connections', 'ALTER TABLE proxy ADD COLUMN active_connections INTEGER DEFAULT 0'),
            ('upload_rate_bps', 'ALTER TABLE proxy ADD COLUMN upload_rate_bps BIGINT DEFAULT 0'),
            ('download_rate_bps', 'ALTER TABLE proxy ADD COLUMN download_rate_bps BIGINT DEFAULT 0'),
            ('quota_bytes', 'ALTER TABLE proxy ADD COLUMN quota_bytes BIGINT DEFAULT 0'),
            ('quota_start', 'ALTER TABLE proxy ADD COLUMN quota_start DATETIME'),
            ('quota_base_upload', 'ALTER TABLE proxy ADD COLUMN quota_base_upload BIGINT DEFAULT 0'),
            ('quota_base_download', 'ALTER TABLE proxy ADD COLUMN quota_base_download BIGINT DEFAULT 0'),
            ('expiry_date', 'ALTER TABLE proxy ADD COLUMN expiry_date DATETIME'),
            ('telegram_chat_id', 'ALTER TABLE proxy ADD COLUMN telegram_chat_id VARCHAR(50)'),
            ('username', 'ALTER TABLE proxy ADD COLUMN username VARCHAR(100)'),
            ('password', 'ALTER TABLE proxy ADD COLUMN password VARCHAR(100)'),
            ('proxy_ip', 'ALTER TABLE proxy ADD COLUMN proxy_ip VARCHAR(50)'),
            ('name', 'ALTER TABLE proxy ADD COLUMN name VARCHAR(100)'),
            ('created_at', 'ALTER TABLE proxy ADD COLUMN created_at DATETIME'),
        ]
        
        with db.engine.connect() as conn:
            for col, sql in migrations:
                if col not in columns:
                    try:
                        conn.execute(text(sql))
                        conn.commit()
                    except:
                        pass
                        
    if inspector.has_table('user'):
        columns = {c['name'] for c in inspector.get_columns('user')}
        if 'created_at' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE user ADD COLUMN created_at DATETIME'))
                conn.commit()
