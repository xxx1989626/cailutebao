# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin


db = SQLAlchemy()

# ==================== 用户模型 ====================
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(18), unique=True, nullable=False, index=True)  # 身份证号码
    password_hash = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    # 现在系统逻辑仅识别 'admin' (统管) 和 'member' (默认身份)
    # 具体权限通过下方的 UserPermission 表分配
    role = db.Column(db.String(20), default='member', nullable=False) 
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ==================== 权限字典表 ====================
class Permission(db.Model):
    __tablename__ = 'permissions'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)  # 如 'hr.view'
    module = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    
    __table_args__ = (db.UniqueConstraint('module', 'action', name='uix_module_action'),)

# ==================== 用户权限关联 (核心修复) ====================
class UserPermission(db.Model):
    __tablename__ = 'user_permissions'

    # 显式增加 autoincrement=True 解决 sqlite3.IntegrityError
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.id'), nullable=False)
    
    # 唯一性约束，防止重复分配
    __table_args__ = (db.UniqueConstraint('user_id', 'permission_id', name='uix_user_perm'),)


# ==================== 任职周期模型 ====================
class EmploymentCycle(db.Model):
    __tablename__ = 'employment_cycles'

    id = db.Column(db.Integer, primary_key=True)
    id_card = db.Column(db.String(18), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    gender = db.Column(db.String(2))
    birthday = db.Column(db.Date)
    hire_date = db.Column(db.Date, nullable=False)
    departure_date = db.Column(db.Date)
    status = db.Column(db.String(10), default='在职')  # 在职、离职
    
    photo_path = db.Column(db.String(200))
    
    # 基本信息
    ethnic = db.Column(db.String(20))
    politics = db.Column(db.String(20))
    education = db.Column(db.String(20))
    
    # 地址
    household_province = db.Column(db.String(20)) # 省/直辖市
    household_city = db.Column(db.String(20)) # 市/市辖区
    household_district = db.Column(db.String(20)) # 区/县
    household_town = db.Column(db.String(50))   # 镇/街道
    household_village = db.Column(db.String(50)) # 新增：村/居委
    household_detail = db.Column(db.String(255)) # 调大详细地址
    residence_province = db.Column(db.String(20)) # 省/直辖市
    residence_city = db.Column(db.String(20)) # 市/市辖区
    residence_district = db.Column(db.String(20)) # 区/县
    residence_town = db.Column(db.String(50))    # 镇/街道
    residence_village = db.Column(db.String(50))  # 新增：村/居委
    residence_detail = db.Column(db.String(255))  # 调大详细地址
    
    # 资质
    military_service = db.Column(db.Boolean, default=False)
    enlistment_date = db.Column(db.Date)
    unit_number = db.Column(db.String(50))
    branch = db.Column(db.String(50))
    discharge_date = db.Column(db.Date)
    
    has_license = db.Column(db.Boolean, default=False)
    license_date = db.Column(db.Date)
    license_type = db.Column(db.String(20))
    license_expiry = db.Column(db.Date)
    
    has_security_license = db.Column(db.Boolean, default=False)
    security_license_number = db.Column(db.String(50))
    security_license_date = db.Column(db.Date)

    # 薪资与岗位
    salary_mode = db.Column(db.String(20))
    position = db.Column(db.String(20))
    post = db.Column(db.String(20))
    
    # 紧急联系人
    emergency_name = db.Column(db.String(50))
    emergency_relation = db.Column(db.String(20))
    emergency_phone = db.Column(db.String(20))
    
    # 工作服尺码
    hat_size = db.Column(db.String(10))
    short_sleeve = db.Column(db.String(10))
    long_sleeve = db.Column(db.String(10))
    winter_uniform = db.Column(db.String(10))
    shoe_size = db.Column(db.String(10))

    # 新增房间关联
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    is_room_leader = db.Column(db.Boolean, default=False)  # 是否为该房宿舍长
    bed_number = db.Column(db.String(50))  # 床位号，1-4
    # 档案JSON（其他证书 + 档案记录 + 离职原因）
    archives = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== 资产模型 ====================
class Asset(db.Model):
    __tablename__ = 'assets'   # 指定数据库中对应的表名为 'assets'
    id = db.Column(db.Integer, primary_key=True)  # 唯一主键，自动递增的数字 ID
    type = db.Column(db.String(20), nullable=False)  # 装备、固定资产、消耗品、其他
    name = db.Column(db.String(100), nullable=False)  # 资产名称（必填）
    number = db.Column(db.String(50), unique=True)  # 资产编号，全局唯一，不能重复    
    total_quantity = db.Column(db.Integer, default=0)  # 总数（拥有的总数量）
    stock_quantity = db.Column(db.Integer, default=0)  # 库存（仓库现有）
    allocated_quantity = db.Column(db.Integer, default=0)  # 已分配（队员手上）    
    photo_path = db.Column(db.String(200))  # 资产照片的存放路径（存储在 static/uploads 里的文件名）
    purchase_date = db.Column(db.Date)  # 购买日期，年月日格式
    location = db.Column(db.String(100))   # 存放的具体物理位置（如：装备仓库三排A架）
    status = db.Column(db.String(20), default='库存')  # 库存、使用中、维修中、报废  
    ownership = db.Column(db.String(20), default='特保队')  
    unit_price = db.Column(db.Float, default=0.0)  # 每个资产的单价（元）
    bed_capacity = db.Column(db.Integer, default=0) # 0:非床, 1:单人床, 2:双层床
    # 个人分配使用人
    # 关联到 employment_cycles 表的 ID，记录当前该资产在谁手里
    current_user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True)
    # 建立关系模型，方便通过 asset.current_user 直接获取到员工的对象信息（名字、电话等）
    current_user = db.relationship('EmploymentCycle', backref='assets')    
    # 集体/部门使用
    allocation_mode = db.Column(db.String(20), default='personal')  # 'personal' or 'group'
    department = db.Column(db.String(50))  # 集体使用部门    
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # 记录创建的时间，默认是当前系统时间
    instances = db.relationship('AssetInstance', 
                               backref='asset_info', 
                               cascade="all, delete-orphan", 
                               lazy=True)

# ==================== 资产个体模型 (固定资产实物) ====================
class AssetInstance(db.Model):
    """
    具体的资产个体。比如 Asset 是'空调'，Instance 就是'107室的那台空调'。
    """
    __tablename__ = 'asset_instances'
    id = db.Column(db.Integer, primary_key=True)
    
    # 关联父类（型号）
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    # 唯一识别码：出厂序列号或内部贴码
    sn_number = db.Column(db.String(100), unique=True, index=True)
    
    # 位置联动：当前在哪间房
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    # 责任人联动：如果分配给个人，则关联此 ID
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True)
    
    status = db.Column(db.String(20), default='正常')  # 见 config.ASSET_STATUS
    last_check_date = db.Column(db.DateTime, default=datetime.now)
    
    # 关系映射
    current_room = db.relationship('Room', backref='room_assets')
    current_holder = db.relationship('EmploymentCycle', backref='personal_assets')
# ==================== 领用人 ====================
class AssetAllocation(db.Model):
    __tablename__ = 'asset_allocations'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)  # 该人领用数量
    issue_date = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime)  # 归还日期（None 表示未归还）
    note = db.Column(db.Text)

    asset = db.relationship('Asset', backref='allocations')
    user = db.relationship('EmploymentCycle')

# ==================== 资产操作历史 ====================
class AssetHistory(db.Model):
    __tablename__ = 'asset_history'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)
    asset = db.relationship('Asset', backref='history')
    action = db.Column(db.String(20), nullable=False)  # 发放、归还、补充、消耗、维修、报废
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True)  # 被操作人（领取/归还者）
    user = db.relationship('EmploymentCycle', foreign_keys=[user_id])
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 操作人（当前登录用户）
    operator = db.relationship('User', foreign_keys=[operator_id])
    quantity = db.Column(db.Integer, default=1)
    action_date = db.Column(db.DateTime, default=datetime.now)
    db.Column(db.DateTime, default=datetime.now)
    note = db.Column(db.Text)
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    operator = db.relationship('User', foreign_keys=[operator_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
# ==================== 资金模块 ====================

class FundsRecord(db.Model):
    __tablename__ = 'funds_records'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False)  # 日期
    payer = db.Column(db.String(50))  # 资方
    item = db.Column(db.String(100))  # 项目
    amount = db.Column(db.Float, nullable=False)  # 金额
    note = db.Column(db.Text)  # 备注
    balance = db.Column(db.Float, nullable=False)  # 余额（自动计算）
    attachment = db.Column(db.String(255), nullable=True)  # 附件路径
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    operator = db.relationship('User', foreign_keys=[operator_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<FundsRecord {self.date} - {self.item} - {self.amount}>'
    
# ==================== 宿舍/房间模型 ====================
class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)  # 101室, 102室
    type = db.Column(db.String(20))  # 宿舍、备勤室、办公室等 (见 config.ROOM_TYPES)
    area = db.Column(db.Float)  # 面积 (平方米)
    
    # 宿舍长关联：关联到 EmploymentCycle
    leader_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True)
    leader = db.relationship('EmploymentCycle', foreign_keys=[leader_id])

    # 坐标信息：用于在平面图上的绝对定位 (x, y 坐标，前端拖拽时更新)
    x_pos = db.Column(db.Integer, default=0)
    y_pos = db.Column(db.Integer, default=0)

    # 关系映射：方便通过 room.occupants 看到屋里所有人
    occupants = db.relationship('EmploymentCycle', backref='room', foreign_keys='EmploymentCycle.room_id')
    
# ==================== 审计日志（Audit Log） ====================
class OperationLog(db.Model):
    __tablename__ = 'operation_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # 操作人
    action_type = db.Column(db.String(50))    # 操作类型：发放、归还、修改队员、删除记录等
    target_type = db.Column(db.String(50))    # 目标对象：Asset, Employee, Funds 等
    target_id = db.Column(db.Integer)         # 目标对象的ID
    description = db.Column(db.Text)          # 详细描述：如 "发放了 2 个肩灯给余传梅"
    ip_address = db.Column(db.String(50))     # 选填：记录操作IP，增强安全性
    created_at = db.Column(db.DateTime, default=datetime.now) # 自动记录时间

    # 关联操作人
    operator = db.relationship('User', backref=db.backref('operation_logs', lazy=True))

# ==================== 考勤排班相关模型 ====================

class ShiftPost(db.Model):
    """排班岗位：如白班、夜班、综合指挥室等"""
    __tablename__ = 'shift_posts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(20), default='#007bff') # 前端标签颜色
    default_start = db.Column(db.String(10), default="08:30")
    default_end = db.Column(db.String(10), default="17:30")

class ShiftSchedule(db.Model):
    """具体排班记录"""
    __tablename__ = 'shift_schedules'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    # 关联 EmploymentCycle 而不是 User，因为排班是基于职位的
    employee_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('shift_posts.id'))
    
    start_time = db.Column(db.String(5), default="08:00")
    end_time = db.Column(db.String(5), default="20:00")
    is_duty_leader = db.Column(db.Boolean, default=False) # 是否值班领导
    is_duty_chief = db.Column(db.Boolean, default=False)  # 是否值班长

    employee = db.relationship('EmploymentCycle', backref='schedules')
    post = db.relationship('ShiftPost', backref='schedules')

class ShiftTemplate(db.Model):
    """排班模板（用于套用）"""
    __tablename__ = 'shift_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    data = db.Column(db.JSON) # 存储排班规则的 JSON 数据

# 这就是在数据库里新建一张叫“排班”的表
class Scheduling(db.Model):
    __tablename__ = 'schedulings'
    id = db.Column(db.Integer, primary_key=True)
    # 改为关联员工档案 ID
    employee_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    # 增加岗位关联
    post_id = db.Column(db.Integer, db.ForeignKey('shift_posts.id'))
    shift_type = db.Column(db.String(10), default='白')
    is_overtime = db.Column(db.Boolean, default=False)
    hours = db.Column(db.Float, default=12.0)

    employee = db.relationship('EmploymentCycle', backref='schedulings_ref')
    post = db.relationship('ShiftPost', backref='schedulings_ref')

# ==================== 通知相关模型 ====================
class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # 接收通知的用户ID
    title = db.Column(db.String(100), nullable=False)  # 通知标题
    content = db.Column(db.Text, nullable=False)  # 通知内容
    is_read = db.Column(db.Boolean, default=False)  # 是否已读
    related_type = db.Column(db.String(50))  # 关联业务类型（如asset/employee/scheduling）
    related_id = db.Column(db.Integer)  # 关联业务ID
    created_at = db.Column(db.DateTime, default=datetime.now)  # 通知创建时间

    # 关联用户
    user = db.relationship('User', backref='notifications')


# ==================== 出差管理模型 ====================
trip_participants = db.Table('trip_participants',
    db.Column('trip_id', db.Integer, db.ForeignKey('business_trips.id'), primary_key=True),
    db.Column('employee_id', db.Integer, db.ForeignKey('employment_cycles.id'), primary_key=True)
)

class BusinessTrip(db.Model):
    __tablename__ = 'business_trips'
    id = db.Column(db.Integer, primary_key=True)
    destination = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    total_days = db.Column(db.Integer)  # 存储天数，方便后续SUM汇总
    status = db.Column(db.String(20), default='进行中')
    
    # 建立多对多关联
    participants = db.relationship('EmploymentCycle', 
                                  secondary=trip_participants,
                                  backref=db.backref('trips', lazy='dynamic'))

# ==================== 请假管理模型 ====================
class LeaveRecord(db.Model):
    __tablename__ = 'leave_records'
    id = db.Column(db.Integer, primary_key=True)
    
    # 关联人员（支持多人请假或单人，通常请假为单人）
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)
    user = db.relationship('EmploymentCycle', backref='leaves')
    
    leave_type = db.Column(db.String(20), nullable=False)  # 事假、病假、年假等
    reason = db.Column(db.Text)                            # 请假事由
    start_date = db.Column(db.Date, nullable=False)        # 开始时间
    end_date = db.Column(db.Date)                          # 预计结束时间
    actual_end_date = db.Column(db.Date)                   # 实际销假时间
    
    total_days = db.Column(db.Float)                       # 请假天数
    status = db.Column(db.String(20), default='请假中')    # 请假中、已销假、待审核
    
    created_at = db.Column(db.DateTime, default=datetime.now)