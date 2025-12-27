from flask import Blueprint, render_template
from flask_login import login_required

tools_bp = Blueprint('tools', __name__, url_prefix='/tools')

@tools_bp.route('/')
@login_required
def index():
    return render_template('pages/admin/tools.html')
