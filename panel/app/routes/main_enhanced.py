import docker
import re
import os
import subprocess
from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from app.models import Proxy, ActivityLog
from app.extensions import db
from app.services.docker_client import client as docker_client
from app.utils.helpers import format_mtproxy_client_secret, parse_mtproxy_secret_input

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    proxies = Proxy.query.order_by(Proxy.created_at.desc()).all()
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    
    # Calculate statistics
    running_count = sum(1 for p in proxies if p.status == 'running')
    total_users = Proxy.query.count()  # This should be actual user count in real implementation
    tls_count = sum(1 for p in proxies if p.proxy_type == 'tls')
    
    if docker_client:
        try:
            db_ports = {p.port for p in proxies}
            containers = docker_client.containers.list(all=True)
            imported = False
            for c in containers:
                name = getattr(c, "name", "") or ""
                if not name.startswith("mtproto_"):
                    continue
                host_port = None
                try:
                    ports = (c.attrs.get("NetworkSettings", {}) or {}).get("Ports", {}) or {}
                    mapping = ports.get("443/tcp")
                    if mapping and isinstance(mapping, list) and mapping:
                        host_port = int(mapping[0].get("HostPort"))
                except Exception:
                    host_port = None

                if not host_port:
                    m = re.match(r"^mtproto_(\d+)$", name)
                    if m:
                        try:
                            host_port = int(m.group(1))
                        except Exception:
                            host_port = None

                if not host_port or host_port in db_ports:
                    continue

                env = []
                try:
                    env = (c.attrs.get("Config", {}) or {}).get("Env", []) or []
                except Exception:
                    pass
                secret = None
                tag = None
                workers = 2
                for e in env:
                    if isinstance(e, str) and e.startswith("SECRET="):
                        secret = e[7:]
                    elif isinstance(e, str) and e.startswith("TAG="):
                        tag = e[4:]
                    elif isinstance(e, str) and e.startswith("WORKERS="):
                        try:
                            workers = int(e[8:])
                        except Exception:
                            workers = 2

                status = c.status
                container_id = c.id
                
                # Check if this is a FakeTLS container
                is_faketls = "faketls" in name
                proxy_type = "tls" if is_faketls else "standard"
                tls_domain = None
                
                if is_faketls:
                    # Extract domain from container inspection
                    try:
                        # For FakeTLS, we need to extract domain from the fake secret
                        if secret and len(secret) > 32:
                            domain_hex = secret[32:]
                            if len(domain_hex) % 2 == 0:
                                try:
                                    tls_domain = bytes.fromhex(domain_hex).decode('utf-8')
                                except:
                                    tls_domain = "google.com"  # Default
                    except:
                        tls_domain = "google.com"
                
                new_proxy = Proxy(
                    port=host_port,
                    secret=secret,
                    proxy_type=proxy_type,
                    tls_domain=tls_domain,
                    tag=tag,
                    workers=workers,
                    container_id=container_id,
                    status=status
                )
                db.session.add(new_proxy)
                imported = True
            
            if imported:
                db.session.commit()
                proxies = Proxy.query.order_by(Proxy.created_at.desc()).all()
                
        except Exception as e:
            pass

    # Add calculated fields
    for proxy in proxies:
        proxy.quota_usage = proxy.upload + proxy.download
        proxy.quota_percent = 0
        if proxy.quota_bytes > 0:
            proxy.quota_percent = min(100, int((proxy.quota_usage / proxy.quota_bytes) * 100))
        
        # Generate connection links
        if proxy.proxy_type == "tls" and proxy.tls_domain:
            domain_hex = proxy.tls_domain.encode('utf-8').hex()
            fake_secret = f"ee{proxy.secret}{domain_hex}"
            proxy.connection_link = f"tg://proxy?server=YOUR_SERVER_IP&port={proxy.port}&secret={fake_secret}"
        else:
            proxy.connection_link = format_mtproxy_client_secret(proxy.proxy_type, proxy.secret, proxy.tls_domain)

    return render_template('pages/admin/dashboard_faketls.html', 
                         proxies=proxies, 
                         logs=logs,
                         running_count=running_count,
                         total_users=total_users,
                         tls_count=tls_count)

@main_bp.route('/api/stats')
@login_required
def api_stats():
    """API endpoint for dashboard statistics"""
    proxies = Proxy.query.all()
    running_count = sum(1 for p in proxies if p.status == 'running')
    tls_count = sum(1 for p in proxies if p.proxy_type == 'tls')
    
    total_upload = sum(p.upload for p in proxies)
    total_download = sum(p.download for p in proxies)
    total_connections = sum(p.active_connections or 0 for p in proxies)
    
    return jsonify({
        'total_proxies': len(proxies),
        'running_proxies': running_count,
        'tls_proxies': tls_count,
        'total_upload': total_upload,
        'total_download': total_download,
        'total_connections': total_connections,
        'success': True
    })

@main_bp.route('/api/proxy/<int:proxy_id>/status')
@login_required
def api_proxy_status(proxy_id):
    """API endpoint for individual proxy status"""
    proxy = Proxy.query.get_or_404(proxy_id)
    
    # Check if container is actually running
    if docker_client and proxy.container_id:
        try:
            container = docker_client.containers.get(proxy.container_id)
            actual_status = container.status
            if actual_status != proxy.status:
                proxy.status = actual_status
                db.session.commit()
        except:
            pass
    
    return jsonify({
        'id': proxy.id,
        'port': proxy.port,
        'status': proxy.status,
        'active_connections': proxy.active_connections or 0,
        'upload': proxy.upload,
        'download': proxy.download,
        'proxy_type': proxy.proxy_type,
        'tls_domain': proxy.tls_domain,
        'success': True
    })