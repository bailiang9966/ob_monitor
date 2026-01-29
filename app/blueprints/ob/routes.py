from flask import render_template, jsonify
from app.blueprints.ob import ob_bp
from app.config import CONFIG

@ob_bp.route('/')
def index():
    return render_template('depth_chart.html')

@ob_bp.route('/api/config')
def get_config():
    return jsonify(CONFIG)
