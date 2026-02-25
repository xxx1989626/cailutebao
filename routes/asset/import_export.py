from datetime import datetime
from io import BytesIO
import pandas as pd
from flask import render_template, request, flash, redirect, url_for, send_file
from flask_login import login_required
from models import db, Asset
from utils import perm, parse_date, format_date, save_uploaded_file
from . import asset_bp

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
                
                # 必填列校验
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
                            stock_quantity=qty,
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
                    flash('<br>'.join(error_rows[:30]), 'danger')
                else:
                    flash(msg, 'success')
                
                return redirect(url_for('asset.asset_list'))
            except Exception as e:
                flash(f'文件读取失败：{str(e)}', 'danger')
    
    return render_template('asset/import.html')