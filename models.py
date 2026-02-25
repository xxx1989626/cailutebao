# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()   # 初始化数据库实例

# ==================== 用户模型 ====================
class User(UserMixin, db.Model):
    __tablename__ = 'users'   # 数据库表名
    id = db.Column(db.Integer, primary_key=True)   # 主键ID
    username = db.Column(db.String(18), unique=True, nullable=False, index=True)  # 身份证号码
    password_hash = db.Column(db.String(128), nullable=False)   # 密码哈希值
    name = db.Column(db.String(50), nullable=False)   # 用户真实姓名
    role = db.Column(db.String(20), default='member', nullable=False)   # 用户角色标识
    created_at = db.Column(db.DateTime, default=datetime.utcnow)   # 用户创建时间
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 创建者ID，关联到同一表的ID
    def set_password(self, password):  # 设置密码
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):   # 验证密码
        return check_password_hash(self.password_hash, password)
# ==================== 权限字典表 ====================
class Permission(db.Model):
    __tablename__ = 'permissions'   # 数据库表名
    id = db.Column(db.Integer, primary_key=True)   # 主键ID
    key = db.Column(db.String(100), unique=True, nullable=False)  # 权限唯一标识键
    module = db.Column(db.String(50), nullable=False)   # 权限所属模块名称
    action = db.Column(db.String(50), nullable=False)   # 权限对应的操作行为
    name = db.Column(db.String(100), nullable=False)  # 权限的中文名称
    description = db.Column(db.String(200))  # 权限的详细描述
    __table_args__ = (db.UniqueConstraint('module', 'action', name='uix_module_action'),)   # 表级约束：联合唯一索引
# ==================== 用户权限关联 ====================
class UserPermission(db.Model):
    __tablename__ = 'user_permissions'   # 数据库表名
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)  # 主键ID
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)   # 用户ID（外键）
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.id'), nullable=False)   # 权限ID（外键）
    __table_args__ = (db.UniqueConstraint('user_id', 'permission_id', name='uix_user_perm'),)  # 表级约束
# ==================== 任职周期模型 ====================
class EmploymentCycle(db.Model):
    __tablename__ = 'employment_cycles'   # 数据库表名
    id = db.Column(db.Integer, primary_key=True)   # 主键ID
    id_card = db.Column(db.String(18), nullable=False, index=True)   # 身份证号码
    name = db.Column(db.String(50), nullable=False)   # 姓名
    phone = db.Column(db.String(20))  # 联系电话
    gender = db.Column(db.String(2))  # 性别，男/女
    birthday = db.Column(db.Date)  # 出生日期
    hire_date = db.Column(db.Date, nullable=False)  # 入职日期
    departure_date = db.Column(db.Date)  # 离职日期
    status = db.Column(db.String(10), default='在职')  # 在职、离职
    photo_path = db.Column(db.String(200))  # 个人照片的存储路径（存储在 static/uploads 里的文件名）
    ethnic = db.Column(db.String(20))  # 民族
    politics = db.Column(db.String(20))  # 政治面貌
    education = db.Column(db.String(20))  # 学历
    household_province = db.Column(db.String(20)) # 省/直辖市
    household_city = db.Column(db.String(20)) # 市/市辖区
    household_district = db.Column(db.String(20)) # 区/县
    household_town = db.Column(db.String(50))   # 镇/街道
    household_village = db.Column(db.String(50)) # 村/居委
    household_detail = db.Column(db.String(255)) # 户籍详细地址
    residence_province = db.Column(db.String(20)) # 省/直辖市
    residence_city = db.Column(db.String(20)) # 市/市辖区
    residence_district = db.Column(db.String(20)) # 区/县
    residence_town = db.Column(db.String(50))    # 镇/街道
    residence_village = db.Column(db.String(50))  # 村/居委
    residence_detail = db.Column(db.String(255))  # 居住详细地址
    military_service = db.Column(db.Boolean, default=False)  # 是否服过兵役
    enlistment_date = db.Column(db.Date)  # 参军入伍日期
    unit_number = db.Column(db.String(50))  # 部队番号
    branch = db.Column(db.String(50))  # 部队军种
    discharge_date = db.Column(db.Date)  # 退伍日期
    has_license = db.Column(db.Boolean, default=False)  # 是否有驾驶证
    license_date = db.Column(db.Date)  # 驾驶证发证日期
    license_type = db.Column(db.String(20))  # 驾驶证类型（C1、C2等）
    license_expiry = db.Column(db.Date)  # 驾驶证到期日期
    has_security_license = db.Column(db.Boolean, default=False)  # 是否有保安证
    security_license_number = db.Column(db.String(50))  # 保安证编号
    security_license_date = db.Column(db.Date)  # 保安证发证日期
    salary_mode = db.Column(db.String(20)) # 薪资模式
    position = db.Column(db.String(20)) # 职位
    post = db.Column(db.String(20)) # 岗位
    emergency_name = db.Column(db.String(50)) # 紧急联系人姓名
    emergency_relation = db.Column(db.String(20)) # 紧急联系人关系
    emergency_phone = db.Column(db.String(20)) # 紧急联系人电话
    hat_size = db.Column(db.String(10)) # 帽围
    short_sleeve = db.Column(db.String(10)) # 短袖
    long_sleeve = db.Column(db.String(10))  # 长袖
    winter_uniform = db.Column(db.String(10))  # 冬装
    shoe_size = db.Column(db.String(10))  # 鞋子
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)  # 关联宿舍房间ID（外键）
    is_room_leader = db.Column(db.Boolean, default=False)  # 是否为该房宿舍长
    bed_number = db.Column(db.String(50))  # 床位号
    archives = db.Column(db.Text)  # 档案JSON字符串
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 档案创建时间
# ==================== 资产模型 ====================
class Asset(db.Model):
    __tablename__ = 'assets'   # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    type = db.Column(db.String(20), nullable=False)  # 资产类型
    name = db.Column(db.String(100), nullable=False)  # 资产名称
    number = db.Column(db.String(50), unique=True)  # 资产编号
    total_quantity = db.Column(db.Integer, default=0)  # 总数
    stock_quantity = db.Column(db.Integer, default=0)  # 库存
    allocated_quantity = db.Column(db.Integer, default=0)  # 已分配
    photo_path = db.Column(db.String(200))  # 资产照片
    purchase_date = db.Column(db.Date)  # 购买日期
    location = db.Column(db.String(100))   # 存放位置
    status = db.Column(db.String(20), default='库存')  #状态
    ownership = db.Column(db.String(20), default='特保队')  # 资产归属
    unit_price = db.Column(db.Float, default=0.0)  # 单价
    bed_capacity = db.Column(db.Integer, default=0) # 是不是床
    current_user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True) # 当前使用人ID
    current_user = db.relationship('EmploymentCycle', backref='assets')    # 建立与 EmploymentCycle 模型的关联关系
    allocation_mode = db.Column(db.String(20), default='personal')  # 分配模式
    department = db.Column(db.String(50))  # 所属部门
    created_at = db.Column(db.DateTime, default=datetime.utcnow) # 创建时间
    instances = db.relationship('AssetInstance', backref='asset_info', cascade="all, delete-orphan", lazy=True)  #子资产
# ==================== 子资产模型 ====================
class AssetInstance(db.Model):
    __tablename__ = 'asset_instances'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)  # 关联主资产ID（外键）
    sn_number = db.Column(db.String(100), unique=True, index=True)  # 资产编号
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)  # 关联宿舍房间ID（外键）
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True)  # 关联使用人ID（外键）
    status = db.Column(db.String(20), default='正常')  #状态
    last_check_date = db.Column(db.DateTime, default=datetime.now)  # 最后盘点日期
    current_room = db.relationship('Room', backref='room_assets')  # 建立与 Room 模型的关联关系
    current_holder = db.relationship('EmploymentCycle', backref='personal_assets')  # 建立与 EmploymentCycle 模型的关联关系
# ==================== 领用人 ====================
class AssetAllocation(db.Model):
    __tablename__ = 'asset_allocations'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)  # 关联资产ID（外键）
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)  # 关联领用人ID（外键）
    quantity = db.Column(db.Integer, default=1)  # 领用数量
    issue_date = db.Column(db.DateTime, nullable=False)  # 发放日期
    return_date = db.Column(db.DateTime)  # 归还日期
    note = db.Column(db.Text)  # 领用/归还备注
    asset = db.relationship('Asset', backref='allocations')  # 建立与 Asset 模型的关联关系
    user = db.relationship('EmploymentCycle')  # 建立与 EmploymentCycle 模型的关联关系
# ==================== 资产操作历史 ====================
class AssetHistory(db.Model):
    __tablename__ = 'asset_history'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'), nullable=False)  # 关联资产ID（外键）
    asset = db.relationship('Asset', backref='history')  # 建立与 Asset 模型的关联关系
    action = db.Column(db.String(20), nullable=False)  # 操作类型
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True)  # 被操作人ID（外键）
    user = db.relationship('EmploymentCycle', foreign_keys=[user_id])  # 建立与 EmploymentCycle 模型的关联关系
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 操作人ID（外键）
    operator = db.relationship('User', foreign_keys=[operator_id])  # 建立与 User 模型的关联关系
    quantity = db.Column(db.Integer, default=1)  # 操作数量
    action_date = db.Column(db.DateTime, default=datetime.now)  # 操作发生时间
    note = db.Column(db.Text)  # 操作备注
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 记录创建时间
# ==================== 资金模块 ====================
class FundsRecord(db.Model):
    __tablename__ = 'funds_records'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    date = db.Column(db.DateTime, nullable=False)  # 日期
    payer = db.Column(db.String(50))  # 资方
    item = db.Column(db.String(100))  # 项目
    amount = db.Column(db.Float, nullable=False)  # 金额
    note = db.Column(db.Text)  # 备注
    balance = db.Column(db.Float, nullable=False)  # 余额（自动计算）
    attachment = db.Column(db.JSON, default=[])  # 附件路径
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 操作人ID（外键）
    operator = db.relationship('User', foreign_keys=[operator_id])  # 建立与 User 模型的关联关系
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 记录创建时间
# ==================== 宿舍/房间模型 ====================
class Room(db.Model):
    __tablename__ = 'rooms'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)  # 房间编号
    type = db.Column(db.String(20))  # 房间名称
    area = db.Column(db.Float)  # 面积
    leader_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=True) # 宿舍长ID（外键）
    leader = db.relationship('EmploymentCycle', foreign_keys=[leader_id])  # 建立与 EmploymentCycle 模型的关联关系（宿舍长）
    x_pos = db.Column(db.Integer, default=0)  # 房间X坐标
    y_pos = db.Column(db.Integer, default=0)  # 房间Y坐标
    occupants = db.relationship('EmploymentCycle', backref='room', foreign_keys='EmploymentCycle.room_id') # 建立与 EmploymentCycle 模型的关联关系
# ==================== 审计日志（Audit Log） ====================
class OperationLog(db.Model):
    __tablename__ = 'operation_logs'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # 操作人
    action_type = db.Column(db.String(50))    # 操作类型
    target_type = db.Column(db.String(50))    # 目标对象
    target_id = db.Column(db.Integer)         # 目标对象的ID
    description = db.Column(db.Text)          # 详细描述
    ip_address = db.Column(db.String(50))     # 选填：记录操作IP，增强安全性
    created_at = db.Column(db.DateTime, default=datetime.now) # 自动记录时间
    operator = db.relationship('User', backref=db.backref('operation_logs', lazy=True))  # 关联操作人
# ==================== 考勤排班相关模型 ====================
class ShiftPost(db.Model):
    __tablename__ = 'shift_posts'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    name = db.Column(db.String(50), unique=True, nullable=False)  # 岗位名称
    color = db.Column(db.String(20), default='#007bff') # 标签颜色
    default_start = db.Column(db.String(10), default="08:30")  # 岗位默认开始时间
    default_end = db.Column(db.String(10), default="17:30")  # 岗位默认结束时间

class ShiftSchedule(db.Model):
    __tablename__ = 'shift_schedules'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    date = db.Column(db.Date, nullable=False, index=True)  # 排班日期
    employee_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)  # 关联员工ID（外键）
    post_id = db.Column(db.Integer, db.ForeignKey('shift_posts.id'))  # 关联排班岗位ID（外键）
    shift_type = db.Column(db.String(10))  # 班次类型
    is_overtime = db.Column(db.Boolean, default=False)  # 是否加班
    hours = db.Column(db.Float, default=12.0)  # 排班时长
    start_time = db.Column(db.String(5), default="08:00")  # 班次实际开始时间
    end_time = db.Column(db.String(5), default="20:00")  # 班次实际结束时间
    is_duty_leader = db.Column(db.Boolean, default=False) # 是否值班领导
    is_duty_chief = db.Column(db.Boolean, default=False)  # 是否值班长
    employee = db.relationship('EmploymentCycle', backref='schedules')  # 建立与 EmploymentCycle 模型的关联关系
    post = db.relationship('ShiftPost', backref='schedules')  # 建立与 ShiftPost 模型的关联关系

class ShiftTemplate(db.Model):
    __tablename__ = 'shift_templates'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    name = db.Column(db.String(100), nullable=False)  # 模板名称
    data = db.Column(db.JSON) # 存储排班规则的 JSON 数据
# ==================== 通知相关模型 ====================
class Notification(db.Model):
    __tablename__ = 'notifications'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # 接收通知的用户ID（外键）
    title = db.Column(db.String(100), nullable=False)  # 通知标题
    content = db.Column(db.Text, nullable=False)  # 通知内容
    is_read = db.Column(db.Boolean, default=False)  # 是否已读
    related_type = db.Column(db.String(50))  # 关联业务类型
    related_id = db.Column(db.Integer)  # 关联业务ID
    created_at = db.Column(db.DateTime, default=datetime.now)  # 通知创建时间
    user = db.relationship('User', backref='notifications')  # 建立与 User 模型的关联关系
# ==================== 出差管理模型 ====================
trip_participants = db.Table('trip_participants',
    db.Column('trip_id', db.Integer, db.ForeignKey('business_trips.id'), primary_key=True),
    db.Column('employee_id', db.Integer, db.ForeignKey('employment_cycles.id'), primary_key=True)
)  #出差参与人员关联表（多对多）
class BusinessTrip(db.Model):
    __tablename__ = 'business_trips'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    destination = db.Column(db.String(100), nullable=False)  # 出差目的地
    start_date = db.Column(db.Date, nullable=False)  # 出差开始日期
    end_date = db.Column(db.Date, nullable=True)  # 出差结束日期
    total_days = db.Column(db.Integer)  # 出差总天数
    status = db.Column(db.String(20), default='进行中')  # 出差状态
    participants = db.relationship('EmploymentCycle',secondary=trip_participants,backref=db.backref('trips', lazy='dynamic'))  # 建立与 EmploymentCycle 模型的多对多关联
# ==================== 请假管理模型 ====================
class LeaveRecord(db.Model):
    __tablename__ = 'leave_records'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    user_id = db.Column(db.Integer, db.ForeignKey('employment_cycles.id'), nullable=False)  # 请假员工ID（外键）
    user = db.relationship('EmploymentCycle', backref='leaves')  # 建立与 EmploymentCycle 模型的关联关系
    leave_type = db.Column(db.String(20), nullable=False)  # 请假类型
    reason = db.Column(db.Text)                            # 请假事由
    start_date = db.Column(db.Date, nullable=False)        # 开始时间
    end_date = db.Column(db.Date)                          # 预计结束时间
    actual_end_date = db.Column(db.Date)                   # 实际销假时间
    total_days = db.Column(db.Float)                       # 请假天数
    status = db.Column(db.String(20), default='请假中')    # 状态
    attachments = db.Column(db.JSON, default=[])          # 附件
    created_at = db.Column(db.DateTime, default=datetime.now)  # 请假记录创建时间
    is_reported = db.Column(db.Boolean, default=False, comment='是否上报：False=未上报，True=已上报')  # 布尔类型，默认未上报
# ==================== 聊天模型 ====================
class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'  # 数据库表名
    id = db.Column(db.Integer, primary_key=True)  # 主键ID
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # 发送人ID（外键）
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # 接收人ID（外键） 为空代表群聊
    content = db.Column(db.Text, nullable=False) # 消息内容
    timestamp = db.Column(db.DateTime, default=datetime.now) # 消息发送时间戳
    is_group = db.Column(db.Boolean, default=False) # 是否为群聊消息
    sender = db.relationship('User', foreign_keys=[sender_id]) # 建立与 User 模型的关联关系（发送人）