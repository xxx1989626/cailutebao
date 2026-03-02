#D:\cailu\cailutebao\app.py   路径必须保留
from flask_migrate import Migrate
from flask import Flask, jsonify, request, send_from_directory
from flask_login import LoginManager, current_user
from utils import today_str, perm, format_date, format_datetime, validate_id_card, get_gender_from_id_card, get_birthday_from_id_card, get_unreturned_assets, register_module_permissions
from config import Config, SECRET_KEY, DATABASE_PATH, UPLOAD_FOLDER, SALARY_MODES, POSITIONS, POSTS
from models import db, Asset, User, Permission, ChatMessage  # 如需彻底清理可删除 ChatMessage
from routes import register_blueprints
import json, os
import time
import logging
from logging.handlers import RotatingFileHandler
import traceback
from sqlalchemy import func
from datetime import datetime, date, timedelta
import threading

# ==================== 核心优化1：日志增强（定位崩溃原因） ====================
LOG_DIR = os.getenv('CAILU_LOG_DIR', 'D:/cailu/log')
os.makedirs(LOG_DIR, exist_ok=True)

app_log_path = os.path.join(LOG_DIR, 'app.log')
error_log_path = os.path.join(LOG_DIR, 'error.log')
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

app_file_handler = RotatingFileHandler(
    app_log_path,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8'
)
app_file_handler.setFormatter(logging.Formatter(log_format))
root_logger.addHandler(app_file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(log_format))
root_logger.addHandler(console_handler)

# 错误日志单独记录
error_logger = logging.getLogger('error')
error_logger.setLevel(logging.ERROR)
error_logger.handlers.clear()
error_file_handler = RotatingFileHandler(
    error_log_path,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8'
)
error_file_handler.setFormatter(logging.Formatter(log_format))
error_logger.addHandler(error_file_handler)
# ==================== 应用初始化 ====================
app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SQLALCHEMY_DATABASE_URI=f'sqlite:///{DATABASE_PATH}',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=50 * 1024 * 1024,
    # 核心优化2：数据库连接池配置（防止连接耗尽）
    SQLALCHEMY_ENGINE_OPTIONS={
        'pool_size': 10,        # 连接池大小
        'max_overflow': 20,     # 最大溢出连接数
        'pool_recycle': 300,    # 5分钟回收连接，防止失效
        'pool_pre_ping': True   # 每次请求前检查连接是否有效
    }
)

# ==================== 扩展初始化 ====================
db.init_app(app)
register_blueprints(app)
migrate = Migrate(app, db, render_as_batch=True)

@app.before_request
def mark_request_start():
    request._start_time = datetime.now()

@app.after_request
def log_request_result(response):
    start_time = getattr(request, '_start_time', None)
    if start_time:
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        logging.info(
            "request %s %s status=%s cost=%.2fms",
            request.method,
            request.path,
            response.status_code,
            duration_ms
        )
    return response

# Flask-Login 初始化
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录系统'
login_manager.login_message_category = 'warning'
login_manager.init_app(app)

# ==================== Jinja2 自定义过滤器（保留原有逻辑） ====================
@app.template_filter('to_date')
def to_date_filter(value):
    """将字符串或date转换为 date 对象，用于计算时长。改进：支持None/date输入"""
    if value is None:
        return datetime.today().date()  # None默认今天
    if isinstance(value, (datetime, date)):  # 已date，直接返回（幂等）
        if isinstance(value, datetime):
            return value.date()
        return value
    if not isinstance(value, str) or not value:  # 非str或空，默认今天
        return datetime.today().date()
    try:
        y, m, d = map(int, value.split('-'))
        return datetime(y, m, d).date()
    except (ValueError, TypeError):  # 捕获无效格式，避免崩溃
        logging.warning(f"日期转换失败: {value}")
        return datetime.today().date()

@app.template_filter('days_to_years_months')
def days_to_years_months_filter(delta):
    """支持 timedelta 对象或 int 天数，返回“X年Y个月”格式。改进：更严格类型检查"""
    if delta is None:
        return '0个月'
    
    # 提取days：支持timedelta/int/float（取整）
    if hasattr(delta, 'days'):
        days = delta.days
    else:
        try:
            days = int(delta)  # 支持float取整
        except (ValueError, TypeError):
            logging.warning(f"天数转换失败: {delta}")
            return '0个月'  # 无效输入默认0
    
    if days <= 0:
        return '0个月'  # 统一负/零处理
    
    years = days // 365
    months = (days % 365) // 30
    
    result = []
    if years:
        result.append(f'{years}年')
    if months:
        result.append(f'{months}个月')
    return ''.join(result) or '不到1个月'

@app.template_filter('calc_work_duration')
def calc_work_duration_filter(start_date, end_date=None):
    """计算两个日期间的时长（str/date），end=None用今天。返回days_to_years_months格式"""
    # 转换输入为date
    start = to_date_filter(start_date)
    end = to_date_filter(end_date) if end_date else datetime.today().date()
    
    # 计算delta，确保start <= end
    if start > end:
        return '0个月'  # 无效范围默认0
    
    delta = end - start
    return days_to_years_months_filter(delta)

@app.template_filter('fromjson')
def fromjson_filter(value):
    """安全地将 JSON 字符串解析为字典，失败返回空字典"""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logging.warning(f"JSON解析失败: {value}")
        return {}

# ==================== 全局模板上下文处理器 ====================
@app.context_processor
def inject_global_variables():
    return {
        'today_str': today_str,
        'format_date': format_date,
        'format_datetime': format_datetime,
        'perm': perm
    }

# 全局通知和待审核数量（优化：添加缓存，减少数据库查询）
_notice_cache = {}
_cache_expire = 60  # 缓存60秒，减少高频查询
@app.context_processor
def inject_global_data():
    if current_user.is_authenticated:
        user_id = current_user.id
        now = datetime.now().timestamp()
        
        # 检查缓存是否过期
        if user_id in _notice_cache and now - _notice_cache[user_id]['time'] < _cache_expire:
            data = _notice_cache[user_id]['data']
        else:
            try:
                from models import EmploymentCycle, Notification
                # 全局获取待审核人数
                p_count = EmploymentCycle.query.filter_by(status='待审核').count()
                # 全局获取未读通知数
                n_count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
                data = dict(pending_count=p_count, unread_notice_count=n_count)
                # 更新缓存
                _notice_cache[user_id] = {'time': now, 'data': data}
            except Exception as e:
                logging.error(f"获取全局数据失败: {e}")
                data = dict(pending_count=0, unread_notice_count=0)
        return data
    return dict(pending_count=0, unread_notice_count=0)

@app.template_global()
def is_within_hour(date_str):
    if not date_str:
        return False
    try:
        # 第一步：把中文日期格式 2026年01月07日 转换为 2026-01-07
        clean_date = str(date_str).replace('年', '-').replace('月', '-').replace('日', '')
        
        # 第二步：尝试多种可能的日期格式进行解析
        record_time = None
        formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']
        
        for fmt in formats:
            try:
                record_time = datetime.strptime(clean_date.strip(), fmt)
                break
            except:
                continue
        
        if not record_time:
            logging.warning(f"无法解析日期字符串 -> {date_str}")
            return False
            
        # 第三步：计算时间差
        diff = datetime.now() - record_time
        return diff < timedelta(hours=1)
        
    except Exception as e:
        logging.error(f"时间判断逻辑出错 -> {e}")
        return False

# ==================== 装备查询相关（优化：添加异常处理） ====================
@app.context_processor
def inject_equipped_assets():
    def get_equipped_assets(cycle_id):
        """查询该员工当前领用的装备（净领用数量 > 0）"""
        try:
            from models import AssetHistory, Asset
            
            # 统计发放和归还数量
            issued = db.session.query(
                AssetHistory.asset_id,
                func.sum(AssetHistory.quantity).label('issued_qty'),
                func.max(AssetHistory.action_date).label('latest_date'),
                func.max(AssetHistory.operator_id).label('operator_id'),
                func.max(AssetHistory.note).label('note')
            ).filter(
                AssetHistory.user_id == cycle_id,
                AssetHistory.action == '发放'
            ).group_by(AssetHistory.asset_id).subquery()
            
            returned = db.session.query(
                AssetHistory.asset_id,
                func.sum(AssetHistory.quantity).label('returned_qty')
            ).filter(
                AssetHistory.user_id == cycle_id,
                AssetHistory.action == '归还'
            ).group_by(AssetHistory.asset_id).subquery()
            
            query = db.session.query(
                Asset,
                (issued.c.issued_qty - func.coalesce(returned.c.returned_qty, 0)).label('net_qty'),
                issued.c.latest_date,
                issued.c.operator_id,
                issued.c.note
            ).join(
                issued, Asset.id == issued.c.asset_id
            ).outerjoin(
                returned, Asset.id == returned.c.asset_id
            ).filter(
                Asset.type.in_(['装备', '服饰']),
                (issued.c.issued_qty - func.coalesce(returned.c.returned_qty, 0)) > 0
            )
            
            results = []
            for asset, net_qty, issue_date, operator_id, note in query.all():
                operator = User.query.get(operator_id)
                results.append({
                    'asset': asset,
                    'quantity': net_qty,
                    'issue_date': issue_date,
                    'issued_by': operator.name if operator else '未知',
                    'note': note or ''
                })
            
            return results
        except Exception as e:
            logging.error(f"查询领用装备失败: {e}")
            return []
    
    return dict(get_equipped_assets=get_equipped_assets)

@app.context_processor
def inject_unreturned_assets():
    def get_unreturned_assets(cycle_id):
        """查询该员工当前领用的装备（净领用数量 > 0） - 与员工详情页保持一致"""
        try:
            from models import AssetHistory, Asset
            
            issued = db.session.query(
                AssetHistory.asset_id,
                func.sum(AssetHistory.quantity).label('issued_qty')
            ).filter(
                AssetHistory.user_id == cycle_id,
                AssetHistory.action == '发放'
            ).group_by(AssetHistory.asset_id).subquery()
            
            returned = db.session.query(
                AssetHistory.asset_id,
                func.sum(AssetHistory.quantity).label('returned_qty')
            ).filter(
                AssetHistory.user_id == cycle_id,
                AssetHistory.action == '归还'
            ).group_by(AssetHistory.asset_id).subquery()
            
            query = db.session.query(Asset)\
                .join(issued, Asset.id == issued.c.asset_id)\
                .outerjoin(returned, Asset.id == returned.c.asset_id)\
                .filter(
                    (issued.c.issued_qty - func.coalesce(returned.c.returned_qty, 0)) > 0
                )
            
            return query.all()
        except Exception as e:
            logging.error(f"查询未归还装备失败: {e}")
            return []
    
    return dict(get_unreturned_assets=get_unreturned_assets)

# ==================== 登录相关 ====================
@login_manager.user_loader
def load_user(user_id):
    try:
        from models import User
        return db.session.get(User, int(user_id))
    except Exception as e:
        logging.error(f"加载用户失败: {e}")
        return None

# ==================== AJAX 接口 ====================
@app.route('/validate_id_card', methods=['POST'])
def validate_id_card_ajax():
    try:
        data = request.get_json()
        id_card = data.get('id_card', '').strip()
        
        if len(id_card) != 18:
            return jsonify({'valid': False, 'error': '身份证必须为18位'})
        
        if not validate_id_card(id_card):
            return jsonify({'valid': False, 'error': '身份证校验码错误'})
        
        return jsonify({
            'valid': True,
            'gender': get_gender_from_id_card(id_card),
            'birthday': format_date(get_birthday_from_id_card(id_card))
        })
    except Exception as e:
        logging.error(f"身份证校验接口出错: {e}")
        return jsonify({'valid': False, 'error': '服务器处理失败'}), 500

@app.context_processor
def inject_keys():
    return dict(TENCENT_KEY_GLOBAL=Config.TENCENT_KEY)

@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    try:
        return send_from_directory(r"D:\cailu\uploads", filename)
    except Exception as e:
        logging.error(f"上传文件访问失败: {e}")
        return jsonify({'code': 404, 'msg': '文件不存在'}), 404

@app.route('/<filename>')
def serve_root_file(filename):
    try:
        return send_from_directory(app.root_path, filename)
    except Exception as e:
        logging.error(f"根文件访问失败: {e}")
        return jsonify({'code': 404, 'msg': '文件不存在'}), 404
@app.route('/healthz')
def healthz():
    """轻量健康检查：用于快速判断应用与数据库是否可用。"""
    try:
        db.session.execute(func.count(User.id)).scalar()
        return jsonify({
            'status': 'ok',
            'time': datetime.now().isoformat(timespec='seconds'),
            'pid': os.getpid(),
            'threads': threading.active_count()
        }), 200
    except Exception as e:
        logging.error(f"健康检查失败: {e}")
        return jsonify({'status': 'degraded', 'error': str(e)}), 500

# ==================== 核心优化3：定时任务独立线程运行 ====================
def start_background_tasks():
    """启动后台定时任务（独立线程）"""
    try:
        from utils import start_backup_scheduler, start_notification_cleanup_scheduler
        # 启动备份任务
        start_backup_scheduler(interval=86400)
        # 启动通知清理任务
        start_notification_cleanup_scheduler(weekday=0, hour=3, minute=33, retention_days=30)
        logging.info("后台定时任务启动成功")
    except Exception as e:
        logging.error(f"后台任务启动失败: {e}")
def start_heartbeat_logger(interval=60):
    """周期性写入心跳日志，便于判断进程是否假活。"""
    def heartbeat_task():
        while True:
            try:
                logging.info("HEARTBEAT alive pid=%s active_threads=%s", os.getpid(), threading.active_count())
            except Exception as e:
                logging.error(f"心跳日志写入失败: {e}")
            time.sleep(interval)

    threading.Thread(target=heartbeat_task, daemon=True).start()

# ==================== 初始化函数 ====================
def init_app():
    """应用初始化（封装核心逻辑）"""
    with app.app_context():
        # 动态注册权限
        try:
            from routes.hr.permissions import HR_PERMISSIONS
            from routes.asset.core import ASSET_PERMISSIONS
            from routes.fund import FUND_PERMISSIONS
            from routes.scheduling import SCHEDULING_PERMISSIONS
            from routes.dorm import DORM_PERMISSIONS
            from routes.trip import TRIP_PERMISSIONS
            from routes.leave import LEAVE_PERMISSIONS
            
            register_module_permissions('hr', HR_PERMISSIONS)
            register_module_permissions('asset', ASSET_PERMISSIONS)
            register_module_permissions('fund', FUND_PERMISSIONS)
            register_module_permissions('scheduling', SCHEDULING_PERMISSIONS)
            register_module_permissions('dorm', DORM_PERMISSIONS)
            register_module_permissions('trip', TRIP_PERMISSIONS)
            register_module_permissions('leave', LEAVE_PERMISSIONS)
            logging.info("权限注册完成")
        except ImportError as e:
            logging.warning(f"部分模块权限未注册: {e}")
        
        # 创建管理员账号
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(
                username='admin',
                name='系统管理员',
                role='admin'
            )
            admin_user.set_password('admin')
            db.session.add(admin_user)
            db.session.commit()
            logging.info("创建系统管理员账号成功")
        
        # 启动后台定时任务（独立线程）
        threading.Thread(target=start_background_tasks, daemon=True).start()
        start_heartbeat_logger(interval=60)
        logging.info("数据库初始化完成，应用启动准备就绪")

# ==================== 主函数 ====================
if __name__ == '__main__':
    init_app()
    
    host = '127.0.0.1' 
    port = 8001
    
    try:
        from waitress import serve
        
        logging.info(f"✅ 后端服务启动成功，监听本地端口：http://{host}:{port}")
        logging.info(f"🚀 请通过 Nginx 代理地址访问：https://cailutebao.top:8000")
        
        serve(
            app,
            host=host,
            port=port,
            threads=24,           
            connection_limit=1024,
            channel_timeout=120,
            cleanup_interval=30
        )
    
    except Exception as e:
        logging.error(f"❌ Waitress 启动失败: {e}")
        app.run(host=host, port=port, debug=False, threaded=True)