# routes/dorm.py
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from models import db, Room, EmploymentCycle, AssetInstance, Asset, OperationLog
from utils import perm, log_action
from config import ROOM_NUMBERS, ROOM_TYPES

# 定义蓝图，所有路径都会带上 /dorm 前缀
dorm_bp = Blueprint('dorm', __name__, url_prefix='/dorm')

# ========================================================
# 1. 数据库初始化路由 (一键生成房间与资产个体 + 更新已有房间属性)
# ========================================================
@dorm_bp.route('/init_data')
@login_required
@perm.require('dorm.view')
def init_dorm_data():
    """
    用途：同步配置中的房间到数据库（新增+更新属性），并补齐资产个体记录
    """
    # 1. 初始化/更新房间（核心：新增+更新逻辑）
    existing_rooms = Room.query.all()  # 查询所有已存在的房间
    existing_room_dict = {room.number: room for room in existing_rooms}  # 房间号→房间对象映射
    rooms_added = 0
    rooms_updated = 0  # 新增：统计更新的房间数
    
    for num in ROOM_NUMBERS:
        # 匹配房间属性（和之前一致，精准匹配）
        if num in ["101室", "102室", "103室", "104室", "105室"]:
            target_type = "宿舍"
        elif num == "106室":
            target_type = "备勤室"
        elif num == "107室":
            target_type = "队长办公室"
        elif num == "108室":
            target_type = "仓库"
        elif num == "109室":
            target_type = "机房"
        elif num == "110室":
            target_type = "洗浴间"
        elif num == "111室":
            target_type = "盥洗室"
        elif num == "112室":
            target_type = "卫生间"
        elif num == "113室":
            target_type = "走廊"
        else:
            target_type = "宿舍"  # 兜底默认
        
        # 核心逻辑：判断房间是否存在
        if num in existing_room_dict:
            # 房间已存在：检查属性是否需要更新
            existing_room = existing_room_dict[num]
            if existing_room.type != target_type:
                existing_room.type = target_type  # 更新属性
                rooms_updated += 1
        else:
            # 房间不存在：新增房间
            new_room = Room(
                number=num, 
                type=target_type, 
                x_pos=100,  # 初始坐标
                y_pos=100
            )
            db.session.add(new_room)
            rooms_added += 1
    
    # 2. 为固定资产生成个体 (AssetInstance)（不变，移到房间循环外）
    fixed_assets = Asset.query.filter_by(type='固定资产').all()
    instances_added = 0
    for a in fixed_assets:
        current_instances_count = AssetInstance.query.filter_by(asset_id=a.id).count()
        needed = a.total_quantity - current_instances_count
        if needed > 0:
            for i in range(needed):
                sn = f"{a.number or 'SN'}-{(current_instances_count + i + 1):03d}"
                new_instance = AssetInstance(asset_id=a.id, sn_number=sn, status='正常')
                db.session.add(new_instance)
                instances_added += 1
    
    try:
        db.session.commit()
        # 返回结果：明确新增和更新的数量
        return (f"初始化成功！<br>"
                f"新增房间：{rooms_added} 个<br>"
                f"更新属性的房间：{rooms_updated} 个<br>"
                f"补齐资产个体：{instances_added} 个")
    except Exception as e:
        db.session.rollback()
        return f"初始化失败，错误原因：{str(e)}"

# ========================================================
# 2. 宿舍地图页面路由 (合并后的逻辑)
# ========================================================
@dorm_bp.route('/map')
@login_required
@perm.require('dorm.view')
def dorm_map():
    """
    用途：渲染宿舍平面分布图页面，并区分住宿与不住宿人员名单
    """
    rooms = Room.query.all()
    
    # 1. 住宿人员名单：已分配房间的在职人员
    assigned_emps = EmploymentCycle.query.filter(
        EmploymentCycle.status == '在职', 
        EmploymentCycle.room_id.isnot(None),
        EmploymentCycle.gender == '男'
    ).all()
    
    # 2. 不住宿人员名单：未分配房间的在职人员
    unassigned_emps = EmploymentCycle.query.filter(
    EmploymentCycle.status == '在职',
    EmploymentCycle.room_id == None,
    EmploymentCycle.gender == '男' # 这样名单里就只会出现男性
).all()
    
    # 3. 待分配资产个体
    unassigned_assets = AssetInstance.query.filter_by(room_id=None).all()

    
    return render_template('dorm/map.html', 
                           rooms=rooms, 
                           assigned_emps=assigned_emps, 
                           unassigned_emps=unassigned_emps, 
                           unassigned_assets=unassigned_assets)


# ========================================================
# 3. 拖拽分配动作路由
# ========================================================
@dorm_bp.route('/assign', methods=['POST'])
@login_required
@perm.require('dorm.edit')
def assign_to_room():
    data = request.json
    target_room_id = data.get('room_id') 
    item_type = data.get('type')        
    item_id = data.get('id')              
    bed_id = data.get('bed_id')           
    is_leader = data.get('is_leader', False)  
    room_number = data.get('room_number', '')
    room_type = data.get('room_type', '')

    try:
        if item_type == 'asset':
            instance = AssetInstance.query.get_or_404(item_id)
            old_room_id = instance.room_id
            instance.room_id = target_room_id if target_room_id else None  # 修复这里！
            
            # 核心修复1：提前定义asset变量，避免未赋值
            asset = instance.asset_info
            leader = None  # 初始化leader变量
            
            # 资产拖入房间：关联宿舍长
            if target_room_id:
                # 查询房间的宿舍长
                leader = EmploymentCycle.query.filter(
                    EmploymentCycle.room_id == target_room_id,
                    EmploymentCycle.is_room_leader == True
                ).first()
                if leader:
                    instance.user_id = leader.id
                    asset.current_user_id = leader.id  # 用提前定义的asset
                # 同步存放位置
                asset.location = room_number
            else:
                # 资产拖回待分配池：清空关联
                instance.user_id = None
                asset.current_user_id = None  # 清空负责人
                asset.location = '待分配'  # 用提前定义的asset
            
            # 改为调用log_action
            full_sn = instance.sn_number
            leader_name = leader.name if leader else '无'
            operated_user_id = leader.id if leader else None  # 被操作人=宿舍长
            log_action(
                action_type="资产调拨",
                target_type="AssetInstance",
                target_id=instance.id,
                description = f"将资产：【{asset.name}】，编号：{full_sn} 移至{room_number if target_room_id else '待分配池'}，负责人：{leader_name}",
                **locals()
            )
        
        # 人员分配逻辑（保持不变）
        elif item_type == 'employee':
            emp = EmploymentCycle.query.get_or_404(item_id)
            old_room_id = emp.room_id
            
            if target_room_id:
                emp.room_id = target_room_id
                emp.bed_number = bed_id
                
                if is_leader:
                    # 取消原有宿舍长
                    EmploymentCycle.query.filter(
                        EmploymentCycle.room_id == target_room_id,
                        EmploymentCycle.is_room_leader == True
                    ).update({EmploymentCycle.is_room_leader: False})
                    emp.is_room_leader = True
                    
                    # 关联房间资产负责人
                    AssetInstance.query.filter(
                        AssetInstance.room_id == target_room_id
                    ).update({AssetInstance.user_id: emp.id})
                    
                    # 子查询更新Asset表
                    asset_ids = db.session.query(AssetInstance.asset_id).filter(
                        AssetInstance.room_id == target_room_id
                    ).distinct().subquery()
                    Asset.query.filter(
                        Asset.id.in_(asset_ids)
                    ).update({Asset.current_user_id: emp.id})
            else:
                # 人员拖回待分配池
                emp.room_id = None
                emp.bed_number = None
                if emp.is_room_leader:
                    emp.is_room_leader = False
                    # 清空资产负责人
                    AssetInstance.query.filter(
                        AssetInstance.room_id == old_room_id
                    ).update({AssetInstance.user_id: None})
                    
                    asset_ids = db.session.query(AssetInstance.asset_id).filter(
                        AssetInstance.room_id == old_room_id
                    ).distinct().subquery()
                    Asset.query.filter(
                        Asset.id.in_(asset_ids)
                    ).update({Asset.current_user_id: None})
            
            # ==================== 替换人员日志代码 ====================
            # 改为调用log_action
            leader_desc = "（宿舍长）" if is_leader else ""
            bed_desc = bed_id if bed_id else '无'
            if bed_desc and '-' in bed_desc:
                bed_parts = bed_desc.split('-')
                if len(bed_parts) >= 3:
                    asset_sn = f"{bed_parts[0]}-{bed_parts[1]}"
                    bed_pos = bed_parts[2]
                    asset_instance = AssetInstance.query.filter_by(sn_number=asset_sn).first()
                    if asset_instance and asset_instance.asset_info:
                        bed_desc = f"{asset_instance.asset_info.name} {asset_sn} {bed_pos}"
            
            log_action(
                action_type="人员调宿" + leader_desc,
                target_type="Employee",
                target_id=emp.id,
                description=f"将队员 【{emp.name}】 分配到{room_number if target_room_id else '待分配池'}，床位: {bed_desc} {leader_desc}",
                **locals()
            )
        
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    
# ===================查询床位======================================
@dorm_bp.route('/get_available_beds/<int:room_id>')
@login_required
@perm.require('dorm.edit')
def get_available_beds(room_id):
    """查询房间里有哪些床位可以选（彻底放松条件）"""
    # 修复：去掉“Asset.type == '固定资产'”的限制，只保留核心条件
    assets = AssetInstance.query.join(Asset).filter(
        AssetInstance.room_id == room_id,          # 必须在该房间
        Asset.bed_capacity > 0,                    # 必须是床位类
        Asset.name.like('%床%')                    # 名称含“床”
    ).all()

    # 调试：打印所有匹配的资产（方便定位）
    print(f"房间{room_id}的床位资产数量：{len(assets)}")
    for inst in assets:
        print(f"资产名称：{inst.asset_info.name}，容量：{inst.asset_info.bed_capacity}，房间ID：{inst.room_id}")

    beds = []
    for inst in assets:
        cap = inst.asset_info.bed_capacity
        asset_name = inst.asset_info.name
        sn_number = inst.sn_number
        
        if cap == 2:
            labels = ["上铺", "下铺"]
        elif cap == 1:
            labels = ["单铺"]
        else:
            continue
        
        for label in labels:
            bed_code = f"{sn_number}-{label}"
            occ = EmploymentCycle.query.filter_by(bed_number=bed_code).first()
            
            beds.append({
                "code": bed_code,
                "asset_name": asset_name,
                "occupied": True if occ else False,
                "occupant": occ.name if occ else ""
            })

    # 调试：打印最终返回的床位数据
    print(f"最终返回的床位数据：{beds}")
    return jsonify(beds)
# ========================================================
# 4. 房间定位保存路由
# ========================================================
@dorm_bp.route('/save_room_pos', methods=['POST'])
@login_required
@perm.require('dorm.edit')
def save_room_pos():
    """持久化房间在地图上的 (x, y) 坐标"""
    data = request.json
    room_id = data.get('room_id')
    room = Room.query.get(room_id)
    if room:
        room.x_pos = data.get('x')
        room.y_pos = data.get('y')
        try:
            db.session.commit()
            return jsonify({"status": "success"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error", "message": "房间未找到"}), 404

# ========================================================
# 5. 调试工具：重置所有房间位置 (可选)
# ========================================================
@dorm_bp.route('/reset_positions')
@login_required
@perm.require('dorm.edit')
def reset_positions():
    """如果地图排版乱了，可以访问此路由将所有房间重置到左上角"""
    rooms = Room.query.all()
    for r in rooms:
        r.x_pos = 50
        r.y_pos = 50
    db.session.commit()
    return "已重置所有房间坐标，请重新在地图上排版。"

# 宿舍管理相关权限
DORM_PERMISSIONS = [
    ('view', '查看宿舍', '查看宿舍地图'),
    ('edit', '编辑宿舍', '编辑宿舍信息')
]