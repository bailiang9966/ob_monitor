from flask import Blueprint

# 创建订单簿监控蓝图
ob_bp = Blueprint('ob', __name__, template_folder='templates')

from app.blueprints.ob import routes
