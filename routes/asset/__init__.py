from flask import Blueprint

# 初始化资产蓝图，路由前缀保持 /asset 不变
asset_bp = Blueprint('asset', __name__, url_prefix='/asset')

# 导入所有视图和功能，确保路由注册生效
from . import views, operations, inventory, import_export

# 导出蓝图供主程序注册
__all__ = ['asset_bp']