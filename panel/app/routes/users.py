from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import User
from app.extensions import db
from app.utils.helpers import log_activity

users_bp = Blueprint('users', __name__, url_prefix='/users')

@users_bp.route('/')
@login_required
def list():
    users = User.query.all()
    return render_template('pages/admin/users.html', users=users)

@users_bp.route('/add', methods=['POST'])
@login_required
def add():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        flash('نام کاربری و رمز عبور الزامی است.', 'danger')
        return redirect(url_for('users.list'))
        
    if User.query.filter_by(username=username).first():
        flash('این نام کاربری قبلاً وجود دارد.', 'danger')
        return redirect(url_for('users.list'))
        
    u = User(username=username)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    
    log_activity("User Add", f"Added admin user: {username}")
    flash('کاربر جدید با موفقیت اضافه شد.', 'success')
    return redirect(url_for('users.list'))

@users_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    if id == current_user.id:
        flash('نمی‌توانید حساب خودتان را حذف کنید.', 'danger')
        return redirect(url_for('users.list'))
        
    u = User.query.get_or_404(id)
    username = u.username
    db.session.delete(u)
    db.session.commit()
    
    log_activity("User Delete", f"Deleted admin user: {username}")
    flash(f'کاربر {username} حذف شد.', 'success')
    return redirect(url_for('users.list'))

@users_bp.route('/change_password/<int:id>', methods=['POST'])
@login_required
def change_password(id):
    u = User.query.get_or_404(id)
    password = request.form.get('password')
    
    if not password:
        flash('رمز عبور جدید وارد نشده است.', 'danger')
        return redirect(url_for('users.list'))
        
    u.set_password(password)
    db.session.commit()
    
    log_activity("User Password", f"Changed password for user: {u.username}")
    flash(f'رمز عبور کاربر {u.username} تغییر کرد.', 'success')
    return redirect(url_for('users.list'))
