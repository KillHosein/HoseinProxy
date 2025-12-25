import secrets
import docker
from datetime import datetime, timedelta
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import login_required
from app.models import Proxy
from app.extensions import db
from app.utils.helpers import log_activity
from app.services.docker_client import client as docker_client

proxy_bp = Blueprint('proxy', __name__, url_prefix='/proxy')

@proxy_bp.route('/add', methods=['POST'])
@login_required
def add():
    port = request.form.get('port', type=int)
    workers = request.form.get('workers', type=int, default=1)
    tag = request.form.get('tag')
    name = request.form.get('name')
    secret = request.form.get('secret')
    proxy_type = request.form.get('proxy_type', 'standard')
    tls_domain = request.form.get('tls_domain', 'google.com')
    quota_gb = request.form.get('quota_gb', type=float)
    expiry_days = request.form.get('expiry_days', type=int)
    proxy_ip = (request.form.get('proxy_ip') or '').strip() or None
    
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
         return redirect(url_for('main.dashboard'))

    if Proxy.query.filter_by(port=port).first():
        flash(f'پورت {port} قبلاً استفاده شده است.', 'warning')
        return redirect(url_for('main.dashboard'))

    if docker_client:
        try:
            ports_config = {'443/tcp': port}
            if proxy_ip:
                ports_config = {'443/tcp': (proxy_ip, port)}

            container = docker_client.containers.run(
                'telegrammessenger/proxy',
                detach=True,
                ports=ports_config,
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
                name=name,
                workers=workers,
                container_id=container.id,
                status="running",
                quota_bytes=quota_bytes,
                quota_start=datetime.utcnow() if quota_bytes > 0 else None,
                expiry_date=expiry_date,
                proxy_ip=proxy_ip
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

    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/bulk_create', methods=['POST'])
@login_required
def bulk_create():
    start_port = request.form.get('start_port', type=int)
    count = request.form.get('count', type=int)
    tag = request.form.get('tag')
    base_name = request.form.get('name_prefix') # Optional base name
    
    if not start_port or not count or count < 1:
        flash('اطلاعات نامعتبر است.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    if count > 50:
        flash('تعداد بالا (حداکثر ۵۰) مجاز نیست.', 'danger')
        return redirect(url_for('main.dashboard'))

    success_count = 0
    errors = []
    
    current_port = start_port
    
    # Pre-check ports
    existing_ports = {p.port for p in Proxy.query.all()}
    
    for i in range(count):
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
            
            p_name = None
            if base_name:
                p_name = f"{base_name} #{i+1}"
            
            p = Proxy(
                port=current_port,
                secret=secret,
                tag=tag,
                name=p_name,
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
        
    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/update/<int:id>', methods=['POST'])
@login_required
def update(id):
    proxy = Proxy.query.get_or_404(id)
    
    # Collect form data
    tag = (request.form.get('tag') or '').strip() or None
    name = (request.form.get('name') or '').strip() or None
    quota_gb = request.form.get('quota_gb', type=float)
    expiry_days = request.form.get('expiry_days', type=int)
    
    # New Fields
    new_secret = (request.form.get('secret') or '').strip()
    new_port = request.form.get('port', type=int)
    new_status = request.form.get('status') # running, stopped
    username = (request.form.get('username') or '').strip() or None
    password = (request.form.get('password') or '').strip() or None
    proxy_ip = (request.form.get('proxy_ip') or '').strip() or None
    
    # Calculate Quota Bytes
    quota_bytes = 0
    if quota_gb is not None and quota_gb > 0:
        quota_bytes = int(quota_gb * 1024 * 1024 * 1024)
    
    # Calculate Expiry
    expiry_date = None
    if expiry_days and expiry_days > 0:
        expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
    elif expiry_days == 0:
         expiry_date = None # Remove expiry if set to 0
    
    changes = []
    recreate_container = False
    
    try:
        # Check if Port or Secret changed -> Need Recreation
        if new_port and new_port != proxy.port:
            if Proxy.query.filter(Proxy.port == new_port, Proxy.id != proxy.id).first():
                flash(f'پورت {new_port} قبلاً توسط پروکسی دیگری استفاده شده است.', 'danger')
                return redirect(url_for('main.dashboard'))
            changes.append(f"Port: {proxy.port} -> {new_port}")
            proxy.port = new_port
            recreate_container = True
            
        if new_secret and new_secret != proxy.secret:
            changes.append("Secret changed")
            proxy.secret = new_secret
            recreate_container = True
            
        # Standard Update fields
        if tag != proxy.tag:
            proxy.tag = tag
            changes.append("Tag updated")
            
        if name != proxy.name:
            proxy.name = name
            changes.append("Name updated")
            
        if quota_bytes != proxy.quota_bytes:
            proxy.quota_bytes = quota_bytes
            changes.append(f"Quota: {quota_bytes}")
            if quota_bytes > 0 and not proxy.quota_start:
                proxy.quota_start = datetime.utcnow()
                proxy.quota_base_upload = int(proxy.upload or 0)
                proxy.quota_base_download = int(proxy.download or 0)
            elif quota_bytes == 0:
                proxy.quota_start = None
                
        if expiry_days is not None:
             proxy.expiry_date = expiry_date
             changes.append("Expiry updated")

        # Update Info fields
        if username != proxy.username:
            proxy.username = username
        if password != proxy.password:
            proxy.password = password
        if proxy_ip != proxy.proxy_ip:
            proxy.proxy_ip = proxy_ip
            if proxy_ip:
                 recreate_container = True
                 changes.append(f"Bind IP: {proxy_ip}")

        # Status Change
        if new_status and new_status != proxy.status:
            if new_status == 'stopped':
                if docker_client and proxy.container_id:
                     try:
                        docker_client.containers.get(proxy.container_id).stop()
                     except: pass
                proxy.status = 'stopped'
                changes.append("Stopped")
            elif new_status == 'running':
                # If recreating, we don't need to start here, it will happen below
                if not recreate_container:
                    if docker_client and proxy.container_id:
                        try:
                           docker_client.containers.get(proxy.container_id).start()
                        except: pass
                    proxy.status = 'running'
                    changes.append("Started")

        # Apply Recreate if needed
        if recreate_container and proxy.status != 'stopped':
             if docker_client:
                 try:
                     # Remove old
                     if proxy.container_id:
                         try:
                             old_c = docker_client.containers.get(proxy.container_id)
                             old_c.remove(force=True)
                         except: pass
                     
                     # Create new
                     ports_config = {'443/tcp': proxy.port}
                     if proxy.proxy_ip:
                         ports_config = {'443/tcp': (proxy.proxy_ip, proxy.port)}

                     container = docker_client.containers.run(
                        'telegrammessenger/proxy',
                        detach=True,
                        ports=ports_config,
                        environment={
                            'SECRET': proxy.secret,
                            'TAG': proxy.tag,
                            'WORKERS': proxy.workers
                        },
                        restart_policy={"Name": "always"},
                        name=f"mtproto_{proxy.port}"
                    )
                     proxy.container_id = container.id
                     proxy.status = "running"
                     changes.append("Container Recreated")
                 except Exception as e:
                     flash(f'خطا در بازسازی کانتینر: {e}', 'danger')
                     log_activity("Update Error", str(e))
                     return redirect(url_for('main.dashboard'))

        db.session.commit()
        if changes:
            log_activity("Update Proxy", f"Updated proxy {proxy.port}: {', '.join(changes)}")
            flash('تنظیمات پروکسی با موفقیت بروزرسانی شد.', 'success')
        else:
            flash('تغییر خاصی اعمال نشد.', 'info')
            
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        flash(f'خطا در ذخیره تنظیمات: {e}', 'danger')
        log_activity("Update Failed", str(e))
        
    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/stop/<int:id>')
@login_required
def stop(id):
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
    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/start/<int:id>')
@login_required
def start(id):
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
    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/delete/<int:id>')
@login_required
def delete(id):
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
    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/restart/<int:id>')
@login_required
def restart(id):
    proxy = Proxy.query.get_or_404(id)
    if docker_client and proxy.container_id:
        try:
            container = docker_client.containers.get(proxy.container_id)
            container.restart()
            log_activity("Restart Proxy", f"Restarted proxy on port {proxy.port}")
            flash(f'پروکسی {proxy.port} ریستارت شد.', 'success')
        except Exception as e:
            flash(f'خطا در ریستارت: {e}', 'danger')
    return redirect(url_for('main.dashboard'))

@proxy_bp.route('/reset_quota/<int:id>')
@login_required
def reset_quota(id):
    proxy = Proxy.query.get_or_404(id)
    try:
        # Reset base counters to current usage so quota starts from 0 effectively relative to container stats
        # Or better, just update quota_start to now and reset base
        proxy.quota_start = datetime.utcnow()
        proxy.quota_base_upload = int(proxy.upload or 0)
        proxy.quota_base_download = int(proxy.download or 0)
        
        db.session.commit()
        log_activity("Reset Quota", f"Reset quota for proxy {proxy.port}")
        flash(f'مصرف حجم پروکسی {proxy.port} ریست شد.', 'success')
    except Exception as e:
        flash(f'خطا در ریست حجم: {e}', 'danger')
        
    return redirect(url_for('main.dashboard'))
