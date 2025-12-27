#!/usr/bin/env python3
"""
Enhanced MTProto Proxy Routes with FakeTLS Support
Integrates with existing panel for easy management
"""

import secrets
import docker
import time
import subprocess
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app.models import Proxy
from app.extensions import db
from app.utils.helpers import (
    log_activity,
    normalize_tls_domain,
    parse_mtproxy_secret_input,
)
from app.services.docker_client import client as docker_client

proxy_enhanced_bp = Blueprint('proxy_enhanced', __name__, url_prefix='/proxy-enhanced')

# Popular domains for FakeTLS
POPULAR_DOMAINS = [
    "google.com",
    "cloudflare.com", 
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "whatsapp.com",
    "telegram.org",
    "cdn.discordapp.com",
    "cdn.cloudflare.com",
    "ajax.googleapis.com",
    "fonts.googleapis.com",
    "apis.google.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
    "accounts.google.com",
    "drive.google.com",
    "docs.google.com"
]

def _faketls_docker_config(port, secret, domain, workers=4, tag=None):
    """Generate Docker Compose configuration for FakeTLS proxy"""
    domain_hex = domain.encode('utf-8').hex()
    fake_secret = f"ee{secret}{domain_hex}"
    
    compose_config = f"""version: '3.8'

services:
  mtproto-faketls-{port}:
    image: golang:1.21-alpine
    container_name: mtproto_faketls_{port}
    restart: always
    ports:
      - "{port}:443"
    command: |
      sh -c "
        apk add --no-cache git openssl &&
        git clone https://github.com/TelegramMessenger/MTProxy.git /app &&
        cd /app &&
        go mod init mtproxy || true &&
        go mod tidy || true &&
        CGO_ENABLED=0 GOOS=linux go build -o mtproto-proxy ./cmd/proxy &&
        mkdir -p /etc/ssl/certs /etc/ssl/private /var/log/mtproto &&
        openssl genrsa -out /etc/ssl/private/privkey.pem 2048 &&
        openssl req -new -key /etc/ssl/private/privkey.pem -out /tmp/cert.csr -subj '/C=US/ST=CA/L=Mountain View/O=Google LLC/CN={domain}' &&
        openssl x509 -req -days 3650 -in /tmp/cert.csr -signkey /etc/ssl/private/privkey.pem -out /etc/ssl/certs/fullchain.pem &&
        rm -f /tmp/cert.csr &&
        ./mtproto-proxy \\
          -u nobody \\
          -p 8888,80,443 \\
          -H 443 \\
          -S {fake_secret} \\
          --address 0.0.0.0 \\
          --port 443 \\
          --http-ports 80 \\
          --slaves {workers} \\
          --max-special-connections 60000 \\
          --allow-skip-dh \\
          --cert /etc/ssl/certs/fullchain.pem \\
          --key /etc/ssl/private/privkey.pem \\
          --dc 1,149.154.175.50,443 \\
          --dc 2,149.154.167.51,443 \\
          --dc 3,149.154.175.100,443 \\
          --dc 4,149.154.167.91,443 \\
          --dc 5,91.108.56.151,443 \\
          {f'--tag {tag}' if tag else ''}
      "
    volumes:
      - ./logs:/var/log/mtproto
    networks:
      - mtproto_network

networks:
  mtproto_network:
    driver: bridge
"""
    return compose_config

@proxy_enhanced_bp.route('/create-faketls', methods=['POST'])
@login_required
def create_faketls_proxy():
    """Create a new FakeTLS-enabled proxy"""
    port = request.form.get('port', type=int)
    workers = request.form.get('workers', type=int, default=4)
    tag = (request.form.get('tag') or '').strip() or None
    name = (request.form.get('name') or '').strip() or None
    secret = request.form.get('secret')
    domain_choice = request.form.get('domain_choice', '1')
    quota_gb = request.form.get('quota_gb', type=float)
    expiry_days = request.form.get('expiry_days', type=int)
    proxy_ip = (request.form.get('proxy_ip') or '').strip() or None
    
    # Map domain choice to domain name
    domain_map = {
        '1': 'google.com',
        '2': 'cloudflare.com',
        '3': 'microsoft.com',
        '4': 'apple.com',
        '5': 'amazon.com',
        '6': 'facebook.com',
        '7': 'twitter.com',
        '8': 'instagram.com',
        '9': 'whatsapp.com',
        '10': 'telegram.org',
        '11': 'cdn.discordapp.com',
        '12': 'cdn.cloudflare.com',
        '13': 'ajax.googleapis.com',
        '14': 'fonts.googleapis.com',
        '15': 'apis.google.com',
        '16': 'ssl.gstatic.com',
        '17': 'www.gstatic.com',
        '18': 'accounts.google.com',
        '19': 'drive.google.com',
        '20': 'docs.google.com'
    }
    
    tls_domain = domain_map.get(domain_choice, 'google.com')
    
    # Calculate quota
    quota_bytes = 0
    if quota_gb is not None and quota_gb > 0:
        quota_bytes = int(quota_gb * 1024 * 1024 * 1024)
    
    # Calculate expiry
    expiry_date = None
    if expiry_days and expiry_days > 0:
        expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
    
    if not secret:
        secret = secrets.token_hex(16)
    
    if not port:
        flash('شماره پورت الزامی است.', 'danger')
        return redirect(url_for('main.dashboard'))
    
    if Proxy.query.filter_by(port=port).first():
        flash(f'پورت {port} قبلاً استفاده شده است.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Create project directory
        project_dir = f"/opt/mtproto-faketls-{port}"
        os.makedirs(project_dir, exist_ok=True)
        
        # Create Docker Compose file
        compose_content = _faketls_docker_config(port, secret, tls_domain, workers, tag)
        compose_file = os.path.join(project_dir, 'docker-compose.yml')
        
        with open(compose_file, 'w') as f:
            f.write(compose_content)
        
        # Start the container using Docker Compose
        cmd = ['docker-compose', '-f', compose_file, 'up', '-d']
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
        
        if result.returncode != 0:
            raise Exception(f"Docker Compose failed: {result.stderr}")
        
        # Wait for container to start
        time.sleep(5)
        
        # Get container ID
        cmd = ['docker-compose', '-f', compose_file, 'ps', '-q']
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
        container_id = result.stdout.strip()
        
        if not container_id:
            raise Exception("Container not found")
        
        # Generate FakeTLS secret
        domain_hex = tls_domain.encode('utf-8').hex()
        fake_secret = f"ee{secret}{domain_hex}"
        
        # Create proxy record in database
        new_proxy = Proxy(
            port=port,
            secret=secret,
            proxy_type="tls",
            tls_domain=tls_domain,
            tag=tag,
            name=name or f"FakeTLS {tls_domain} {port}",
            workers=workers,
            container_id=container_id,
            status="running",
            quota_bytes=quota_bytes,
            quota_start=datetime.utcnow(),
            expiry_date=expiry_date,
            proxy_ip=proxy_ip
        )
        
        db.session.add(new_proxy)
        db.session.commit()
        
        # Get server IP
        try:
            server_ip = subprocess.check_output(['curl', '-s', 'ifconfig.me']).decode().strip()
        except:
            server_ip = "YOUR_SERVER_IP"
        
        # Generate proxy link
        proxy_link = f"https://t.me/proxy?server={server_ip}&port={port}&secret={fake_secret}"
        
        log_activity("Create FakeTLS Proxy", f"Created FakeTLS proxy on port {port} for domain {tls_domain}")
        flash(f'✅ پروکسی FakeTLS با دامنه {tls_domain} روی پورت {port} با موفقیت ساخته شد.', 'success')
        flash(f'🔗 لینک پروکسی: {proxy_link}', 'info')
        
    except Exception as e:
        flash(f'❌ خطا در ساخت پروکسی FakeTLS: {e}', 'danger')
        log_activity("FakeTLS Proxy Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_enhanced_bp.route('/get-faketls-domains', methods=['GET'])
@login_required
def get_faketls_domains():
    """Get list of available domains for FakeTLS"""
    domains_with_info = [
        {"value": "1", "name": "google.com", "description": "Most reliable and recommended"},
        {"value": "2", "name": "cloudflare.com", "description": "Good for CDN-like traffic"},
        {"value": "3", "name": "microsoft.com", "description": "Good for corporate environments"},
        {"value": "4", "name": "apple.com", "description": "Perfect for iOS/macOS users"},
        {"value": "5", "name": "amazon.com", "description": "E-commerce traffic disguise"},
        {"value": "6", "name": "facebook.com", "description": "Social media traffic"},
        {"value": "7", "name": "twitter.com", "description": "Social media traffic"},
        {"value": "8", "name": "instagram.com", "description": "Social media traffic"},
        {"value": "9", "name": "whatsapp.com", "description": "Messaging traffic"},
        {"value": "10", "name": "telegram.org", "description": "Messaging traffic"},
        {"value": "11", "name": "cdn.discordapp.com", "description": "Gaming/communication"},
        {"value": "12", "name": "cdn.cloudflare.com", "description": "CDN traffic"},
        {"value": "13", "name": "ajax.googleapis.com", "description": "Google APIs"},
        {"value": "14", "name": "fonts.googleapis.com", "description": "Web fonts"},
        {"value": "15", "name": "apis.google.com", "description": "Google APIs"},
        {"value": "16", "name": "ssl.gstatic.com", "description": "Google static content"},
        {"value": "17", "name": "www.gstatic.com", "description": "Google static content"},
        {"value": "18", "name": "accounts.google.com", "description": "Google authentication"},
        {"value": "19", "name": "drive.google.com", "description": "Google Drive"},
        {"value": "20", "name": "docs.google.com", "description": "Google Docs"}
    ]
    
    return jsonify({
        'domains': domains_with_info,
        'success': True
    })

@proxy_enhanced_bp.route('/stop-faketls/<int:proxy_id>')
@login_required
def stop_faketls_proxy(proxy_id):
    """Stop a FakeTLS proxy"""
    proxy = Proxy.query.get_or_404(proxy_id)
    
    if proxy.proxy_type != "tls":
        flash('این پروکسی از نوع FakeTLS نیست.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        project_dir = f"/opt/mtproto-faketls-{proxy.port}"
        compose_file = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_file):
            cmd = ['docker-compose', '-f', compose_file, 'down']
            subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
        
        proxy.status = "stopped"
        db.session.commit()
        
        log_activity("Stop FakeTLS Proxy", f"Stopped FakeTLS proxy on port {proxy.port}")
        flash(f'پروکسی FakeTLS روی پورت {proxy.port} متوقف شد.', 'success')
        
    except Exception as e:
        flash(f'خطا در توقف پروکسی: {e}', 'danger')
        log_activity("Stop FakeTLS Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_enhanced_bp.route('/start-faketls/<int:proxy_id>')
@login_required
def start_faketls_proxy(proxy_id):
    """Start a FakeTLS proxy"""
    proxy = Proxy.query.get_or_404(proxy_id)
    
    if proxy.proxy_type != "tls":
        flash('این پروکسی از نوع FakeTLS نیست.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        project_dir = f"/opt/mtproto-faketls-{proxy.port}"
        compose_file = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_file):
            cmd = ['docker-compose', '-f', compose_file, 'up', '-d']
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
            
            if result.returncode == 0:
                proxy.status = "running"
                db.session.commit()
                
                log_activity("Start FakeTLS Proxy", f"Started FakeTLS proxy on port {proxy.port}")
                flash(f'پروکسی FakeTLS روی پورت {proxy.port} روشن شد.', 'success')
            else:
                raise Exception(f"Failed to start: {result.stderr}")
        else:
            raise Exception("Docker Compose file not found")
        
    except Exception as e:
        flash(f'خطا در روشن کردن پروکسی: {e}', 'danger')
        log_activity("Start FakeTLS Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_enhanced_bp.route('/restart-faketls/<int:proxy_id>')
@login_required
def restart_faketls_proxy(proxy_id):
    """Restart a FakeTLS proxy"""
    proxy = Proxy.query.get_or_404(proxy_id)
    
    if proxy.proxy_type != "tls":
        flash('این پروکسی از نوع FakeTLS نیست.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        project_dir = f"/opt/mtproto-faketls-{proxy.port}"
        compose_file = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_file):
            cmd = ['docker-compose', '-f', compose_file, 'restart']
            subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
            
            proxy.status = "running"
            db.session.commit()
            
            log_activity("Restart FakeTLS Proxy", f"Restarted FakeTLS proxy on port {proxy.port}")
            flash(f'پروکسی FakeTLS روی پورت {proxy.port} ریستارت شد.', 'success')
        else:
            raise Exception("Docker Compose file not found")
        
    except Exception as e:
        flash(f'خطا در ریستارت پروکسی: {e}', 'danger')
        log_activity("Restart FakeTLS Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_enhanced_bp.route('/delete-faketls/<int:proxy_id>')
@login_required
def delete_faketls_proxy(proxy_id):
    """Delete a FakeTLS proxy"""
    proxy = Proxy.query.get_or_404(proxy_id)
    port = proxy.port
    
    if proxy.proxy_type != "tls":
        flash('این پروکسی از نوع FakeTLS نیست.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    try:
        # Stop and remove container
        project_dir = f"/opt/mtproto-faketls-{port}"
        compose_file = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_file):
            cmd = ['docker-compose', '-f', compose_file, 'down']
            subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
        
        # Remove project directory
        import shutil
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        
        # Delete from database
        db.session.delete(proxy)
        db.session.commit()
        
        log_activity("Delete FakeTLS Proxy", f"Deleted FakeTLS proxy on port {port}")
        flash(f'پروکسی FakeTLS روی پورت {port} حذف شد.', 'success')
        
    except Exception as e:
        flash(f'خطا در حذف پروکسی: {e}', 'danger')
        log_activity("Delete FakeTLS Error", str(e))
    
    return redirect(url_for('main.dashboard'))

@proxy_enhanced_bp.route('/get-faketls-logs/<int:proxy_id>')
@login_required
def get_faketls_logs(proxy_id):
    """Get logs for a FakeTLS proxy"""
    proxy = Proxy.query.get_or_404(proxy_id)
    
    if proxy.proxy_type != "tls":
        return jsonify({'success': False, 'message': 'This is not a FakeTLS proxy'})
    
    try:
        project_dir = f"/opt/mtproto-faketls-{proxy.port}"
        compose_file = os.path.join(project_dir, 'docker-compose.yml')
        
        if os.path.exists(compose_file):
            cmd = ['docker-compose', '-f', compose_file, 'logs', '--tail', '100']
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
            
            if result.returncode == 0:
                return jsonify({
                    'success': True,
                    'logs': result.stdout,
                    'port': proxy.port
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Failed to get logs: {result.stderr}'
                })
        else:
            return jsonify({
                'success': False,
                'message': 'Docker Compose file not found'
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error getting logs: {str(e)}'
        })