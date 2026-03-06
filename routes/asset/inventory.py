from datetime import datetime
from flask import render_template, request, jsonify
from flask_login import login_required
from models import db, AssetInstance, Asset, Room
from utils import perm, format_date
from . import asset_bp

# ==================== 全局资产盘点 ====================
@asset_bp.route('/inventory')
@login_required
@perm.require('asset.inventory')
def asset_inventory():
    """全局资产盘点：显示所有资产，支持按状态/类型筛选"""
    type_filter = request.args.get('type', '')
    status_filter = request.args.get('status', '')
    
    # 全局查询所有资产个体
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
    
    from config import ASSET_TYPES, ASSET_STATUS
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
    # 支持更新资产状态
    from config import ASSET_STATUS
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

    # 查找SN对应的资产
    asset = AssetInstance.query.filter_by(sn_number=sn).first()
    
    if not asset:
        return jsonify({"status": "error", "message": f"库中未找到编号: {sn}"}), 404

    # 更新盘点时间和状态
    asset.last_check_date = datetime.now()
    asset.status = '正常'
    
    try:
        db.session.commit()
        return jsonify({
            "status": "success", 
            "message": "盘点成功",
            "asset_name": asset.asset_info.name,
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
    from flask import send_file
    
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