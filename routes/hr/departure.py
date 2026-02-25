import json
from datetime import datetime
from flask import request, redirect, url_for, flash
from flask_login import login_required, current_user

from . import hr_bp
from models import EmploymentCycle, AssetAllocation, Asset, AssetHistory, db
from utils import parse_date, perm, log_action

# ==================== 办理离职（含资产自动核销） ====================
@hr_bp.route('/departure/<int:cycle_id>', methods=['POST'])
@login_required
@perm.require('hr.departure')
def departure(cycle_id):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    
    # 状态校验
    if cycle.status == '离职':
        flash('已离职，无需重复操作', 'info')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    # 强制勾选校验
    if 'confirm_return' not in request.form or 'settle_utilities' not in request.form:
        flash('请确认所有离职事项', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    # 1. 自动归还未归还的资产
    user_allocations = AssetAllocation.query.filter_by(
        user_id=cycle.id, 
        return_date=None
    ).all()

    returned_assets_summary = []

    for alloc in user_allocations:
        asset = alloc.asset
        qty = alloc.quantity
        
        # 更新资产分配记录
        alloc.return_date = datetime.today().date()
        
        # 更新资产库存
        asset.stock_quantity += qty
        asset.allocated_quantity -= qty
        
        # 防止负数
        if asset.allocated_quantity < 0:
            asset.allocated_quantity = 0
        
        # 更新资产状态
        if asset.allocated_quantity == 0:
            asset.status = '库存'
        
        # 记录归还摘要
        returned_assets_summary.append(f"{asset.name}x{qty}")

        # 记录资产历史
        history = AssetHistory(
            asset_id=asset.id,
            action='归还（离职自动）',
            user_id=cycle.id,
            operator_id=current_user.id,
            quantity=qty,
            action_date=datetime.now(),
            note=f'{cycle.name}离职自动归还'
        )
        db.session.add(history)
    
    # 2. 床位占用释放
    room_id = cycle.room_id
    is_room_leader = cycle.is_room_leader
    
    # 清空床位信息
    cycle.bed_number = None
    cycle.is_room_leader = False
    
    # 若为宿舍长，清空房间资产负责人
    if is_room_leader and room_id:
        from models import AssetInstance
        # 清空房间资产个体负责人
        AssetInstance.query.filter(
            AssetInstance.room_id == room_id
        ).update({AssetInstance.user_id: None})
        
        # 更新资产主表当前使用人
        asset_ids = db.session.query(AssetInstance.asset_id).filter(
            AssetInstance.room_id == room_id
        ).distinct().subquery()
        Asset.query.filter(
            Asset.id.in_(asset_ids)
        ).update({Asset.current_user_id: None})

    # 3. 处理离职信息
    reason = request.form.get('departure_reason', '').strip()
    dep_date_str = request.form.get('departure_date')
    dep_date = parse_date(dep_date_str) or datetime.today().date()
    
    cycle.status = '离职'
    cycle.departure_date = dep_date
    
    # 更新离职原因到档案
    archives = json.loads(cycle.archives or '{}')
    archives['departure_reason'] = reason or '无原因说明'
    cycle.archives = json.dumps(archives, ensure_ascii=False)
    
    # 4. 记录审计日志
    asset_msg = f" | 自动回收资产: {', '.join(returned_assets_summary)}" if returned_assets_summary else " | 无资产需回收"
    log_description = (
        f"为队员【{cycle.name}】办理了离职手续。"
        f"离职日期：{dep_date.strftime('%Y-%m-%d')}，"
        f"原因：{reason or '未填写'}"
        f"{asset_msg}"
    )

    log_action(
        action_type='人员离职',
        target_type='Employee',
        target_id=cycle.id,
        description=log_description,** locals()
    )

    # 5. 提交所有变更
    try:
        db.session.commit()
        flash(f'离职成功，已自动归还全部个人装备({len(returned_assets_summary)}项)，并释放床位', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'办理离职失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))