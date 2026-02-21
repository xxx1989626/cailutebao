# cailutebao/app.py.py
from flask_migrate import Migrate
from flask import Flask, jsonify, request, send_from_directory
from flask_login import LoginManager, current_user
from utils import today_str, perm, format_date, format_datetime, validate_id_card, get_gender_from_id_card, get_birthday_from_id_card, get_unreturned_assets, register_module_permissions
from config import Config, SECRET_KEY, DATABASE_PATH, UPLOAD_FOLDER, SALARY_MODES, POSITIONS, POSTS
from models import db, Asset, User, Permission, ChatMessage  # 如需彻底清理可删除 ChatMessage
from routes import register_blueprints
import json, os
from sqlalchemy import func

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SQLALCHEMY_DATABASE_URI=f'sqlite:///{DATABASE_PATH}',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=50 * 1024 * 1024
)

db.init_app(app)
register_blueprints(app)
migrate = Migrate(app, db, render_as_batch=True)

# Flask-Login 初始化
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录系统'
login_manager.login_message_category = 'warning'
login_manager.init_app(app)

# ==================== Jinja2 自定义过滤器 ====================
from datetime import datetime, date  # 确保导入

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
        return datetime.today().date()  # 静默默认今天（可加日志 if debug）

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

# ==================== 新增过滤器：计算工龄（核心修复） ====================
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

# ==================== Jinja2 自定义过滤器 ====================
@app.template_filter('fromjson')
def fromjson_filter(value):
    """安全地将 JSON 字符串解析为字典，失败返回空字典"""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}

# ==================== 全局模板上下文处理器（必须保留在 app.py） ====================
@app.context_processor
def inject_global_variables():
    return {
        'today_str': today_str,
        'format_date': format_date,
        'format_datetime': format_datetime,
        'perm': perm
    }

# 全局通知和待审核数量
@app.context_processor
def inject_global_data():
    if current_user.is_authenticated:
        from models import EmploymentCycle, Notification
        # 全局获取待审核人数
        p_count = EmploymentCycle.query.filter_by(status='待审核').count()
        # 全局获取未读通知数
        n_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(pending_count=p_count, unread_notice_count=n_count)
    return dict(pending_count=0, unread_notice_count=0)

# 注册一个全局模板函数
from datetime import datetime, timedelta

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
            print(f"DEBUG: 无法解析日期字符串 -> {date_str}")
            return False
            
        # 第三步：计算时间差
        diff = datetime.now() - record_time
        # 如果是未来时间（比如录入错误），或者在一小时内
        return diff < timedelta(hours=1)
        
    except Exception as e:
        print(f"DEBUG: 时间判断逻辑出错 -> {e}")
        return False

# ==================== 查询该员工领用的装备 ====================
@app.context_processor
def inject_equipped_assets():
    def get_equipped_assets(cycle_id):
        """查询该员工当前领用的装备（净领用数量 > 0）"""
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
    
    return dict(get_equipped_assets=get_equipped_assets)

# ==================== 查询该员工未归还的装备 ====================
@app.context_processor
def inject_unreturned_assets():
    def get_unreturned_assets(cycle_id):
        """查询该员工当前领用的装备（净领用数量 > 0） - 与员工详情页保持一致"""
        from models import AssetHistory, Asset
        from sqlalchemy import func
        
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
    
    return dict(get_unreturned_assets=get_unreturned_assets)

# ====================登录路由====================
@login_manager.user_loader
def load_user(user_id):
    from models import User
    return db.session.get(User, int(user_id))

# ==================== AJAX: 身份证校验（保持在主 app，不放蓝图） ====================
@app.route('/validate_id_card', methods=['POST'])
def validate_id_card_ajax():
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

@app.context_processor
def inject_keys():
    # 这样所有模板都能直接使用 {{ TENCENT_KEY_GLOBAL }}
    return dict(TENCENT_KEY_GLOBAL=Config.TENCENT_KEY)

@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    # 这里非常关键！
    # 如果数据库存的是 "uploads/asset/xxx.jpg"
    # 浏览器请求的是 "/uploads/asset/xxx.jpg"
    # 那么这里的 filename 接收到的就是 "asset/xxx.jpg"
    # 我们应该去 "D:\cailu\uploads" 下面找这个 filename
    return send_from_directory(r"D:\cailu\uploads", filename)

# 新增：允许访问根目录下的文件（用于微信验证）
@app.route('/<filename>')
def serve_root_file(filename):
    # 直接从项目根目录返回文件（微信验证文件放在根目录）
    return send_from_directory(app.root_path, filename)

if __name__ == '__main__':
    with app.app_context():

        # 新增：启动定时备份服务（项目启动时自动运行）
        from utils import start_backup_scheduler, start_notification_cleanup_scheduler
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            start_backup_scheduler(interval=86400)  # 86400秒=24小时，可修改间隔
        start_notification_cleanup_scheduler(weekday=0, hour=3, minute=33, retention_days=30)  # weekly 03:33 cleanup
        
        # 动态注册所有模块权限（必须在 context 内）
        try:
            from routes.hr import HR_PERMISSIONS
            from routes.asset import ASSET_PERMISSIONS
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
        except ImportError:
            pass  # 模块未定义权限列表，跳过
        
        # --- 证书路径配置 ---
        # 使用 r"" 原始字符串防止 Windows 路径转义错误
        cert_file = r"C:\Users\39160\AppData\Local\Posh-ACME\LE_PROD\3070382756\cailutebao.top\fullchain.cer"
        key_file = r"C:\Users\39160\AppData\Local\Posh-ACME\LE_PROD\3070382756\cailutebao.top\cert.key"

        # 创建系统管理员账号
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
            print("创建系统管理员账号成功")
        
        print("数据库初始化完成，定时备份服务已启动")
    
    # 启动服务器
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print("检测到安全证书，正在以 HTTPS 模式启动服务器...")
        app.run(
            host='0.0.0.0', 
            port=8000, 
            debug=False, 
            ssl_context=(cert_file, key_file)
        )
    else:
        print("警告：未找到证书文件，将以普通的 HTTP 模式启动！")
        app.run(host='0.0.0.0', port=8000, debug=False)