from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from models import db, User, EmploymentCycle, ChatMessage
from datetime import datetime
from utils import perm

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/api/chat/users')
@login_required
def get_chat_users():
    try:
        # 1. 获取所有在职人员 ID
        active_cycles = EmploymentCycle.query.filter(
            EmploymentCycle.departure_date == None,
            EmploymentCycle.status == '在职'
        ).all()
        active_id_cards = [cycle.id_card for cycle in active_cycles]
        
        # 2. 基本过滤：只看在职且有账号的人
        base_query = User.query.filter(User.username.in_(active_id_cards), User.id != current_user.id)

        # 核心逻辑判断
        if current_user.role == 'admin' or perm.can('chat.send_private'):
            # 管理员或有权者：看到所有在职人员
            users = base_query.all()
        else:
            # 普通队员：平时名单为空，但要查出“谁给我发过私聊”
            # 从聊天记录里找：接收者是我，且不是群聊的消息发送者
            talked_user_ids = db.session.query(ChatMessage.sender_id).filter(
                ChatMessage.recipient_id == current_user.id,
                ChatMessage.is_group == False
            ).distinct().all()
            user_ids = [u[0] for u in talked_user_ids]
            users = User.query.filter(User.id.in_(user_ids)).all()

        return jsonify([{'id': u.id, 'name': u.name} for u in users])
    except Exception as e:
        return jsonify([])

@chat_bp.route('/api/chat/history/<target_id>')
@login_required
def get_history(target_id):
    try:
        if target_id == 'group':
            msgs = ChatMessage.query.filter_by(is_group=True)\
                .order_by(ChatMessage.timestamp.asc()).limit(50).all()
        else:
            msgs = ChatMessage.query.filter(
                ((ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_id == target_id)) |
                ((ChatMessage.sender_id == target_id) & (ChatMessage.recipient_id == current_user.id))
            ).order_by(ChatMessage.timestamp.asc()).limit(50).all()
        
        return jsonify([{
            'sender_id': m.sender_id,
            'sender_name': m.sender.name if m.sender else "系统",
            'content': m.content,
            'timestamp': m.timestamp.strftime('%H:%M'),
            'full_date': m.timestamp.strftime('%Y-%m-%d'), 
            'is_group': m.is_group
        } for m in msgs])
    except Exception as e:
        print(f"获取历史记录失败: {str(e)}")
        return jsonify([])
    
CHAT_PERMISSIONS = [
    ('view_group', '查看群聊', '查看群聊信息'),
    ('view_private', '查看私聊', '查看私聊信息'),
    ('send_private', '发送私聊', '发送私聊信息')
]