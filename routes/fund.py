# routes/fund.py
# 资金管理模块 (已集成附件上传功能)

import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from models import db, FundsRecord, Asset
from utils import parse_date, format_date, perm, log_action, today_str
from datetime import datetime
from io import BytesIO
import pandas as pd
from werkzeug.utils import secure_filename

fund_bp = Blueprint('fund', __name__, url_prefix='/fund')

# ==================== 资金收支列表 ====================
@fund_bp.route('/list')
@login_required
@perm.require('fund.view')
def fund_list():
    # 筛选
    date_filter = request.args.get('date')
    payer_filter = request.args.get('payer')
    item_filter = request.args.get('item')
    
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
    
    records = query.order_by(order).all()
    total_balance = db.session.query(db.func.sum(FundsRecord.amount)).scalar() or 0
    
    return render_template('fund/list.html',
                           records=records,
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
    # 优先取财务片段的 'amount'，若无则由资产片段的 'unit_price' * 'quantity' 计算
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
    attachment_path = None
    if 'attachment' in request.files:
        file = request.files['attachment']
        # 只有当用户确实选择了文件时，才执行保存
        if file and file.filename != '':
            from utils import save_uploaded_file
            # 必须在 if 内部执行保存，确保 file 变量是有效的
            attachment_path = save_uploaded_file(file, module='funds')

    # 最后将 attachment_path 存入数据库
    # new_record.attachment = attachment_path

    # 5. 余额计算（基于最新一条记录）
    last_record = FundsRecord.query.order_by(FundsRecord.date.desc(), FundsRecord.id.desc()).first()
    last_balance = last_record.balance if last_record else 0
    new_balance = last_balance + amount

    # 6. 创建财务记录
    record = FundsRecord(
        date=record_datetime,
        payer=payer,
        item=item,
        amount=amount,
        note=note,
        balance=new_balance,
        attachment=attachment_path,
        operator_id=operator_id,
    )
    db.session.add(record)
    db.session.flush()
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
                # 调用资产保存函数
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

# ==================== 3. 批量导入（全格式日期兼容版） ====================
@fund_bp.route('/import', methods=['GET', 'POST'])
@login_required
@perm.require('fund.import')
def fund_import():
    from models import User
    if request.method == 'POST':
        file = request.files.get('file')
        if not file: return redirect(request.url)
        
        try:
            df = pd.read_excel(file)
            df.columns = [col.strip() for col in df.columns]
            
            last_rec = FundsRecord.query.order_by(FundsRecord.id.desc()).first()
            current_bal = last_rec.balance if last_rec else 0
            
            for idx, row in df.iterrows():
                amt = float(row['金额'])
                current_bal += amt
                
                # --- 1. 处理操作人 ---
                op_name = str(row.get('操作人', '')).strip()
                user = User.query.filter_by(name=op_name).first()
                final_op_id = user.id if user else current_user.id
                
                # --- 2. 处理凭证文件名 (解决 final_attachment 定义问题) ---
                excel_attachment = str(row.get('凭证', '')).strip()
                # 预设变量，确保它一定被定义
                current_attachment_value = None 
                
                # 只要不是无效字符，就取 Excel 里的文件名
                if excel_attachment and excel_attachment.lower() != 'nan' and excel_attachment != '无':
                    current_attachment_value = excel_attachment

                record = FundsRecord(
                    date=pd.to_datetime(row['日期']).to_pydatetime(),
                    payer=str(row['资方']).strip(),
                    item=str(row['项目']).strip(),
                    amount=amt,
                    note=str(row.get('备注', '')).strip() if pd.notna(row.get('备注')) else '',
                    balance=current_bal,
                    attachment=current_attachment_value, # 存入文件名，网页就会生成链接
                    operator_id=final_op_id
                )
                db.session.add(record)
            
            db.session.commit()
            flash('数据导入成功，凭证链接已关联', 'success')
            return redirect(url_for('fund.fund_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'导入失败：{str(e)}', 'danger')
            
    return render_template('fund/import.html')
# ==================== 4. 导出清单 ====================
@fund_bp.route('/export')
@login_required
@perm.require('fund.export')
def fund_export():
    # 获取当前筛选下的所有记录
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
    # 按照你要求的顺序重新排序列（确保万一）
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

FUND_PERMISSIONS = [
    ('view', '查看资金', '查看资金收支列表'),
    ('add', '新增资金', '手动添加收支记录'),
    ('import', '导入资金', '通过Excel批量导入'),
    ('export', '导出资金', '导出资金明细到Excel'),
]