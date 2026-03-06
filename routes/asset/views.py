from flask import render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required,current_user
from models import db, Asset, EmploymentCycle
from utils import log_action, today_str, delete_physical_file,parse_date,save_uploaded_file
from config import ASSET_STATUS, ASSET_TYPES

# 导入蓝图和核心函数
from . import asset_bp
from .core import perform_asset_save, ASSET_PERMISSIONS
from utils import perm

# ==================== 资产列表 ====================
@asset_bp.route('/list')
@login_required
@perm.require('asset.view')
def asset_list():
    # 1. 获取参数
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

    # 8. 默认显示所有字段
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
            # 1. 保存资产（调用核心函数）
            asset = perform_asset_save(request.form, request.files)
            
            # 2. 检查联动开关 (sync_fund)
            sync_msg = ""
            if request.form.get('sync_fund') == 'on':
                from ..fund import perform_fund_save
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
        return redirect(url_for('asset.asset_detail', asset_id=asset_id))
    
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
        from models import AssetAllocation, AssetHistory
        AssetAllocation.query.filter_by(asset_id=asset_id).delete()
        AssetHistory.query.filter_by(asset_id=asset_id).delete()
    
        db.session.delete(asset)
        db.session.commit()

        # 数据库删除成功后，清理物理文件
        if photo_path:
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
    from models import AssetHistory, AssetAllocation
    asset = Asset.query.get_or_404(asset_id)
    in_service_employees = EmploymentCycle.query.filter_by(status='在职').order_by(EmploymentCycle.name).all()
    allocations = AssetHistory.query.filter_by(asset_id=asset_id, action='发放').all()
    page = request.args.get('page', 1, type=int)
    pagination = AssetHistory.query.filter_by(asset_id=asset_id)\
        .order_by(AssetHistory.action_date.desc())\
        .paginate(page=page, per_page=10, error_out=False)
    history_items = pagination.items

    next_url = request.args.get('next')
    if next_url and not next_url.startswith('/'):
        next_url = None
    return render_template('asset/detail.html',
                           asset=asset,
                           in_service_employees=in_service_employees,
                           pagination=pagination,
                           history_items=history_items,
                           return_url=next_url)