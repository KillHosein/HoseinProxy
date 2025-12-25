from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.utils.helpers import log_activity
from app.extensions import limiter

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            log_activity("Login", f"User {username} logged in")
            return redirect(url_for('main.dashboard'))
        flash('نام کاربری یا رمز عبور اشتباه است.', 'danger')
        log_activity("Login Failed", f"Failed login attempt for {username}")
    return render_template('pages/auth/login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    log_activity("Logout", f"User {current_user.username} logged out")
    logout_user()
    flash('با موفقیت خارج شدید.', 'success')
    return redirect(url_for('auth.login'))
