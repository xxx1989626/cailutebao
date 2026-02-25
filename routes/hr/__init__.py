from flask import Blueprint

# 创建 HR 蓝图
hr_bp = Blueprint('hr', __name__, url_prefix='/hr')

# 导入各功能模块（确保蓝图注册所有路由）
from . import basic
from . import self_register
from . import archive
from . import departure
from . import import_export
from . import assets
from . import permissions