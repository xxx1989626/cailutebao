import os
from datetime import datetime
from flask import current_app
from models import db, Asset, AssetInstance

# 导入工具函数（保持原有导入路径）
from utils import save_uploaded_file, parse_date

def perform_asset_save(form_data, files=None):
    """
    资产核心保存逻辑：从 form_data 读数据，执行资产入库。
    拆分后保持函数逻辑完全不变，仅移到 core.py 中
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

# 资产模块权限列表（移到核心模块）
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