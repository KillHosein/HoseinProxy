from flask import Blueprint, render_template
from flask_login import login_required

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

@reports_bp.route('/')
@login_required
def index():
    return render_template('pages/admin/reports.html')
