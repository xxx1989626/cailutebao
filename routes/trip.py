# routes/trip.py
from flask import Blueprint, render_template, request, redirect, url_for, flash,make_response
from flask_login import login_required, current_user
from models import db, BusinessTrip, EmploymentCycle
from utils import perm
from datetime import datetime
from sqlalchemy.orm import joinedload
from io import BytesIO
import pandas as pd

trip_bp = Blueprint('trip', __name__, url_prefix='/trip')

# ==================== 出差列表 ====================
@trip_bp.route('/list')
@login_required
@perm.require('trip.view')
def trip_list():
    # 获取用户选择的年份，默认为当前年
    selected_year = request.args.get('year', datetime.now().year, type=int)
    
    # 1. 获取所有存在记录的年份，用于前端下拉菜单
    all_dates = db.session.query(BusinessTrip.start_date).all()
    years = sorted(list(set(d[0].year for d in all_dates if d[0])), reverse=True)

    # 2. 按照选定年份筛选，并保持“最新大序号在顶”的倒序排列
    trips = BusinessTrip.query.filter(
        db.extract('year', BusinessTrip.start_date) == selected_year
    ).order_by(BusinessTrip.id.desc()).all()

    return render_template('trip/list.html', 
                           trips=trips, 
                           years=years, 
                           selected_year=selected_year)

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
            reason=request.form.get('reason'),
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
        
        log_action(
            action_type='出差登记',
            target_type='BusinessTrip',
            target_id=new_trip.id,
            description=f"登记了人员出差：{names}，目的地：{new_trip.destination}，出发时间：{start_date}",
            cycle_id=participant_ids[0] if participant_ids else None
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
    trip = BusinessTrip.query.get_or_404(id)
    
    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        
        trip.destination = request.form.get('destination')
        trip.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        trip.reason = request.form.get('reason')
        
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
        
        # 3. 循环为每个参与人发送通知并记录审计
        # 因为你的 log_action 内部逻辑是按单人识别的，为了让每个当事人都收到通知，这里循环调用
        for p in trip.participants:
            log_action(
                action_type=action_type,
                target_type='BusinessTrip',
                target_id=trip.id,
                description=f"{names} 的出差记录已更新。目的地：{trip.destination}，当前状态：{trip.status}",
                cycle_id=participant_ids[0] if participant_ids else None
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