from datetime import datetime
from flask import flash, redirect, url_for, request
from flask_login import login_required, current_user
from models import db, Asset, AssetAllocation, AssetHistory, AssetInstance, EmploymentCycle, FundsRecord
from utils import log_action, perm

# 导入蓝图
from . import asset_bp

# ==================== 发放资产（支持多数量） ====================
@asset_bp.route('/issue/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.issue')
def asset_issue(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    user_id = request.form.get('user_id')
    quantity = int(request.form.get('quantity', 1))

    # 获取被发放人的信息
    emp = EmploymentCycle.query.get(user_id)
    emp_name = emp.name if emp else f"ID:{user_id}"
    
    if asset.stock_quantity < quantity:
        flash('库存不足', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 更新库存
    asset.stock_quantity -= quantity
    asset.allocated_quantity += quantity
    asset.status = '使用中'
    asset.current_user_id = user_id

    # 记录个人领用
    allocation = AssetAllocation(
        asset_id=asset_id,
        user_id=user_id,
        quantity=quantity,
        issue_date=datetime.today().date(),
        note=request.form.get('note', '')
    )
    db.session.add(allocation)
    
    # 历史记录
    history = AssetHistory(
        asset_id=asset_id,
        action='发放',
        user_id=user_id,
        operator_id=current_user.id,
        quantity=quantity,
        note=request.form.get('note', '')
    )
    db.session.add(history)
    
    # 审计日志
    log_action(
        action_type='发放资产',
        target_type='Asset',
        target_id=asset_id,
        description=f"向队员【{emp_name}】发放了资产：{asset.name} (编号:{asset.number})，数量：{quantity}",
        **locals()
    )
    db.session.commit()
    flash('发放成功', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 更换资产（归还+报废+发放） ====================
@asset_bp.route('/exchange/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.issue')
def asset_exchange(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    user_id = request.form.get('user_id')
    quantity = int(request.form.get('quantity', 1))
    reason = request.form.get('note', '以旧换新')

    emp = EmploymentCycle.query.get(user_id)
    emp_name = emp.name if emp else f"ID:{user_id}"

    # 校验用户持有的旧物资是否够换
    allocations = AssetAllocation.query.filter_by(asset_id=asset_id, user_id=user_id, return_date=None).all()
    total_held = sum(a.quantity for a in allocations)
    if total_held < quantity:
        flash(f'更换失败：该员工仅持有 {total_held} 个，无法更换 {quantity} 个', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 检查仓库是否有新物资可换
    if asset.stock_quantity < quantity:
        flash(f'更换失败：库存余量 {asset.stock_quantity} 不足以支持更换 {quantity} 个新装备', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    try:
        now_time = datetime.now()
        
        # 执行“归还”并直接“报废”逻辑
        remaining_to_return = quantity
        for alloc in allocations:
            if remaining_to_return <= 0: break
            if alloc.quantity <= remaining_to_return:
                remaining_to_return -= alloc.quantity
                alloc.return_date = now_time
            else:
                alloc.quantity -= remaining_to_return
                db.session.add(AssetAllocation(
                    asset_id=asset_id, user_id=user_id, quantity=remaining_to_return,
                    issue_date=alloc.issue_date, return_date=now_time, note="更换时部分归还"
                ))
                remaining_to_return = 0

        # 核心：资产家底扣减 (报废旧物)
        asset.total_quantity -= quantity
        # 执行“发放”新物逻辑
        asset.stock_quantity -= quantity
        asset.allocated_quantity += quantity
        
        # 记录新分配
        new_alloc = AssetAllocation(
            asset_id=asset_id, 
            user_id=user_id, 
            quantity=quantity,
            issue_date=now_time.date(), 
            note=f"更换发放：{reason}"
        )
        db.session.add(new_alloc)

        # 记录历史
        db.session.add(AssetHistory(
            asset_id=asset_id, 
            action='更换(回收)', 
            user_id=user_id,
            operator_id=current_user.id, 
            quantity=quantity, 
            note=f"回收报废: {reason}"
        ))
        db.session.add(AssetHistory(
            asset_id=asset_id, 
            action='更换(发放)', 
            user_id=user_id,
            operator_id=current_user.id, 
            quantity=quantity, 
            note=f"发放新物: "
        ))

        # 审计日志
        log_action(
            action_type='更换资产', target_type='Asset', target_id=asset_id,
            description=f"为队员【{emp_name}】更换了{asset.name}：回收报废 {quantity} 件，重新发放 {quantity} 件。备注：{reason}",
            **locals()
        )

        db.session.commit()
        flash(f'更换成功：已回收并报废队员手中的旧装备，并下发了新库存。', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'系统错误：{str(e)}', 'danger')

    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 归还资产 ====================
@asset_bp.route('/return/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.return')
def asset_return(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    user_id = request.form.get('user_id')
    quantity = int(request.form.get('quantity', 1))

    # 获取归还人姓名
    emp = EmploymentCycle.query.get(user_id)
    emp_name = emp.name if emp else f"ID:{user_id}"

    # 查找未归还的分配记录
    allocations = AssetAllocation.query.filter_by(
        asset_id=asset_id, 
        user_id=user_id, 
        return_date=None
    ).all()
    
    # 校验持有数量
    total_held = sum(a.quantity for a in allocations)
    if total_held < quantity:
        flash(f'归还失败：用户仅持有 {total_held} 个，无法归还 {quantity} 个', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 核销分配记录
    remaining_to_return = quantity
    now_time = datetime.now()
    for alloc in allocations:
        if remaining_to_return <= 0: break
        
        if alloc.quantity <= remaining_to_return:
            remaining_to_return -= alloc.quantity
            alloc.return_date = now_time
        else:
            alloc.quantity -= remaining_to_return
            returned_part = AssetAllocation(
                asset_id=asset_id, user_id=user_id, quantity=remaining_to_return,
                issue_date=alloc.issue_date, return_date= now_time,
                note=f"部分归还自原记录"
            )
            db.session.add(returned_part)
            remaining_to_return = 0

    # 更新资产库存
    asset.stock_quantity += quantity
    asset.allocated_quantity -= quantity
    if asset.allocated_quantity <= 0:
        asset.status = '库存'
    
    # 记录历史
    history = AssetHistory(
        asset_id=asset_id, action='归还', user_id=user_id,
        operator_id=current_user.id, quantity=quantity,
        action_date=datetime.now(), note=request.form.get('note', '')
    )
    db.session.add(history)
    
    # 审计日志
    log_action(
        action_type='归还资产',
        target_type='Asset',
        target_id=asset_id,
        description=f"回收了队员【{emp_name}】归还的资产：{asset.name} (编号:{asset.number})，数量：{quantity}",
        **locals()
    )
    db.session.commit()
    flash('归还成功', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 批量发放归还 ====================
@asset_bp.route('/issue_from_hr', methods=['POST'])
@login_required
@perm.require('asset.issue')
def asset_issue_from_hr():
    user_id = request.form.get('user_id')
    id_card = request.form.get('id_card')
    selected_asset_ids = request.form.getlist('asset_ids')
    note = request.form.get('note', '')
    
    if not selected_asset_ids:
        flash('未选择任何资产', 'warning')
        return redirect(url_for('hr.hr_detail', id_card=id_card))

    emp = EmploymentCycle.query.get_or_404(user_id)
    issued_items = []

    try:
        for aid in selected_asset_ids:
            qty = int(request.form.get(f'qty_{aid}', 0))
            if qty <= 0: continue
            
            asset = Asset.query.get(aid)
            if not asset or asset.stock_quantity < qty:
                flash(f'资产 {asset.name if asset else aid} 库存不足，已跳过', 'danger')
                continue

            # 更新库存
            asset.stock_quantity -= qty
            asset.allocated_quantity += qty
            asset.status = '使用中'
            asset.current_user_id = user_id

            # 领用记录
            allocation = AssetAllocation(
                asset_id=asset.id,
                user_id=user_id,
                quantity=qty,
                issue_date=datetime.today().date(),
                note=note
            )
            db.session.add(allocation)

            # 资产历史
            history = AssetHistory(
                asset_id=asset.id,
                action='发放',
                user_id=user_id,
                operator_id=current_user.id,
                quantity=qty,
                note=f"入职发放: {note}"
            )
            db.session.add(history)
            
            issued_items.append(f"{asset.name} x{qty}")

        if issued_items:
            # 审计记录
            log_action(
                action_type='发放资产',
                target_type='Asset',
                target_id=None,
                description=f"向队员【{emp.name}】发放了资产：{', '.join(issued_items)}。备注：{note}",
                **locals()
            )
            db.session.commit()
            flash(f'成功为 {emp.name} 发放资产：{", ".join(issued_items)}', 'success')
        else:
            db.session.rollback()

    except Exception as e:
        db.session.rollback()
        flash(f'发放失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_detail', id_card=id_card))

# ==================== 消耗品消耗 ====================
@asset_bp.route('/consume/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.consume')
def asset_consume(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if asset.type != '消耗品':
        flash('仅消耗品可直接消耗', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    quantity = int(request.form.get('quantity', 1))
    if asset.stock_quantity < quantity:
        flash('库存不足', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    asset.stock_quantity -= quantity
    now_time = datetime.now()

    history = AssetHistory(
        asset_id=asset_id,
        action='消耗',
        user_id=current_user.id if current_user.is_authenticated else None,
        operator_id=current_user.id,
        quantity=quantity,
        action_date=now_time,
        note=request.form.get('note', '')
    )
    db.session.add(history)
    
    # 审计日志
    log_description = f"消耗了消耗品：{asset.name} (编号:{asset.number})，数量：{quantity}"
    if request.form.get('note'):
        log_description += f"，备注：{request.form.get('note', '')}"

    log_action(
        action_type='资产消耗',
        target_type='Asset',
        target_id=asset_id,
        description=log_description
    )
    db.session.commit()
    flash(f'消耗 {quantity} 个成功，剩余 {asset.stock_quantity} 个', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 补充库存 ====================
@asset_bp.route('/supplement/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.supplement')
def asset_supplement(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    quantity = int(request.form.get('quantity', 0))
    is_sync = request.form.get('sync_fund') == 'on'
    raw_price = request.form.get('unit_price', '0').strip()
    unit_price = float(raw_price if raw_price else 0)

    if quantity <= 0:
        flash('数量无效', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    asset.total_quantity += quantity
    asset.stock_quantity += quantity
    
    # 同步财务扣款
    sync_desc = ""
    if asset.ownership == '特保队' and is_sync and unit_price > 0:
        total_cost = unit_price * quantity
        last_record = FundsRecord.query.order_by(FundsRecord.date.desc(), FundsRecord.id.desc()).first()
        last_balance = last_record.balance if last_record else 0
        
        new_fund = FundsRecord(
            date=datetime.now(),
            payer="特保队费",
            item=f"补充资产支出: {asset.name}",
            amount=-total_cost,
            balance=last_balance - total_cost,
            note=f"资产编号: {asset.number} (补充入库联动)",
            operator_id=current_user.id
        )
        db.session.add(new_fund)
        sync_desc = f"并同步扣款 {total_cost} 元"

    history = AssetHistory(
        asset_id=asset_id,
        action='补充',
        quantity=quantity,
        operator_id=current_user.id,
        action_date=datetime.now(),
        note=f"补充入库 {quantity} 个 {sync_desc}"
    )
    db.session.add(history)
    
    db.session.commit()
    flash(f'补充成功 {sync_desc}', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 报废资产 ====================
@asset_bp.route('/scrap/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.scrap')
def asset_scrap(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    
    try:
        quantity = int(request.form.get('quantity', 0))
    except ValueError:
        quantity = 0
    reason = request.form.get('reason', '').strip()
    
    # 基础校验
    if quantity <= 0:
        flash('报废数量必须大于 0', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 业务校验：仅能报废库存部分
    if quantity > asset.stock_quantity:
        flash(f'报废失败：当前库存仅余 {asset.stock_quantity}，无法报废 {quantity}。'
              f'若要报废已发放物资，请先执行“归还入库”操作。', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 扣减逻辑
    asset.total_quantity -= quantity
    asset.stock_quantity -= quantity
    
    # 自动更新状态
    if asset.total_quantity == 0:
        asset.status = '报废'
    
    # 记录历史
    history = AssetHistory(
        asset_id=asset_id,
        action='报废',
        quantity=quantity,
        user_id=current_user.id,
        operator_id=current_user.id,
        action_date=datetime.now(),
        note=f'报废原因: {reason}' if reason else '原因: 未备注'
    )
    db.session.add(history)
    
    # 审计日志
    log_description = f"执行资产报废：{asset.name}(编号:{asset.number})，数量：{quantity}。总数已同步扣减。"
    if reason:
        log_description += f" 备注原因：{reason}"

    log_action(
        action_type='资产报废',
        target_type='Asset',
        target_id=asset_id,
        description=log_description
    )
    
    db.session.commit()
    flash(f'成功报废 {quantity} 个资产，库存及总数已更新', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 固定资产维修 ====================
@asset_bp.route('/repair/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.repair')
def asset_repair(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if asset.type != '固定资产':
        flash('仅固定资产可添加维修记录', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    note = request.form.get('note', '').strip()
    
    # 变更状态
    asset.status = '维修中'
    now_time = datetime.now()

    # 记录历史
    history = AssetHistory(
        asset_id=asset_id,
        action='维修',
        user_id=current_user.id,
        operator_id=current_user.id,
        action_date=now_time,
        note=note
    )
    db.session.add(history)

    # 审计日志
    log_description = f"将固定资产标记为维修状态：{asset.name} (编号:{asset.number})"
    if note:
        log_description += f"，故障/维修备注：{note}"

    log_action(
        action_type='资产维修',
        target_type='Asset',
        target_id=asset_id,
        description=log_description
    )

    db.session.commit()
    flash('维修记录添加成功，资产状态已更新为“维修中”', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 固定资产修复完成 ====================
@asset_bp.route('/complete_repair/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.complete_repair')
def asset_complete_repair(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    if asset.type != '固定资产':
        flash('仅固定资产可标记修复完成', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    if asset.status != '维修中':
        flash('当前状态不是维修中，无法标记修复完成', 'warning')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    note = request.form.get('note', '').strip()
    
    # 恢复状态
    asset.status = '正常'
    now_time = datetime.now()

    # 记录历史
    history = AssetHistory(
        asset_id=asset_id,
        action='修复完成',
        user_id=current_user.id,
        operator_id=current_user.id,
        action_date=now_time,
        note=note
    )
    db.session.add(history)

    # 审计日志
    log_description = f"确认资产维修完成：{asset.name} (编号:{asset.number})，已恢复正常状态"
    if note:
        log_description += f"，结算备注：{note}"

    log_action(
        action_type='维修完成',
        target_type='Asset',
        target_id=asset_id,
        description=log_description
    )

    db.session.commit()
    flash('资产已标记为修复完成，可重新投入使用', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 子资产操作 ====================
# 子资产维修
@asset_bp.route('/repair_sub', methods=['POST'])
@login_required
@perm.require('asset.repair')
def asset_repair_sub():
    sub_asset_id = request.form.get('sub_asset_id')
    note = request.form.get('note', '').strip()
    instance = AssetInstance.query.get_or_404(sub_asset_id)
    
    instance.status = '维修'
    # 记录历史
    history = AssetHistory(
        asset_id=instance.asset_id,
        action='维修（单件）',
        operator_id=current_user.id,
        quantity=0,
        note=f"SN: {instance.sn_number} | 备注: {note}"
    )
    db.session.add(history)

    log_action(
        action_type='子资产维修',
        target_type='AssetInstance',
        target_id=instance.id,
        description=f"单件资产标记维修：{instance.asset_info.name} (SN: {instance.sn_number})。备注: {note}"
    )

    db.session.commit()
    flash(f'子资产 {instance.sn_number} 已标记为维修状态', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=instance.asset_id))

# 子资产报废
@asset_bp.route('/scrap_sub', methods=['POST'])
@login_required
@perm.require('asset.scrap')
def asset_scrap_sub():
    sub_asset_id = request.form.get('sub_asset_id')
    reason = request.form.get('note', '').strip()
    instance = AssetInstance.query.get_or_404(sub_asset_id)
    asset = instance.asset_info
    
    instance.status = '报废'
    # 扣减主库存
    asset.total_quantity -= 1
    if asset.stock_quantity > 0:
        asset.stock_quantity -= 1
        
    history = AssetHistory(
        asset_id=asset.id,
        action='报废（单件）',
        operator_id=current_user.id,
        quantity=-1,
        note=f"SN: {instance.sn_number} | 原因: {reason}"
    )
    db.session.add(history)

    log_action(
        action_type='子资产报废',
        target_type='AssetInstance',
        target_id=instance.id,
        description=f"单件资产报废：{asset.name} (SN: {instance.sn_number})。主库存已扣减。"
    )

    db.session.commit()
    flash(f'子资产 {instance.sn_number} 已成功报废', 'warning')
    return redirect(url_for('asset.asset_detail', asset_id=asset.id))

# 子资产维修完成
@asset_bp.route('/complete_repair_sub', methods=['POST'])
@login_required
@perm.require('asset.complete_repair')
def asset_complete_repair_sub():
    sub_asset_id = request.form.get('sub_asset_id')
    note = request.form.get('note', '').strip()
    
    instance = AssetInstance.query.get_or_404(sub_asset_id)
    instance.status = '正常'
    
    # 记录历史
    history = AssetHistory(
        asset_id=instance.asset_id,
        action='维修完成（单件）',
        operator_id=current_user.id,
        quantity=0,
        note=f"SN: {instance.sn_number} 已修复。备注: {note}"
    )
    
    db.session.add(history)

    log_action(
        action_type='子资产维修完成',
        target_type='AssetInstance',
        target_id=instance.id,
        description=f"单件资产修复：{instance.asset_info.name} (SN: {instance.sn_number})，状态已恢复正常。"
    )
    
    db.session.commit()
    flash(f'子资产 {instance.sn_number} 维修完成，已恢复正常状态', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=instance.asset_id))