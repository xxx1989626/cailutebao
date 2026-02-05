# utils.py
# 系统通用工具函数
__all__ = [
    'validate_id_card', 'validate_phone', 'parse_date', 'format_date', 'today_str',
    'get_unreturned_assets', 'register_module_permissions', 'PermissionManager'
]

import os
import uuid
import shutil
import time
import threading
import re
import json
from datetime import datetime, timedelta, date
from typing import Union, Optional
from flask import current_app, flash, redirect, url_for
from flask_login import current_user
from functools import wraps
import pandas as pd
from werkzeug.utils import secure_filename


# ==================== 身份证相关 ====================
def validate_id_card(id_card: str) -> bool:
    """校验身份证号码是否合法（18位，包含校验码验证）"""
    id_card = id_card.strip()  # 去除前后空格
    if len(id_card) != 18:
        return False
    
    # 前17位必须是数字
    if not id_card[:17].isdigit():
        return False
    
    # 加权因子
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    # 校验码对应表
    check_codes = '10X98765432'
    
    # 只计算前17位
    total = sum(int(id_card[i]) * weights[i] for i in range(17))
    check_code = check_codes[total % 11]
    
    # 校验码比较（X 不区分大小写）
    return id_card[-1].upper() == check_code

def get_gender_from_id_card(id_card: str) -> str:
    """从身份证号码提取性别"""
    if len(id_card) != 18:
        return ''
    gender_code = int(id_card[16])
    return '男' if gender_code % 2 == 1 else '女'

def get_birthday_from_id_card(id_card: str) -> Optional[datetime.date]:
    """从身份证号码提取出生日期"""
    if len(id_card) != 18:
        return None
    try:
        year = int(id_card[6:10])
        month = int(id_card[10:12])
        day = int(id_card[12:14])
        return datetime(year, month, day).date()
    except ValueError:
        return None

# ==================== 手机号码校验 ====================
def validate_phone(phone: str) -> bool:
    """校验中国大陆手机号码"""
    pattern = re.compile(r'^1[3-9]\d{9}$')
    return bool(pattern.match(phone))


# ==================== 日期工具 ====================
def parse_date(date_input) -> Optional[date]:
    """
    解析多种日期格式，返回 date 对象
    """
    if date_input is None or (isinstance(date_input, float) and pd.isna(date_input)):
        return None
    
    # 1. 已经是 date 或 datetime 对象
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input

    # 2. pandas Timestamp
    if isinstance(date_input, pd.Timestamp):
        return date_input.date()
    
    # 3. Excel 序列号处理
    if isinstance(date_input, (int, float)):
        try:
            # Excel在Windows下以1899-12-30为基准
            return (datetime(1899, 12, 30) + timedelta(days=int(date_input))).date()
        except:
            pass
    
    # 4. 字符串处理
    s = str(date_input).strip()
    if not s or s.lower() in ('none', 'nan', 'null'):
        return None
        
    # 尝试多种解析格式
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d', '%Y年%m月%d日'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
            
    # 特殊处理 YYYY.MM 格式
    if '.' in s and len(s.split('.')) == 2:
        try:
            parts = s.split('.')
            return date(int(parts[0]), int(parts[1]), 1)
        except:
            pass

    return None

def format_date(date_obj, fmt='%Y年%m月%d日') -> str:
    """
    【核心修改点】将日期对象格式化为中文显示
    如果你想要 2023-11-11，就把上面的 fmt 改为 '%Y-%m-%d'
    """
    if not date_obj:
        return ''
    
    # 如果已经是字符串，先尝试转换成日期再格式化，防止格式不统一
    if isinstance(date_obj, str):
        # 如果字符串已经包含“年”，说明可能已经格式化过了
        if '年' in date_obj: return date_obj
        obj = parse_date(date_obj)
        return format_date(obj, fmt) if obj else date_obj
        
    try:
        return date_obj.strftime(fmt)
    except:
        return str(date_obj)

def today_str(fmt='%Y年%m月%d日') -> str:
    """获取今天的格式化字符串"""
    return datetime.today().strftime(fmt)

def format_datetime(dt_obj, fmt='%Y年%m月%d日 %H:%M') -> str:
    """格式化具体时间"""
    if not dt_obj:
        return ''
    if isinstance(dt_obj, str):
        return dt_obj
    try:
        return dt_obj.strftime(fmt)
    except:
        return str(dt_obj)

# ==================== 下拉选项数据 ====================
def get_ethnic_options() -> list[str]:
    """民族选项"""
    from config import FALLBACK_DATA
    return FALLBACK_DATA['ethnic']

def get_politics_options() -> list[str]:
    """政治面貌选项"""
    from config import FALLBACK_DATA
    return FALLBACK_DATA['politics']

def get_education_options() -> list[str]:
    """学历选项"""
    from config import FALLBACK_DATA
    return FALLBACK_DATA['education']

# ==================== 离职提醒：未归还资产 ====================
# utils.py - 添加离职未归还资产查询函数
def get_unreturned_assets(cycle_id):
    """查询该员工当前领用的个人分配资产（未归还）"""
    from models import Asset
    
    return Asset.query.filter(
        Asset.current_user_id == cycle_id,
        Asset.allocation_mode == 'personal',
        Asset.status == '使用中'
    ).all()


# ==================== 权限管理 ====================

class PermissionManager:
    """权限分配器：去角色化，只看数据库里的权限记录"""
    
    # 基础配置
    ROLE_DEFAULT_PERMISSIONS = {
        'admin': 'all',    # 超级管理员拥有所有权限
        'member': ['base_view'] # 普通成员默认只有基础查看权
    }

    def can(self, permission_key):
        """核心判断：检查当前登录人手里有没有具体的权限钥匙"""
        from models import Permission, UserPermission
        
        # 如果没登录，啥也干不了
        if not current_user or not current_user.is_authenticated:
            return False
            
        # 1. 如果角色是 admin，直接放行，不用查表
        if current_user.role == 'admin':
            return True
            
        # 2. 核心：去数据库里查 UserPermission 表，看这个用户有没有对应的权限
        perm_obj = Permission.query.filter_by(key=permission_key).first()
        if perm_obj:
            # 看看关联表里有没有 (用户ID + 权限ID) 的记录
            has_assigned = UserPermission.query.filter_by(
                user_id=current_user.id,
                permission_id=perm_obj.id
            ).first()
            if has_assigned:
                return True
                
        # 3. 兜底：检查角色自带的基础权限（比如 member 默认能看自己的 view）
        allowed_perms = self.ROLE_DEFAULT_PERMISSIONS.get(current_user.role, [])
        return 'all' in allowed_perms or permission_key in allowed_perms

    def require(self, permission_key):
        """修饰器：保护路由，没权限就踢出去"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if not self.can(permission_key):
                    from models import Permission
                    perm_obj = Permission.query.filter_by(key=permission_key).first()
                    display_name = perm_obj.name if perm_obj else permission_key
                    flash(f'权限不足，缺少: {display_name}', 'danger')
                    return redirect(url_for('main.index'))
                return f(*args, **kwargs)
            return decorated_function
        return decorator

# 重要：在这里实例化对象，供 app.py 导入使用
perm = PermissionManager()

def register_module_permissions(module, permissions):
    """把我们在路由里定义的权限列表，同步到数据库中"""
    from models import Permission, db
    try:
        for action, name, description in permissions:
            key = f"{module}.{action}"
            # 如果数据库里还没这个权限，就加进去
            if not Permission.query.filter_by(key=key).first():
                new_p = Permission(
                    key=key, module=module, action=action,
                    name=name, description=description
                )
                db.session.add(new_p)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"权限注册失败: {e}")



# ==================== 审计日志（Audit Log）+通知 ====================
def log_action(action_type, target_type, target_id, description, **kwargs):
    """
    记录审计日志 + 自动发送通知（支持自动提取被操作人）
    :param kwargs: 接收额外参数（如 user_id、cycle_id，自动识别为 operated_user_id）
    """
    try:
        from models import db, OperationLog, Notification, User, EmploymentCycle
        from flask_login import current_user
        
        # 1. 原有逻辑：记录审计日志（不变）
        new_log = OperationLog(
            user_id=current_user.id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            description=description
        )
        db.session.add(new_log)
        
        # 2. 自动提取被操作人 ID（核心优化：支持多场景自动识别）
        operated_user_id = None
        # 场景1：资产发放/归还（参数为 user_id）
        if 'user_id' in kwargs:
            operated_user_id = kwargs['user_id']
        # 场景2：人员编辑/离职（参数为 cycle_id）
        elif 'cycle_id' in kwargs:
            operated_user_id = kwargs['cycle_id']
        # 场景3：从 target_id 反向查询（如 target_type 是 Employee 时，target_id 即 cycle_id）
        elif target_type == 'Employee':
            operated_user_id = target_id
        
        # 3. 筛选通知接收人（队长、副队长、领班 + 被操作人）
        receiver_ids = set()
        
        # 步骤1：查询管理人员（队长/副队长/领班）
        managers = EmploymentCycle.query.filter(
            EmploymentCycle.status == '在职',
            EmploymentCycle.position.in_(["队长", "副队长", "领班"])
        ).all()
        for manager in managers:
            manager_user = User.query.filter_by(username=manager.id_card).first()
            if manager_user:
                receiver_ids.add(manager_user.id)
        
        # 步骤2：添加被操作人（当事人）
        operated_user_name = "未知用户"
        if operated_user_id:
            operated_emp = EmploymentCycle.query.get(operated_user_id)
            if operated_emp:
                operated_user_name = operated_emp.name
                # 关联被操作人的 User ID
                operated_user = User.query.filter_by(username=operated_emp.id_card).first()
                if operated_user:
                    receiver_ids.add(operated_user.id)
        
        # 4. 生成通知（包含被操作人名字）
        if receiver_ids:
            notify_title = f"系统操作通知：{action_type}"
            notify_content = f"""
            <p>操作人：{current_user.name}</p>
            <p>操作类型：{action_type}</p>
            <p>操作对象：{target_type}（ID：{target_id}）</p>
            <p>被操作人：{operated_user_name}</p>
            <p>操作详情：{description}</p>
            <p>操作时间：{format_datetime(datetime.now())}</p>
            """
            for receiver_id in receiver_ids:
                notification = Notification(
                    user_id=receiver_id,
                    title=notify_title,
                    content=notify_content,
                    related_type=target_type,
                    related_id=target_id
                )
                db.session.add(notification)
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()  # 出错时回滚
        print(f"日志记录/通知发送失败: {str(e)}")



# ==================== 文件上传 ====================
def save_uploaded_file(file, module='misc', sub_folder=None):
    """通用文件上传处理 - 存储至 D:/cailu/uploads"""
    if not (file and file.filename):
        return None
    
    ext = os.path.splitext(file.filename)[1].lower()
    
    # 安全黑名单
    denied_extensions = {'.exe', '.php', '.py', '.sh', '.bat', '.js', '.vbs'}
    if ext in denied_extensions:
        return None

    now = datetime.now()
    if sub_folder:
        relative_sub_path = os.path.join('uploads', module, str(sub_folder))
    else:
        relative_sub_path = os.path.join('uploads', module, str(now.year), f"{now.month:02d}")
        
    base_physical_dir = r"D:\cailu"
    physical_upload_dir = os.path.join(base_physical_dir, relative_sub_path)
    
    # 确保目录存在，递归创建
    os.makedirs(physical_upload_dir, exist_ok=True)
    
    unique_filename = f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    full_save_path = os.path.join(physical_upload_dir, unique_filename)
    
    # 增加文件保存异常捕获
    try:
        file.save(full_save_path)
    except Exception as e:
        print(f"文件保存失败: {str(e)}")
        return None
    
    # 返回数据库路径：统一用 / 分隔
    return os.path.join(relative_sub_path, unique_filename).replace('\\', '/')

# ==================== 清理孤立文件（安全版） ====================
def cleanup_isolated_files():
    """
    深度解析版：专门针对 archives JSON 结构进行文件保护
    """
    from models import db, Asset, FundsRecord, User, EmploymentCycle
    
    base_dir = r"D:\cailu"
    uploads_dir = os.path.join(base_dir, 'uploads')
    recycle_bin_dir = os.path.join(base_dir, 'recycle_bin', datetime.now().strftime('%Y%m%d_%H'))
    
    if not os.path.exists(uploads_dir):
        return

    try:
        # --- 第一步：深度收集合法路径 ---
        used_files = set()

        def add_to_used(path):
            if path:
                # 统一标准化：转小写、标准化斜杠、去掉两端空格
                norm = os.path.normpath(path).lower().strip().lstrip('\\').lstrip('/')
                used_files.add(norm)

        # 1. 基础字段收集 (资产、财务、头像)
        assets = db.session.query(Asset.photo_path).filter(Asset.photo_path.isnot(None)).all()
        for (p,) in assets: add_to_used(p)

        funds = db.session.query(FundsRecord.attachment).filter(FundsRecord.attachment.isnot(None)).all()
        for (p,) in funds:
            p_full = p if p.lower().startswith('uploads') else os.path.join('uploads', 'funds', p)
            add_to_used(p_full)

        # 2. 队员信息深度扫描 (照片 + JSON档案)
        employees = db.session.query(EmploymentCycle.photo_path, EmploymentCycle.archives).all()
        for photo, archives_json in employees:
            if photo: 
                add_to_used(photo)
            
            # --- 核心：解析你的 JSON 结构 ---
            if archives_json:
                try:
                    data = json.loads(archives_json)
                    # 处理 archive_records 列表中的文件
                    records = data.get('archive_records', [])
                    for rec in records:
                        f_path = rec.get('file_path')
                        if f_path:
                            add_to_used(f_path)
                    
                    # 处理 other_certificates 列表中的文件 (预防性增加)
                    certs = data.get('other_certificates', [])
                    for cert in certs:
                        c_path = cert.get('file_path') or cert.get('path')
                        if c_path:
                            add_to_used(c_path)
                except Exception as e:
                    print(f"JSON解析跳过: {e}")

        # --- 第二步：系统级保护名单 ---
        # 保护默认头像、系统图标，以及你提到的 archive 关键词以防万一
        SYSTEM_SAFE = ['avatar_default', 'default', 'logo', 'favicon', 'static']

        # --- 第三步：物理扫描与安全移动 ---
        count = 0
        now_ts = time.time()
        
        for root, dirs, files in os.walk(uploads_dir):
            for file in files:
                # 1. 优先命中系统白名单则不删
                if any(kw in file.lower() for kw in SYSTEM_SAFE):
                    continue
                
                full_path = os.path.join(root, file)
                # 计算相对 D:\cailu 的路径（如 uploads\archive\...\xxx.jpg）
                rel_path = os.path.relpath(full_path, base_dir)
                rel_path_norm = os.path.normpath(rel_path).lower().strip()

                # 2. 只有不在数据库集合里的才移动
                if rel_path_norm not in used_files:
                    # 3. 存在超过 2 小时才动，给上传过程留缓冲
                    if now_ts - os.path.getmtime(full_path) > 7200:
                        if not os.path.exists(recycle_bin_dir):
                            os.makedirs(recycle_bin_dir)
                        
                        target = os.path.join(recycle_bin_dir, f"{datetime.now().strftime('%M%S')}_{file}")
                        shutil.move(full_path, target)
                        count += 1

        if count > 0:
            print(f"[{datetime.now()}] 维护完成：{count}个文件已移至回收站")

    except Exception as e:
        print(f"维护逻辑出错: {str(e)}")

# ==================== 删除物理文件（安全版） ====================
def delete_physical_file(file_relative_path):
    if not file_relative_path:
        return False
    
    # --- 紧急新增：保护硬编码的系统文件 ---
    # 只要路径里包含这些词，不管谁调用，绝对不准物理删除
    PROTECTED_SYSTEM_FILES = ['default', 'avatar_default', 'logo', 'favicon', 'static']
    if any(word in file_relative_path.lower() for word in PROTECTED_SYSTEM_FILES):
        print(f"安全拦截：系统保护文件，拒绝物理删除: {file_relative_path}")
        return False

    base_dir = r"D:\cailu"
    abs_path = os.path.normpath(os.path.join(base_dir, file_relative_path))
    
    # 安全校验：仅允许删除 uploads 目录下的文件
    if not abs_path.lower().startswith(os.path.join(base_dir, 'uploads').lower()):
        print(f"安全拦截：禁止删除非uploads目录文件: {abs_path}")
        return False
    
    try:
        if os.path.exists(abs_path):
            # 【核心修改】：将物理删除改为移动到回收站，双重保险
            recycle_base = os.path.join(base_dir, 'recycle_bin', 'manual_delete')
            os.makedirs(recycle_base, exist_ok=True)
            
            target_path = os.path.join(recycle_base, f"{datetime.now().strftime('%H%M%S')}_{os.path.basename(abs_path)}")
            import shutil
            shutil.move(abs_path, target_path)
            print(f"成功将文件移至备份区（替代删除）: {target_path}")
            return True
        return False
    except Exception as e:
        print(f"处理文件失败: {str(e)}")
        return False

# ==================== 数据库自动备份 ====================
def auto_backup_database():
    from config import DATABASE_PATH
    BACKUP_DIR = r"D:\cailu\backups"
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        
    filename = f'db_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    try:
        shutil.copy2(DATABASE_PATH, os.path.join(BACKUP_DIR, filename))
        print(f"[{datetime.now()}] 数据库备份成功: {filename}")
    except Exception as e:
        print(f"备份失败: {str(e)}")

# ==================== 后台调度器 ====================
def start_backup_scheduler(interval=86400):
    def maintenance_task():
        time.sleep(30) # 启动后避开高峰
        while True:
            try:
                from app import app
                with app.app_context():
                    print(f"[{datetime.now()}] 启动例行维护任务...")
                    # 只有在这里被调用，清理才会执行
                    cleanup_isolated_files()
                    auto_backup_database()
            except Exception as e:
                print(f"维护线程遇到致命错误: {e}")
            time.sleep(interval)

    thread = threading.Thread(target=maintenance_task, daemon=True)
    thread.start()