from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.utils.helpers import get_setting, set_setting

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')

@settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        if 'server_ip' in request.form:
            set_setting('server_ip', request.form.get('server_ip'))
        if 'server_domain' in request.form:
            set_setting('server_domain', request.form.get('server_domain'))
        if 'alert_conn_threshold' in request.form:
            set_setting('alert_conn_threshold', request.form.get('alert_conn_threshold'))
        if 'alert_ip_conn_threshold' in request.form:
            set_setting('alert_ip_conn_threshold', request.form.get('alert_ip_conn_threshold'))
        if 'telegram_bot_token' in request.form:
            set_setting('telegram_bot_token', request.form.get('telegram_bot_token'))
        if 'telegram_chat_id' in request.form:
            set_setting('telegram_chat_id', request.form.get('telegram_chat_id'))
        
        # Checkbox handling
        if request.form.get('settings_form_submitted') == '1':
             set_setting('auto_block_enabled', '1' if request.form.get('auto_block_enabled') == 'on' else '0')
            
        flash('تنظیمات ذخیره شد.', 'success')
        return redirect(url_for('settings.index'))
        
    return render_template('pages/admin/settings.html', 
                           server_ip=get_setting('server_ip', ''),
                           server_domain=get_setting('server_domain', ''),
                           alert_conn_threshold=get_setting('alert_conn_threshold', '300'),
                           alert_ip_conn_threshold=get_setting('alert_ip_conn_threshold', '20'),
                           telegram_bot_token=get_setting('telegram_bot_token', ''),
                           telegram_chat_id=get_setting('telegram_chat_id', ''),
                           auto_block_enabled=get_setting('auto_block_enabled', '0'))
