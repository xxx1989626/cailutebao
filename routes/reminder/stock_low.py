#D:\cailu\cailutebao\routes\reminder\stock_low.py
# 库存不足提醒：单文件单路由
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from models import db, User, Asset, Notification, Permission, UserPermission
from utils import perm
from datetime import datetime, timedelta
from sqlalchemy import and_
import logging

bp = Blueprint('reminder_stock', __name__, url_prefix='/reminder/stock')

# 低库存阈值（库存量 <= 该值触发提醒）
LOW_STOCK_THRESHOLD = 2
# 通知去重周期（天）
DEDUP_DAYS = 3
# 接收人所需的权限key（资产提醒）
REQUIRED_PERM_KEY = 'asset.alert'


def _get_recipients():
    """查询拥有补充库存权限的用户列表（权限分配模式）"""
    perm_obj = Permission.query.filter_by(key=REQUIRED_PERM_KEY).first()
    if not perm_obj:
        return []
    return User.query.join(UserPermission, UserPermission.user_id == User.id)\
        .filter(UserPermission.permission_id == perm_obj.id).all()


def run_check():
    """检查消耗品库存情况，低于阈值时通知有补充库存权限的用户（供定时任务调用）"""
    # 仅检查消耗品类型，固定资产/装备等不触发库存提醒
    low_assets = Asset.query.filter(
        Asset.type == '消耗品',
        Asset.stock_quantity <= LOW_STOCK_THRESHOLD
    ).all()
    if not low_assets:
        return 0

    # 查询拥有补充库存权限的接收人
    recipients = _get_recipients()
    if not recipients:
        return 0

    sent_count = 0
    for asset in low_assets:
        title = f'库存不足：{asset.name}'

        # 去重：每个接收人最近 DEDUP_DAYS 天内同类通知不重复发送
        for recipient in recipients:
            recent = Notification.query.filter(
                and_(
                    Notification.user_id == recipient.id,
                    Notification.title == title,
                    Notification.created_at >= datetime.now() - timedelta(days=DEDUP_DAYS)
                )
            ).first()
            if recent:
                continue

            content = f"""<p>资产名称：{asset.name}</p>
<p>资产编号：{asset.number or '无'}</p>
<p>资产类型：{asset.type}</p>
<p>当前库存：<span class="text-danger">{asset.stock_quantity}</span></p>
<p>存放位置：{asset.location or '未设置'}</p>
<p>请及时补充库存。</p>"""

            notification = Notification(
                user_id=recipient.id,
                title=title,
                content=content,
                related_type='stock_low',
                related_id=asset.id
            )
            db.session.add(notification)
            sent_count += 1

    db.session.commit()
    if sent_count:
        logging.info(f"库存不足提醒：发送 {sent_count} 条通知")
    return sent_count


@bp.route('/check', methods=['POST'])
@login_required
def check():
    """手动触发库存检查（需拥有补充库存权限）"""
    if not perm.can(REQUIRED_PERM_KEY):
        return jsonify({'success': False, 'message': '权限不足'}), 403
    count = run_check()
    return jsonify({'success': True, 'message': f'检查完成，发送 {count} 条提醒'})
