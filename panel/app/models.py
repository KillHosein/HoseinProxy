from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=True)

class Proxy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    port = db.Column(db.Integer, unique=True, nullable=False)
    secret = db.Column(db.String(100), nullable=False)
    proxy_type = db.Column(db.String(20), default="standard")
    tls_domain = db.Column(db.String(255), nullable=True)
    tag = db.Column(db.String(100), nullable=True)
    workers = db.Column(db.Integer, default=1)
    container_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="stopped") # running, stopped, paused, error
    
    # Traffic stats (cumulative)
    upload = db.Column(db.BigInteger, default=0) # bytes
    download = db.Column(db.BigInteger, default=0) # bytes
    active_connections = db.Column(db.Integer, default=0)
    upload_rate_bps = db.Column(db.BigInteger, default=0)
    download_rate_bps = db.Column(db.BigInteger, default=0)
    quota_bytes = db.Column(db.BigInteger, default=0)
    quota_start = db.Column(db.DateTime, nullable=True)
    quota_base_upload = db.Column(db.BigInteger, default=0)
    quota_base_download = db.Column(db.BigInteger, default=0)
    expiry_date = db.Column(db.DateTime, nullable=True)
    telegram_chat_id = db.Column(db.String(50), nullable=True) # Per-user chat ID override if needed later
    username = db.Column(db.String(100), nullable=True) # For SOCKS5 or future use
    password = db.Column(db.String(100), nullable=True) # For SOCKS5 or future use
    proxy_ip = db.Column(db.String(50), nullable=True) # Specific Bind IP for this proxy
    name = db.Column(db.String(100), nullable=True) # User friendly name for the proxy

class ProxyStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proxy_id = db.Column(db.Integer, db.ForeignKey('proxy.id'), nullable=False)
    upload = db.Column(db.BigInteger, default=0)
    download = db.Column(db.BigInteger, default=0)
    active_connections = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    proxy_id = db.Column(db.Integer, db.ForeignKey('proxy.id'), nullable=True)
    severity = db.Column(db.String(20), default="warning")
    message = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)

class BlockedIP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(50), unique=True, nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
