#D:\cailu\cailutebao\routes\reminder\document_expiry.py
# 证件到期提醒：单文件单路由
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from models import db, User, EmploymentCycle, EmployeeDocument, Notification
from datetime import date, datetime, timedelta
from sqlalchemy import and_
import logging

bp = Blueprint('reminder_document', __name__, url_prefix='/reminder/document')

# 到期提醒阈值（天）
EXPIRE_WARN_DAYS = 7
# 通知去重周期（天）
DEDUP_DAYS = 3


def run_check():
    """检查所有在职员工证件到期情况并发送通知（供定时任务调用）"""
    today = date.today()
    # 查询所有有到期日期的证件，关联在职员工
    docs = EmployeeDocument.query.join(EmploymentCycle)\
        .filter(
            EmployeeDocument.expire_date.isnot(None),
            EmploymentCycle.status == '在职'
        ).all()
    
    sent_count = 0
    for doc in docs:
        cycle = doc.cycle
        if not cycle:
            continue
        # 通过身份证号找用户
        user = User.query.filter_by(username=cycle.id_card).first()
        if not user:
            continue
        
        days_left = (doc.expire_date - today).days
        
        if days_left < 0:
            status_text = '已过期'
            title = f'证件已过期：{doc.doc_type}'
        elif days_left <= EXPIRE_WARN_DAYS:
            status_text = f'即将过期（{days_left}天后）'
            title = f'证件即将过期：{doc.doc_type}'
        else:
            continue
        
        # 去重：最近 DEDUP_DAYS 天内同类通知不重复发送
        recent = Notification.query.filter(
            and_(
                Notification.user_id == user.id,
                Notification.title == title,
                Notification.created_at >= datetime.now() - timedelta(days=DEDUP_DAYS)
            )
        ).first()
        if recent:
            continue
        
        content = f"""<p>证件类型：{doc.doc_type}</p>
<p>证件号码：{doc.doc_number or '无'}</p>
<p>到期日期：{doc.expire_date.strftime('%Y-%m-%d')}</p>
<p>状态：<span class="text-danger">{status_text}</span></p>
<p>请及时处理，以免影响正常工作。</p>"""
        
        notification = Notification(
            user_id=user.id,
            title=title,
            content=content,
            related_type='document_expiry',
            related_id=doc.id
        )
        db.session.add(notification)
        sent_count += 1
    
    db.session.commit()
    if sent_count:
        logging.info(f"证件到期提醒：发送 {sent_count} 条通知")
    return sent_count


@bp.route('/check', methods=['POST'])
@login_required
def check():
    """手动触发证件到期检查（仅管理员）"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': '权限不足'}), 403
    count = run_check()
    return jsonify({'success': True, 'message': f'检查完成，发送 {count} 条提醒'})
