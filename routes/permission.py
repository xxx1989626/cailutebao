#D:\cailu\cailutebao\routes\permission.py
# 权限管理模块
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required,current_user
from models import db, Permission, UserPermission, EmploymentCycle, User,OperationLog
from utils import perm  # 确保 utils.py 底部有 perm = PermissionManager()
from datetime import datetime
permission_bp = Blueprint('permission', __name__, url_prefix='/permission')


# ==================== 权限分配界面 ====================
@permission_bp.route('/manage')
@login_required
@perm.require('manage')
def permission_manage():
    # 1. 获取员工并进行自定义职务排序 ---
    all_in_service = EmploymentCycle.query.filter_by(status='在职').all()
    
    # 手动定义职务的优先级（数字越小，排得越靠前）
    pos_order = {
        '队长': 1,
        '副队长': 2,
        '领班': 3,
        '队员': 4
    }

    # 使用 sorted 进行多级排序：
    # 第一优先级：职务权重 (pos_order)
    # 第二优先级：如果职务相同，按姓名排序
    sorted_employees = sorted(
        all_in_service, 
        key=lambda x: (pos_order.get(x.position.strip() if x.position else '', 99), x.name)
    )
    # 2. 获取账号映射：身份证号(username) -> 用户对象
    users = User.query.all() 
    id_card_to_user_id = {u.username: u.id for u in users} 
    
    # 3. 获取所有权限并按模块分组（用于前端表格展示）
    all_permissions = Permission.query.order_by(Permission.module, Permission.id).all()
    modules = {}
    for p in all_permissions:
        modules.setdefault(p.module, []).append(p)
    
    # 4. 获取用户权限映射关系：user_id -> [permission_id_list]
    user_perms_records = UserPermission.query.all()
    user_perms_dict = {}
    for up in user_perms_records:
        user_perms_dict.setdefault(up.user_id, []).append(up.permission_id)
    
    return render_template('permission/manage.html',
                           employees=sorted_employees,
                           modules=modules,
                           user_perms=user_perms_dict,
                           id_map=id_card_to_user_id)


# ==================== 权限保存（含全量差异审计） ====================
@permission_bp.route('/update', methods=['POST'])
@login_required
@perm.require('manage')
def permission_update():
    from utils import log_action
    
    # 1. 获取目标用户 ID
    raw_id = request.form.get('target_user_id') or request.values.get('target_user_id')
    if not raw_id:
        flash('未识别到目标用户，请重新选择员工', 'danger')
        return redirect(url_for('permission.permission_manage'))

    try:
        target_user_id = int(float(raw_id))
        target_user = User.query.get_or_404(target_user_id)
        emp_cycle = EmploymentCycle.query.filter_by(id_card=target_user.username).first()
        cycle_id = emp_cycle.id if emp_cycle else None
        
        # 2. 获取旧权限列表（用于差异对比）
        # 假设 UserPermission 关联了 Permission 表，我们取权限名称
        old_permissions = db.session.query(Permission.name).join(
            UserPermission, UserPermission.permission_id == Permission.id
        ).filter(UserPermission.user_id == target_user_id).all()
        old_set = {p[0] for p in old_permissions}

        # 3. 获取新勾选的权限 ID 列表并查询其名称
        selected_perm_ids = [int(pid) for pid in request.form.getlist('selected_permissions')]
        new_permissions = Permission.query.filter(Permission.id.in_(selected_perm_ids)).all() if selected_perm_ids else []
        new_set = {p.name for p in new_permissions}

        # 4. 计算差异
        added = new_set - old_set
        removed = old_set - new_set

        # 5. 执行数据库更新：先删再增
        UserPermission.query.filter_by(user_id=target_user_id).delete()
        for pid in selected_perm_ids:
            new_up = UserPermission(user_id=target_user_id, permission_id=pid)
            db.session.add(new_up)

        # 6. 构造差异化日志描述
        if not added and not removed:
            log_desc = f"保存了用户【{target_user.name}】的权限，但未做任何实际改动。"
        else:
            parts = []
            if added:
                parts.append(f"新增了: [{', '.join(added)}]")
            if removed:
                parts.append(f"移除了: [{', '.join(removed)}]")
            log_desc = f"调整了用户【{target_user.name}】的系统权限：{'; '.join(parts)}"

        # 7. 写入审计日志
        log_action(
            action_type='权限变更',
            target_type='UserPermission',
            target_id=target_user_id,
            description=log_desc,
            cycle_id=cycle_id,
        )

        db.session.commit()
        flash(f'用户 {target_user.name} 的权限保存成功', 'success')
        
    except Exception as e:
        db.session.rollback()
        print(f"数据库操作失败，原因: {str(e)}")
        flash(f'保存失败: {str(e)}', 'danger')
    
    return redirect(url_for('permission.permission_manage'))

# ==================== 批量赋予/移除权限 ====================
@permission_bp.route('/batch_update', methods=['POST'])
@login_required
@perm.require('manage')
def permission_batch_update():
    from utils import log_action

    try:
        perm_ids = [int(pid) for pid in request.form.getlist('perm_ids')]
        user_ids = [int(uid) for uid in request.form.getlist('user_ids')]
        mode = request.form.get('mode', 'grant')
        if mode not in ('grant', 'revoke'):
            mode = 'grant'
    except ValueError:
        flash('参数错误，请重试', 'danger')
        return redirect(url_for('permission.permission_manage'))

    if not perm_ids or not user_ids:
        flash('请至少选择一个权限和一名员工', 'warning')
        return redirect(url_for('permission.permission_manage'))

    perms = Permission.query.filter(Permission.id.in_(perm_ids)).all()
    perm_names = {p.id: p.name for p in perms}
    users = User.query.filter(User.id.in_(user_ids)).all()
    user_names = {u.id: u.name for u in users}
    # 身份证 -> 任职周期ID（记录被操作人）
    cycles = EmploymentCycle.query.filter(EmploymentCycle.id_card.in_([u.username for u in users])).all()
    cycle_map = {c.id_card: c.id for c in cycles}
    user_cycle = {u.id: cycle_map.get(u.username) for u in users}

    action_word = '赋予' if mode == 'grant' else '移除'
    affected_total = 0
    try:
        for uid in user_ids:
            changed = []
            for pid in perm_ids:
                up = UserPermission.query.filter_by(user_id=uid, permission_id=pid).first()
                if mode == 'grant' and not up:
                    db.session.add(UserPermission(user_id=uid, permission_id=pid))
                    changed.append(perm_names.get(pid, str(pid)))
                elif mode == 'revoke' and up:
                    db.session.delete(up)
                    changed.append(perm_names.get(pid, str(pid)))
            if changed:
                affected_total += 1
                log_action(
                    action_type='权限变更',
                    target_type='UserPermission',
                    target_id=uid,
                    description=f"批量{action_word}了用户【{user_names.get(uid, uid)}】的权限：{', '.join(changed)}",
                    cycle_id=user_cycle.get(uid),
                )
        db.session.commit()
        if affected_total:
            flash(f'批量{action_word}完成，共影响 {affected_total} 名员工', 'success')
        else:
            flash('没有需要变更的权限（所选员工已具备/已不具备所选权限）', 'info')
    except Exception as e:
        db.session.rollback()
        print(f"批量权限操作失败，原因: {str(e)}")
        flash(f'批量操作失败: {str(e)}', 'danger')

    return redirect(url_for('permission.permission_manage'))

# ==================== 审计日志（Audit Log） ====================
@permission_bp.route('/operations')
@login_required
def permission_operations():
    """
    显示操作记录汇总页。
    系统管理员(admin)可查看全员日志，普通管理员仅能查看个人日志。
    """
    from models import User  # 确保导入了 User 模型进行关联查询
    from sqlalchemy.orm import joinedload
    
    # 1. 获取分页参数
    page = request.args.get('page', 1, type=int)
    per_page = 50  # 每页记录数
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # 2. 构造基础查询对象
    query = OperationLog.query.options(joinedload(OperationLog.operator))
    
    # 时间筛选
    if start_date:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        query = query.filter(OperationLog.created_at >= start)
    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        query = query.filter(OperationLog.created_at <= end)

    # 3. 权限逻辑判断
    if current_user.role != 'admin':
        query = query.filter_by(user_id=current_user.id)
    
    # 4. 执行分页查询
    # 使用 order_by(OperationLog.created_at.desc()) 确保时间倒序
    pagination = query.order_by(OperationLog.created_at.desc())\
        .paginate(page=page, per_page=20, error_out=False)
    
    logs = pagination.items
    
    # 5. 渲染模板
    return render_template('permission/operations.html', 
                           logs=logs, 
                           pagination=pagination)