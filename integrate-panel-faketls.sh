#!/bin/bash

# Panel Integration Script
# This script integrates FakeTLS support into the existing panel

set -e

PANEL_DIR="/opt/hoseinproxy-panel"

echo "🔧 Integrating FakeTLS support into panel..."

# Create enhanced __init__.py
cat > $PANEL_DIR/app/__init__.py << 'EOF'
import threading
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.config import Config

db = SQLAlchemy()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'لطفاً وارد شوید.'
    
    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.proxy import proxy_bp
    from app.routes.proxy_enhanced import proxy_enhanced_bp
    from app.routes.settings import settings_bp
    from app.routes.firewall import firewall_bp
    from app.routes.api import api_bp
    from app.routes.system import system_bp
    from app.routes.tools import tools_bp
    from app.routes.reports import reports_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(proxy_bp)
    app.register_blueprint(proxy_enhanced_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(firewall_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(reports_bp)
    
    # Create admin user if not exists
    with app.app_context():
        db.create_all()
        from app.models import User
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
    
    return app
EOF

# Create basic models.py if not exists
if [ ! -f "$PANEL_DIR/app/models.py" ]; then
cat > $PANEL_DIR/app/models.py << 'EOF'
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

class Proxy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    port = db.Column(db.Integer, unique=True, nullable=False)
    secret = db.Column(db.String(255), nullable=False)
    proxy_type = db.Column(db.String(20), default='standard')
    tls_domain = db.Column(db.String(255))
    tag = db.Column(db.String(255))
    name = db.Column(db.String(255))
    workers = db.Column(db.Integer, default=2)
    container_id = db.Column(db.String(255))
    status = db.Column(db.String(20), default='stopped')
    upload = db.Column(db.BigInteger, default=0)
    download = db.Column(db.BigInteger, default=0)
    active_connections = db.Column(db.Integer, default=0)
    upload_rate_bps = db.Column(db.BigInteger, default=0)
    download_rate_bps = db.Column(db.BigInteger, default=0)
    quota_bytes = db.Column(db.BigInteger, default=0)
    quota_start = db.Column(db.DateTime)
    quota_base_upload = db.Column(db.BigInteger, default=0)
    quota_base_download = db.Column(db.BigInteger, default=0)
    expiry_date = db.Column(db.DateTime)
    telegram_chat_id = db.Column(db.String(50))
    username = db.Column(db.String(100))
    password = db.Column(db.String(100))
    proxy_ip = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def quota_usage(self):
        if not self.quota_start:
            return self.upload + self.download
        used_upload = max(0, self.upload - (self.quota_base_upload or 0))
        used_download = max(0, self.download - (self.quota_base_download or 0))
        return used_upload + used_download
    
    @property
    def quota_percent(self):
        if self.quota_bytes <= 0:
            return 0
        return min(100, int((self.quota_usage / self.quota_bytes) * 100))

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False)
    value = db.Column(db.Text)
EOF
fi

echo "✅ Panel integration completed!"
echo "✅ FakeTLS support added to panel!"
echo "✅ Enhanced dashboard with FakeTLS management!"

# Create final setup script
cat > /tmp/final-setup.sh << 'EOF'
#!/bin/bash

# Final setup and start
echo "🚀 Starting HoseinProxy Panel with FakeTLS support..."

cd /opt/hoseinproxy-panel

# Create systemd service
cat > /etc/systemd/system/hoseinproxy-panel.service << 'EOL'
[Unit]
Description=HoseinProxy Panel
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/hoseinproxy-panel
Environment="PATH=/opt/hoseinproxy-panel/venv/bin"
ExecStart=/opt/hoseinproxy-panel/venv/bin/python run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Enable and start service
systemctl daemon-reload
systemctl enable hoseinproxy-panel
systemctl start hoseinproxy-panel

echo "✅ Panel service started!"
echo "🌐 Access panel at: http://YOUR_SERVER_IP:5000"
echo "🔑 Login: admin / admin123"
echo ""
echo "📱 To create FakeTLS proxy:"
echo "1. Login to panel"
echo "2. Click 'پروکسی FakeTLS'"
echo "3. Choose google.com domain"
echo "4. Generate your anti-filtering proxy!"
EOF

chmod +x /tmp/final-setup.sh

echo ""
echo "🎉 Integration complete!"
echo "Run: /tmp/final-setup.sh to start the panel with FakeTLS support!"