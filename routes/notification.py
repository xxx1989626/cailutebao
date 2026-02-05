# routes/notification.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from models import Notification, User, db
from utils import perm
from datetime import datetime

notification_bp = Blueprint('notification', __name__, url_prefix='/notification')

# 职位列表（与需求一致）
POSITIONS = ["队长", "副队长", "领班", "队员"]


def send_operation_notice(title, content, operated_user_id):
    """
    发送操作通知：
    :param title: 通知标题
    :param content: 通知内容
    :param operated_user_id: 被操作人的用户ID（当事人）
    """
    # 步骤1：筛选接收人 - 队长、副队长、领班
    managers = User.query.filter(
        User.position.in_(["队长", "副队长", "领班"])
    ).all()
    # 步骤2：获取被操作人（当事人）
    operated_user = User.query.get(operated_user_id)
    
    # 步骤3：合并接收人（去重，避免重复通知）
    receiver_ids = set()
    # 添加管理人员ID
    for manager in managers:
        receiver_ids.add(manager.id)
    # 添加被操作人ID（确保存在）
    if operated_user:
        receiver_ids.add(operated_user.id)
    
    # 步骤4：为每个接收人生成通知
    for receiver_id in receiver_ids:
        new_notice = Notification(
            user_id=receiver_id,  # 接收人ID
            title=title,
            content=content,
            is_read=False,  # 默认为未读
            created_at=datetime.now()  # 自动生成当前时间
        )
        db.session.add(new_notice)
    db.session.commit()

# 原有接口保持不变
@notification_bp.route('/list')
@login_required
def notification_list():
    # 获取页码参数，默认为第 1 页，每页显示 10 条
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # 使用 paginate 进行分页查询
    pagination = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    
    # 获取当前用户的总未读数（用于顶部显示，不受分页影响）
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    
    return render_template('notification/list.html', 
                           pagination=pagination, 
                           notifications=pagination.items,
                           unread_count=unread_count)

@notification_bp.route('/read/<int:notify_id>')
@login_required
def mark_as_read(notify_id):
    """标记通知为已读"""
    notification = Notification.query.filter_by(id=notify_id, user_id=current_user.id).first_or_404()
    notification.is_read = True
    db.session.commit()
    return redirect(url_for('notification.notification_list'))


@notification_bp.route('/read_all', methods=['POST'])
@login_required
def read_all():
    from models import Notification, db
    # 找到当前用户所有未读的通知
    unread_notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).all()
    
    for notice in unread_notifications:
        notice.is_read = True
    
    db.session.commit()
    flash('所有通知已标记为已读', 'success')
    return redirect(request.referrer or url_for('main.index'))

@notification_bp.route('/unread_count')
@login_required
def get_unread_count():
    from models import Notification, EmploymentCycle
    # 1. 检查未读通知
    notice_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    
    # 2. 检查待审核人员 (仅给有权限的管理人员报警)
    pending_hr_count = 0
    from utils import perm 
    if perm.can('hr.view'):
        pending_hr_count = EmploymentCycle.query.filter_by(status='待审核').count()
    
    # 返回总和。只要这个数字 > 0，网页就会嘀嘀嘀
    return {"unread_count": notice_count + pending_hr_count}