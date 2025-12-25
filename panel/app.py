import os
import secrets
import docker
import psutil
import threading
import time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

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
            
    SQLALCHEMY_DATABASE_URI = 'sqlite:///panel.db'
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

# --- Background Task for Stats ---
def update_docker_stats():
    """Periodically updates proxy traffic stats from Docker"""
    # Wait for tables to be created
    while True:
        try:
            with app.app_context():
                # Check if table exists
                db.engine.inspect(db.engine).has_table("proxy")
                break
        except:
            time.sleep(2)
            
    last_history_update = datetime.utcnow() - datetime.timedelta(hours=1, minutes=1) # Force run on start
    
    while True:
        try:
            with app.app_context():
                if docker_client:
                    proxies = Proxy.query.filter(Proxy.container_id != None).all()
                    
                    # Get all network connections once to save resources
                    all_connections = psutil.net_connections(kind='tcp')
                    
                    for p in proxies:
                        try:
                            # 1. Update Traffic Stats
                            container = docker_client.containers.get(p.container_id)
                            stats = container.stats(stream=False)
                            networks = stats.get('networks', {})
                            rx = 0
                            tx = 0
                            for iface, data in networks.items():
                                rx += data.get('rx_bytes', 0)
                                tx += data.get('tx_bytes', 0)
                            
                            p.download = rx
                            p.upload = tx
                            
                            # 2. Update Active Connections
                            # Count established connections to the proxy port
                            # This is an approximation based on host port bindings
                            conns = [c for c in all_connections if c.laddr.port == p.port and c.status == 'ESTABLISHED']
                            p.active_connections = len(conns)
                                
                        except Exception as e:
                            # Container might be stopped or deleted
                            continue
                    
                    db.session.commit()
                    
                    # 3. Update Historical Stats (Every ~1 hour)
                    # For demo purposes/testing, let's do it every minute if it's a new minute
                    # or just rely on a time check.
                    now = datetime.utcnow()
                    if (now - last_history_update).total_seconds() > 3600: # 1 hour
                        for p in proxies:
                            # Calculate delta since last snapshot? 
                            # For simplicity in this chart, we just store current totals. 
                            # The chart logic calculates differences or shows totals.
                            # Actually, for "Usage History", we usually want daily usage.
                            # Let's store the current snapshot.
                            stat = ProxyStats(
                                proxy_id=p.id,
                                upload=p.upload,
                                download=p.download,
                                active_connections=p.active_connections,
                                timestamp=now
                            )
                            db.session.add(stat)
                        db.session.commit()
                        last_history_update = now

        except OperationalError:
             print("DB Operational Error in Stats Thread. Retrying...")
        except Exception as e:
            print(f"Stats Loop Error: {e}")
        
        time.sleep(10) # Run every 10 seconds

# Start background thread
stats_thread = threading.Thread(target=update_docker_stats, daemon=True)
stats_thread.start()

# Ensure DB is created
with app.app_context():
    try:
        db.create_all()
    except:
        pass

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
        set_setting('server_ip', request.form.get('server_ip'))
        set_setting('server_domain', request.form.get('server_domain'))
        flash('تنظیمات ذخیره شد.', 'success')
        return redirect(url_for('settings'))
        
    return render_template('settings.html', 
                           server_ip=get_setting('server_ip', ''),
                           server_domain=get_setting('server_domain', ''))

@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_system_metrics())

@app.route('/api/history')
@login_required
def api_history():
    """Returns historical traffic data for charts"""
    try:
        # Group by date for the last 7 days
        from sqlalchemy import func
        
        end_date = datetime.utcnow()
        start_date = end_date - datetime.timedelta(days=7)
        
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
                d = start_date + datetime.timedelta(days=i)
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
                status="running"
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
