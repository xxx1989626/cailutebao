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
from datetime import datetime, timedelta, date,time as dt_time
from typing import Union, Optional
from flask import current_app, flash, redirect, url_for
from flask_login import current_user
from functools import wraps
import pandas as pd
from werkzeug.utils import secure_filename

# ==================== 身份证相关 ====================
def validate_id_card(id_card: str) -> bool:
    id_card = id_card.strip()  
    if len(id_card) != 18:
        return False
    if not id_card[:17].isdigit():
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = '10X98765432'
    total = sum(int(id_card[i]) * weights[i] for i in range(17))
    check_code = check_codes[total % 11]
    return id_card[-1].upper() == check_code

def get_gender_from_id_card(id_card: str) -> str:
    if len(id_card) != 18:
        return ''
    gender_code = int(id_card[16])
    return '男' if gender_code % 2 == 1 else '女'

def get_birthday_from_id_card(id_card: str) -> Optional[datetime.date]:
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
    pattern = re.compile(r'^1[3-9]\d{9}$')
    return bool(pattern.match(phone))

# ==================== 日期工具 ====================
def parse_date(date_input) -> Optional[date]:
    if date_input is None or (isinstance(date_input, float) and pd.isna(date_input)):
        return None
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input
    if isinstance(date_input, pd.Timestamp):
        return date_input.date()
    if isinstance(date_input, (int, float)):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=int(date_input))).date()
        except:
            pass
    s = str(date_input).strip()
    if not s or s.lower() in ('none', 'nan', 'null'):
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d', '%Y年%m月%d日'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    if '.' in s and len(s.split('.')) == 2:
        try:
            parts = s.split('.')
            return date(int(parts[0]), int(parts[1]), 1)
        except:
            pass
    return None

def format_date(date_obj, fmt='%Y-%m-%d') -> str:
    if not date_obj:
        return ''
    if isinstance(date_obj, str):
        if '年' in date_obj: return date_obj
        obj = parse_date(date_obj)
        return format_date(obj, fmt) if obj else date_obj
    try:
        return date_obj.strftime(fmt)
    except:
        return str(date_obj)

def today_str(fmt='%Y-%m-%d') -> str:
    return datetime.today().strftime(fmt)

def format_datetime(dt_obj, fmt='%Y年%m月%d日 %H:%M') -> str:
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
    from config import FALLBACK_DATA
    return FALLBACK_DATA['ethnic']

def get_politics_options() -> list[str]:
    from config import FALLBACK_DATA
    return FALLBACK_DATA['politics']

def get_education_options() -> list[str]:
    from config import FALLBACK_DATA
    return FALLBACK_DATA['education']

# ==================== 离职提醒：未归还资产 ====================
def get_unreturned_assets(cycle_id):
    from models import Asset
    
    return Asset.query.filter(
        Asset.current_user_id == cycle_id,
        Asset.allocation_mode == 'personal',
        Asset.status == '使用中'
    ).all()

# ==================== 权限管理 ====================
class PermissionManager:
    ROLE_DEFAULT_PERMISSIONS = {
        'admin': 'all',    
        'member': ['base_view'] 
    }
    def can(self, permission_key):
        from models import Permission, UserPermission
        if not current_user or not current_user.is_authenticated:
            return False
        if current_user.role == 'admin':
            return True
        perm_obj = Permission.query.filter_by(key=permission_key).first()
        if perm_obj:
            has_assigned = UserPermission.query.filter_by(
                user_id=current_user.id,
                permission_id=perm_obj.id
            ).first()
            if has_assigned:
                return True
        allowed_perms = self.ROLE_DEFAULT_PERMISSIONS.get(current_user.role, [])
        return 'all' in allowed_perms or permission_key in allowed_perms
    
    def require(self, permission_key):
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

perm = PermissionManager()
def register_module_permissions(module, permissions):
    from models import Permission, db
    try:
        for action, name, description in permissions:
            key = f"{module}.{action}"
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
    try:
        from models import db, OperationLog, Notification, User, EmploymentCycle
        from flask_login import current_user
        new_log = OperationLog(
            user_id=current_user.id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            description=description
        )
        db.session.add(new_log)
        operated_user_id = None
        if 'user_id' in kwargs:
            operated_user_id = kwargs['user_id']
        elif 'cycle_id' in kwargs:
            operated_user_id = kwargs['cycle_id']
        elif target_type == 'Employee':
            operated_user_id = target_id
        receiver_ids = set()
        managers = EmploymentCycle.query.filter(
            EmploymentCycle.status == '在职',
            EmploymentCycle.position.in_(["队长", "副队长", "领班"])
        ).all()
        for manager in managers:
            manager_user = User.query.filter_by(username=manager.id_card).first()
            if manager_user:
                receiver_ids.add(manager_user.id)
        operated_user_name = "未知用户"
        if operated_user_id:
            operated_emp = EmploymentCycle.query.get(operated_user_id)
            if operated_emp:
                operated_user_name = operated_emp.name
                operated_user = User.query.filter_by(username=operated_emp.id_card).first()
                if operated_user:
                    receiver_ids.add(operated_user.id)
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
        db.session.rollback()  
        print(f"日志记录/通知发送失败: {str(e)}")

# ==================== 文件上传 ====================
def save_uploaded_file(file, module='misc', sub_folder=None):
    if not (file and file.filename):
        return None
    ext = os.path.splitext(file.filename)[1].lower()
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
    os.makedirs(physical_upload_dir, exist_ok=True)
    unique_filename = f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    full_save_path = os.path.join(physical_upload_dir, unique_filename)
    try:
        file.save(full_save_path)
    except Exception as e:
        print(f"文件保存失败: {str(e)}")
        return None
    return os.path.join(relative_sub_path, unique_filename).replace('\\', '/')

# ==================== 清理孤立文件（安全版） ====================
def cleanup_isolated_files():
    from models import db, Asset, FundsRecord, User, EmploymentCycle, LeaveRecord
    base_dir = r"D:\cailu"
    uploads_dir = os.path.join(base_dir, 'uploads')
    recycle_bin_dir = os.path.join(base_dir, 'recycle_bin', datetime.now().strftime('%Y%m%d_%H'))
    if not os.path.exists(uploads_dir):
        return
    try:
        used_files = set()
        def add_to_used(path):
            if not path:
                return
            if isinstance(path, list):
                for item in path:
                    add_to_used(item)
                return
            if isinstance(path, str):
                try:
                    norm = os.path.normpath(path).lower().strip().lstrip('\\').lstrip('/')
                    used_files.add(norm)
                except Exception:
                    pass
        assets = db.session.query(Asset.photo_path).filter(Asset.photo_path.isnot(None)).all()
        for (p,) in assets: add_to_used(p)
        funds = db.session.query(FundsRecord.attachment).filter(FundsRecord.attachment.isnot(None)).all()
        for (p,) in funds:
            p_full = p if p.lower().startswith('uploads') else os.path.join('uploads', 'funds', p)
            add_to_used(p_full)
        employees = db.session.query(EmploymentCycle.photo_path, EmploymentCycle.archives).all()
        for photo, archives_json in employees:
            if photo: add_to_used(photo)
            if archives_json:
                try:
                    data = json.loads(archives_json)
                    for rec in data.get('archive_records', []):
                        add_to_used(rec.get('file_path'))
                    for cert in data.get('other_certificates', []):
                        add_to_used(cert.get('file_path') or cert.get('path'))
                except:
                    pass
        leaves = db.session.query(LeaveRecord.attachments).filter(LeaveRecord.attachments.isnot(None)).all()
        for (attachments,) in leaves:
            if isinstance(attachments, str) and (attachments.startswith('[') or attachments.startswith('{')):
                try:
                    parsed = json.loads(attachments)
                    add_to_used(parsed)
                except:
                    add_to_used(attachments)
            else:
                add_to_used(attachments)
        SYSTEM_SAFE = ['avatar_default', 'default', 'logo', 'favicon', 'static']
        count = 0
        now_ts = time.time()
        for root, dirs, files in os.walk(uploads_dir):
            for file in files:
                if any(kw in file.lower() for kw in SYSTEM_SAFE):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_dir)
                rel_path_norm = os.path.normpath(rel_path).lower().strip()
                if rel_path_norm not in used_files:
                    if now_ts - os.path.getmtime(full_path) > 7200:
                        if not os.path.exists(recycle_bin_dir):
                            os.makedirs(recycle_bin_dir)
                        target = os.path.join(recycle_bin_dir, f"{datetime.now().strftime('%M%S')}_{file}")
                        try:
                            shutil.move(full_path, target)
                            count += 1
                        except:
                            pass 
        if count > 0:
            print(f"[{datetime.now()}] 维护完成：{count}个孤立文件已移至回收站")
    except Exception as e:
        db.session.rollback()
        print(f"维护逻辑出错并已回滚: {str(e)}")
    finally:
        db.session.remove()

# ==================== 删除物理文件（安全版） ====================
def delete_physical_file(file_relative_path):
    if not file_relative_path:
        return False
    PROTECTED_SYSTEM_FILES = ['default', 'avatar_default', 'logo', 'favicon', 'static']
    if any(word in file_relative_path.lower() for word in PROTECTED_SYSTEM_FILES):
        print(f"安全拦截：系统保护文件，拒绝物理删除: {file_relative_path}")
        return False
    base_dir = r"D:\cailu"
    abs_path = os.path.normpath(os.path.join(base_dir, file_relative_path))
    if not abs_path.lower().startswith(os.path.join(base_dir, 'uploads').lower()):
        print(f"安全拦截：禁止删除非uploads目录文件: {abs_path}")
        return False
    try:
        if os.path.exists(abs_path):
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
def cleanup_old_notifications(days=30):
    try:
        from models import Notification, db
        cutoff = datetime.now() - timedelta(days=days)
        Notification.query.filter(Notification.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        print(f"[{datetime.now()}] 清理了 {days} 天前的通知")
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f"[{datetime.now()}] 清理通知时出错: {e}")

def _next_weekly_run(now, weekday, hour, minute):
    days_ahead = (weekday - now.weekday()) % 7
    run_date = (now + timedelta(days=days_ahead)).date()
    run_dt = datetime.combine(run_date, dt_time(hour, minute))
    if run_dt <= now:
        run_dt += timedelta(days=7)
    return run_dt

def start_notification_cleanup_scheduler(weekday=0, hour=3, minute=33, retention_days=30):
    def task():
        time.sleep(30)
        while True:
            next_run = _next_weekly_run(datetime.now(), weekday, hour, minute)
            sleep_sec = max(1, (next_run - datetime.now()).total_seconds())
            time.sleep(sleep_sec)
            try:
                from app import app
                with app.app_context():
                    cleanup_old_notifications(retention_days)
            except Exception as e:
                print(f"[{datetime.now()}] 通知清理线程出错: {e}")
    thread = threading.Thread(target=task, daemon=True)
    thread.start()

def start_backup_scheduler(interval=86400):
    def maintenance_task():
        time.sleep(30) 
        while True:
            try:
                from app import app
                with app.app_context():
                    print(f"[{datetime.now()}] 启动例行维护任务...")
                    cleanup_isolated_files()
                    auto_backup_database()
            except Exception as e:
                print(f"维护线程遇到致命错误: {e}")
            time.sleep(interval)
    thread = threading.Thread(target=maintenance_task, daemon=True)
    thread.start()