# routes/scheduling.py 
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import login_required
from models import db, EmploymentCycle, ShiftPost, ShiftSchedule
from utils import perm
from datetime import datetime
import pandas as pd
import io
import re
from models import BusinessTrip, LeaveRecord

scheduling_bp = Blueprint('scheduling', __name__, url_prefix='/scheduling')

# 权限定义
SCHEDULING_PERMISSIONS = [
    ('view', '查看排班', '查看全员排班表'),
    ('edit', '管理排班', '拖拽排班、保存排班数据'),
    ('post', '岗位管理', '增删改查排班岗位')
]

# --- 路由 1：纯粹的排班日历主页 ---
@scheduling_bp.route('/list')
@login_required
def schedule_list():
    if not perm.can('scheduling.view'):
        flash("权限不足", "danger")
        return redirect(url_for('main.index'))
    
    # 现在的逻辑很纯粹：只管排班需要的数据
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    posts = ShiftPost.query.all()
    today = datetime.now().date()
    
    # 获取出差人员
    active_trips = BusinessTrip.query.filter(
        BusinessTrip.status == '出差中',
        ((BusinessTrip.end_date >= today) | (BusinessTrip.end_date == None))
    ).all()
    on_trip_ids = {p.id for trip in active_trips for p in trip.participants}

    # 获取请假人员
    active_leaves = LeaveRecord.query.filter(
        LeaveRecord.status == '请假中',
        LeaveRecord.start_date <= today, LeaveRecord.end_date >= today
    ).all()
    on_leave_ids = {leave.user_id for leave in active_leaves}

    return render_template('scheduling/list.html', 
                           employees=employees, 
                           posts=posts, 
                           on_trip_ids=on_trip_ids,
                           on_leave_ids=on_leave_ids)


# --- 功能：为 FullCalendar 插件提供排班数据接口 ---
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
                'color': '#ffc107' if s.shift_type == '夜' else post.color,
                'extendedProps': {
                    'empId': s.employee_id,
                    'postId': s.post_id,
                    'shiftId': s.id 
                }
            })
    return jsonify(events)

# --- 功能：保存或更新单个排班记录 ---
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
        
        shift.post_id = int(data.get('post_id'))
        shift.shift_type = data.get('shift_type', '白')
        shift.is_overtime = data.get('is_overtime', False)
        shift.hours = 12.0 
        db.session.add(shift)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

# --- 功能：删除指定的排班记录 ---
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


# --- 功能：导出考勤统计表（支持 A/B 表及 174 小时保底） ---
@scheduling_bp.route('/export/<string:table_type>')
@login_required
def export_attendance(table_type):
    target_month = datetime.now().strftime("%Y-%m") 
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
            data_list.append({
                "姓名": emp.name, 
                "身份证": emp.id_card, 
                "实际工时": actual_h,
                "结算工时(保底174)": final_h, 
                "超额加班": max(0, actual_h - 174)
            })
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

# --- 功能核心：直接从复杂 Excel 排班表批量导入数据 ---
@scheduling_bp.route('/data/import', methods=['POST'])
@login_required
def import_schedule_data():
    file = request.files.get('file')
    if not file: return jsonify({'success': False, 'message': '未选择文件'})
    
    try:
        # 1. 直接读取 Sheet1
        df = pd.read_excel(file, sheet_name=0, header=None)
        
        # 2. 获取第一行作为岗位名称，并进行清洗（去掉括号及以后的时间说明）
        # 例如将 "守台-白班 (8:00-20:00)" 简化为 "守台-白班"
        raw_headers = df.iloc[0].fillna("").astype(str).tolist()
        clean_headers = []
        for h in raw_headers:
            # 使用正则去掉括号里的内容和多余空格
            clean_name = re.sub(r'[\(（].*?[\)）]', '', h).strip()
            clean_headers.append(clean_name)
            
        # 预加载数据库岗位，建立 名字 -> 对象 的映射
        post_map = {p.name.strip(): p for p in ShiftPost.query.all()}
        
        success_count = 0
        missing_names = set()

        # 3. 从第二行（Index 1）开始遍历日期和人名
        for index, row in df.iloc[1:].iterrows():
            # 处理日期列 (第 0 列)
            date_val = row[0]
            if pd.isna(date_val) or str(date_val).strip() == "": continue
            
            try:
                # 自动解析日期
                current_date = pd.to_datetime(str(date_val)).date()
            except: continue

            # 4. 遍历每一列人名 (从第 1 列开始)
            for col_idx in range(1, len(row)):
                emp_name = str(row[col_idx]).strip()
                
                # 排除空单元格、nan 和 休息
                if not emp_name or emp_name.lower() == 'nan' or "休息" in emp_name:
                    continue
                
                # 获取该列对应的岗位名称
                post_name = clean_headers[col_idx]
                target_post = post_map.get(post_name)
                
                if not target_post:
                    # 如果岗位名没对上，尝试模糊匹配（只要网页岗位名包含在表头里即可）
                    for p_name, p_obj in post_map.items():
                        if p_name in post_name or post_name in p_name:
                            target_post = p_obj
                            break
                
                if not target_post: continue

                # 5. 匹配员工 (确保名字完全一致)
                emp = EmploymentCycle.query.filter_by(name=emp_name).first()
                if emp:
                    # 识别班次类型（夜班标记）
                    s_type = '夜' if '夜' in post_name else '白'
                    
                    # 检查是否已存在
                    exists = ShiftSchedule.query.filter_by(
                        employee_id=emp.id, 
                        date=current_date, 
                        post_id=target_post.id
                    ).first()
                    
                    if not exists:
                        new_s = ShiftSchedule(
                            employee_id=emp.id, 
                            date=current_date, 
                            post_id=target_post.id,
                            shift_type=s_type,
                            hours=12.0 # 默认 12 小时，可根据需要调整
                        )
                        db.session.add(new_s)
                        success_count += 1
                else:
                    missing_names.add(emp_name)

        db.session.commit()
        
        res_msg = f"成功导入 {success_count} 条记录。"
        if missing_names:
            res_msg += f" 未在系统找到员工：{', '.join(list(missing_names)[:5])}"
            
        return jsonify({'success': True, 'message': res_msg})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'导入出错: {str(e)}'})
    
# --- 功能后端增加清空接口    
@scheduling_bp.route('/clear_month', methods=['POST'])
@login_required
def clear_month():
    # 获取要清空的年月，默认为 2026-01
    year_month = request.json.get('month', '2026-01')
    try:
        # 匹配该月的所有排班
        start_date = f"{year_month}-01"
        # 简单粗暴删除该月所有排班（如果你想更安全，可以按日期范围删除）
        num_deleted = ShiftSchedule.query.filter(
            ShiftSchedule.date.like(f"{year_month}%")
        ).delete(synchronize_session=False)
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'已成功清空 {year_month} 的 {num_deleted} 条排班记录'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'清空失败: {str(e)}'})

# --- 功能：查询今日及明日的值班人员列表（用于大屏或通知） ---
@scheduling_bp.route('/api/daily_duty')
def get_daily_duty():
    from datetime import date, timedelta
    from sqlalchemy import case
    from models import ShiftSchedule, EmploymentCycle, ShiftPost, db

    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    def get_duty_by_date(target_date):
        try:
            priority_case = case((ShiftPost.name == '值班领导', 1), (ShiftPost.name == '值班长', 2), (ShiftPost.name == '备勤领班', 3),(ShiftPost.name == '机动-白班', 4),(ShiftPost.name == '机动-夜班', 5),else_=6)
            shifts = db.session.query(ShiftSchedule, EmploymentCycle, ShiftPost)\
                .join(EmploymentCycle, ShiftSchedule.employee_id == EmploymentCycle.id)\
                .join(ShiftPost, ShiftSchedule.post_id == ShiftPost.id)\
                .filter(ShiftSchedule.date == target_date)\
                .order_by(priority_case, ShiftPost.id).all()
            
            return [{
                "name": emp.name,
                "post": post.name,
                "phone": getattr(emp, 'phone', '-') or '-',
                "type": s.shift_type
            } for s, emp, post in shifts]
        except Exception as e:
            return []

    try:
        return jsonify({
            "today": get_duty_by_date(today),
            "tomorrow": get_duty_by_date(tomorrow),
            "status": "success"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500