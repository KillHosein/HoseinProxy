import docker
import re
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
                    env = []
                env_map = {}
                for item in env:
                    if not item or "=" not in item:
                        continue
                    k, v = item.split("=", 1)
                    env_map[k] = v

                secret = (env_map.get("SECRET") or "").strip()
                if not secret:
                    continue

                tag = (env_map.get("TAG") or "").strip() or None
                workers = 1
                try:
                    workers = int(env_map.get("WORKERS") or 1)
                except Exception:
                    workers = 1

                try:
                    parsed = parse_mtproxy_secret_input(None, secret)
                except Exception:
                    continue

                p = Proxy(
                    port=host_port,
                    secret=parsed["base_secret"],
                    proxy_type=parsed["proxy_type"],
                    tls_domain=parsed["tls_domain"],
                    tag=tag,
                    workers=workers,
                    container_id=c.id,
                    status=c.status or "unknown",
                )
                db.session.add(p)
                db_ports.add(host_port)
                imported = True

            if imported:
                db.session.commit()
                proxies = Proxy.query.order_by(Proxy.created_at.desc()).all()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

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
