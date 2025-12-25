import os
import sys
import secrets
import docker
import psutil
import threading
import time
import subprocess
import tarfile
import shutil
import requests
import ipaddress
from collections import defaultdict, deque
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import OperationalError
from sqlalchemy import inspect, text, func
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

# Configuration Class
class Config:
    # Persistent Secret Key
    key_file = os.path.join(os.path.dirname(__file__), 'secret.key')
    if os.path.exists(key_file):
        with open(key_file, 'r') as f:
            SECRET_KEY = f.read().strip()
    else:
        SECRET_KEY = secrets.token_hex(32)
        try:
            with open(key_file, 'w') as f:
                f.write(SECRET_KEY)
        except:
            pass
            
    SQLALCHEMY_DATABASE_URI = os.environ.get('HOSEINPROXY_DATABASE_URI', 'sqlite:///panel.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

# App Initialization
app = Flask(__name__)
app.config.from_object(Config)

# Extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

# Security: Rate Limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://"
)

# Docker Client Initialization
try:
    docker_client = docker.from_env()
except Exception as e:
    print(f"Warning: Docker connection failed. {e}")
    docker_client = None

# --- Models ---
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
    telegram_chat_id = db.Column(db.String(50), nullable=True) # Per-user chat ID override if needed later, but for now we use global settings


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


_db_initialized = False
_db_init_lock = threading.Lock()

_live_connections_lock = threading.Lock()
_conn_first_seen = {}
_live_connections = defaultdict(list)

_rate_lock = threading.Lock()
_last_bytes = {}

_geo_lock = threading.Lock()
_geo_cache = {}
_geo_cache_expiry = {}

_alerts_lock = threading.Lock()
_last_alert_by_key = {}

# --- Helpers ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_activity(action, details=None):
    try:
        ip = request.remote_addr if request else 'CLI'
        log = ActivityLog(action=action, details=details, ip_address=ip)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Logging Error: {e}")

def get_setting(key, default=None):
    s = Settings.query.filter_by(key=key).first()
    return s.value if s else default

def set_setting(key, value):
    s = Settings.query.filter_by(key=key).first()
    if not s:
        s = Settings(key=key)
        db.session.add(s)
    s.value = value
    db.session.commit()

def get_system_metrics():
    """Returns system metrics for the API"""
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        
        return {
            "cpu": cpu,
            "mem_percent": mem.percent,
            "mem_used": round(mem.used / (1024**3), 2),
            "mem_total": round(mem.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "net_sent": round(net.bytes_sent / (1024**2), 2),
            "net_recv": round(net.bytes_recv / (1024**2), 2)
        }
    except Exception as e:
        return {"error": str(e)}

def _ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        db.create_all()
        inspector = inspect(db.engine)
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
                ('created_at', 'ALTER TABLE proxy ADD COLUMN created_at DATETIME'),
            ]
            with db.engine.connect() as conn:
                for col, stmt in migrations:
                    if col not in columns:
                        conn.execute(text(stmt))
                conn.commit()
        _db_initialized = True

@app.before_request
def _before_request():
    try:
        _ensure_db_initialized()
    except Exception as e:
        print(f"DB Init Error: {e}")

def _is_private_ip(ip_str):
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
    except Exception:
        return False

def _lookup_country(ip_str):
    if not ip_str or _is_private_ip(ip_str):
        return "Local"
    now = time.time()
    with _geo_lock:
        if ip_str in _geo_cache and _geo_cache_expiry.get(ip_str, 0) > now:
            return _geo_cache[ip_str]
    country = "Unknown"
    try:
        if sys.platform.startswith('linux') and shutil.which("geoiplookup"):
            out = subprocess.check_output(["geoiplookup", ip_str], timeout=1).decode(errors='ignore').strip()
            if ":" in out:
                country = out.split(":", 1)[1].strip()
    except Exception:
        country = "Unknown"
    with _geo_lock:
        _geo_cache[ip_str] = country
        _geo_cache_expiry[ip_str] = now + 86400
    return country

def _format_duration(seconds):
    if seconds < 0:
        seconds = 0
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02}:{m:02}:{s:02}"
    return f"{m:02}:{s:02}"

def _quota_usage_bytes(proxy):
    if not proxy.quota_start:
        return None
    used_upload = max(0, int(proxy.upload) - int(proxy.quota_base_upload or 0))
    used_download = max(0, int(proxy.download) - int(proxy.quota_base_download or 0))
    return used_upload + used_download

def _send_telegram_alert(message):
    try:
        bot_token = get_setting('telegram_bot_token')
        chat_id = get_setting('telegram_chat_id')
        if not bot_token or not chat_id:
            return
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": message}
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def _maybe_emit_alert(proxy_id, severity, message, key, cooldown_seconds=60):
    now = datetime.utcnow()
    with _alerts_lock:
        last = _last_alert_by_key.get(key)
        if last and (now - last).total_seconds() < cooldown_seconds:
            return
        _last_alert_by_key[key] = now
    try:
        alert = Alert(proxy_id=proxy_id, severity=severity, message=message)
        db.session.add(alert)
        db.session.commit()
        
        # Send Telegram notification for warnings/errors
        if severity in ['warning', 'error', 'critical']:
            _send_telegram_alert(f"⚠️ Alert [{severity.upper()}]\n{message}")
            
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _check_proxy_limits(proxies):
    now = datetime.utcnow()
    for p in proxies:
        if p.status != 'running':
            continue
            
        should_stop = False
        reason = ""
        
        # Check Expiry
        if p.expiry_date and now > p.expiry_date:
            should_stop = True
            reason = "Expired"
            
        # Check Quota
        elif p.quota_bytes and p.quota_bytes > 0:
            used = _quota_usage_bytes(p) or 0
            if used >= p.quota_bytes:
                should_stop = True
                reason = "Quota Exceeded"
        
        if should_stop:
            print(f"Stopping proxy {p.port} due to {reason}")
            try:
                if docker_client and p.container_id:
                    container = docker_client.containers.get(p.container_id)
                    container.stop()
                p.status = "stopped"
                log_activity("Auto-Stop", f"Proxy {p.port} stopped due to {reason}")
                _maybe_emit_alert(p.id, "warning", f"پروکسی {p.port} به دلیل {reason} متوقف شد.", f"autostop:{p.id}")
            except Exception as e:
                print(f"Error auto-stopping proxy {p.port}: {e}")

def _apply_firewall_rule(ip, action='block'):
    """Applies iptables rule for a specific IP"""
    if not sys.platform.startswith('linux'):
        return
        
    try:
        # Check if rule exists
        check_cmd = f"iptables -C INPUT -s {ip} -j DROP"
        rule_exists = subprocess.call(check_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
        
        if action == 'block':
            if not rule_exists:
                # Add DROP rule to INPUT and FORWARD chains
                subprocess.check_call(f"iptables -I INPUT -s {ip} -j DROP", shell=True)
                subprocess.check_call(f"iptables -I FORWARD -s {ip} -j DROP", shell=True)
                # print(f"Blocked IP {ip}")
        elif action == 'unblock':
            if rule_exists:
                # Remove rule (might need loop if duplicates exist, but -D removes one)
                try:
                    subprocess.check_call(f"iptables -D INPUT -s {ip} -j DROP", shell=True)
                    subprocess.check_call(f"iptables -D FORWARD -s {ip} -j DROP", shell=True)
                except:
                    pass
                # print(f"Unblocked IP {ip}")
    except Exception as e:
        print(f"Firewall Error ({action} {ip}): {e}")

def _sync_firewall():
    """Syncs DB blocked IPs with iptables on startup"""
    if not sys.platform.startswith('linux'):
        return
    try:
        blocked = BlockedIP.query.all()
        for b in blocked:
            _apply_firewall_rule(b.ip_address, 'block')
    except:
        pass

# --- Background Task for Stats ---
def update_docker_stats():
    """Periodically updates proxy traffic stats from Docker"""
    # Wait for tables to be created
    while True:
        try:
            with app.app_context():
                _ensure_db_initialized()
                inspector = inspect(db.engine)
                if inspector.has_table("proxy"):
                    _sync_firewall()
                    break
        except:
            time.sleep(2)
            
    last_stats_sample = datetime.utcnow() - timedelta(minutes=2)
    
    while True:
        try:
            with app.app_context():
                if docker_client:
                    proxies = Proxy.query.filter(Proxy.container_id != None).all()
                    
                    # Get all network connections once to save resources
                    try:
                        all_connections = psutil.net_connections(kind='tcp')
                    except Exception as psutil_error:
                        # print(f"Psutil Error: {psutil_error}")
                        all_connections = []
                    
                    for p in proxies:
                        try:
                            # 1. Try internal stats first (Most accurate for MTProto Proxy)
                            # MTProto proxy usually exposes stats on http://container_ip:8888/stats
                            internal_stats_found = False
                            if sys.platform.startswith('linux'):
                                try:
                                    container_ip = container.attrs.get('NetworkSettings', {}).get('IPAddress')
                                    if not container_ip:
                                         nets = container.attrs.get('NetworkSettings', {}).get('Networks', {})
                                         if nets:
                                             container_ip = list(nets.values())[0].get('IPAddress')
                                    
                                    if container_ip:
                                        # Try port 8888 (standard)
                                        resp = requests.get(f"http://{container_ip}:8888/stats", timeout=1)
                                        if resp.status_code == 200:
                                            # Default MTProto Proxy stats format (not JSON, simple text)
                                            # Or sometimes JSON if using other images.
                                            # Official one returns text like:
                                            # active_connections 1
                                            # ...
                                            # But let's check what keys are there.
                                            # Official telegrammessenger/proxy might not expose bytes per direction easily via stats.
                                            # But let's assume if user says "Equal", they rely on interface stats.
                                            pass
                                except:
                                    pass

                            # 2. Interface Stats (Docker API / IPTables)
                            rx = 0
                            tx = 0
                            
                            # Method: IPTables with Port Detection (Best for distinguishing Client Upload)
                            iptables_success = False
                            if sys.platform.startswith('linux'):
                                try:
                                    container_ip = container.attrs.get('NetworkSettings', {}).get('IPAddress')
                                    if not container_ip:
                                        nets = container.attrs.get('NetworkSettings', {}).get('Networks', {})
                                        if nets:
                                            container_ip = list(nets.values())[0].get('IPAddress')
                                    
                                    if container_ip:
                                        cmd = "iptables -nvx -L FORWARD"
                                        output = subprocess.check_output(cmd, shell=True).decode()
                                        
                                        ipt_client_upload = 0   # dst=container dpt=port
                                        ipt_total_tx = 0        # src=container (All outgoing)
                                        ipt_total_rx = 0        # dst=container (All incoming)
                                        
                                        for line in output.split('\n'):
                                            if container_ip in line:
                                                parts = line.split()
                                                if len(parts) >= 8:
                                                    try:
                                                        b = int(parts[1])
                                                        src = parts[7]
                                                        dst = parts[8]
                                                        
                                                        if dst == container_ip:
                                                            ipt_total_rx += b
                                                            # Check if this rule targets the proxy port
                                                            if f"dpt:{p.port}" in line:
                                                                ipt_client_upload += b
                                                        elif src == container_ip:
                                                            ipt_total_tx += b
                                                    except:
                                                        pass
                                        
                                        if ipt_total_rx > 0 or ipt_total_tx > 0:
                                            # Heuristic:
                                            # Client Upload = ipt_client_upload (Traffic hitting the proxy port)
                                            # Client Download = Total TX - Client Upload (Traffic leaving container minus traffic sent to web/DC)
                                            # Wait, Total TX = Client Download + Web Upload.
                                            # And Web Upload (to DC) is roughly equal to Client Upload.
                                            # So Client Download ≈ Total TX - Client Upload.
                                            
                                            # Fallback if dpt match not found (ipt_client_upload == 0)
                                            if ipt_client_upload == 0:
                                                # Assume 10% upload, 90% download? Or just split equally?
                                                # User wants "Different". 
                                                # Let's assume standard proxy usage: mostly download.
                                                # But if we can't measure, sticking to Total is safer than guessing.
                                                # However, to fix "Equal" complaint, we can try:
                                                rx = ipt_total_rx
                                                tx = ipt_total_tx
                                            else:
                                                # We have a specific upload measurement!
                                                p_upload = ipt_client_upload
                                                p_download = max(0, ipt_total_tx - ipt_client_upload)
                                                
                                                # Override rx/tx with these interpreted values
                                                rx = p_download # User Download (Server -> User)
                                                tx = p_upload   # User Upload (User -> Server)
                                                
                                                # Note: in database 'download' is usually traffic sent to user.
                                                # 'upload' is traffic received from user.
                                                # So:
                                                # p.download = rx (Server->User)
                                                # p.upload = tx (User->Server)
                                                
                                                iptables_success = True
                                except Exception as e:
                                    # print(f"IPTables Error: {e}")
                                    pass

                            # 3. Fallback to Docker Stats (Interface Total) if IPTables failed
                            if not iptables_success:
                                container = docker_client.containers.get(p.container_id)
                                stats = container.stats(stream=False)
                                networks = stats.get('networks', {})
                                raw_rx = 0
                                raw_tx = 0
                                for iface, data in networks.items():
                                    raw_rx += data.get('rx_bytes', 0)
                                    raw_tx += data.get('tx_bytes', 0)
                                
                                # Fallback /proc/net/dev
                                if raw_rx == 0 and raw_tx == 0:
                                     # ... (proc code omitted for brevity, similar to before) ...
                                     # Let's reuse existing logic structure but apply heuristic
                                     pass

                                # Apply Heuristic to Interface Stats if we couldn't separate them
                                # Interface RX = Client Upload + Web Download
                                # Interface TX = Client Download + Web Upload
                                # Web Download ≈ Client Download
                                # Web Upload ≈ Client Upload
                                # So Raw RX ≈ Raw TX ≈ Total Traffic / 2
                                
                                # To give user "Different" values, we can't do much without port info.
                                # But we can approximate Client Download = Raw TX / 2 ?? No, that's just dividing by 2.
                                # It's better to show raw values but maybe label them "Total Traffic"?
                                # User complained they are EQUAL.
                                # If we assign p.download = raw_rx and p.upload = raw_tx, they are equal.
                                
                                # Let's try to assume "Download" is the dominant factor and "Upload" is small.
                                # But that's lying.
                                
                                # If iptables failed, we likely can't fix it perfectly.
                                # But let's stick to the previous logic for fallback, 
                                # OR try to run the iptables logic block above as primary.
                                
                                rx = raw_rx
                                tx = raw_tx
                            
                            # Final assignment (iptables logic might have already set it)
                            if iptables_success:
                                p.download = rx
                                p.upload = tx
                            else:
                                # Legacy/Fallback: Interface stats (Equal-ish)
                                # If we want to hack it to look "real":
                                # Client Download ≈ Interface TX / 2 * 1.05?
                                # No, let's keep it honest for fallback.
                                p.download = rx
                                p.upload = tx

                            # Method 2: Fallback to /proc/net/dev inside container if Docker stats fail or return 0
                            if not iptables_success and rx == 0 and tx == 0:
                                try:
                                    # Method 2a: IPTables (Most accurate for Docker if running as root)
                                    # ... (Moved logic up) ...
                                    pass

                                    # Method 2b: /proc/net/dev (Fallback if IPTables fails or returns 0)
                                    if rx == 0 and tx == 0:
                                        # Try reading directly from Host /proc (Faster & More Reliable)
                                        pid = container.attrs.get('State', {}).get('Pid')
                                        if pid and os.path.exists(f"/proc/{pid}/net/dev"):
                                            with open(f"/proc/{pid}/net/dev", "r") as f:
                                                output_str = f.read()
                                                for line in output_str.split('\n'):
                                                    if ':' in line:
                                                        parts = line.split(':')
                                                        iface_name = parts[0].strip()
                                                        if iface_name == 'lo': continue
                                                        values = parts[1].split()
                                                        if len(values) >= 9:
                                                            rx += int(values[0])
                                                            tx += int(values[8])
                                        else:
                                            # Fallback to docker exec
                                            exit_code, output = container.exec_run("cat /proc/net/dev")
                                            if exit_code != 0:
                                                 exit_code, output = container.exec_run("ip -s link")
                                                 
                                            if exit_code == 0:
                                                output_str = output.decode('utf-8')
                                                if "Receive" in output_str or "Inter-" in output_str:
                                                    for line in output_str.split('\n'):
                                                        if ':' in line:
                                                            parts = line.split(':')
                                                            iface_name = parts[0].strip()
                                                            if iface_name == 'lo': continue
                                                            values = parts[1].split()
                                                            if len(values) >= 9:
                                                                rx += int(values[0])
                                                                tx += int(values[8])
                                except Exception as e2:
                                    pass
                            
                            if not iptables_success:
                                p.download = rx
                                p.upload = tx

                            with _rate_lock:
                                prev = _last_bytes.get(p.id)
                                _last_bytes[p.id] = (tx, rx, time.time())
                            if prev:
                                prev_tx, prev_rx, prev_time = prev
                                dt = max(1e-3, time.time() - prev_time)
                                p.upload_rate_bps = int(max(0, tx - prev_tx) / dt)
                                p.download_rate_bps = int(max(0, rx - prev_rx) / dt)
                            else:
                                p.upload_rate_bps = 0
                                p.download_rate_bps = 0
                            if p.quota_start and (p.quota_base_upload == 0 and p.quota_base_download == 0):
                                p.quota_base_upload = int(tx)
                                p.quota_base_download = int(rx)
                            
                            # 2. Update Active Connections
                            # Method 1: psutil (Works if running on host or same net namespace)
                            conns = [c for c in all_connections if c.laddr.port == p.port and c.status == 'ESTABLISHED']
                            count = len(conns)

                            # Method 2: ss command (Linux only, more reliable for systemd services)
                            if count == 0 and sys.platform.startswith('linux'):
                                try:
                                    # Try ss (Socket Statistics)
                                    cmd = f"ss -tnH state established sport = :{p.port} | wc -l"
                                    output = subprocess.check_output(cmd, shell=True).decode().strip()
                                    if output.isdigit() and int(output) > 0:
                                        count = int(output)
                                    
                                    # Method 3: conntrack (if ss fails or returns 0, try netfilter conntrack)
                                    if count == 0 and os.path.exists("/proc/net/nf_conntrack"):
                                        # Count established connections in conntrack for this port
                                        # Line format: ... sport=443 ...
                                        with open("/proc/net/nf_conntrack", "r") as f:
                                            conntrack_data = f.read()
                                            # Simple counting of lines containing sport={port} and ESTABLISHED
                                            # Note: Docker maps host port to container port. Users connect to host port.
                                            # We need to count dport={port} (destination port from client perspective)
                                            # But in conntrack it might appear as dport={port} in original direction.
                                            term1 = f"dport={p.port}"
                                            term2 = "ESTABLISHED"
                                            c_count = 0
                                            for line in conntrack_data.split('\n'):
                                                if term1 in line and term2 in line:
                                                    c_count += 1
                                            if c_count > 0:
                                                count = c_count
                                except Exception as e_ss:
                                    # print(f"SS/Conntrack Error: {e_ss}")
                                    pass

                            p.active_connections = count
                                
                            # Method 4: Netstat (Classic tool)
                            if count == 0 and sys.platform.startswith('linux'):
                                try:
                                    # netstat -tn | grep :PORT | grep ESTABLISHED
                                    cmd = f"netstat -tn 2>/dev/null | grep ':{p.port} ' | grep ESTABLISHED | wc -l"
                                    output = subprocess.check_output(cmd, shell=True).decode().strip()
                                    if output.isdigit():
                                        count = int(output)
                                except:
                                    pass

                            p.active_connections = count
                                
                        except Exception as e:
                            # Container might be stopped or deleted
                            # print(f"Error updating proxy {p.port}: {e}")
                            continue
                    
                    if proxies:
                        _check_proxy_limits(proxies)
                        db.session.commit()
                        # print("Stats updated successfully.")
                    
                    now = datetime.utcnow()
                    if (now - last_stats_sample).total_seconds() >= 60:
                        for p in proxies:
                            stat = ProxyStats(
                                proxy_id=p.id,
                                upload=p.upload,
                                download=p.download,
                                active_connections=p.active_connections,
                                timestamp=now
                            )
                            db.session.add(stat)
                        db.session.commit()
                        last_stats_sample = now
                        cutoff = now - timedelta(days=30)
                        ProxyStats.query.filter(ProxyStats.timestamp < cutoff).delete()
                        Alert.query.filter(Alert.created_at < cutoff).delete()
                        db.session.commit()

                    now_epoch = time.time()
                    new_live = defaultdict(list)
                    ip_counts = defaultdict(int)
                    current_conn_keys = set()
                    for p in proxies:
                        conns = [c for c in all_connections if c.laddr.port == p.port and c.status == 'ESTABLISHED']
                        for c in conns:
                            if not c.raddr:
                                continue
                            ip = getattr(c.raddr, "ip", None) or c.raddr[0]
                            rport = getattr(c.raddr, "port", None) or c.raddr[1]
                            conn_key = (p.id, ip, int(rport), int(p.port))
                            current_conn_keys.add(conn_key)
                            first_seen = _conn_first_seen.get(conn_key)
                            if not first_seen:
                                _conn_first_seen[conn_key] = now_epoch
                                first_seen = now_epoch
                            ip_counts[(p.id, ip)] += 1
                            new_live[p.id].append({
                                "ip": ip,
                                "country": _lookup_country(ip),
                                "connected_for": _format_duration(now_epoch - first_seen),
                                "connected_for_seconds": int(now_epoch - first_seen),
                                "remote_port": int(rport)
                            })
                    with _live_connections_lock:
                        _live_connections.clear()
                        _live_connections.update(new_live)
                        to_del = [k for k in _conn_first_seen.keys() if k not in current_conn_keys]
                        for k in to_del:
                            _conn_first_seen.pop(k, None)

                    alert_total_threshold = int(get_setting("alert_conn_threshold", "300") or 300)
                    alert_per_ip_threshold = int(get_setting("alert_ip_conn_threshold", "20") or 20)
                    for p in proxies:
                        if p.active_connections >= alert_total_threshold:
                            _maybe_emit_alert(p.id, "warning", f"اتصالات غیرعادی روی پورت {p.port}: {p.active_connections}", f"total:{p.id}")
                        for (pid, ip), cnt in ip_counts.items():
                            if pid != p.id:
                                continue
                            if cnt >= alert_per_ip_threshold:
                                _maybe_emit_alert(p.id, "warning", f"اتصالات زیاد از یک IP روی پورت {p.port}: {ip} ({cnt})", f"ip:{p.id}:{ip}")
                                
                                # Auto-Block Logic
                                try:
                                    auto_block = get_setting('auto_block_enabled', '0') == '1'
                                    if auto_block:
                                        if not BlockedIP.query.filter_by(ip_address=ip).first():
                                            b = BlockedIP(ip_address=ip, reason=f"Auto-Block: {cnt} connections on port {p.port}")
                                            db.session.add(b)
                                            db.session.commit()
                                            _apply_firewall_rule(ip, 'block')
                                            log_activity("Auto-Block", f"Blocked IP {ip} due to high connections")
                                            _send_telegram_alert(f"🚫 Auto-Blocked IP {ip}\nReason: High connections ({cnt}) on port {p.port}")
                                except Exception as e:
                                    print(f"Auto-Block Error: {e}")


        except OperationalError:
             print("DB Operational Error in Stats Thread. Retrying...")
        except Exception as e:
            print(f"Stats Loop Error: {e}")
        
        time.sleep(3) # Run every 3 seconds for real-time feel

if os.environ.get("HOSEINPROXY_DISABLE_STATS_THREAD", "0") != "1":
    stats_thread = threading.Thread(target=update_docker_stats, daemon=True)
    stats_thread.start()

# --- Routes ---

@app.context_processor
def inject_globals():
    return {
        'now': datetime.utcnow(),
        'server_ip': get_setting('server_ip', request.host.split(':')[0]),
        'server_domain': get_setting('server_domain', '')
    }

@app.route('/')
@login_required
def dashboard():
    proxies = Proxy.query.order_by(Proxy.created_at.desc()).all()
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    
    # Sync status
    if docker_client:
        try:
            running_containers = {c.id: c.status for c in docker_client.containers.list()}
            for p in proxies:
                if p.container_id:
                    if p.container_id in running_containers:
                        p.status = "running"
                    else:
                         try:
                             c = docker_client.containers.get(p.container_id)
                             p.status = c.status
                         except docker.errors.NotFound:
                             p.status = "deleted"
                         except:
                             p.status = "unknown"
                else:
                    p.status = "stopped"
            db.session.commit()
        except Exception as e:
            print(f"Sync Error: {e}")

    return render_template('dashboard.html', proxies=proxies, logs=logs)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        if 'server_ip' in request.form:
            set_setting('server_ip', request.form.get('server_ip'))
        if 'server_domain' in request.form:
            set_setting('server_domain', request.form.get('server_domain'))
        if 'alert_conn_threshold' in request.form:
            set_setting('alert_conn_threshold', request.form.get('alert_conn_threshold'))
        if 'alert_ip_conn_threshold' in request.form:
            set_setting('alert_ip_conn_threshold', request.form.get('alert_ip_conn_threshold'))
        if 'telegram_bot_token' in request.form:
            set_setting('telegram_bot_token', request.form.get('telegram_bot_token'))
        if 'telegram_chat_id' in request.form:
            set_setting('telegram_chat_id', request.form.get('telegram_chat_id'))
        if 'auto_block_enabled' in request.form:
            set_setting('auto_block_enabled', '1' if request.form.get('auto_block_enabled') == 'on' else '0')
        else:
            # Handle checkbox unchecked case if it was present in form but unchecked
            # But since this is a unified settings route, we should be careful.
            # If the form was submitted from the settings page, it should have a hidden field or we check context.
            # For simplicity, if we are saving settings, we assume checkbox presence logic.
            # Actually, let's just check if it's a settings form submit.
            # A safer way for checkboxes in update forms:
            if request.form.get('settings_form_submitted') == '1':
                 set_setting('auto_block_enabled', '1' if request.form.get('auto_block_enabled') == 'on' else '0')
            
        flash('تنظیمات ذخیره شد.', 'success')
        return redirect(url_for('settings'))
        
    return render_template('settings.html', 
                           server_ip=get_setting('server_ip', ''),
                           server_domain=get_setting('server_domain', ''),
                           alert_conn_threshold=get_setting('alert_conn_threshold', '300'),
                           alert_ip_conn_threshold=get_setting('alert_ip_conn_threshold', '20'),
                           telegram_bot_token=get_setting('telegram_bot_token', ''),
                           telegram_chat_id=get_setting('telegram_chat_id', ''),
                           auto_block_enabled=get_setting('auto_block_enabled', '0'))

@app.route('/firewall')
@login_required
def firewall():
    blocked_ips = BlockedIP.query.order_by(BlockedIP.created_at.desc()).all()
    return render_template('firewall.html', blocked_ips=blocked_ips)

@app.route('/firewall/add', methods=['POST'])
@login_required
def firewall_add():
    ip = request.form.get('ip')
    reason = request.form.get('reason')
    if ip:
        if not BlockedIP.query.filter_by(ip_address=ip).first():
            b = BlockedIP(ip_address=ip, reason=reason)
            db.session.add(b)
            db.session.commit()
            _apply_firewall_rule(ip, 'block')
            log_activity("Firewall Block", f"Blocked IP {ip}: {reason}")
            flash(f'آی‌پی {ip} مسدود شد.', 'success')
        else:
            flash('این آی‌پی قبلاً مسدود شده است.', 'warning')
    return redirect(url_for('firewall'))

@app.route('/firewall/delete/<int:id>')
@login_required
def firewall_delete(id):
    b = BlockedIP.query.get_or_404(id)
    ip = b.ip_address
    db.session.delete(b)
    db.session.commit()
    _apply_firewall_rule(ip, 'unblock')
    log_activity("Firewall Unblock", f"Unblocked IP {ip}")
    flash(f'آی‌پی {ip} آزاد شد.', 'success')
    return redirect(url_for('firewall'))

@app.route('/proxy/bulk_create', methods=['POST'])
@login_required
def bulk_create_proxies():
    start_port = request.form.get('start_port', type=int)
    count = request.form.get('count', type=int)
    tag = request.form.get('tag')
    
    if not start_port or not count or count < 1:
        flash('اطلاعات نامعتبر است.', 'danger')
        return redirect(url_for('dashboard'))
        
    if count > 50:
        flash('تعداد بالا (حداکثر ۵۰) مجاز نیست.', 'danger')
        return redirect(url_for('dashboard'))

    success_count = 0
    errors = []
    
    current_port = start_port
    
    # Pre-check ports
    existing_ports = {p.port for p in Proxy.query.all()}
    
    for _ in range(count):
        while current_port in existing_ports:
            current_port += 1
            
        try:
            secret = secrets.token_hex(16)
            container = docker_client.containers.run(
                'telegrammessenger/proxy',
                detach=True,
                ports={'443/tcp': current_port},
                environment={
                    'SECRET': secret,
                    'TAG': tag,
                    'WORKERS': 1
                },
                restart_policy={"Name": "always"},
                name=f"mtproto_{current_port}"
            )
            
            p = Proxy(
                port=current_port,
                secret=secret,
                tag=tag,
                workers=1,
                container_id=container.id,
                status="running"
            )
            db.session.add(p)
            existing_ports.add(current_port) # Update local cache
            success_count += 1
            current_port += 1
            
        except Exception as e:
            errors.append(f"Port {current_port}: {e}")
            current_port += 1 # Skip this port
            
    db.session.commit()
    log_activity("Bulk Create", f"Created {success_count} proxies starting from {start_port}")
    
    if errors:
        flash(f'{success_count} پروکسی ساخته شد. خطاها: {", ".join(errors[:3])}...', 'warning')
    else:
        flash(f'{success_count} پروکسی با موفقیت ساخته شد.', 'success')
        
    return redirect(url_for('dashboard'))


@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/api/reports/top_ips')
@login_required
def api_reports_top_ips():
    # Simple aggregation from ActivityLog or we could use ProxyStats if we stored IP-level stats there
    # For now, let's look at current live connections snapshot or ActivityLog
    # Since we don't store historical IP traffic in DB yet, we can show "Top IPs currently connected"
    
    with _live_connections_lock:
        all_conns = []
        for pid, conns in _live_connections.items():
            for c in conns:
                c['proxy_id'] = pid
                all_conns.append(c)
                
    # Count by IP
    ip_counts = defaultdict(int)
    ip_details = {}
    for c in all_conns:
        ip = c['ip']
        ip_counts[ip] += 1
        if ip not in ip_details:
            ip_details[ip] = c['country']
            
    sorted_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    
    result = []
    for ip, count in sorted_ips:
        result.append({
            "ip": ip,
            "country": ip_details.get(ip, "Unknown"),
            "connections": count
        })
        
    return jsonify(result)

@app.route('/api/reports/traffic_by_tag')
@login_required
def api_reports_traffic_by_tag():
    # Group proxies by tag and sum upload/download
    proxies = Proxy.query.all()
    tag_stats = defaultdict(lambda: {'upload': 0, 'download': 0, 'count': 0})
    
    for p in proxies:
        tag = p.tag or "بدون تگ"
        tag_stats[tag]['upload'] += p.upload
        tag_stats[tag]['download'] += p.download
        tag_stats[tag]['count'] += 1
        
    result = []
    for tag, stats in tag_stats.items():
        result.append({
            "tag": tag,
            "upload_gb": round(stats['upload'] / (1024**3), 3),
            "download_gb": round(stats['download'] / (1024**3), 3),
            "total_gb": round((stats['upload'] + stats['download']) / (1024**3), 3),
            "proxy_count": stats['count']
        })
        
    result.sort(key=lambda x: x['total_gb'], reverse=True)
    return jsonify(result)


@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_system_metrics())

@app.route('/api/proxies')
@login_required
def api_proxies():
    proxies = Proxy.query.all()
    data = []
    for p in proxies:
        quota_used = _quota_usage_bytes(p)
        quota_remaining = None
        if p.quota_bytes and p.quota_bytes > 0 and quota_used is not None:
            quota_remaining = max(0, int(p.quota_bytes) - int(quota_used))
        data.append({
            'id': p.id,
            'status': p.status,
            'active_connections': p.active_connections,
            'upload': round(p.upload / (1024*1024), 2),
            'download': round(p.download / (1024*1024), 2),
            'upload_rate_mbps': round((p.upload_rate_bps * 8) / (1024*1024), 3),
            'download_rate_mbps': round((p.download_rate_bps * 8) / (1024*1024), 3),
            'quota_mb': round((p.quota_bytes or 0) / (1024*1024), 2),
            'quota_used_mb': round((quota_used or 0) / (1024*1024), 2) if quota_used is not None else None,
            'quota_remaining_mb': round((quota_remaining or 0) / (1024*1024), 2) if quota_remaining is not None else None
        })
    return jsonify(data)

@app.route('/api/proxy/<int:proxy_id>/connections')
@login_required
def api_proxy_connections(proxy_id):
    ip_filter = (request.args.get("ip") or "").strip()
    country_filter = (request.args.get("country") or "").strip()
    with _live_connections_lock:
        items = list(_live_connections.get(proxy_id, []))
    if ip_filter:
        items = [it for it in items if ip_filter in (it.get("ip") or "")]
    if country_filter:
        items = [it for it in items if country_filter.lower() in (it.get("country") or "").lower()]
    items.sort(key=lambda x: x.get("connected_for_seconds", 0), reverse=True)
    return jsonify({
        "proxy_id": proxy_id,
        "active_connections": len(items),
        "items": items[:500]
    })

@app.route('/api/proxy/<int:proxy_id>/connections_history')
@login_required
def api_proxy_connections_history(proxy_id):
    minutes = request.args.get("minutes", default=60, type=int)
    minutes = max(5, min(24 * 60, minutes))
    end = datetime.utcnow()
    start = end - timedelta(minutes=minutes)
    rows = ProxyStats.query.filter(
        ProxyStats.proxy_id == proxy_id,
        ProxyStats.timestamp >= start,
        ProxyStats.timestamp <= end
    ).order_by(ProxyStats.timestamp.asc()).all()
    labels = [r.timestamp.strftime('%H:%M') for r in rows]
    values = [int(r.active_connections or 0) for r in rows]
    return jsonify({"labels": labels, "values": values})

def _compute_usage_series(rows, granularity):
    if not rows:
        return {"labels": [], "upload_mb": [], "download_mb": []}
    rows = sorted(rows, key=lambda r: r.timestamp)
    groups = defaultdict(list)
    for r in rows:
        if granularity == "hourly":
            key = r.timestamp.strftime('%Y-%m-%d %H:00')
        elif granularity == "monthly":
            key = r.timestamp.strftime('%Y-%m')
        else:
            key = r.timestamp.strftime('%Y-%m-%d')
        groups[key].append(r)
    labels = []
    upload_mb = []
    download_mb = []
    for k in sorted(groups.keys()):
        items = groups[k]
        first = items[0]
        last = items[-1]
        du = max(0, int(last.upload or 0) - int(first.upload or 0))
        dd = max(0, int(last.download or 0) - int(first.download or 0))
        labels.append(k)
        upload_mb.append(round(du / (1024 * 1024), 2))
        download_mb.append(round(dd / (1024 * 1024), 2))
    return {"labels": labels, "upload_mb": upload_mb, "download_mb": download_mb}

@app.route('/api/proxy/<int:proxy_id>/usage_history')
@login_required
def api_proxy_usage_history(proxy_id):
    granularity = (request.args.get("granularity") or "daily").strip().lower()
    if granularity not in ("hourly", "daily", "monthly"):
        granularity = "daily"
    days = request.args.get("days", default=7, type=int)
    days = max(1, min(60, days))
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    rows = ProxyStats.query.filter(
        ProxyStats.proxy_id == proxy_id,
        ProxyStats.timestamp >= start,
        ProxyStats.timestamp <= end
    ).order_by(ProxyStats.timestamp.asc()).all()
    return jsonify(_compute_usage_series(rows, granularity))

@app.route('/api/alerts')
@login_required
def api_alerts():
    since_id = request.args.get("since_id", default=0, type=int)
    q = Alert.query.filter(Alert.id > since_id).order_by(Alert.id.asc()).limit(50).all()
    data = []
    for a in q:
        data.append({
            "id": a.id,
            "proxy_id": a.proxy_id,
            "severity": a.severity,
            "message": a.message,
            "created_at": a.created_at.isoformat() + "Z",
            "resolved": bool(a.resolved)
        })
    return jsonify(data)

@app.route('/api/history')
@login_required
def api_history():
    """Returns historical traffic data for charts"""
    try:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        # Check if we have any stats
        # If no stats yet, return empty data to prevent errors
        # Note: Since we are not actively populating ProxyStats in the background thread yet (to keep it simple),
        # this will return empty charts. To make it work, we need to populate ProxyStats.
        # For now, let's return a placeholder or real data if it exists.
        
        stats = db.session.query(
            func.date(ProxyStats.timestamp).label('date'),
            func.sum(ProxyStats.upload).label('total_upload'),
            func.sum(ProxyStats.download).label('total_download')
        ).filter(ProxyStats.timestamp >= start_date)\
         .group_by(func.date(ProxyStats.timestamp))\
         .all()
         
        labels = []
        upload_data = []
        download_data = []
        
        for s in stats:
            labels.append(s.date)
            upload_data.append(round(s.total_upload / (1024*1024), 2)) # MB
            download_data.append(round(s.total_download / (1024*1024), 2)) # MB
            
        # If no data, provide last 7 days empty
        if not labels:
            for i in range(7):
                d = start_date + timedelta(days=i)
                labels.append(d.strftime('%Y-%m-%d'))
                upload_data.append(0)
                download_data.append(0)
            
        return jsonify({
            "labels": labels,
            "upload": upload_data,
            "download": download_data
        })
    except Exception as e:
        print(f"History API Error: {e}")
        return jsonify({
            "labels": [],
            "upload": [],
            "download": []
        })

@app.route('/system')
@login_required
def system_page():
    # Get git version
    try:
        current_version = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('utf-8').strip()
    except:
        current_version = "Unknown"
        
    return render_template('system.html', current_version=current_version)

@app.route('/system/check_update', methods=['POST'])
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

@app.route('/system/do_update', methods=['POST'])
@login_required
def do_update():
    try:
        # Run update script in background or via subprocess
        # Using the manage.sh script would be ideal if available, but let's do simple git pull here
        subprocess.check_call(['git', 'pull'])
        subprocess.check_call(['pip', 'install', '-r', 'requirements.txt'])
        
        # Restart service
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
        
        flash('سیستم به‌روزرسانی شد و در حال ریستارت است. لطفاً چند لحظه صبر کنید...', 'success')
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/system/restart_service', methods=['POST'])
@login_required
def restart_service():
    try:
        subprocess.Popen(['systemctl', 'restart', 'hoseinproxy'])
        flash('سرویس در حال ریستارت است...', 'info')
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/system/logs')
@login_required
def system_logs():
    try:
        with open('/var/log/hoseinproxy_manager.log', 'r') as f:
            content = f.read()
        return jsonify({'content': content})
    except:
        return jsonify({'content': 'Log file not found.'})

@app.route('/system/backup', methods=['POST'])
@login_required
def create_backup():
    try:
        backup_dir = "/root/backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{backup_dir}/hoseinproxy_backup_{timestamp}.tar.gz"
        
        # Path to panel directory (current dir)
        panel_dir = os.path.dirname(os.path.abspath(__file__))
        
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(os.path.join(panel_dir, 'panel.db'), arcname='panel.db')
            tar.add(os.path.join(panel_dir, 'app.py'), arcname='app.py')
            tar.add(os.path.join(panel_dir, 'requirements.txt'), arcname='requirements.txt')
            # Add templates and static if needed, but code is in git usually. DB is most important.
            
        return jsonify({'status': 'success', 'path': backup_file})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            log_activity("Login", f"User {username} logged in")
            return redirect(url_for('dashboard'))
        flash('نام کاربری یا رمز عبور اشتباه است.', 'danger')
        log_activity("Login Failed", f"Failed login attempt for {username}")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    log_activity("Logout", f"User {current_user.username} logged out")
    logout_user()
    flash('با موفقیت خارج شدید.', 'success')
    return redirect(url_for('login'))

@app.route('/proxy/add', methods=['POST'])
@login_required
def add_proxy():
    port = request.form.get('port', type=int)
    workers = request.form.get('workers', type=int, default=1)
    tag = request.form.get('tag')
    secret = request.form.get('secret')
    proxy_type = request.form.get('proxy_type', 'standard')
    tls_domain = request.form.get('tls_domain', 'google.com')
    quota_gb = request.form.get('quota_gb', type=float)
    expiry_days = request.form.get('expiry_days', type=int)
    
    quota_bytes = 0
    if quota_gb is not None and quota_gb > 0:
        quota_bytes = int(quota_gb * 1024 * 1024 * 1024)
        
    expiry_date = None
    if expiry_days and expiry_days > 0:
        expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
    
    # Advanced Secret Generation
    if not secret:
        base_hex = secrets.token_hex(16) # 32 chars
        if proxy_type == 'dd':
            secret = 'dd' + base_hex
        elif proxy_type == 'tls':
            # EE + Secret + Hex(Domain)
            domain_hex = tls_domain.encode('utf-8').hex()
            secret = 'ee' + base_hex + domain_hex
        else:
            secret = base_hex
    else:
        # Validate/Fix user provided secret based on type
        if proxy_type == 'dd' and not secret.startswith('dd'):
             secret = 'dd' + secret
        elif proxy_type == 'tls' and not secret.startswith('ee'):
             # If user provided a raw hex, upgrade it to TLS
             domain_hex = tls_domain.encode('utf-8').hex()
             secret = 'ee' + secret + domain_hex

    if not port:
         flash('شماره پورت الزامی است.', 'danger')
         return redirect(url_for('dashboard'))

    if Proxy.query.filter_by(port=port).first():
        flash(f'پورت {port} قبلاً استفاده شده است.', 'warning')
        return redirect(url_for('dashboard'))

    if docker_client:
        try:
            container = docker_client.containers.run(
                'telegrammessenger/proxy',
                detach=True,
                ports={'443/tcp': port},
                environment={
                    'SECRET': secret,
                    'TAG': tag,
                    'WORKERS': workers
                },
                restart_policy={"Name": "always"},
                name=f"mtproto_{port}"
            )
            
            new_proxy = Proxy(
                port=port,
                secret=secret,
                tag=tag,
                workers=workers,
                container_id=container.id,
                status="running",
                quota_bytes=quota_bytes,
                quota_start=datetime.utcnow() if quota_bytes > 0 else None,
                expiry_date=expiry_date
            )
            db.session.add(new_proxy)
            db.session.commit()
            log_activity("Create Proxy", f"Created {proxy_type} proxy on port {port}")
            flash(f'پروکسی {proxy_type} روی پورت {port} با موفقیت ساخته شد.', 'success')
            
        except docker.errors.APIError as e:
             flash(f'خطای داکر: {e}', 'danger')
             log_activity("Docker Error", str(e))
        except Exception as e:
            flash(f'خطای ناشناخته: {e}', 'danger')
            log_activity("System Error", str(e))
    else:
        flash('ارتباط با داکر برقرار نیست.', 'danger')

    return redirect(url_for('dashboard'))

@app.route('/proxy/update/<int:id>', methods=['POST'])
@login_required
def update_proxy(id):
    proxy = Proxy.query.get_or_404(id)
    tag = (request.form.get('tag') or '').strip() or None
    quota_gb = request.form.get('quota_gb', type=float)
    expiry_days = request.form.get('expiry_days', type=int)
    
    quota_bytes = 0
    if quota_gb is not None and quota_gb > 0:
        quota_bytes = int(quota_gb * 1024 * 1024 * 1024)
    
    expiry_date = None
    if expiry_days and expiry_days > 0:
        expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
    elif expiry_days == 0:
         expiry_date = None # Remove expiry if set to 0
    
    try:
        proxy.tag = tag
        proxy.quota_bytes = quota_bytes
        if expiry_days is not None:
             proxy.expiry_date = expiry_date
             
        if quota_bytes > 0 and not proxy.quota_start:
            proxy.quota_start = datetime.utcnow()
            proxy.quota_base_upload = int(proxy.upload or 0)
            proxy.quota_base_download = int(proxy.download or 0)
        if quota_bytes == 0:
            proxy.quota_start = None
            proxy.quota_base_upload = 0
            proxy.quota_base_download = 0
        db.session.commit()
        log_activity("Update Proxy", f"Updated proxy on port {proxy.port}")
        flash('تنظیمات پروکسی ذخیره شد.', 'success')
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash(f'خطا در ذخیره تنظیمات: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/api/activity')
@login_required
def api_activity():
    action = (request.args.get("action") or "").strip()
    ip = (request.args.get("ip") or "").strip()
    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(200, limit))
    q = ActivityLog.query
    if action:
        q = q.filter(ActivityLog.action.ilike(f"%{action}%"))
    if ip:
        q = q.filter(ActivityLog.ip_address.ilike(f"%{ip}%"))
    logs = q.order_by(ActivityLog.timestamp.desc()).limit(limit).all()
    return jsonify([{
        "id": l.id,
        "action": l.action,
        "details": l.details,
        "ip_address": l.ip_address,
        "timestamp": l.timestamp.isoformat() + "Z"
    } for l in logs])

@app.route('/proxy/stop/<int:id>')
@login_required
def stop_proxy(id):
    proxy = Proxy.query.get_or_404(id)
    if docker_client and proxy.container_id:
        try:
            container = docker_client.containers.get(proxy.container_id)
            container.stop()
            proxy.status = "stopped"
            db.session.commit()
            flash('پروکسی متوقف شد.', 'success')
        except Exception as e:
            flash(f'خطا: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/proxy/start/<int:id>')
@login_required
def start_proxy(id):
    proxy = Proxy.query.get_or_404(id)
    if docker_client and proxy.container_id:
        try:
            container = docker_client.containers.get(proxy.container_id)
            container.start()
            proxy.status = "running"
            db.session.commit()
            flash('پروکسی روشن شد.', 'success')
        except Exception as e:
            flash(f'خطا: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/proxy/delete/<int:id>')
@login_required
def delete_proxy(id):
    proxy = Proxy.query.get_or_404(id)
    port = proxy.port
    
    if docker_client and proxy.container_id:
        try:
            try:
                container = docker_client.containers.get(proxy.container_id)
                container.stop()
                container.remove()
            except docker.errors.NotFound:
                pass
        except Exception as e:
            flash(f'خطا در حذف کانتینر: {e}', 'warning')
    
    db.session.delete(proxy)
    db.session.commit()
    log_activity("Delete Proxy", f"Deleted proxy on port {port}")
    flash(f'پروکسی {port} حذف شد.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/proxy/restart/<int:id>')
@login_required
def restart_proxy(id):
    proxy = Proxy.query.get_or_404(id)
    if docker_client and proxy.container_id:
        try:
            container = docker_client.containers.get(proxy.container_id)
            container.restart()
            log_activity("Restart Proxy", f"Restarted proxy on port {proxy.port}")
            flash(f'پروکسی {proxy.port} ریستارت شد.', 'success')
        except Exception as e:
            flash(f'خطا در ریستارت: {e}', 'danger')
    return redirect(url_for('dashboard'))

# --- CLI Commands ---
def create_admin(username, password):
    with app.app_context():
        db.create_all()
        user = User.query.filter_by(username=username).first()
        if not user:
            u = User(username=username)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            print(f"User {username} created successfully.")
        else:
            u.set_password(password)
            db.session.commit()
            print(f"User {username} password updated.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
