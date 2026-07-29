#D:\cailu\cailutebao\routes\reminder\__init__.py
# 提醒模块：自动遍历目录下单文件单路由，动态注册蓝图
import os
import importlib
import logging

# 收集所有提醒检查函数（供定时任务统一调用）
_REMINDER_CHECKS = []
# 收集所有蓝图
_REMINDER_BPS = []


def _autodiscover():
    """自动遍历 reminder 目录下所有 .py 文件（排除本文件），动态导入并注册"""
    if _REMINDER_BPS:
        return  # 已加载，避免重复
    pkg_dir = os.path.dirname(__file__)
    for fname in sorted(os.listdir(pkg_dir)):
        if not fname.endswith('.py') or fname.startswith('_'):
            continue
        mod_name = fname[:-3]  # 去掉 .py
        try:
            mod = importlib.import_module(f'.{mod_name}', package='routes.reminder')
            # 收集蓝图
            bp = getattr(mod, 'bp', None)
            if bp is not None:
                _REMINDER_BPS.append(bp)
            # 收集检查函数（约定函数名：run_check）
            check_fn = getattr(mod, 'run_check', None)
            if callable(check_fn):
                _REMINDER_CHECKS.append(check_fn)
        except Exception as e:
            logging.error(f"提醒模块加载失败 {mod_name}: {e}")


def register_reminder_blueprints(app):
    """动态注册所有提醒蓝图到应用"""
    _autodiscover()
    for bp in _REMINDER_BPS:
        app.register_blueprint(bp)


def run_all_checks():
    """统一执行所有提醒检查（供定时任务调用）"""
    _autodiscover()
    for check_fn in _REMINDER_CHECKS:
        try:
            check_fn()
        except Exception as e:
            logging.error(f"提醒检查执行失败 {check_fn.__module__}: {e}")
