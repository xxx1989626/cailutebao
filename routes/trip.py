#D:\cailu\cailutebao\routes\trip.py
from flask import Blueprint, render_template, request, redirect, url_for, flash,make_response
from flask_login import login_required, current_user
from models import db, BusinessTrip, EmploymentCycle, TripParticipant
from sqlalchemy.orm import selectinload
from utils import perm, parse_date
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

    # 2. 分页查询（预加载逐人归队链接，避免 N+1）
    pagination = BusinessTrip.query.filter(
        extract('year', BusinessTrip.start_date) == selected_year
    ).order_by(BusinessTrip.id.desc())\
     .options(selectinload(BusinessTrip.participant_links))\
     .paginate(page=page, per_page=per_page, error_out=False)
    trips = pagination.items

    # 逐人归队信息：{trip_id: {employee_id: {end_date, status, total_days, emp_name}}}
    per_trip_participants = {}
    for t in trips:
        per_trip_participants[t.id] = {}
        for link in t.participant_links:
            emp_name = link.employee.name if link.employee else ''
            per_trip_participants[t.id][link.employee_id] = {
                'end_date': link.end_date.isoformat() if link.end_date else '',
                'status': link.status or '出差中',
                'total_days': link.total_days if link.total_days else 0,
                'emp_name': emp_name
            }

    # 3. 统计逻辑：按「逐人归队日期」计算频次 + 总天数（支持同次出差不同人不同归队日）
    user_trip_stats = {}

    # 获取该年份内所有出差记录（不分页，用于年度计数、序号连续、统计）
    yearly_trips = BusinessTrip.query.filter(
        extract('year', BusinessTrip.start_date) == selected_year
    ).options(
        selectinload(BusinessTrip.participant_links),
        selectinload(BusinessTrip.participants)
    ).all()
    yearly_total = len(yearly_trips)

    # 构造 id -> 年度序号 映射（按 id 降序，最大 id 为年度第 N 次）
    trips_sorted_by_id_desc = sorted(yearly_trips, key=lambda t: -t.id)
    trip_id_to_idx = {t.id: yearly_total - i for i, t in enumerate(trips_sorted_by_id_desc)}

    # 把 (trip, employee_id, 归队日期, 天数) 展开为列表，按「该人的 start_date」升序后再判断频次
    per_person_events = []
    for trip in yearly_trips:
        # 快速构造员工查询
        for link in trip.participant_links:
            # 如果关联对象没预加载 employee，兜底查一次
            emp_name = link.employee.name if link.employee else ''
            # 归队日期优先逐人，然后回退主记录
            end = link.end_date if link.end_date is not None else trip.end_date
            days = link.total_days
            if days is None:
                if end is not None:
                    days = (end - trip.start_date).days + 1
                else:
                    days = (datetime.now().date() - trip.start_date).days + 1
            per_person_events.append({
                'emp_id': link.employee_id,
                'emp_name': emp_name,
                'start_date': trip.start_date,
                'end_date': end,
                'days': days,
            })

    # 按 start_date 升序，按人分桶计算 count（去重频次）与总天数
    per_person_events.sort(key=lambda e: (e['start_date'] or date.min, e['emp_id']))
    last_end_per_person = {}
    for ev in per_person_events:
        uid = ev['emp_id']
        if uid not in user_trip_stats:
            user_trip_stats[uid] = {
                'name': ev['emp_name'],
                'count': 0,
                'total_days': 0,
                'last_end_date': None,
            }
        st = user_trip_stats[uid]
        if ev['emp_name'] and not st['name']:
            st['name'] = ev['emp_name']
        # 逐人判断连续/新出差：start > 上次此人 last_end + 1 则算新的一次
        if st['last_end_date'] is None or (
            ev['start_date'] is not None and ev['start_date'] > st['last_end_date'] + timedelta(days=1)
        ):
            st['count'] += 1
        st['total_days'] += ev['days'] or 0
        # 更新该人的 last_end（逐人维度）
        if ev['end_date'] and (st['last_end_date'] is None or ev['end_date'] > st['last_end_date']):
            st['last_end_date'] = ev['end_date']

    # 按频次从高到低排序
    sorted_stats = dict(sorted(user_trip_stats.items(), key=lambda x: x[1]['count'], reverse=True))

    return render_template(
        'trip/list.html',
        trips=trips,
        years=years,
        selected_year=selected_year,
        pagination=pagination,
        user_trip_stats=sorted_stats,         # 包含count和total_days
        trip_id_to_idx=trip_id_to_idx,       # 年度连续序号映射
        yearly_total=yearly_total,           # 当前年度总出差次数
        per_trip_participants=per_trip_participants  # 逐人归队详情
    )

# ==================== 新增出差 ====================
@trip_bp.route('/add', methods=['GET', 'POST'])
@login_required
@perm.require('trip.add')
def trip_add():
    from utils import log_action  # 局部导入工具函数
    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')  # 整批默认归队日期，可空

        # 开始日期通常是必填的
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

        # 初始化变量（主记录字段做"整批默认值/聚合展示"用）
        batch_end_date = None
        batch_total_days = None
        batch_status = '出差中'
        if end_date_str and end_date_str.strip():
            batch_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            batch_total_days = (batch_end_date - start_date).days + 1
            batch_status = '已归队'

        # 绑定人员
        participant_ids = request.form.getlist('user_ids')
        employees_map = {}
        if participant_ids:
            for emp in EmploymentCycle.query.filter(EmploymentCycle.id.in_(participant_ids)).all():
                employees_map[emp.id] = emp

        new_trip = BusinessTrip(
            destination=request.form.get('destination'),
            start_date=start_date,
            end_date=batch_end_date,
            total_days=batch_total_days,
            status=batch_status
        )

        # 为每个参与人创建 TripParticipant 关联对象，写入逐人归队日期/状态
        for pid in participant_ids:
            emp = employees_map.get(int(pid))
            if not emp:
                continue
            link = TripParticipant()
            link.employee = emp
            if batch_end_date is not None:
                link.end_date = batch_end_date
                link.status = '已归队'
                link.total_days = batch_total_days
            else:
                link.status = '出差中'
            new_trip.participant_links.append(link)

        # 提取姓名用于通知
        names = "、".join([employees_map[int(p)].name for p in participant_ids if int(p) in employees_map]) or "未指定人员"

        db.session.add(new_trip)
        db.session.flush()  # 生成 new_trip.id 供审计记录使用

        # 遍历所有参与者，确保每个人都能收到通知
        if participant_ids:
            for cycle_id in participant_ids:
                log_action(
                    action_type='出差登记',
                    target_type='BusinessTrip',
                    target_id=new_trip.id,
                    description=f"登记了人员出差：{names}，目的地：{new_trip.destination}，出发时间：{start_date}",
                    user_id=int(cycle_id)
                )
        else:
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
    trip = db.session.query(BusinessTrip)\
        .options(selectinload(BusinessTrip.participant_links)).get_or_404(id)

    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        # 整批默认归队日期：当且仅当某些人未逐人指定日期时作为回退
        batch_end_date_str = request.form.get('end_date') or ''

        trip.destination = request.form.get('destination')
        trip.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

        # 解析整批默认 end_date / total_days / status（聚合展示用）
        if batch_end_date_str.strip():
            batch_end_date = datetime.strptime(batch_end_date_str, '%Y-%m-%d').date()
            trip.end_date = batch_end_date
            trip.total_days = (batch_end_date - trip.start_date).days + 1
        else:
            batch_end_date = None
            trip.end_date = None
            trip.total_days = None

        # 人员集合
        participant_ids = [int(x) for x in request.form.getlist('user_ids')]
        emp_objs = EmploymentCycle.query.filter(EmploymentCycle.id.in_(participant_ids)).all() if participant_ids else []
        emp_map = {e.id: e for e in emp_objs}

        # ==== 按人归队日期解析：表单字段格式 = end_date_{employee_id} ====
        # 用于日志：记录哪些人是新归队的
        new_return_ids = []
        # 构造现有链接 map，便于快速查找
        existing_links = {(link.employee_id, link.trip_id): link for link in trip.participant_links}

        # 主记录聚合状态：只要有一人未归队，整行显示"部分归队"；全部未归则"出差中"；全部已归则"已归队"
        returned_count = 0
        total_expected = len(participant_ids) if participant_ids else len(trip.participant_links)

        # 先构建新参与人集合下的所有 link
        kept_pids = set()
        for pid in participant_ids:
            if pid not in emp_map:
                continue
            kept_pids.add(pid)
            key = (pid, trip.id)
            link = existing_links.get(key)
            if link is None:
                link = TripParticipant(trip_id=trip.id, employee_id=pid)
                link.status = '出差中'
                db.session.add(link)
                trip.participant_links.append(link)

            # 逐人归队日期：优先看个人表单字段；否则回退到整批默认
            per_end_str = request.form.get(f'end_date_{pid}') or ''
            was_not_returned = (link.end_date is None)

            if per_end_str.strip():
                link.end_date = datetime.strptime(per_end_str, '%Y-%m-%d').date()
            elif batch_end_date is not None and link.end_date is None:
                # 整批填充到之前尚未归队的人
                link.end_date = batch_end_date

            if link.end_date is not None:
                link.total_days = (link.end_date - trip.start_date).days + 1
                link.status = '已归队'
                returned_count += 1
                if was_not_returned:
                    new_return_ids.append(pid)
            else:
                link.total_days = None
                link.status = '出差中'

        # 删除不再属于本次参与人的 link
        for key, link in list(existing_links.items()):
            if key[0] not in kept_pids:
                trip.participant_links.remove(link)
                db.session.delete(link)

        # 聚合主记录状态
        if total_expected > 0:
            if returned_count == 0:
                trip.status = '出差中'
            elif returned_count < total_expected:
                trip.status = '部分归队'
            else:
                trip.status = '已归队'
        # end_date 不主动置 None：保留整批默认值便于展示

        # --- 审计与通知 ---
        names = "、".join([emp_map[p].name for p in participant_ids if p in emp_map]) or "未指定人员"

        if new_return_ids:
            action_type = '出差归队确认'
            returned_names = "、".join([emp_map[p].name for p in new_return_ids if p in emp_map])
            desc = f"{returned_names} 已归队；当前参与人：{names}。目的地：{trip.destination}，整批状态：{trip.status}"
        else:
            action_type = '出差信息修改'
            desc = f"{names} 的出差记录已更新。目的地：{trip.destination}，当前状态：{trip.status}"

        for cycle_id in participant_ids:
            log_action(
                action_type=action_type,
                target_type='BusinessTrip',
                target_id=trip.id,
                description=desc,
                user_id=cycle_id
            )
        if not participant_ids:
            log_action(
                action_type=action_type,
                target_type='BusinessTrip',
                target_id=trip.id,
                description=f"无参与人的出差记录已更新，目的地：{trip.destination}，状态：{trip.status}"
            )
        # --- 审计结束 ---

        db.session.commit()
        flash('修改成功', 'success')
        return redirect(url_for('trip.trip_list'))

    employees = EmploymentCycle.query.filter(EmploymentCycle.status.in_(['在职', '离职'])).all()
    current_ids = [p.id for p in trip.participants]
    # 逐人当前 end_date 映射，给模板渲染用
    per_end_dates = {}
    per_status = {}
    per_days = {}
    for link in trip.participant_links:
        per_end_dates[link.employee_id] = link.end_date.isoformat() if link.end_date else ''
        per_status[link.employee_id] = link.status or '出差中'
        per_days[link.employee_id] = link.total_days if link.total_days else 0
    return render_template(
        'trip/edit.html',
        trip=trip,
        employees=employees,
        current_ids=current_ids,
        per_end_dates=per_end_dates,
        per_status=per_status,
        per_days=per_days
    )

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

    # 1. 获取数据 + 预加载逐人归队链接
    trips = BusinessTrip.query.filter(
        db.extract('year', BusinessTrip.start_date) == year
    ).options(
        selectinload(BusinessTrip.participant_links),
        selectinload(BusinessTrip.participants)
    ).order_by(BusinessTrip.id.desc()).all()
    trips_total = len(trips)

    # 2. 构造逐人展开的数据列表（一行一个人，方便不同人不同归队日期）
    data = []
    for index, t in enumerate(trips):
        trip_idx = f"第{trips_total - index}次"
        # 先把主记录逐人归队映射做好，加速
        per = {}
        for link in t.participant_links:
            per[link.employee_id] = link
        if not t.participants:
            data.append({
                "出差次数": trip_idx,
                "出差人员": "（未指定）",
                "目的地": t.destination,
                "开始日期": t.start_date,
                "归队日期": t.end_date or "",
                "逐人天数": "",
                "整批状态": t.status,
            })
            continue
        for p in t.participants:
            link = per.get(p.id)
            if link and link.end_date is not None:
                p_end = link.end_date
                p_days = link.total_days if link.total_days else (link.end_date - t.start_date).days + 1
                p_status = link.status or '已归队'
            else:
                p_end = ""
                p_days = ""
                p_status = '出差中'
            data.append({
                "出差次数": trip_idx,
                "出差人员": p.name,
                "目的地": t.destination,
                "开始日期": t.start_date,
                "归队日期": p_end,
                "逐人天数": p_days,
                "整批状态": t.status,
                "个人状态": p_status,
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
    ('import', '导入出差', '批量导入出差记录'),
]

# ==================== 导入出差记录 ====================
# 模板下载
@trip_bp.route('/import_template')
@login_required
@perm.require('trip.import')
def trip_import_template():
    """下载导入模板（逐人展开格式，同一出差次数的多人写多行，出差次数相同则视为同一次出差）"""
    data = [
        {
            "出差次数": "第1次",
            "出差人员": "张三",
            "目的地": "示例地点",
            "开始日期": "2026-01-15",
            "归队日期": "2026-01-17",
            "个人状态": "已归队"
        },
        {
            "出差次数": "第1次",
            "出差人员": "李四",
            "目的地": "示例地点",
            "开始日期": "2026-01-15",
            "归队日期": "2026-01-19",
            "个人状态": "已归队"
        },
        {
            "出差次数": "第2次",
            "出差人员": "王五",
            "目的地": "另一地点",
            "开始日期": "2026-02-01",
            "归队日期": "",
            "个人状态": "出差中"
        },
    ]
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='出差记录导入模板')
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=Business_Trip_Import_Template.xlsx'
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return response

# 导入处理
@trip_bp.route('/import', methods=['GET', 'POST'])
@login_required
@perm.require('trip.import')
def trip_import():
    from utils import log_action
    if request.method == 'POST':
        # 校验文件
        if 'file' not in request.files:
            flash('未选择文件', 'danger')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('未选择文件', 'danger')
            return redirect(request.url)

        if not file.filename.endswith('.xlsx'):
            flash('仅支持 .xlsx 格式', 'danger')
            return redirect(request.url)

        try:
            df = pd.read_excel(file)
        except Exception as e:
            flash(f'文件解析失败: {e}', 'danger')
            return redirect(request.url)

        # 必填列校验：两种格式兼容
        #   格式A（老格式）: 一行=一次出差，多人用顿号/逗号连接在【出差人员】列
        #   格式B（新格式逐人展开）: 同一【出差次数】值的多行视为同一出差，可分别填归队日期
        required = ['出差人员', '目的地', '开始日期']
        missing = [c for c in required if c not in df.columns]
        if missing:
            flash(f'缺少必填列: {", ".join(missing)}', 'danger')
            return redirect(request.url)

        # 预加载员工
        all_emps = EmploymentCycle.query.filter(EmploymentCycle.status.in_(['在职', '离职'])).all()
        name_to_emp = {}
        for emp in all_emps:
            if emp.name not in name_to_emp:
                name_to_emp[emp.name] = emp

        # 预加载已有记录用于去重
        existing_keys = set()
        all_trips = BusinessTrip.query.options(
            selectinload(BusinessTrip.participant_links),
            selectinload(BusinessTrip.participants)
        ).all()
        for t in all_trips:
            p_names = sorted([p.name for p in t.participants])
            # 用 (目的地, 开始日期, 人员集合) 作为幂等 key（忽略归队日期，因为逐人不同）
            key = (t.destination, str(t.start_date), '|'.join(p_names))
            existing_keys.add(key)

        success = 0
        skipped = 0
        errors = []
        import re

        # ===== 步骤1: 聚合出差次数分组 =====
        # group_key -> 包含成员列表、共用的目的地/开始日期
        groups = {}  # group_key -> dict(rows, destination, start_date)
        group_order = []
        has_trip_idx_col = '出差次数' in df.columns

        for idx, row in df.iterrows():
            # 目的地
            destination = str(row['目的地']).strip()
            if not destination or destination.lower() in ('nan', 'none'):
                errors.append(f"行{idx+2}: 目的地为空，跳过")
                continue
            # 开始日期
            start_date = parse_date(row['开始日期'])
            if not start_date:
                errors.append(f"行{idx+2}: 开始日期无效 ({row['开始日期']})，跳过")
                continue

            # 归队日期（逐人）
            end_date_raw = row.get('归队日期')
            end_date = parse_date(end_date_raw) if end_date_raw is not None and not pd.isna(end_date_raw) else None
            if end_date:
                per_days = (end_date - start_date).days + 1
                per_status = '已归队'
            else:
                per_days = None
                per_status = '出差中'

            # 出差人员（兼容老格式顿号分隔，和新格式逐人单行单名）
            names_str = str(row['出差人员']).strip()
            # 过滤 NaT/NaN/nan 等空值占位符（pandas 读取空单元格或合并单元格时产生）
            if not names_str or names_str.lower() in ('nat', 'nan', 'none', ''):
                errors.append(f"行{idx+2}: 出差人员为空，跳过")
                continue
            name_list = [n.strip() for n in re.split(r'[、,，\s]+', names_str)
                         if n.strip() and n.strip().lower() not in ('nat', 'nan', 'none')]
            if not name_list:
                errors.append(f"行{idx+2}: 出差人员为空，跳过")
                continue

            # 确定分组 key
            if has_trip_idx_col:
                idx_raw = str(row.get('出差次数', '')).strip()
                # 如果 出差次数 有效，则以 (出差次数值, 目的地, 开始日期) 作为分组
                if idx_raw and idx_raw.lower() not in ('nan', 'none', ''):
                    gkey = ('trip_' + idx_raw, destination, str(start_date))
                else:
                    gkey = ('row_' + str(idx), destination, str(start_date))
            else:
                # 老格式：按行作为独立出差
                gkey = ('row_' + str(idx), destination, str(start_date))

            if gkey not in groups:
                groups[gkey] = {
                    'destination': destination,
                    'start_date': start_date,
                    'rows': []
                }
                group_order.append(gkey)

            for n in name_list:
                emp = name_to_emp.get(n)
                groups[gkey]['rows'].append({
                    'excel_row': idx + 2,
                    'name': n,
                    'employee': emp,
                    'per_end': end_date,
                    'per_days': per_days,
                    'per_status': per_status,
                })

        # ===== 步骤2: 按分组创建出差记录 =====
        for gkey in group_order:
            g = groups[gkey]
            destination = g['destination']
            start_date = g['start_date']
            rows = g['rows']
            participants = []
            per_map = {}  # employee_id -> (end_date, days, status)
            unmatched_here = []
            excel_rows_here = set()
            for r in rows:
                excel_rows_here.add(r['excel_row'])
                if r['employee']:
                    participants.append(r['employee'])
                    # 同一人出现在同一出差里取归队日期最晚的
                    prev = per_map.get(r['employee'].id)
                    if prev is None:
                        per_map[r['employee'].id] = (r['per_end'], r['per_days'], r['per_status'])
                    elif r['per_end'] is not None and (prev[0] is None or r['per_end'] > prev[0]):
                        per_map[r['employee'].id] = (r['per_end'], r['per_days'], r['per_status'])
                else:
                    unmatched_here.append(r['name'])

            if unmatched_here:
                errors.append(f"行{sorted(excel_rows_here)}: 未匹配到人员 [{', '.join(unmatched_here)}]")

            # 整组无任何匹配人员时跳过（不再二次报错，避免与上面 unmatched 重复）
            if not participants:
                continue

            # 去重：(目的地, 开始日期, 人员集合)
            p_names_sorted = sorted([p.name for p in participants])
            dedup_key = (destination, str(start_date), '|'.join(p_names_sorted))
            if dedup_key in existing_keys:
                skipped += 1
                errors.append(
                    f"行{sorted(excel_rows_here)}: 重复记录已跳过（{'、'.join(p_names_sorted)} {start_date} {destination}）"
                )
                continue
            existing_keys.add(dedup_key)

            # 整批默认值：取逐人最新的归队日期
            batch_end = None
            returned_count = 0
            for pid, (per_end, _, _) in per_map.items():
                if per_end is not None:
                    returned_count += 1
                    if batch_end is None or per_end > batch_end:
                        batch_end = per_end
            if batch_end:
                batch_total = (batch_end - start_date).days + 1
            else:
                batch_total = None

            total_expected = len(per_map)
            if returned_count == 0:
                batch_status = '出差中'
            elif returned_count < total_expected:
                batch_status = '部分归队'
            else:
                batch_status = '已归队'

            new_trip = BusinessTrip(
                destination=destination,
                start_date=start_date,
                end_date=batch_end,
                total_days=batch_total,
                status=batch_status
            )
            # 构造逐人关联对象
            for emp in participants:
                end_p, days_p, status_p = per_map[emp.id]
                link = TripParticipant()
                link.employee = emp
                link.end_date = end_p
                link.status = status_p
                link.total_days = days_p
                new_trip.participant_links.append(link)
            db.session.add(new_trip)
            db.session.flush()

            success += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'提交数据库失败: {e}', 'danger')
            return redirect(request.url)

        if errors or skipped > 0:
            msg_parts = [f'导入完成: 成功 {success} 条']
            if skipped:
                msg_parts.append(f'跳过重复 {skipped} 条')
            if errors:
                msg_parts.append(f'失败/提示 {len(errors)} 条')
            detail = '；'.join(msg_parts)
            if errors:
                detail += f'。{"；".join(errors[:5])}'
            flash(detail, 'warning' if errors else 'info')
        else:
            flash(f'导入成功 {success} 条记录', 'success')
        return redirect(url_for('trip.trip_list'))

    return render_template('trip/import.html')