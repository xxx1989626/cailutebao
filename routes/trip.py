# routes/trip.py
from flask import Blueprint, render_template, request, redirect, url_for, flash,make_response
from flask_login import login_required, current_user
from models import db, BusinessTrip, EmploymentCycle
from utils import perm
from datetime import datetime, timedelta
from sqlalchemy import extract
from sqlalchemy.orm import joinedload
from io import BytesIO
import pandas as pd

trip_bp = Blueprint('trip', __name__, url_prefix='/trip')

# ==================== 出差列表 ====================
@trip_bp.route('/list')
@login_required
@perm.require('trip.view')
def trip_list():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    selected_year = request.args.get('year', datetime.now().year, type=int)
    
    # 1. 获取年份列表
    all_dates = db.session.query(BusinessTrip.start_date).all()
    years = sorted(list(set(d[0].year for d in all_dates if d[0])), reverse=True) if all_dates else [datetime.now().year]

    # 2. 分页查询
    pagination = BusinessTrip.query.filter(
        extract('year', BusinessTrip.start_date) == selected_year
    ).order_by(BusinessTrip.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    trips = pagination.items

    # 3. 统计逻辑：计算该年份内每人的出差频次 + 总天数（核心修改）
    user_trip_stats = {}
    
    # 获取该年份内所有出差记录（为了统计所有人的总数，不分页查询）
    yearly_trips = BusinessTrip.query.filter(
        extract('year', BusinessTrip.start_date) == selected_year
    ).all()

    for trip in yearly_trips:
        for emp in trip.participants:
            if emp.id not in user_trip_stats:
                user_trip_stats[emp.id] = {
                    'name': emp.name,
                    'count': 0,
                    'total_days': 0,  # 新增：统计总天数
                    'last_end_date': None
                }
            
            current_stats = user_trip_stats[emp.id]
            
            # 原有逻辑：统计去重后的出差频次
            if current_stats['last_end_date'] is None or trip.start_date > (current_stats['last_end_date'] + timedelta(days=1)):
                current_stats['count'] += 1
            
            # 新增逻辑：统计该条出差记录的天数并累加
            if trip.total_days:
                # 优先使用数据库中已计算的total_days
                current_stats['total_days'] += trip.total_days
            elif trip.start_date and trip.end_date:
                # 无total_days时，手动计算（结束日-开始日+1天，包含起止日）
                days = (trip.end_date - trip.start_date).days + 1
                current_stats['total_days'] += days
            else:
                # 未结束的出差（end_date为空），计算到当前日期
                days = (datetime.now().date() - trip.start_date).days + 1
                current_stats['total_days'] += days
            
            # 更新最晚结束日期（原有逻辑保留）
            if trip.end_date:
                if current_stats['last_end_date'] is None or trip.end_date > current_stats['last_end_date']:
                    current_stats['last_end_date'] = trip.end_date

    # 按频次从高到低排序
    sorted_stats = dict(sorted(user_trip_stats.items(), key=lambda x: x[1]['count'], reverse=True))

    return render_template(
        'trip/list.html', 
        trips=trips, 
        years=years, 
        selected_year=selected_year,
        pagination=pagination,
        user_trip_stats=sorted_stats  # 包含count和total_days
    )

# ==================== 新增出差 ====================
@trip_bp.route('/add', methods=['GET', 'POST'])
@login_required
@perm.require('trip.add')
def trip_add():
    from utils import log_action  # 局部导入工具函数
    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date') # 可能是空字符串 ''
        
        # 开始日期通常是必填的
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # 初始化变量
        end_date = None
        total_days = None
        status = '出差中'

        # 核心修复：只有 end_date_str 有值时才解析
        if end_date_str and end_date_str.strip(): 
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            # 计算天数（包含当天）
            total_days = (end_date - start_date).days + 1
            status = '已归队'

        new_trip = BusinessTrip(
            destination=request.form.get('destination'),
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            status=status
        )
        
        # 绑定人员
        participant_ids = request.form.getlist('user_ids')
        if participant_ids:
            new_trip.participants = EmploymentCycle.query.filter(EmploymentCycle.id.in_(participant_ids)).all()
        
        # 【新增：提取人员姓名字符串】
        # 遍历参与者对象，将姓名用顿号连接
        names = "、".join([p.name for p in new_trip.participants]) if new_trip.participants else "未指定人员"

        db.session.add(new_trip)
        db.session.flush()  # 【新增：刷新 Session 以生成 new_trip.id 供审计记录使用】
        
        # ========== 关键修复1：遍历所有参与者，改用 user_id 参数 ==========
        if participant_ids:
            # 遍历每个参与者ID，确保每个人都能收到通知
            for cycle_id in participant_ids:
                log_action(
                    action_type='出差登记',
                    target_type='BusinessTrip',
                    target_id=new_trip.id,
                    description=f"登记了人员出差：{names}，目的地：{new_trip.destination}，出发时间：{start_date}",
                    user_id=cycle_id  # 改用 user_id 参数，和请假模块保持一致
                )
        else:
            # 无参与者时的兜底日志
            log_action(
                action_type='出差登记',
                target_type='BusinessTrip',
                target_id=new_trip.id,
                description=f"登记了无指定人员的出差，目的地：{new_trip.destination}，出发时间：{start_date}"
            )
        
        db.session.commit()
        flash('登记成功', 'success')
        return redirect(url_for('trip.trip_list'))
    
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    return render_template('trip/add.html', employees=employees)

# ==================== 编辑出差 ====================
@trip_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@perm.require('trip.edit')
def trip_edit(id):
    from utils import log_action  # 局部导入
    trip = db.session.query(BusinessTrip).get_or_404(id)
    
    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        
        trip.destination = request.form.get('destination')
        trip.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # 记录操作前的状态，用于判断是普通编辑还是“确认归队”
        old_status = trip.status

        # 核心逻辑：处理归队日期和状态
        if end_date_str and end_date_str.strip():
            trip.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            trip.total_days = (trip.end_date - trip.start_date).days + 1
            trip.status = '已归队'
        else:
            trip.end_date = None
            trip.total_days = None
            trip.status = '出差中'
            
        participant_ids = request.form.getlist('user_ids')
        if participant_ids:
            trip.participants = EmploymentCycle.query.filter(EmploymentCycle.id.in_(participant_ids)).all()
            
        # --- 审计与通知逻辑开始 ---
        # 1. 提取参与人姓名字符串
        names = "、".join([p.name for p in trip.participants]) if trip.participants else "未指定人员"
        
        # 2. 确定动作类型
        action_type = '出差信息修改'
        if old_status == '出差中' and trip.status == '已归队':
            action_type = '出差归队确认'
        
        # ========== 关键修复2：遍历所有参与者，改用 user_id 参数，移除无效循环 ==========
        if participant_ids:
            # 遍历每个参与者ID，确保每个人都能收到通知
            for cycle_id in participant_ids:
                log_action(
                    action_type=action_type,
                    target_type='BusinessTrip',
                    target_id=trip.id,
                    description=f"{names} 的出差记录已更新。目的地：{trip.destination}，当前状态：{trip.status}",
                    user_id=cycle_id  # 改用 user_id 参数
                )
        else:
            # 无参与者时的兜底日志
            log_action(
                action_type=action_type,
                target_type='BusinessTrip',
                target_id=trip.id,
                description=f"未指定人员的出差记录已更新，当前状态：{trip.status}"
            )
        # --- 审计与通知逻辑结束 ---

        db.session.commit()
        flash('修改成功', 'success')
        return redirect(url_for('trip.trip_list'))
    
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    current_ids = [p.id for p in trip.participants]
    return render_template('trip/edit.html', trip=trip, employees=employees, current_ids=current_ids)

# ==================== 删除出差 ====================
@trip_bp.route('/delete/<int:id>')
@login_required
@perm.require('trip.delete')
def trip_delete(id):
    trip = BusinessTrip.query.get_or_404(id)
    db.session.delete(trip)
    db.session.commit()
    flash('记录已删除', 'warning')
    return redirect(url_for('trip.trip_list'))

# ==================== 导出出差 ====================
@trip_bp.route('/export_report')
@login_required
def export_trip_report():
    year = request.args.get('year', datetime.now().year, type=int)
    
    # 1. 获取数据
    trips = BusinessTrip.query.filter(
        db.extract('year', BusinessTrip.start_date) == year
    ).order_by(BusinessTrip.id.desc()).all()
    
    # 2. 构造数据列表
    data = []
    for index, t in enumerate(trips):
        data.append({
            "出差次数": f"第{len(trips) - index}次",
            "出差人员": "、".join([p.name for p in t.participants]),
            "目的地": t.destination,
            "开始日期": t.start_date,
            "归队日期": t.end_date or "执行中",
            "天数": t.total_days or "--",
            "状态": t.status
        })
    
    # 3. 使用 Pandas 转换为 Excel
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='出差记录')
    
    output.seek(0)
    
    # 4. 生成响应对象
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=Business_Trips_{year}.xlsx'
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    return response

# 出差模块权限定义
TRIP_PERMISSIONS = [
    ('view', '查看出差', '查看所有出差记录'),
    ('add', '登记出差', '新增出差申请'),
    ('edit', '编辑出差记录', '编辑出差记录'),
    ('delete', '删除记录', '删除出差历史'),
]