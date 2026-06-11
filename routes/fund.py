#D:\cailu\cailutebao\routes\fund.py
# 资金管理模块 - 修复版（余额计算逻辑修正）

import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from models import db, FundsRecord, Asset, User
from utils import parse_date, format_date, perm, log_action, today_str, save_uploaded_file
from datetime import datetime
from io import BytesIO
import pandas as pd
from werkzeug.utils import secure_filename

fund_bp = Blueprint('fund', __name__, url_prefix='/fund')

# ==================== 核心余额重算函数 ====================
def recalculate_balances():
    """
    按日期顺序重新计算所有余额，确保数据一致性。
    在新增、导入、编辑、删除记录后调用。
    """
    # 按日期升序、ID升序获取所有记录
    records = FundsRecord.query.order_by(FundsRecord.date.asc(), FundsRecord.id.asc()).all()
    
    running_balance = 0.0
    for record in records:
        running_balance += record.amount
        record.balance = running_balance
    
    db.session.flush()
    return running_balance  # 返回最终余额

# ==================== 资金收支列表 ====================
@fund_bp.route('/list')
@login_required
@perm.require('fund.view')
def fund_list():
    # 筛选
    date_filter = request.args.get('date')
    payer_filter = request.args.get('payer')
    item_filter = request.args.get('item')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # 每页显示20条
    
    # 自定义排序
    sort = request.args.get('sort', 'date_desc')
    valid_sorts = {
        'date_asc': FundsRecord.date.asc(),
        'date_desc': FundsRecord.date.desc(),
        'payer_asc': FundsRecord.payer.asc(),
        'payer_desc': FundsRecord.payer.desc(),
        'item_asc': FundsRecord.item.asc(),
        'item_desc': FundsRecord.item.desc(),
        'amount_asc': FundsRecord.amount.asc(),
        'amount_desc': FundsRecord.amount.desc(),
        'balance_asc': FundsRecord.balance.asc(),
        'balance_desc': FundsRecord.balance.desc(),
    }
    order = valid_sorts.get(sort, FundsRecord.date.desc())
    
    query = FundsRecord.query
    if date_filter:
        query = query.filter(FundsRecord.date == parse_date(date_filter))
    if payer_filter:
        query = query.filter(FundsRecord.payer.ilike(f'%{payer_filter}%'))
    if item_filter:
        query = query.filter(FundsRecord.item.ilike(f'%{item_filter}%'))
    
    # 使用分页
    pagination = query.order_by(order).paginate(page=page, per_page=per_page, error_out=False)
    records = pagination.items
    
    # 使用最新记录的余额作为总余额（更准确）
    latest_record = FundsRecord.query.order_by(FundsRecord.date.desc(), FundsRecord.id.desc()).first()
    total_balance = latest_record.balance if latest_record else 0
    
    return render_template('fund/list.html',
                           records=records,
                           pagination=pagination,
                           total_balance=total_balance,
                           date_filter=date_filter,
                           payer_filter=payer_filter,
                           item_filter=item_filter,
                           sort=sort)

# ==================== 核心财务保存逻辑函数 ==================== 
def perform_fund_save(form_data, operator_id, files=None):
    """
    财务核心保存逻辑：从 form_data 读数据，执行财务入库。
    """
    # 1. 金额提取与计算逻辑
    if form_data.get('amount'):
        amount = float(form_data.get('amount'))
    elif form_data.get('unit_price') and form_data.get('quantity'):
        qty = int(form_data.get('quantity', 1))
        price = float(form_data.get('unit_price', 0))
        amount = -(qty * price)  # 资产买入默认为支出，转为负数
    else:
        amount = 0.0

    # 2. 字段对齐（兼容资产联动传参）
    item = form_data.get('item') or f"采购资产入库: {form_data.get('name', '未命名资产')}"
    payer = form_data.get('payer') or form_data.get('ownership', '特保队')
    note = form_data.get('note') or form_data.get('asset_note', '')
    
    # 3. 日期处理
    date_input = form_data.get('date') or form_data.get('purchase_date')
    if date_input:
        selected_date = parse_date(date_input)
        record_datetime = datetime.combine(selected_date, datetime.now().time())
    else:
        record_datetime = datetime.now()

    # 4. 附件/凭证上传逻辑
    attachment_paths = []
    if files and 'attachment' in files:
        uploaded_files = files.getlist('attachment')
        for file in uploaded_files:
            if file and file.filename != '':
                path = save_uploaded_file(file, module='funds')
                if path:
                    attachment_paths.append(path)

    delete_attachments = form_data.get('delete_attachments')
    if delete_attachments:
        try:
            paths_to_delete = json.loads(delete_attachments)
            from routes.leave import delete_physical_file
            for path in paths_to_delete:
                delete_physical_file(path)
        except:
            pass

    # 5. 创建财务记录（余额暂设为0，后续统一重算）
    record = FundsRecord(
        date=record_datetime,
        payer=payer,
        item=item,
        amount=amount,
        note=note,
        balance=0,  # 临时值，稍后重算
        attachment=attachment_paths,
        operator_id=operator_id,
    )
    db.session.add(record)
    db.session.flush()
    
    # 6. 重新计算所有余额（确保一致性）
    recalculate_balances()
    
    return record

# ==================== 添加收支记录 ====================
@fund_bp.route('/get_form_snippet')
@login_required
def get_fund_form_snippet():
    """供资产页面 AJAX 调用，返回财务表单 HTML"""
    return render_template('fund/_partial_fund_form.html', default_date=today_str())

@fund_bp.route('/add', methods=['GET', 'POST'])
@login_required
def fund_add():
    if request.method == 'POST':
        try:
            # 1. 保存财务记录
            record = perform_fund_save(request.form, current_user.id, request.files)
            
            # 2. 检查联动开关 (sync_asset)
            sync_msg = ""
            if request.form.get('sync_asset') == 'on':
                from .asset import perform_asset_save
                perform_asset_save(request.form, request.files)
                sync_msg = "，并已同步登记资产入库"

            # 记录日志
            log_action(
                action_type="财务新增",
                target_type="FundsRecord",
                target_id=record.id,
                description=f"记录 {record.item} 金额 {record.amount}{sync_msg}"
            )

            db.session.commit()
            flash(f'财务记录保存成功{sync_msg}', 'success')
            return redirect(url_for('fund.fund_list'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fund Add Error: {str(e)}")
            flash(f'保存失败：{str(e)}', 'danger')

    return render_template('fund/add.html', default_date=today_str())

# ==================== 编辑收支记录 ====================
@fund_bp.route('/edit/<int:record_id>', methods=['GET', 'POST'])
@login_required
@perm.require('fund.edit')
def fund_edit(record_id):
    record = FundsRecord.query.get_or_404(record_id)
    
    if request.method == 'POST':
        try:
            # 更新字段
            record.date = datetime.combine(parse_date(request.form.get('date')), datetime.now().time())
            record.payer = request.form.get('payer')
            record.item = request.form.get('item')
            record.amount = float(request.form.get('amount'))
            record.note = request.form.get('note', '')
            
            # 处理附件
            if 'attachment' in request.files:
                uploaded_files = request.files.getlist('attachment')
                for file in uploaded_files:
                    if file and file.filename != '':
                        path = save_uploaded_file(file, module='funds')
                        if path:
                            if record.attachment:
                                record.attachment.append(path)
                            else:
                                record.attachment = [path]
            
            # 重新计算所有余额
            recalculate_balances()
            
            log_action(
                action_type="财务编辑",
                target_type="FundsRecord",
                target_id=record.id,
                description=f"修改记录 {record.item} 金额 {record.amount}"
            )
            
            db.session.commit()
            flash('财务记录已更新', 'success')
            return redirect(url_for('fund.fund_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败：{str(e)}', 'danger')
    
    return render_template('fund/edit.html', record=record)

# ==================== 删除收支记录 ====================
@fund_bp.route('/delete/<int:record_id>', methods=['POST'])
@login_required
@perm.require('fund.delete')
def fund_delete(record_id):
    record = FundsRecord.query.get_or_404(record_id)
    
    try:
        log_action(
            action_type="财务删除",
            target_type="FundsRecord",
            target_id=record.id,
            description=f"删除记录 {record.item} 金额 {record.amount}"
        )
        
        db.session.delete(record)
        
        # 删除后重新计算所有余额
        recalculate_balances()
        
        db.session.commit()
        flash('财务记录已删除', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{str(e)}', 'danger')
    
    return redirect(url_for('fund.fund_list'))

# ==================== 批量导入 ====================
@fund_bp.route('/import', methods=['GET', 'POST'])
@login_required
@perm.require('fund.import')
def fund_import():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('请选择文件', 'warning')
            return redirect(request.url)
        
        try:
            df = pd.read_excel(file)
            df.columns = [col.strip() for col in df.columns]
            
            # 验证必要列
            required_cols = ['日期', '资方', '项目', '金额']
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                flash(f'Excel缺少必要列：{missing}', 'danger')
                return redirect(request.url)
            
            imported_count = 0
            for idx, row in df.iterrows():
                # 处理操作人
                op_name = str(row.get('操作人', '')).strip()
                user = User.query.filter_by(name=op_name).first()
                final_op_id = user.id if user else current_user.id
                
                # 处理凭证
                excel_attachment = str(row.get('凭证', '')).strip()
                attachment_value = None
                if excel_attachment and excel_attachment.lower() not in ['nan', '无', '']:
                    attachment_value = excel_attachment
                
                record = FundsRecord(
                    date=pd.to_datetime(row['日期']).to_pydatetime(),
                    payer=str(row['资方']).strip(),
                    item=str(row['项目']).strip(),
                    amount=float(row['金额']),
                    note=str(row.get('备注', '')).strip() if pd.notna(row.get('备注')) else '',
                    balance=0,  # 临时值，稍后统一重算
                    attachment=attachment_value,
                    operator_id=final_op_id
                )
                db.session.add(record)
                imported_count += 1
            
            # 导入完成后，统一重算所有余额
            final_balance = recalculate_balances()
            
            db.session.commit()
            flash(f'成功导入 {imported_count} 条记录，当前余额：{final_balance:.2f} 元', 'success')
            return redirect(url_for('fund.fund_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'导入失败：{str(e)}', 'danger')
            
    return render_template('fund/import.html')

# ==================== 导出清单 ====================
@fund_bp.route('/export')
@login_required
@perm.require('fund.export')
def fund_export():
    records = FundsRecord.query.order_by(FundsRecord.date.desc()).all()
    
    data = []
    for r in records:
        data.append({
            '日期': r.date.strftime('%Y-%m-%d %H:%M') if r.date else '',
            '资方': r.payer,
            '项目': r.item,
            '金额': r.amount,
            '类型': '收入' if r.amount >= 0 else '支出',
            '操作人': r.operator.name if r.operator else '系统',
            '凭证': r.attachment if r.attachment else '无',
            '备注': r.note
        })
    
    df = pd.DataFrame(data)
    column_order = ['日期', '资方', '项目', '金额', '类型', '操作人', '备注', '凭证']
    df = df[column_order]

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='资金收支明细')
    output.seek(0)
    
    curr_time = datetime.now().strftime('%Y%m%d_%H%M')
    return send_file(output, as_attachment=True, 
                     download_name=f"财务导出_{curr_time}.xlsx",
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ==================== 权限定义 ====================
FUND_PERMISSIONS = [
    ('view', '查看资金', '查看资金收支列表'),
    ('add', '新增资金', '手动添加收支记录'),
    ('edit', '编辑资金', '修改收支记录'),
    ('delete', '删除资金', '删除收支记录'),
    ('import', '导入资金', '通过Excel批量导入'),
    ('export', '导出资金', '导出资金明细到Excel'),
]