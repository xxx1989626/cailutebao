#D:\cailu\cailutebao\routes\fund.py
# 资金管理模块 - 修复版（余额计算逻辑修正）

import os
import json
import re
import ast
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user
from models import db, FundsRecord, Asset, User
from utils import (
    parse_date, format_date, perm, log_action, today_str, save_uploaded_file,
    parse_money_decimal, money_to_cents, yuan_to_cents, cents_to_yuan,
)
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
    
    running_balance = 0
    for record in records:
        running_balance += record.amount_cents
        record.balance_cents = running_balance
    
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
        'amount_asc': FundsRecord.amount_cents.asc(),
        'amount_desc': FundsRecord.amount_cents.desc(),
        'balance_asc': FundsRecord.balance_cents.asc(),
        'balance_desc': FundsRecord.balance_cents.desc(),
    }
    order = valid_sorts.get(sort, FundsRecord.date.desc())
    
    query = FundsRecord.query
    if date_filter:
        selected_date = parse_date(date_filter)
        if selected_date:
            day_start = datetime.combine(selected_date, datetime.min.time())
            day_end = datetime.combine(selected_date, datetime.max.time())
            query = query.filter(FundsRecord.date >= day_start, FundsRecord.date <= day_end)
        else:
            query = query.filter(db.false())
    if payer_filter:
        query = query.filter(FundsRecord.payer.ilike(f'%{payer_filter}%'))
    if item_filter:
        query = query.filter(FundsRecord.item.ilike(f'%{item_filter}%'))
    
    # 使用分页
    pagination = query.order_by(order).paginate(page=page, per_page=per_page, error_out=False)
    records = pagination.items

    # 备注含「分账批次#N」的支出记录 → 附上分账批次详情反向链接
    settle_map = {}
    for rec in records:
        m = re.search(r'分账批次#(\d+)', rec.note or '')
        if m:
            settle_map[rec.id] = int(m.group(1))

    # 使用最新记录的余额作为总余额（更准确）
    latest_record = FundsRecord.query.order_by(FundsRecord.date.desc(), FundsRecord.id.desc()).first()
    total_balance_cents = latest_record.balance_cents if latest_record else 0
    
    return render_template('fund/list.html',
                           records=records,
                           pagination=pagination,
                           total_balance_cents=total_balance_cents,
                           date_filter=date_filter,
                           payer_filter=payer_filter,
                           item_filter=item_filter,
                           settle_map=settle_map,
                           sort=sort)

# ==================== 核心财务保存逻辑函数 ==================== 
def perform_fund_save(form_data, operator_id, files=None):
    """
    财务核心保存逻辑：从 form_data 读数据，执行财务入库。
    """
    # 1. 金额提取与计算逻辑
    amount_raw = form_data.get('amount')
    if amount_raw is not None and str(amount_raw).strip() != '':
        amount_cents = yuan_to_cents(amount_raw, allow_zero=False)
    elif form_data.get('unit_price') not in (None, '') and form_data.get('quantity') not in (None, ''):
        qty = int(form_data.get('quantity', 1))
        price = parse_money_decimal(form_data.get('unit_price', 0), '资产单价')
        if qty <= 0 or price <= 0:
            raise ValueError('资产数量和单价必须大于0')
        amount_cents = -money_to_cents(qty * price)  # 资产买入默认为支出，转为负数
        if amount_cents == 0:
            raise ValueError('金额必须为非零有效数字')
    else:
        raise ValueError('金额不能为空')

    # 2. 字段对齐（兼容资产联动传参）
    item = form_data.get('item')
    if not item and form_data.get('name'):
        item = f"采购资产入库: {form_data.get('name')}"
    item = (item or '').strip()
    payer = (form_data.get('payer') or form_data.get('ownership') or '特保队').strip()
    if not item or not payer:
        raise ValueError('资方和费用项目不能为空')
    note = form_data.get('note') or form_data.get('asset_note', '')
    
    # 3. 日期处理
    date_input = form_data.get('date') or form_data.get('purchase_date')
    if date_input:
        selected_date = parse_date(date_input)
        if not selected_date:
            raise ValueError('财务日期格式不正确')
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
        amount_cents=amount_cents,
        note=note,
        balance_cents=0,  # 临时值，稍后重算
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
@perm.require('fund.add')
def fund_add():
    if request.method == 'POST':
        if request.form.get('sync_asset') == 'on' and not perm.can('asset.add'):
            flash('权限不足，联动登记资产还需要资产新增权限', 'danger')
            return render_template('fund/add.html', default_date=today_str()), 403
        try:
            required_fields = {'date': '财务日期', 'payer': '资方/付款人', 'item': '费用项目', 'amount': '金额'}
            missing = [label for field, label in required_fields.items() if not (request.form.get(field) or '').strip()]
            if missing:
                raise ValueError(f"请填写完整：{'、'.join(missing)}")
            if not parse_date(request.form.get('date')):
                raise ValueError('财务日期格式不正确')

            # 1. 保存财务记录
            record = perform_fund_save(request.form, current_user.id, request.files)
            
            # 2. 检查联动开关 (sync_asset)
            sync_msg = ""
            if request.form.get('sync_asset') == 'on':
                from .asset.core import perform_asset_save
                perform_asset_save(request.form, request.files)
                sync_msg = "，并已同步登记资产入库"

            # 记录日志
            log_action(
                action_type="财务新增",
                target_type="FundsRecord",
                target_id=record.id,
                description=f"记录 {record.item} 金额 {cents_to_yuan(record.amount_cents)}{sync_msg}"
            )

            db.session.commit()
            flash(f'财务记录保存成功{sync_msg}', 'success')
            # 可选 next：其他模块（如抓狗分账弹窗）提交后跳回原页面；只允许站内路径防开放重定向
            next_url = (request.form.get('next') or '').strip()
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('fund.fund_list'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Fund Add Error: {str(e)}")
            flash(f'保存失败：{str(e)}', 'danger')

    return render_template('fund/add.html', default_date=today_str())

# ==================== 编辑收支记录 ====================
@fund_bp.route('/edit/<int:record_id>', methods=['GET', 'POST'])
@login_required
def fund_edit(record_id):
    # 兜底操作：仅管理员可修改资金记录（不开放给普通权限分配）
    if current_user.role != 'admin':
        flash('权限不足，仅管理员可修改资金记录', 'danger')
        return redirect(url_for('fund.fund_list'))

    record = FundsRecord.query.get_or_404(record_id)

    if request.method == 'POST':
        try:
            required_fields = {'date': '财务日期', 'payer': '资方/付款人', 'item': '费用项目', 'amount': '金额'}
            missing = [label for field, label in required_fields.items() if not (request.form.get(field) or '').strip()]
            if missing:
                raise ValueError(f"请填写完整：{'、'.join(missing)}")
            selected_date = parse_date(request.form.get('date'))
            if not selected_date:
                raise ValueError('财务日期格式不正确')
            amount_cents = yuan_to_cents(request.form.get('amount'), allow_zero=False)

            # 更新字段
            record.date = datetime.combine(selected_date, datetime.now().time())
            record.payer = request.form.get('payer').strip()
            record.item = request.form.get('item').strip()
            record.amount_cents = amount_cents
            record.note = request.form.get('note', '')

            # 处理已有附件删除（由 _attachment.html 组件通过 delete_attachments 隐藏字段提交 JSON 数组）
            delete_paths_raw = request.form.get('delete_attachments', '')
            if delete_paths_raw:
                try:
                    delete_paths = json.loads(delete_paths_raw)
                    current_attachments = list(record.attachment or [])
                    record.attachment = [p for p in current_attachments if p not in delete_paths]
                except (json.JSONDecodeError, TypeError):
                    pass

            # 处理新附件上传
            if 'attachment' in request.files:
                uploaded_files = request.files.getlist('attachment')
                new_attachment_paths = []
                for file in uploaded_files:
                    if file and file.filename != '':
                        path = save_uploaded_file(file, module='funds')
                        if path:
                            new_attachment_paths.append(path)
                if new_attachment_paths:
                    # 关键：不要用 record.attachment.append()，JSON 列的原地修改
                    # 不会被 SQLAlchemy 检测到，导致 commit 时附件丢失。
                    # 必须整体重新赋值才能触发变更追踪。
                    merged = list(record.attachment or [])
                    merged.extend(new_attachment_paths)
                    record.attachment = merged

            # 重新计算所有余额
            recalculate_balances()

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
            description=f"删除记录 {record.item} 金额 {cents_to_yuan(record.amount_cents)}"
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
            for row_number, (_, row) in enumerate(df.iterrows(), start=2):
                missing_values = [c for c in required_cols if pd.isna(row.get(c)) or not str(row.get(c)).strip()]
                if missing_values:
                    raise ValueError(f"第{row_number}行必填内容不完整：{'、'.join(missing_values)}")
                record_date = pd.to_datetime(row['日期'], errors='raise').to_pydatetime()
                payer = str(row['资方']).strip()
                item = str(row['项目']).strip()
                try:
                    amount_cents = yuan_to_cents(row['金额'], allow_zero=False)
                except ValueError as exc:
                    raise ValueError(f'第{row_number}行{exc}') from exc

                # 处理操作人
                op_name = str(row.get('操作人', '')).strip()
                user = User.query.filter_by(name=op_name).first()
                final_op_id = user.id if user else current_user.id
                
                # 凭证统一保存为路径列表，并兼容历史导出的列表字符串
                excel_attachment = str(row.get('凭证', '')).strip()
                attachment_value = []
                if excel_attachment and excel_attachment.lower() not in ['nan', '无', '']:
                    try:
                        parsed_attachment = ast.literal_eval(excel_attachment)
                    except (ValueError, SyntaxError):
                        parsed_attachment = excel_attachment
                    if isinstance(parsed_attachment, (list, tuple)):
                        attachment_value = [str(p).strip() for p in parsed_attachment if p is not None and str(p).strip()]
                    else:
                        attachment_value = [excel_attachment]
                
                record = FundsRecord(
                    date=record_date,
                    payer=payer,
                    item=item,
                    amount_cents=amount_cents,
                    note=str(row.get('备注', '')).strip() if pd.notna(row.get('备注')) else '',
                    balance_cents=0,  # 临时值，稍后统一重算
                    attachment=attachment_value,
                    operator_id=final_op_id
                )
                db.session.add(record)
                imported_count += 1
            
            # 导入完成后，统一重算所有余额
            final_balance_cents = recalculate_balances()
            
            db.session.commit()
            flash(f'成功导入 {imported_count} 条记录，当前余额：{cents_to_yuan(final_balance_cents):.2f} 元', 'success')
            return redirect(url_for('fund.fund_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'导入失败：{str(e)}', 'danger')
            
    return render_template('fund/import.html')


@fund_bp.route('/import/template')
@login_required
@perm.require('fund.import')
def fund_import_template():
    """下载与导入字段一致的标准 Excel 模板。"""
    columns = ['日期', '资方', '项目', '金额', '操作人', '凭证', '备注']
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(columns=columns).to_excel(writer, index=False, sheet_name='资金导入模板')
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name='资金导入模板.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ==================== 导出清单 ====================
@fund_bp.route('/export')
@login_required
@perm.require('fund.export')
def fund_export():
    date_filter = request.args.get('date')
    payer_filter = request.args.get('payer')
    item_filter = request.args.get('item')
    query = FundsRecord.query
    if date_filter:
        selected_date = parse_date(date_filter)
        if selected_date:
            day_start = datetime.combine(selected_date, datetime.min.time())
            day_end = datetime.combine(selected_date, datetime.max.time())
            query = query.filter(FundsRecord.date >= day_start, FundsRecord.date <= day_end)
        else:
            query = query.filter(db.false())
    if payer_filter:
        query = query.filter(FundsRecord.payer.ilike(f'%{payer_filter}%'))
    if item_filter:
        query = query.filter(FundsRecord.item.ilike(f'%{item_filter}%'))
    records = query.order_by(FundsRecord.date.desc(), FundsRecord.id.desc()).all()
    
    data = []
    for r in records:
        data.append({
            '日期': r.date.strftime('%Y-%m-%d %H:%M') if r.date else '',
            '资方': r.payer,
            '项目': r.item,
            '金额': float(cents_to_yuan(r.amount_cents)),
            '类型': '收入' if r.amount_cents >= 0 else '支出',
            '操作人': r.operator.name if r.operator else '系统',
            '凭证': r.attachment if r.attachment else '无',
            '备注': r.note
        })
    
    column_order = ['日期', '资方', '项目', '金额', '类型', '操作人', '备注', '凭证']
    df = pd.DataFrame(data, columns=column_order)

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