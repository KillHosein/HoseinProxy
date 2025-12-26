import docker
from flask import Blueprint, render_template
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

    dirty = False
    for p in proxies:
        s = (p.secret or "").strip().lower()
        if s.startswith("dd") or s.startswith("ee"):
            try:
                parsed = parse_mtproxy_secret_input(None, s, tls_domain=p.tls_domain)
                p.secret = parsed["base_secret"]
                p.proxy_type = parsed["proxy_type"]
                p.tls_domain = parsed["tls_domain"]
                dirty = True
            except Exception:
                pass
    if dirty:
        try:
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    for p in proxies:
        p.display_secret = format_mtproxy_client_secret(p.proxy_type or "standard", p.secret, p.tls_domain)

    return render_template('pages/admin/dashboard.html', proxies=proxies, logs=logs)
