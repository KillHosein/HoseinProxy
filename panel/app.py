import os
import secrets
import subprocess
import docker
import psutil
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Configuration
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///panel.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Docker Client
try:
    docker_client = docker.from_env()
except Exception as e:
    print(f"Warning: Docker not connected. {e}")
    docker_client = None

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Proxy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    port = db.Column(db.Integer, unique=True, nullable=False)
    secret = db.Column(db.String(100), nullable=False)
    tag = db.Column(db.String(100), nullable=True)
    workers = db.Column(db.Integer, default=1)
    container_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="stopped") # running, stopped

# --- Helpers ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_system_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    return {"cpu": cpu, "mem": mem, "disk": disk}

def generate_mtproto_secret():
    return secrets.token_hex(16)

# --- Routes ---

@app.route('/')
@login_required
def dashboard():
    stats = get_system_stats()
    proxies = Proxy.query.all()
    
    # Sync status with Docker
    if docker_client:
        running_containers = {c.id: c for c in docker_client.containers.list()}
        for p in proxies:
            if p.container_id and p.container_id in running_containers:
                 p.status = "running"
            else:
                 # Check if it exists but stopped
                 try:
                     if p.container_id:
                        c = docker_client.containers.get(p.container_id)
                        p.status = c.status
                     else:
                        p.status = "unknown"
                 except:
                     p.status = "stopped"
        db.session.commit()

    return render_template('dashboard.html', stats=stats, proxies=proxies)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/proxy/add', methods=['POST'])
@login_required
def add_proxy():
    port = request.form.get('port', type=int)
    workers = request.form.get('workers', type=int, default=1)
    tag = request.form.get('tag')
    secret = request.form.get('secret') or generate_mtproto_secret()

    if Proxy.query.filter_by(port=port).first():
        flash(f'Port {port} is already in use in DB.')
        return redirect(url_for('dashboard'))

    # Create Docker Container
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
            log_activity("Create Proxy", f"Created proxy on port {port}")
            flash(f'Proxy on port {port} created successfully!')
            
        except Exception as e:
            flash(f'Error creating container: {e}')
            log_activity("Create Proxy Error", str(e))
    else:
        flash('Docker client not available.')

    return redirect(url_for('dashboard'))

@app.route('/proxy/delete/<int:id>')
@login_required
def delete_proxy(id):
    proxy = Proxy.query.get_or_404(id)
    port = proxy.port
    if docker_client and proxy.container_id:
        try:
            container = docker_client.containers.get(proxy.container_id)
            container.stop()
            container.remove()
        except Exception as e:
            flash(f'Error removing container: {e}')
    
    db.session.delete(proxy)
    db.session.commit()
    log_activity("Delete Proxy", f"Deleted proxy on port {port}")
    flash(f'Proxy {port} deleted.')
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
            flash(f'Proxy {proxy.port} restarted.')
        except Exception as e:
            flash(f'Error restarting: {e}')
    return redirect(url_for('dashboard'))

# CLI command to create admin user
def create_admin(username, password):
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username=username).first():
            u = User(username=username)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            print(f"User {username} created.")
        else:
            print(f"User {username} already exists.")

if __name__ == '__main__':
    # Initialize DB
    with app.app_context():
        db.create_all()
    
    app.run(host='0.0.0.0', port=5000, debug=True)
