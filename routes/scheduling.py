# D:\cailu\cailutebao\routes\scheduling.py
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import login_required
from models import db, EmploymentCycle, ShiftPost, ShiftSchedule, BusinessTrip, LeaveRecord
from utils import perm
from datetime import datetime, date, timedelta
import pandas as pd
import io
import re
from sqlalchemy import case

scheduling_bp = Blueprint('scheduling', __name__, url_prefix='/scheduling')

# 权限定义
SCHEDULING_PERMISSIONS = [
    ('view', '查看排班', '查看全员排班表'),
    ('edit', '管理排班', '拖拽排班、保存排班数据'),
    ('post', '岗位管理', '增删改查排班岗位')
]
# --- 路由 1：重构后的排班主页 ---
@scheduling_bp.route('/list')
@login_required
def schedule_list():
    if not perm.can('scheduling.view'):
        flash("权限不足", "danger")
        return redirect(url_for('main.index'))
    
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    posts = ShiftPost.query.all()
    today = date.today()
    
    # Get selected year and month from request args, with defaults to current date
    selected_year = request.args.get('year', today.year, type=int)
    selected_month = request.args.get('month', today.month, type=int)
    
    
    # Calculate start and end dates for the selected month
    from calendar import monthrange
    _, last_day = monthrange(selected_year, selected_month)
    month_start = date(selected_year, selected_month, 1)
    month_end = date(selected_year, selected_month, last_day)
    
    # Fetch all trips that overlap with the selected month
    trips = BusinessTrip.query.filter(
        db.or_(
            db.and_(BusinessTrip.start_date >= month_start, BusinessTrip.start_date <= month_end),
            db.and_(BusinessTrip.end_date >= month_start, BusinessTrip.end_date <= month_end),
            db.and_(BusinessTrip.start_date <= month_start, db.or_(BusinessTrip.end_date >= month_end, BusinessTrip.end_date == None))
        )
    ).all()
    
    # Generate trip dates in the format "user_id-date" for each day of the trip within the selected month
    on_trip_dates = set()
    for trip in trips:
        start_date = max(trip.start_date, month_start)
        end_date = min(trip.end_date or today, month_end)
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            for p in trip.participants:
                on_trip_dates.add(f"{p.id}-{date_str}")
            current_date += timedelta(days=1)

    # Fetch all leaves that overlap with the selected month
    leaves = LeaveRecord.query.filter(
        db.or_(
            db.and_(LeaveRecord.start_date >= month_start, LeaveRecord.start_date <= month_end),
            db.and_(LeaveRecord.end_date >= month_start, LeaveRecord.end_date <= month_end),
            db.and_(LeaveRecord.start_date <= month_start, db.or_(LeaveRecord.end_date >= month_end, LeaveRecord.end_date == None))
        )
    ).all()
    
    # Generate leave dates in the format "user_id-date" for each day of the leave within the selected month
    on_leave_dates = set()
    for leave in leaves:
        start_date = max(leave.start_date, month_start)
        end_date = min(leave.end_date or today, month_end)
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            on_leave_dates.add(f"{leave.user_id}-{date_str}")
            current_date += timedelta(days=1)

    return render_template('scheduling/list.html', 
                           employees=employees, 
                           posts=posts, 
                           on_trip_dates=list(on_trip_dates),
                           on_leave_dates=list(on_leave_dates),
                           selected_year=selected_year,
                           selected_month=selected_month)

# --- 核心：Excel 矩阵数据接口 (已实现四级自定义排序) ---
@scheduling_bp.route('/api/get_matrix_data')
@login_required
def get_matrix_data():
    month_str = request.args.get('month', datetime.now().strftime("%Y-%m"))
    
    # 1. 定义前三级优先级权重 (数值越小越靠前)
    # 第一优先级：薪资模式
    SALARY_MAP = {"220元/天制": 1, "200元/天制": 2, "月工时制": 3}
    # 第二优先级：岗位层级
    POSITION_MAP = {"队长": 1, "副队长": 2, "领班": 3, "队员": 4}
    # 第三优先级：班组 (对应数据库中的 post 字段)
    GROUP_MAP = {"机动": 1, "监控": 2, "窗口": 3, "外口": 4}

    # 2. 基础数据查询
    employees_query = EmploymentCycle.query.filter_by(status='在职').all()

    # 3. 执行四级排序逻辑
    def sort_key(emp):
        """
        排序逻辑：
        p1: 薪资模式权重
        p2: 职位权重
        p3: 班组权重
        p4: 数据库ID (作为同条件下的固定唯一顺序)
        """
        p1 = SALARY_MAP.get(emp.salary_mode, 99)
        p2 = POSITION_MAP.get(emp.position, 99)
        # 注意：这里假设你的模型中班组字段名为 post，如果实际是 group 或其他请对应修改
        p3 = GROUP_MAP.get(emp.post, 99)
        p4 = emp.id  # 同条件下，按入职先后(ID大小)固定死，不随刷新变动
        
        return (p1, p2, p3, p4)

    # 应用排序
    employees = sorted(employees_query, key=sort_key)
    
    # 4. 岗位信息缓存 (包含默认工时)
    posts = {p.id: {'name': p.name, 'color': p.color, 'default_hours': p.default_hours} for p in ShiftPost.query.all()}
    
    # 5. 获取当月排班
    schedules = ShiftSchedule.query.filter(ShiftSchedule.date.like(f"{month_str}%")).all()
    sched_map = {(s.employee_id, s.date.day): s for s in schedules}
    
    # 6. 计算月份的开始和结束日期
    from calendar import monthrange
    year, month = map(int, month_str.split('-'))
    _, last_day = monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)
    today = date.today()
    
    # 7. 获取当月的出差记录
    trips = BusinessTrip.query.filter(
        db.or_(
            db.and_(BusinessTrip.start_date >= month_start, BusinessTrip.start_date <= month_end),
            db.and_(BusinessTrip.end_date >= month_start, BusinessTrip.end_date <= month_end),
            db.and_(BusinessTrip.start_date <= month_start, db.or_(BusinessTrip.end_date >= month_end, BusinessTrip.end_date == None))
        )
    ).all()
    
    # 8. 生成出差日期集合
    on_trip_dates = set()
    for trip in trips:
        start_date = max(trip.start_date, month_start)
        end_date = min(trip.end_date or today, month_end)
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            for p in trip.participants:
                on_trip_dates.add(f"{p.id}-{date_str}")
            current_date += timedelta(days=1)
    
    # 9. 获取当月的请假记录
    leaves = LeaveRecord.query.filter(
        db.or_(
            db.and_(LeaveRecord.start_date >= month_start, LeaveRecord.start_date <= month_end),
            db.and_(LeaveRecord.end_date >= month_start, LeaveRecord.end_date <= month_end),
            db.and_(LeaveRecord.start_date <= month_start, db.or_(LeaveRecord.end_date >= month_end, LeaveRecord.end_date == None))
        )
    ).all()
    
    # 10. 生成请假日期集合
    on_leave_dates = set()
    for leave in leaves:
        start_date = max(leave.start_date, month_start)
        end_date = min(leave.end_date or today, month_end)
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            on_leave_dates.add(f"{leave.user_id}-{date_str}")
            current_date += timedelta(days=1)
    
    matrix = []
    for emp in employees:
        emp_data = {
            'id': emp.id,
            'name': emp.name,
            'position': emp.position or '队员',
            'shifts': {}
        }
        
        for day in range(1, last_day + 1):
            s = sched_map.get((emp.id, day))
            if s:
                p_info = posts.get(s.post_id, {'name': '未知', 'color': '#ccc', 'default_hours': 12.0})
                emp_data['shifts'][day] = {
                    'id': s.id,
                    'post_id': s.post_id,
                    'post_name': p_info['name'],
                    'type': s.shift_type,
                    'hours': s.hours,
                    'default_hours': p_info['default_hours'],
                    'color': p_info['color']
                }
            else:
                emp_data['shifts'][day] = None
        matrix.append(emp_data)

    return jsonify({
        'matrix': matrix,
        'posts': posts,
        'month': month_str,
        'on_trip_dates': list(on_trip_dates),
        'on_leave_dates': list(on_leave_dates)
    })
# --- 其余函数保持原样 ---
@scheduling_bp.route('/save_shift', methods=['POST'])
@login_required
def save_shift():
    if not perm.can('scheduling.edit'):
        return jsonify({'success': False, 'message': '无权操作'})
    data = request.json
    try:
        date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
        shift = ShiftSchedule.query.filter_by(employee_id=int(data['user_id']), date=date_obj).first()
        if not shift:
            shift = ShiftSchedule(employee_id=int(data['user_id']), date=date_obj)
        post = ShiftPost.query.get(int(data.get('post_id')))
        default_hours = post.default_hours if post else 12.0
        shift.post_id = int(data.get('post_id'))
        shift.shift_type = data.get('shift_type', '白')
        shift.is_overtime = data.get('is_overtime', False)
        shift.hours = None
        db.session.add(shift)
        db.session.commit()
        return jsonify({'success': True, 'shift_id': shift.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@scheduling_bp.route('/api/delete_shift_by_date', methods=['POST'])
@login_required
def delete_shift_by_date():
    if not perm.can('scheduling.edit'):
        return jsonify({'success': False, 'message': '无权操作'})
    data = request.json
    try:
        date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
        ShiftSchedule.query.filter_by(employee_id=int(data['user_id']), date=date_obj).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})
    
@scheduling_bp.route('/api/delete_overtime_by_date', methods=['POST'])
@login_required
def delete_overtime_by_date():
    if not perm.can('scheduling.edit'):
        return jsonify({'success': False, 'message': '无权操作'})
    data = request.json
    try:
        date_obj = datetime.strptime(data['date'], '%Y-%m-%d').date()
        ShiftSchedule.query.filter_by(employee_id=int(data['user_id']), date=date_obj, is_overtime=True).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@scheduling_bp.route('/api/get_shifts')
@login_required
def get_shifts():
    schedules = ShiftSchedule.query.all()
    events = []
    for s in schedules:
        emp = EmploymentCycle.query.get(s.employee_id)
        post = ShiftPost.query.get(s.post_id)
        if emp and post:
            events.append({
                'id': s.id,
                'title': f"{emp.name}-{'夜' if s.shift_type=='夜' else post.name}",
                'start': s.date.isoformat(),
                'color': '#333' if s.shift_type == '夜' else post.color,
                'extendedProps': { 'empId': s.employee_id, 'postId': s.post_id, 'shiftId': s.id }
            })
    return jsonify(events)

@scheduling_bp.route('/api/delete_shift/<int:id>', methods=['POST'])
@login_required
def delete_shift(id):
    if not perm.can('scheduling.edit'):
        return jsonify({'success': False, 'message': '无权操作'})
    shift = ShiftSchedule.query.get_or_404(id)
    try:
        db.session.delete(shift)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@scheduling_bp.route('/export/<string:table_type>')
@login_required
def export_attendance(table_type):
    target_month = request.args.get('month', datetime.now().strftime("%Y-%m"))
    if table_type == 'A':
        emps = EmploymentCycle.query.filter_by(salary_mode='月工时制').all()
    else:
        emps = EmploymentCycle.query.filter(EmploymentCycle.salary_mode != '月工时制').all()
    data_list = []
    for emp in emps:
        shifts = ShiftSchedule.query.filter(ShiftSchedule.employee_id == emp.id, ShiftSchedule.date.like(f"{target_month}%")).all()
        if not shifts: continue 
        actual_h = sum(s.hours for s in shifts)
        night_count = sum(1 for s in shifts if s.shift_type == '夜')
        if table_type == 'A':
            final_h = max(174.0, actual_h) 
            data_list.append({"姓名": emp.name, "身份证": emp.id_card, "实际工时": actual_h, "结算工时(保底174)": final_h, "超额加班": max(0, actual_h - 174)})
        else:
            data_list.append({"姓名": emp.name, "身份证": emp.id_card, "夜班次": night_count, "夜补金额": night_count*15})
    if not data_list:
        flash(f"{target_month} 暂无有效数据", "warning")
        return redirect(url_for('scheduling.schedule_list'))
    df = pd.DataFrame(data_list)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name=f"{table_type}表_{target_month}.xlsx", as_attachment=True)

@scheduling_bp.route('/data/import', methods=['POST'])
@login_required
def import_schedule_data():
    file = request.files.get('file')
    if not file: return jsonify({'success': False, 'message': '未选择文件'})
    try:
        df = pd.read_excel(file, sheet_name=0, header=None)
        raw_headers = df.iloc[0].fillna("").astype(str).tolist()
        clean_headers = [re.sub(r'[\(（].*?[\)）]', '', h).strip() for h in raw_headers]
        post_map = {p.name.strip(): p for p in ShiftPost.query.all()}
        success_count, missing_names = 0, set()
        for index, row in df.iloc[1:].iterrows():
            date_val = row[0]
            if pd.isna(date_val) or str(date_val).strip() == "": continue
            try: current_date = pd.to_datetime(str(date_val)).date()
            except: continue
            for col_idx in range(1, len(row)):
                emp_name = str(row[col_idx]).strip()
                if not emp_name or emp_name.lower() == 'nan' or "休息" in emp_name: continue
                post_name = clean_headers[col_idx]
                target_post = post_map.get(post_name) or next((p_obj for p_name, p_obj in post_map.items() if p_name in post_name or post_name in p_name), None)
                if not target_post: continue
                emp = EmploymentCycle.query.filter_by(name=emp_name, status='在职').first()
                if emp:
                    s_type = '夜' if '夜' in post_name else '白'
                    if not ShiftSchedule.query.filter_by(
                        employee_id=emp.id, 
                        date=current_date, 
                        post_id=target_post.id).first():
                        db.session.add(ShiftSchedule(
                            employee_id=emp.id, 
                            date=current_date, 
                            post_id=target_post.id, 
                            shift_type=s_type, 
                            hours=None))
                        success_count += 1
                else: missing_names.add(emp_name)
        db.session.commit()
        res_msg = f"成功导入 {success_count} 条记录。"
        if missing_names: res_msg += f" 未在系统找到员工：{', '.join(list(missing_names)[:5])}"
        return jsonify({'success': True, 'message': res_msg})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'导入出错: {str(e)}'})
    
@scheduling_bp.route('/clear_month', methods=['POST'])
@login_required
def clear_month():
    year_month = request.json.get('month', datetime.now().strftime("%Y-%m"))
    try:
        num_deleted = ShiftSchedule.query.filter(ShiftSchedule.date.like(f"{year_month}%")).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({'success': True, 'message': f'已成功清空 {year_month} 的 {num_deleted} 条排班记录'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'清空失败: {str(e)}'})

@scheduling_bp.route('/api/daily_duty')
def get_daily_duty():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    def get_duty_by_date(target_date):
        try:
            priority_case = case((ShiftPost.name == '值班领导', 1), (ShiftPost.name == '值班长', 2), (ShiftPost.name == '备勤领班', 3),(ShiftPost.name == '机动-白班', 4),(ShiftPost.name == '机动-夜班', 5),else_=6)
            shifts = db.session.query(ShiftSchedule, EmploymentCycle, ShiftPost).join(EmploymentCycle, ShiftSchedule.employee_id == EmploymentCycle.id).join(ShiftPost, ShiftSchedule.post_id == ShiftPost.id).filter(ShiftSchedule.date == target_date).order_by(priority_case, ShiftPost.id).all()
            return [{"name": emp.name, "post": post.name, "phone": getattr(emp, 'phone', '-') or '-', "type": s.shift_type} for s, emp, post in shifts]
        except: return []
    try: return jsonify({"today": get_duty_by_date(today), "tomorrow": get_duty_by_date(tomorrow), "status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@scheduling_bp.route('/save_overtime', methods=['POST'])
@login_required
def save_overtime():
    if not perm.can('scheduling.edit'):
        return jsonify({'success': False, 'message': '无权操作'})
    
    data = request.json
    user_id = int(data['user_id'])
    date_str = data.get('date')  
    hours = data.get('hours')

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()  

        # 查询当天该员工的排班
        shift = ShiftSchedule.query.filter_by(employee_id=user_id, date=date_obj).first()
        
        if hours in (None, '', 'null'):
            # 清空加班
            if shift:
                shift.hours = None
        else:
            # 保存加班
            hours_val = float(hours)
            if not shift:
                # 没有排班 → 直接创建一条记录存加班
                shift = ShiftSchedule(
                    employee_id=user_id,
                    date=date_obj,
                    hours=hours_val
                )
                db.session.add(shift)
            else:
                shift.hours = hours_val

        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})