from flask import render_template, request, redirect, url_for, flash,json
from flask_login import login_required, current_user
from sqlalchemy import or_
from datetime import datetime

from . import hr_bp
from models import EmploymentCycle, User, db
from utils import (
    validate_id_card, validate_phone, get_gender_from_id_card, get_birthday_from_id_card,
    save_uploaded_file, get_ethnic_options, get_politics_options, get_education_options,
    parse_date, format_date, today_str, perm, log_action
)
from config import SALARY_MODES, POSITIONS, POSTS

# ==================== 花名册列表 ====================
@hr_bp.route('/list')
@login_required
def hr_list():
    if not perm.can('hr.view'):
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))
    
    status_filter = request.args.get('status', '在职')
    if status_filter not in ['待审核', '在职', '离职']:
        status_filter = '在职'
    
    pending_count = EmploymentCycle.query.filter_by(status='待审核').count()
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'hire_date_desc')
    
    # 排序规则
    valid_sorts = {
        'name_asc': EmploymentCycle.name.asc(),
        'name_desc': EmploymentCycle.name.desc(),
        'id_card_asc': EmploymentCycle.id_card.asc(),
        'id_card_desc': EmploymentCycle.id_card.desc(),
        'phone_asc': EmploymentCycle.phone.asc(),
        'phone_desc': EmploymentCycle.phone.desc(),
        'hire_date_asc': EmploymentCycle.hire_date.asc(),
        'hire_date_desc': EmploymentCycle.hire_date.desc(),
        'position_asc': EmploymentCycle.position.asc(),
        'position_desc': EmploymentCycle.position.desc(),
        'post_asc': EmploymentCycle.post.asc(),
        'post_desc': EmploymentCycle.post.desc(),
        'salary_mode_asc': EmploymentCycle.salary_mode.asc(),
        'salary_mode_desc': EmploymentCycle.salary_mode.desc()
    }
    order = valid_sorts.get(sort, EmploymentCycle.hire_date.desc())
    
    # 子查询：获取每个身份证最新的入职记录
    subquery = db.session.query(
        EmploymentCycle.id_card,
        db.func.max(EmploymentCycle.hire_date).label('max_hire_date')
    ).group_by(EmploymentCycle.id_card).subquery()
    
    query = EmploymentCycle.query.join(
        subquery,
        db.and_(
            EmploymentCycle.id_card == subquery.c.id_card,
            EmploymentCycle.hire_date == subquery.c.max_hire_date
        )
    )
    
    # 状态过滤
    if status_filter == '待审核':
        query = query.filter(EmploymentCycle.status == '待审核')
    elif status_filter == '离职':
        query = query.filter(EmploymentCycle.status == '离职')
    else:
        query = query.filter(EmploymentCycle.status == '在职')
    
    # 搜索过滤
    if search:
        query = query.filter(
            or_(
                EmploymentCycle.name.ilike(f'%{search}%'),
                EmploymentCycle.id_card.ilike(f'%{search}%'),
                EmploymentCycle.phone.ilike(f'%{search}%')
            )
        )
    
    # 显示字段
    show_fields = request.args.getlist('show')
    if not show_fields:
        show_fields = [
            'name', 'id_card', 'phone', 'position', 'post', 'salary_mode', 
            'hire_date', 'tenure', 'gender', 'birthday', 'ethnic', 'politics', 
            'education', 'household_address', 'residence_address', 'military', 
            'license', 'security_license', 'emergency', 'uniform'
        ]
    
    employees = query.order_by(order).all()
    return render_template('hr/list.html',
                           employees=employees,
                           search=search,
                           status_filter=status_filter,
                           sort=sort,
                           show_fields=show_fields,
                           pending_count=pending_count)

# ==================== 新增员工 ====================
@hr_bp.route('/add', methods=['GET', 'POST'])
@login_required
@perm.require('hr.add')
def hr_add():
    if request.method == 'POST':
        id_card = request.form['id_card'].strip()
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        
        # 必填项校验
        if not all([name, id_card, phone]):
            flash('姓名、身份证、手机为必填项', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        # 身份证校验
        if not validate_id_card(id_card):
            flash('身份证号码无效', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        # 手机号校验
        if not validate_phone(phone):
            flash('手机号码格式错误', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        # 重复入职校验
        if EmploymentCycle.query.filter_by(id_card=id_card, status='在职').first():
            flash('该身份证当前在职，不能重复入职', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        # 从身份证提取信息
        gender = get_gender_from_id_card(id_card)
        birthday = get_birthday_from_id_card(id_card)
        
        # 处理头像上传
        photo_path = None
        if 'photo' in request.files and request.files['photo'].filename:
            photo_path = save_uploaded_file(request.files.get('photo'), module='avatar')
        
        # 收集其他证书
        other_certs = []
        i = 0
        while f'cert_name_{i}' in request.form:
            cert_name = request.form.get(f'cert_name_{i}')
            cert_number = request.form.get(f'cert_number_{i}')
            cert_date = request.form.get(f'cert_date_{i}')
            if cert_name and cert_number and cert_date:
                other_certs.append({'name': cert_name, 'number': cert_number, 'date': cert_date})
            i += 1
        
        # 处理档案JSON
        archives = None
        if other_certs:
            archives = json.dumps({'other_certificates': other_certs}, ensure_ascii=False)
        
        # 创建入职记录
        cycle = EmploymentCycle(
            id_card=id_card,
            name=name,
            phone=phone,
            gender=gender,
            birthday=birthday,
            hire_date=parse_date(request.form.get('hire_date')) or datetime.today().date(),
            status='在职',
            photo_path=photo_path,
            ethnic=request.form.get('ethnic'),
            politics=request.form.get('politics'),
            education=request.form.get('education'),
            household_province=request.form.get('household_province'),
            household_city=request.form.get('household_city'),
            household_district=request.form.get('household_district'),
            household_town=request.form.get('household_town'),
            household_village=request.form.get('household_village'),
            household_detail=request.form.get('household_detail'),
            residence_province=request.form.get('residence_province'),
            residence_city=request.form.get('residence_city'),
            residence_district=request.form.get('residence_district'),
            residence_town=request.form.get('residence_town'),
            residence_village=request.form.get('residence_village'),
            residence_detail=request.form.get('residence_detail'),
            military_service='military_service' in request.form,
            enlistment_date=parse_date(request.form.get('enlistment_date')),
            unit_number=request.form.get('unit_number'),
            branch=request.form.get('branch'),
            discharge_date=parse_date(request.form.get('discharge_date')),
            has_license='has_license' in request.form,
            license_date=parse_date(request.form.get('license_date')),
            license_type=request.form.get('license_type'),
            license_expiry=parse_date(request.form.get('license_expiry')),
            security_license_number=request.form.get('security_license_number'),
            security_license_date=parse_date(request.form.get('security_license_date')),
            salary_mode=request.form['salary_mode'],
            emergency_name=request.form.get('emergency_name'),
            emergency_relation=request.form.get('emergency_relation'),
            emergency_phone=request.form.get('emergency_phone'),
            position=request.form['position'],
            post=request.form['post'],
            hat_size=request.form.get('hat_size'),
            short_sleeve=request.form.get('short_sleeve'),
            long_sleeve=request.form.get('long_sleeve'),
            winter_uniform=request.form.get('winter_uniform'),
            shoe_size=request.form.get('shoe_size'),
            archives=archives
        )
        
        db.session.add(cycle)
        db.session.flush()  # 预生成 cycle.id
        
        # 自动创建账号
        user_created_msg = ''
        if not User.query.filter_by(username=id_card).first():
            default_password = id_card[-6:]
            new_user = User(
                username=id_card,
                name=name,
                role='member'
            )
            new_user.set_password(default_password)
            db.session.add(new_user)
            user_created_msg = '（账号已自动创建）'
        
        # 记录审计日志
        log_action(
            action_type='人员入职',
            target_type='Employee',
            target_id=cycle.id,
            description=f"办理了队员入职：{name} (身份证:{id_card})，职位：{cycle.position}-{cycle.post}{user_created_msg}",
            **locals()
        )
        
        db.session.commit()
        flash(f'{name} 入职成功！', 'success')
        if user_created_msg:
            flash(f'账号自动创建成功！用户名：{id_card}，初始密码：{default_password}（请及时修改）', 'info')
        
        return redirect(url_for('hr.hr_detail', id_card=id_card))
    
    # GET请求返回表单页面
    return render_template('hr/add.html',
                           ethnic_options=get_ethnic_options(),
                           politics_options=get_politics_options(),
                           education_options=get_education_options(),
                           salary_modes=SALARY_MODES,
                           positions=POSITIONS,
                           posts=POSTS)

# ==================== 详情页 ====================
@hr_bp.route('/detail/<id_card>')
@login_required
def hr_detail(id_card):
    # 权限校验
    if id_card != current_user.username and not perm.can('hr.view'):
        flash('权限不足，您只能查看自己的信息', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))
    
    # 查询该身份证的所有入职记录
    cycles = EmploymentCycle.query.filter_by(id_card=id_card).order_by(EmploymentCycle.hire_date.desc()).all()
    if not cycles:
        flash('未找到该身份证记录', 'warning')
        return redirect(url_for('hr.hr_list'))
    
    # 获取当前在职周期
    current_cycle = next((c for c in cycles if c.status == '在职'), None)
    associated_user = User.query.filter_by(username=current_cycle.id_card).first() if current_cycle else None

    # 获取可发放的资产列表
    available_assets = []
    if current_cycle:
        from models import Asset
        available_assets = Asset.query.filter(
            Asset.type.in_(['装备', '服饰']),
            Asset.stock_quantity > 0
        ).all()
    
    return render_template('hr/detail.html',
                           cycles=cycles,
                           current_cycle=current_cycle,
                           id_card=id_card,
                           available_assets=available_assets,
                           associated_user=associated_user,
                           positions=POSITIONS, 
                           posts=POSTS,
                           salary_modes=SALARY_MODES,
                           ethnic_options=get_ethnic_options(),
                           politics_options=get_politics_options(),
                           education_options=get_education_options())

# ==================== 编辑当前在职周期 ====================
@hr_bp.route('/edit/<int:cycle_id>', methods=['GET', 'POST'])
@login_required
@perm.require('hr.edit')
def edit_cycle(cycle_id):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    
    # 仅允许编辑在职周期
    if cycle.status != '在职':
        flash('仅在职周期可编辑', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    if request.method == 'POST':
        # 字段映射（用于日志显示中文）
        field_map = {
            'name': '姓名', 'phone': '手机号', 'ethnic': '民族', 'politics': '政治面貌',
            'education': '学历', 'position': '职位', 'post': '岗位', 'salary_mode': '工资模式',
            'hire_date': '入职日期', 'household_province': '户籍省', 'household_city': '户籍市',
            'household_district': '户籍区', 'household_town': '户籍镇', 'household_village': '户籍村','household_detail': '户籍详址',
            'residence_province': '居住省', 'residence_city': '居住市', 'residence_district': '居住区',
            'residence_town': '居住镇', 'residence_village': '居住村', 'residence_detail': '居住详址', 'military_service': '服役经历',
            'enlistment_date': '入伍日期', 'unit_number': '部队代号', 'branch': '兵种',
            'discharge_date': '退伍日期', 'has_license': '驾照', 'license_date': '领证日期',
            'license_type': '驾照类型', 'license_expiry': '驾照到期', 'security_license_number': '保安证号',
            'security_license_date': '保安证日期', 'emergency_name': '紧急联系人',
            'emergency_relation': '联系人关系', 'emergency_phone': '联系人电话',
            'hat_size': '帽子尺寸', 'short_sleeve': '短袖尺寸', 'long_sleeve': '长袖尺寸',
            'winter_uniform': '冬装尺寸', 'shoe_size': '鞋码'
        }

        changes = []

        # 辅助函数：统一转为字符串对比
        def to_str(v):
            if v is None: return ""
            if isinstance(v, bool): return "是" if v else "否"
            return str(v).strip()

        # 自动对比并赋值
        for field, label in field_map.items():
            old_val_raw = getattr(cycle, field)
            
            # 根据字段类型获取新值
            if field in ['military_service', 'has_license']:
                new_val_raw = field in request.form
            elif field in ['hire_date', 'enlistment_date', 'discharge_date', 'license_date', 'license_expiry', 'security_license_date']:
                parsed = parse_date(request.form.get(field))
                new_val_raw = parsed if parsed else (old_val_raw if field == 'hire_date' else None)
            else:
                new_val_raw = request.form.get(field, '').strip()

            # 记录变更
            if to_str(old_val_raw) != to_str(new_val_raw):
                changes.append(f"{label}[{to_str(old_val_raw)} -> {to_str(new_val_raw)}]")
                setattr(cycle, field, new_val_raw)

        # 处理头像更新
        if 'photo' in request.files and request.files['photo'].filename:
            path = save_uploaded_file(request.files['photo'], module='avatar')
            if path:
                cycle.photo_path = path
                changes.append("更新了证件照")
        
        # 修正头像路径的NaN问题
        if not cycle.photo_path or str(cycle.photo_path).lower() == 'nan':
            cycle.photo_path = 'uploads/default-avatar.png'

        # 提交变更
        try:
            # 有变更才记录日志
            if changes:
                log_action(
                    action_type='编辑人员',
                    target_type='Employee',
                    target_id=cycle.id,
                    description=f"修改了队员【{cycle.name}】的档案：{', '.join(changes)}",
                    **locals()
                )
            
            db.session.commit()
            flash('员工信息更新成功', 'success')
            return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败，错误：{str(e)}', 'danger')
    
    # GET请求返回编辑页面
    return render_template('hr/edit.html',
                           cycle=cycle,
                           ethnic_options=get_ethnic_options(),
                           politics_options=get_politics_options(),
                           education_options=get_education_options(),
                           salary_modes=SALARY_MODES,
                           positions=POSITIONS,
                           posts=POSTS)