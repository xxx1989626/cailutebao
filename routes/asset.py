# routes/asset.py
# 资产管理模块
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify, current_app
from flask_login import login_required, current_user
from models import db, Asset, AssetHistory, EmploymentCycle, AssetAllocation,AssetInstance,Room
from config import ASSET_STATUS, ASSET_TYPES
from utils import save_uploaded_file, parse_date, format_date,perm, log_action, today_str, delete_physical_file
from datetime import datetime
from io import BytesIO
import pandas as pd

asset_bp = Blueprint('asset', __name__, url_prefix='/asset')

# ==================== 资产列表 ====================
@asset_bp.route('/list')
@login_required
@perm.require('asset.view')
def asset_list():
    # 1. 获取参数
    # 注意：这里不再给 type_filter 设硬编码默认值，后面根据逻辑判断
    type_filter = request.args.get('type')  
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '').strip()
    user_filter = request.args.get('user_id')
    
    # 2. 统计报修
    repair_count = Asset.query.filter_by(status='维修中').count()

    # 3. 构建基础查询
    query = Asset.query

    # 4. 全局搜索逻辑（优先级最高）
    if search:
        # 先执行全局模糊搜索
        query = query.filter(
            db.or_(
                Asset.name.ilike(f'%{search}%'),
                Asset.number.ilike(f'%{search}%') 
            )
        )
        # 自动切换标签：如果没选标签，或者搜到的第一个结果不在当前标签
        first_asset = query.first()
        if first_asset:
            type_filter = first_asset.type  # 核心：自动跳转到匹配到的资产分类
    
    # 5. 类型过滤（如果没有搜索，或者搜索后确定了类型）
    if not type_filter:
        type_filter = '固定资产'  # 仅在既没搜索也没选标签时，默认显示固定资产
    
    query = query.filter_by(type=type_filter)
    
    # 6. 其他过滤
    if status_filter:
        query = query.filter_by(status=status_filter)
    if user_filter:
        query = query.filter_by(current_user_id=user_filter)

    # 7. 获取数据
    assets = query.order_by(Asset.id.desc()).all()
    in_service_employees = EmploymentCycle.query.filter_by(status='在职').order_by(EmploymentCycle.name).all()

    # 8. 默认显示所有字段（因为你删除了字段控制功能）
    show_fields = ['name', 'number', 'status', 'location', 'current_user', 'ownership']

    return render_template('asset/list.html',
                           assets=assets,
                           in_service_employees=in_service_employees,
                           type_filter=type_filter,
                           status_filter=status_filter,
                           search=search,
                           user_filter=user_filter,
                           show_fields=show_fields,
                           repair_count=repair_count)

# ==================== 核心资产保存逻辑函数 ==================== 
def perform_asset_save(form_data, files=None):
    """
    资产核心保存逻辑：从 form_data 读数据，执行资产入库。
    """
    # 基础数据获取 (兼容资产片段和财务片段的字段差异)
    asset_type = form_data.get('type') or form_data.get('asset_type', '其他')
    name = form_data.get('name') or form_data.get('item')
    quantity = int(form_data.get('quantity') or form_data.get('asset_qty', 1))
    
    # 金额处理：如果有单价用单价，没有则从总额折算
    if form_data.get('unit_price'):
        unit_price = float(form_data.get('unit_price'))
    elif form_data.get('amount'):
        unit_price = abs(float(form_data.get('amount'))) / quantity if quantity > 0 else 0
    else:
        unit_price = 0.0

    ownership = form_data.get('ownership', '特保队')
    prefix = form_data.get('number', '').strip() or f"SN-{datetime.now().strftime('%Y%m%d')}-"
    
    # 日期处理
    date_input = form_data.get('purchase_date') or form_data.get('date')
    purchase_date = parse_date(date_input) if date_input else datetime.now().date()

    # 图片处理
    photo_path = None
    if files:
        # 使用 .get() 安全获取文件对象
        photo_file = files.get('photo')
        # 确保文件对象存在且文件名不为空（用户确实选择了文件）
        if photo_file and photo_file.filename != '':
            photo_path = save_uploaded_file(photo_file, module='asset')

    # 创建资产对象
    asset = Asset(
        type=asset_type,
        name=name,
        number=prefix,
        total_quantity=quantity,
        stock_quantity=quantity,
        unit_price=unit_price,
        ownership=ownership,
        location=form_data.get('location', '待定'),
        purchase_date=purchase_date,
        bed_capacity=int(form_data.get('bed_capacity', 0)),
        photo_path=photo_path,
        status='库存',
    )
    db.session.add(asset)
    db.session.flush()

    # 3. 子资产个体生成逻辑
    if asset_type == '固定资产' and quantity > 0:
        # 获取前端传来的自定义编号列表
        custom_suffixes = form_data.getlist('instance_numbers[]')
        for i in range(quantity):
            raw_suffix = custom_suffixes[i].strip() if i < len(custom_suffixes) else f"{i+1:03d}"
            # 序列号拼接逻辑：处理前缀重复情况
            full_sn = raw_suffix if prefix and raw_suffix.startswith(prefix) else f"{prefix}{raw_suffix}"
            if prefix and full_sn.startswith(prefix + prefix):
                full_sn = full_sn.replace(prefix + prefix, prefix)
            
            instance = AssetInstance(asset_id=asset.id, sn_number=full_sn, status='正常')
            db.session.add(instance)
    
    return asset

# ==================== 新增资产 ====================

@asset_bp.route('/get_form_snippet')
@login_required
@perm.require('asset.add')
def get_form_snippet():
    """供财务页面 AJAX 调用，返回资产表单 HTML"""
    return render_template('asset/_partial_asset_form.html', default_date=today_str())

@asset_bp.route('/add', methods=['GET', 'POST'])
@login_required
@perm.require('asset.add')
def asset_add():
    if request.method == 'POST':
        try:
            # 1. 保存资产
            asset = perform_asset_save(request.form, request.files)
            
            # 2. 检查联动开关 (sync_fund)
            sync_msg = ""
            if request.form.get('sync_fund') == 'on':
                from .fund import perform_fund_save
                # 调用财务保存函数
                perform_fund_save(request.form, current_user.id, request.files)
                sync_msg = "，并已同步登记财务支出"
            
            # 记录日志
            log_action(
                action_type="资产入库",
                target_type="Asset",
                target_id=asset.id,
                description=f"入库 {asset.name} x{asset.total_quantity}{sync_msg}"
            )

            db.session.commit()
            flash(f'资产 {asset.name} 入库成功{sync_msg}', 'success')
            return redirect(url_for('asset.asset_list'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Asset Add Error: {str(e)}")
            flash(f'入库失败: {str(e)}', 'danger')
            
    return render_template('asset/add.html', default_date=today_str())
# ==================== 编辑资产 ====================
@asset_bp.route('/edit/<int:asset_id>', methods=['GET', 'POST'])
@login_required
@perm.require('asset.edit')
def asset_edit(asset_id):
    from utils import log_action
    asset = Asset.query.get_or_404(asset_id)
    
    if request.method == 'POST':
        # 1. 在修改前，记录下所有的“旧值”
        old_values = {
            '类型': asset.type,
            '名称': asset.name,
            '编号': asset.number,
            '总数': asset.total_quantity,
            '购置日期': str(asset.purchase_date),
            '存放位置': asset.location or '未填写',
            '归属': asset.ownership or '未填写',
        }
        
        # 2. 接收新值
        new_type = request.form['type']
        new_name = request.form['name'].strip()
        new_total = int(request.form['total_quantity'])
        new_purchase_date = parse_date(request.form.get('purchase_date'))
        new_location = request.form.get('location', '').strip()
        new_ownership = request.form.get('ownership', '').strip()

        # 3. 比较哪些字段发生了变化
        changes = []
        if old_values['类型'] != new_type:
            changes.append(f"类型({old_values['类型']} -> {new_type})")
        if old_values['名称'] != new_name:
            changes.append(f"名称({old_values['名称']} -> {new_name})")
        if old_values['总数'] != new_total:
            changes.append(f"总数({old_values['总数']} -> {new_total})")
        if old_values['购置日期'] != str(new_purchase_date):
            changes.append(f"购置日期({old_values['购置日期']} -> {new_purchase_date})")
        if old_values['存放位置'] != (new_location or '未填写'):
            changes.append(f"位置({old_values['存放位置']} -> {new_location})")
        if old_values['归属'] != (new_ownership or '未填写'):
            changes.append(f"归属({old_values['归属']} -> {new_ownership})")

        # 4. 执行更新
        asset.type = new_type
        asset.name = new_name
        asset.total_quantity = new_total
        asset.purchase_date = new_purchase_date
        asset.location = new_location
        asset.ownership = new_ownership
        
        if 'photo' in request.files and request.files['photo'].filename != '':
            if asset.photo_path:
                delete_physical_file(asset.photo_path)
            asset.photo_path = save_uploaded_file(request.files['photo'], module='asset')
            changes.append("更新了资产照片")

        # 5. 写入审计日志
        if changes:
            log_desc = f"修改了资产【{old_values['名称']}】的项：{', '.join(changes)}"
        else:
            log_desc = f"打开并保存了资产【{asset.name}】，但未修改任何内容"

        log_action(
            action_type='编辑资产',
            target_type='Asset',
            target_id=asset.id,
            description=log_desc
        )
        
        db.session.commit()
        flash('资产信息更新成功', 'success')
        return redirect(url_for('asset.asset_detail', asset_id=asset.id))
    
    return render_template('asset/edit.html', asset=asset)
# ==================== 删除资产（谨慎使用） ====================
@asset_bp.route('/delete/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.delete')
def asset_delete(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    try:
        # 获取照片路径
        photo_path = asset.photo_path
    
        # 强制清理：先删除所有关联的分配记录，再删除资产
        AssetAllocation.query.filter_by(asset_id=asset_id).delete()
        # 同理，如果历史记录也导致报错，也需要清理
        AssetHistory.query.filter_by(asset_id=asset_id).delete()
    
        db.session.delete(asset)
        db.session.commit()

        # 数据库删除成功后，清理物理文件
        if photo_path:
            from utils import delete_physical_file # 需在utils中定义此简单函数
            delete_physical_file(photo_path)

        flash('资产已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'danger')
    return redirect(url_for('asset.asset_list'))

# ==================== 资产详情 ====================
@asset_bp.route('/detail/<int:asset_id>')
@login_required
@perm.require('asset.view')
def asset_detail(asset_id):
    asset = Asset.query.get_or_404(asset_id)
    in_service_employees = EmploymentCycle.query.filter_by(status='在职').order_by(EmploymentCycle.name).all()
    allocations = AssetHistory.query.filter_by(asset_id=asset_id, action='发放').all()
    page = request.args.get('page', 1, type=int) # 获取当前页码
    pagination = AssetHistory.query.filter_by(asset_id=asset_id)\
        .order_by(AssetHistory.action_date.desc())\
        .paginate(page=page, per_page=10, error_out=False) # 针对该资产的操作历史进行分页查询
    history_items = pagination.items  # current page history items

    next_url = request.args.get('next')
    if next_url and not next_url.startswith('/'):
        next_url = None
    return render_template('asset/detail.html',
                           asset=asset,
                           in_service_employees=in_service_employees,
                           pagination=pagination,  # 传递分页对象用于渲染页码)
                           history_items=history_items,
                           return_url=next_url) # 传递当前页数据

# ==================== 发放资产（支持多数量） ====================
@asset_bp.route('/issue/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.issue')
def asset_issue(asset_id):
    from utils import log_action  # 确保局部导入，防止循环依赖
    asset = Asset.query.get_or_404(asset_id)
    user_id = request.form.get('user_id')
    quantity = int(request.form.get('quantity', 1))

    # 获取被发放人的信息（用于日志描述更友好）
    from models import EmploymentCycle
    emp = EmploymentCycle.query.get(user_id)
    emp_name = emp.name if emp else f"ID:{user_id}"
    
    if asset.stock_quantity < quantity:
        flash('库存不足', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 更新库存
    asset.stock_quantity -= quantity
    asset.allocated_quantity += quantity
    asset.status = '使用中'
    
    # 发放后必须设置当前使用人
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
        user_id=user_id,  # 被操作人
        operator_id=current_user.id,  # 操作人（当前登录用户）
        quantity=quantity,
        note=request.form.get('note', '')
    )
    db.session.add(history)
    # 4. 【新增】记录管理操作日志 (操作人维度的审计)
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
@perm.require('asset.issue') # 更换涉及发放权限
def asset_exchange(asset_id):
    from utils import log_action
    from datetime import datetime
    from models import EmploymentCycle, AssetAllocation, AssetHistory

    asset = Asset.query.get_or_404(asset_id)
    user_id = request.form.get('user_id')
    quantity = int(request.form.get('quantity', 1))
    reason = request.form.get('note', '以旧换新')

    emp = EmploymentCycle.query.get(user_id)
    emp_name = emp.name if emp else f"ID:{user_id}"

    # --- 1. 校验环节 ---
    # 检查用户持有的旧物资是否够换
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
        
        # --- 2. 执行“归还”并直接“报废”逻辑 ---
        # 我们合并这两步：不增加 stock_quantity，而是直接从 total_quantity 中扣除
        # 依次核销分配记录
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
        # 注意：此处不增加 stock_quantity，因为旧的直接丢弃了
        asset.allocated_quantity -= quantity 

        # --- 3. 执行“发放”新物逻辑 ---
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

        # --- 4. 记录历史 (两条记录：一收一发) ---
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

        # --- 5. 审计日志 ---
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


# ==================== 归还资产（修复逻辑：校验数量并更新分配表） ====================
@asset_bp.route('/return/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.return')
def asset_return(asset_id):
    from utils import log_action  # 局部导入
    from datetime import datetime
    from models import EmploymentCycle

    asset = Asset.query.get_or_404(asset_id)
    user_id = request.form.get('user_id')
    quantity = int(request.form.get('quantity', 1))

    # 获取归还人姓名用于日志描述
    emp = EmploymentCycle.query.get(user_id)
    emp_name = emp.name if emp else f"ID:{user_id}"

    # 1. 查找该用户该资产下所有“未归还”的分配记录
    allocs = AssetAllocation.query.filter_by(asset_id=asset_id, user_id=user_id, return_date=None).all()
    allocations = AssetAllocation.query.filter_by(
        asset_id=asset_id, 
        user_id=user_id, 
        return_date=None
    ).all()
    
    # 校验用户持有的总数是否足够归还
    total_held = sum(a.quantity for a in allocations)
    if total_held < quantity:
        flash(f'归还失败：用户仅持有 {total_held} 个，无法归还 {quantity} 个', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 2. 依次“核销”这些分配记录（先进先出原则）
    remaining_to_return = quantity
    now_time = datetime.now()
    for alloc in allocations:
        if remaining_to_return <= 0: break
        
        if alloc.quantity <= remaining_to_return:
            # 该笔记录全额归还，标记归还日期
            remaining_to_return -= alloc.quantity
            alloc.return_date = now_time
        else:
            # 该笔记录部分归还，需要拆分记录
            alloc.quantity -= remaining_to_return
            # 创建一条已归还的记录作为备份
            returned_part = AssetAllocation(
                asset_id=asset_id, user_id=user_id, quantity=remaining_to_return,
                issue_date=alloc.issue_date, return_date= now_time,
                note=f"部分归还自原记录"
            )
            db.session.add(returned_part)
            remaining_to_return = 0

    # 3. 更新资产主表的库存和分配数
    asset.stock_quantity += quantity
    asset.allocated_quantity -= quantity
    if asset.allocated_quantity <= 0:
        asset.status = '库存'
    
    # 4. 记录历史
    history = AssetHistory(
        asset_id=asset_id, action='归还', user_id=user_id,
        operator_id=current_user.id, quantity=quantity,
        action_date=datetime.now(), note=request.form.get('note', '')
    )
    db.session.add(history)
    # 5. 【核心新增】记录管理员操作审计日志
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
    from utils import log_action
    
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

            # 1. 更新库存
            asset.stock_quantity -= qty
            asset.allocated_quantity += qty
            asset.status = '使用中'
            asset.current_user_id = user_id

            # 2. 领用记录
            allocation = AssetAllocation(
                asset_id=asset.id,
                user_id=user_id,
                quantity=qty,
                issue_date=datetime.today().date(),
                note=note
            )
            db.session.add(allocation)

            # 3. 资产历史
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
            # 4. 【审计记录】
            log_action(
                action_type='发放资产',
                target_type='Asset',
                target_id=None, # 批量操作可设为None
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
    from utils import log_action  # 局部导入
    from datetime import datetime

    asset = Asset.query.get_or_404(asset_id)
    if asset.type != '消耗品':
        flash('仅消耗品可直接消耗', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    quantity = int(request.form.get('quantity', 1))
    if asset.stock_quantity < quantity:
        flash('库存不足', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    asset.stock_quantity -= quantity
    now_time = datetime.now() # 使用精确时间

    history = AssetHistory(
        asset_id=asset_id,
        action='消耗',
        user_id=current_user.id if current_user.is_authenticated else None,
        operator_id=current_user.id,  # 操作人
        quantity=quantity,
        action_date=now_time,
        note=request.form.get('note', '')
    )
    db.session.add(history)
    # 3. 【核心新增】记录管理员审计日志
    # 将备注信息也加入描述，方便管理人员追溯为什么消耗
    log_description = f"消耗了消耗品：{asset.name} (编号:{asset.number})，数量：{quantity}"
    if request:
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

# ==================== 补充库存（支持财务联动） ====================
@asset_bp.route('/supplement/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.supplement')
def asset_supplement(asset_id):
    from utils import log_action
    from models import FundsRecord

    asset = Asset.query.get_or_404(asset_id)
    quantity = int(request.form.get('quantity', 0))
    # 补充时是否记账
    is_sync = request.form.get('sync_fund') == 'on'
    raw_price = request.form.get('unit_price', '0').strip()
    unit_price = float(raw_price if raw_price else 0)

    if quantity <= 0:
        flash('数量无效', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    asset.total_quantity += quantity
    asset.stock_quantity += quantity
    
    # 只有归属是特保队，且勾选了同步，才扣钱
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
    from utils import log_action  # 局部导入
    from datetime import datetime

    # 获取资产对象，不存在则返回404
    asset = Asset.query.get_or_404(asset_id)
    
    # 获取表单提交的报废数量和原因
    try:
        quantity = int(request.form.get('quantity', 0))
    except ValueError:
        quantity = 0
    reason = request.form.get('reason', '').strip()
    
    # 1. 基础校验
    if quantity <= 0:
        flash('报废数量必须大于 0', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 2. 业务校验：报废仅限库存部分，不扣除已分配（队员手中）的物资
    # 如果要报废队员手中的物资，必须先执行“归还”入库，再执行“报废”
    if quantity > asset.stock_quantity:
        flash(f'报废失败：当前库存仅余 {asset.stock_quantity}，无法报废 {quantity}。'
              f'若要报废已发放物资，请先执行“归还入库”操作。', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    # 3. 执行扣减逻辑
    # 减少总数（资产家底真实减少）
    asset.total_quantity -= quantity
    # 减少库存（实物从仓库核销）
    asset.stock_quantity -= quantity
    
    # 4. 自动更新资产状态
    # 如果总数清零，则标记为报废状态；否则保持原状态（如：在库/领用中）
    if asset.total_quantity == 0:
        asset.status = '报废'
    
    # 5. 记录资产变更历史
    history = AssetHistory(
        asset_id=asset_id,
        action='报废',
        quantity=quantity,
        user_id=current_user.id,     # 责任人/关联人
        operator_id=current_user.id, # 实际操作人
        action_date=datetime.now(),
        note=f'报废原因: {reason}' if reason else '原因: 未备注'
    )
    db.session.add(history)
    
    # 6. 记录管理员审计日志
    log_description = f"执行资产报废：{asset.name}(编号:{asset.number})，数量：{quantity}。总数已同步扣减。"
    if reason:
        log_description += f" 备注原因：{reason}"

    log_action(
        action_type='资产报废',
        target_type='Asset',
        target_id=asset_id,
        description=log_description
    )
    
    # 提交数据库事务
    db.session.commit()
    
    flash(f'成功报废 {quantity} 个资产，库存及总数已更新', 'success')
    return redirect(url_for('asset.asset_detail', asset_id=asset_id))

# ==================== 固定资产维修 ====================
@asset_bp.route('/repair/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.repair')
def asset_repair(asset_id):
    from utils import log_action  # 局部导入
    from datetime import datetime

    asset = Asset.query.get_or_404(asset_id)
    if asset.type != '固定资产':
        flash('仅固定资产可添加维修记录', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))

    note = request.form.get('note', '').strip()
    
    # 1. 变更资产状态
    asset.status = '维修中'
    now_time = datetime.now() # 使用精确时间

    # 2. 记录资产维度历史
    history = AssetHistory(
        asset_id=asset_id,
        action='维修',
        user_id=current_user.id,
        operator_id=current_user.id,
        action_date=now_time,
        note=note
    )
    db.session.add(history)

    # 3. 【核心新增】记录管理员审计日志
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
    from utils import log_action  # 局部导入
    from datetime import datetime

    asset = Asset.query.get_or_404(asset_id)
    if asset.type != '固定资产':
        flash('仅固定资产可标记修复完成', 'danger')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    if asset.status != '维修中':
        flash('当前状态不是维修中，无法标记修复完成', 'warning')
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
    note = request.form.get('note', '').strip()
    
    # 1. 恢复资产状态
    asset.status = '正常'  # 标记为正常，即可重新发放使用
    now_time = datetime.now() # 使用精确时间

    # 2. 记录资产维度历史
    history = AssetHistory(
        asset_id=asset_id,
        action='修复完成',
        user_id=current_user.id,
        operator_id=current_user.id,
        action_date=now_time,
        note=note
    )
    db.session.add(history)

    # 3. 【核心新增】记录管理员审计日志
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
    # 记录历史并关联主资产
    history = AssetHistory(
        asset_id=instance.asset_id,
        action='维修（单件）',
        operator_id=current_user.id,
        quantity=0, # 单件状态变更不影响库存总数
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
    reason = request.form.get('note', '').strip() # 注意前端form里的textarea叫note
    instance = AssetInstance.query.get_or_404(sub_asset_id)
    asset = instance.asset_info
    
    instance.status = '报废'
    # 报废单件通常需要扣减主库存
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
# 子资产维修完成（修复）
@asset_bp.route('/complete_repair_sub', methods=['POST'])
@login_required
@perm.require('asset.complete_repair')
def asset_complete_repair_sub():
    sub_asset_id = request.form.get('sub_asset_id')
    note = request.form.get('note', '').strip()
    
    # 找到该单件资产
    instance = AssetInstance.query.get_or_404(sub_asset_id)
    
    # 将状态从“维修”改回“正常”
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

# ==================== 全局资产盘点（管理员专用） ====================
@asset_bp.route('/inventory')
@login_required
@perm.require('asset.inventory')  # 仅管理员/有权限用户可盘点
def asset_inventory():
    """全局资产盘点：显示所有资产，支持按状态/类型筛选"""
    type_filter = request.args.get('type', '')
    status_filter = request.args.get('status', '')
    
    # 全局查询所有资产个体（AssetInstance）
    query = AssetInstance.query.join(Asset).join(Room, isouter=True)
    
    # 筛选条件
    if type_filter:
        query = query.filter(Asset.type == type_filter)
    if status_filter:
        query = query.filter(AssetInstance.status == status_filter)
    
    assets = query.order_by(Asset.type, Asset.name, AssetInstance.sn_number).all()
    
    # 统计信息
    total = len(assets)
    normal = len([a for a in assets if a.status == '正常'])
    abnormal = total - normal
    
    return render_template('asset/inventory.html',
                           assets=assets,
                           type_filter=type_filter,
                           status_filter=status_filter,
                           total=total,
                           normal=normal,
                           abnormal=abnormal,
                           asset_types=ASSET_TYPES,
                           asset_status=ASSET_STATUS)

@asset_bp.route('/inventory/update/<int:asset_id>', methods=['POST'])
@login_required
@perm.require('asset.inventory')
def update_inventory(asset_id):
    """标记资产盘点状态"""
    asset = AssetInstance.query.get_or_404(asset_id)
    asset.last_check_date = datetime.now()
    # 支持更新资产状态（如维修→正常）
    new_status = request.json.get('status', asset.status)
    if new_status in ASSET_STATUS:
        asset.status = new_status
    db.session.commit()
    return jsonify({"status": "success", "message": f"资产 {asset.sn_number} 盘点成功"})

@asset_bp.route('/inventory/quick_check', methods=['POST'])
@login_required
@perm.require('asset.inventory')
def quick_check():
    """连续扫码盘点接口：通过 SN 编号快速标记"""
    data = request.get_json()
    sn = data.get('sn')
    
    if not sn:
        return jsonify({"status": "error", "message": "无效的资产编号"}), 400

    # 1. 在 AssetInstance 表中查找该 SN
    # 注意：根据你的模型字段，这里假设是 AssetInstance 且字段名为 sn_number
    asset = AssetInstance.query.filter_by(sn_number=sn).first()
    
    if not asset:
        return jsonify({"status": "error", "message": f"库中未找到编号: {sn}"}), 404

    # 2. 更新盘点时间
    asset.last_check_date = datetime.now()
    
    # 3. 自动将状态改为正常（扫码即表示资产存在且可用）
    asset.status = '正常'
    
    try:
        db.session.commit()
        return jsonify({
            "status": "success", 
            "message": "盘点成功",
            "asset_name": asset.asset_info.name, # 返回资产名称供前端展示
            "sn": asset.sn_number
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "数据库更新失败"}), 500

@asset_bp.route('/inventory/export')
@login_required
@perm.require('asset.inventory')
def export_inventory():
    """导出全局盘点清单"""
    from io import BytesIO
    import pandas as pd
    
    assets = AssetInstance.query.join(Asset).join(Room, isouter=True).all()
    data = []
    for a in assets:
        data.append({
            '资产类型': a.asset_info.type,
            '资产名称': a.asset_info.name,
            '资产编号': a.sn_number,
            '父类编号': a.asset_info.number,
            '存放位置': a.current_room.number if a.current_room else '待分配',
            '房间类型': a.current_room.type if a.current_room else '',
            '负责人': a.current_holder.name if a.current_holder else '无',
            '资产状态': a.status,
            '资产归属': a.asset_info.ownership or '',
            '上次盘点时间': format_date(a.last_check_date) or '未盘点',
            '购置日期': format_date(a.asset_info.purchase_date)
        })
    
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='全局资产盘点清单')
    output.seek(0)
    
    filename = f"全局资产盘点清单_{datetime.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ==================== 导出资产清单 ====================
@asset_bp.route('/export')
@login_required
@perm.require('asset.export')
def asset_export():
    type_filter = request.args.get('type')
    status_filter = request.args.get('status')
    user_filter = request.args.get('user_id')
    
    query = Asset.query
    if type_filter:
        query = query.filter_by(type=type_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if user_filter:
        query = query.filter_by(current_user_id=user_filter)
    
    assets = query.order_by(Asset.id.desc()).all()
    
    data = []
    for a in assets:
        data.append({
            '资产类型': a.type,
            '资产名称': a.name,
            '资产编号': a.number,
            '总数': a.total_quantity,
            '库存': a.stock_quantity,
            '已分配': a.allocated_quantity,
            '分配模式': a.allocation_mode,
            '部门': a.department or '',
            '当前使用人': a.current_user.name if a.current_user else '',
            '状态': a.status,
            '购置日期': format_date(a.purchase_date),
            '存放位置': a.location or '',
            '创建时间': format_date(a.created_at),
            '照片路径': a.photo_path or ''
        })
    
    df = pd.DataFrame(data)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='资产清单')
    
    output.seek(0)
    
    filename = f"资产清单_{datetime.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ==================== 批量导入资产 ====================
@asset_bp.route('/import', methods=['GET', 'POST'])
@login_required
@perm.require('asset.import')
def asset_import():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('未选择文件', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('未选择文件', 'danger')
            return redirect(request.url)
        
        if file and file.filename.endswith('.xlsx'):
            try:
                df = pd.read_excel(file)
                
                # 必填列
                required_columns = ['资产类型', '资产名称', '资产编号']
                if not all(col in df.columns for col in required_columns):
                    flash('Excel必须包含列：资产类型、资产名称、资产编号', 'danger')
                    return redirect(request.url)
                
                success_count = 0
                error_rows = []
                
                for idx, row in df.iterrows():
                    try:
                        number = str(row['资产编号']).strip()
                        # 编号唯一校验
                        if Asset.query.filter_by(number=number).first():
                            error_rows.append(f"行{idx+2}: 资产编号 {number} 已存在")
                            continue
                        
                        qty = int(row.get('总数', 1) or 1)
                        if qty <= 0:
                            error_rows.append(f"行{idx+2}: 数量必须大于0")
                            continue
                        
                        asset = Asset(
                            type=str(row['资产类型']).strip(),
                            name=str(row['资产名称']).strip(),
                            number=number,
                            total_quantity=qty,
                            stock_quantity=qty,        # 初始库存 = 总数
                            allocated_quantity=0,
                            purchase_date=parse_date(row.get('购置日期')),
                            location=str(row.get('存放位置', '')),
                            allocation_mode=str(row.get('分配模式', 'personal')),
                            department=str(row.get('部门', '')) if row.get('分配模式') == 'group' else None,
                            status='库存',
                            photo_path=str(row.get('照片路径', '')) if row.get('照片路径') else None
                            
                        )
                        db.session.add(asset)
                        success_count += 1
                    except Exception as e:
                        error_rows.append(f"行{idx+2}: {str(e)}")
                
                db.session.commit()
                
                msg = f'导入完成：成功 {success_count} 条'
                if error_rows:
                    msg += f'，失败 {len(error_rows)} 条'
                    flash(msg, 'warning')
                    flash('<br>'.join(error_rows[:30]), 'danger')  # 只显示前30条错误
                else:
                    flash(msg, 'success')
                
                return redirect(url_for('asset.asset_list'))
            except Exception as e:
                flash(f'文件读取失败：{str(e)}', 'danger')
    
    return render_template('asset/import.html')

# 资产模块权限列表
ASSET_PERMISSIONS = [
    ('view', '查看资产', '查看资产列表和详情'),
    ('add', '新增资产', '新增资产记录'),
    ('edit', '编辑资产', '编辑资产信息'),
    ('issue', '发放资产', '发放资产给员工'),
    ('return', '归还资产', '归还资产'),
    ('consume', '消耗记录', '记录消耗品使用'),
    ('supplement', '补充库存', '补充资产库存'),
    ('repair', '维修记录', '记录维修'),
    ('complete_repair', '修复完成', '标记修复完成'),
    ('scrap', '报废资产', '报废资产'),
    ('delete', '删除资产', '删除资产记录'),
    ('inventory', '资产盘点', '进行资产盘点操作'),
    ('import', '批量导入资产', '从Excel导入资产'),
    ('export', '批量导出资产', '导出资产清单'),
]