from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.models import BlockedIP
from app.extensions import db
from app.utils.helpers import log_activity
from app.services.firewall_service import _apply_firewall_rule

firewall_bp = Blueprint('firewall', __name__, url_prefix='/firewall')

@firewall_bp.route('/')
@login_required
def index():
    blocked_ips = BlockedIP.query.order_by(BlockedIP.created_at.desc()).all()
    return render_template('pages/admin/firewall.html', blocked_ips=blocked_ips)

@firewall_bp.route('/add', methods=['POST'])
@login_required
def add():
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
    return redirect(url_for('firewall.index'))

@firewall_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    b = BlockedIP.query.get_or_404(id)
    ip = b.ip_address
    db.session.delete(b)
    db.session.commit()
    _apply_firewall_rule(ip, 'unblock')
    log_activity("Firewall Unblock", f"Unblocked IP {ip}")
    flash(f'آی‌پی {ip} آزاد شد.', 'success')
    return redirect(url_for('firewall.index'))
