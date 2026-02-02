# routes/hr.py
# 人事管理模块所有路由（已模块化）

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, json, send_file
from flask_login import login_required, current_user
from models import Asset, db, EmploymentCycle, User, AssetHistory
from utils import (
    validate_id_card, validate_phone, get_gender_from_id_card, get_birthday_from_id_card,
    save_uploaded_file, get_ethnic_options, get_politics_options, get_education_options,
    parse_date, format_date, today_str,get_unreturned_assets, perm
)
from config import SALARY_MODES, POSITIONS, POSTS,Config
from datetime import datetime, timedelta
from sqlalchemy import or_
import pandas as pd
from io import BytesIO
from models import AssetAllocation
import qrcode
import io
import base64

hr_bp = Blueprint('hr', __name__, url_prefix='/hr')

# ==================== 花名册列表 ====================
@hr_bp.route('/list')
@login_required
def hr_list():
    # 逻辑：如果没有【人事管理钥匙】，说明是普通队员，直接踢到他自己的详情页
    if not perm.can('hr.view'):
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))
    # 标签页
    status_filter = request.args.get('status', '在职')
    if status_filter not in ['待审核', '在职', '离职']:
        status_filter = '在职'
    # 2. 统计所有待审核人数（无论当前在哪个标签页都统计，用于红点显示）
    pending_count = EmploymentCycle.query.filter_by(status='待审核').count()

    # 搜索
    search = request.args.get('search', '').strip()
    sort = request.args.get('sort', 'hire_date_desc')
    

    # 排序
    sort = request.args.get('sort', 'hire_date_desc')
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

    
   
        # 其他角色显示所有人最新周期
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
        
    # 5. 【核心修改：状态严格过滤】
    # 这里的 status_filter 必须是互斥的
    if status_filter == '待审核':
        query = query.filter(EmploymentCycle.status == '待审核')
    elif status_filter == '离职':
        query = query.filter(EmploymentCycle.status == '离职')
    else:
        # 默认 '在职' 模式下，坚决不显示 '待审核' 的人
        query = query.filter(EmploymentCycle.status == '在职')

    # 6. 搜索过滤
    if search:
        query = query.filter(
            db.or_(
                EmploymentCycle.name.ilike(f'%{search}%'),
                EmploymentCycle.id_card.ilike(f'%{search}%'),
                EmploymentCycle.phone.ilike(f'%{search}%')
            )
        )
            # 字段显示控制（默认全部显示）
    show_fields = request.args.getlist('show')
    if not show_fields:
        show_fields = [
        'name', 'id_card', 'phone', 'position', 'post', 'salary_mode', 
        'hire_date', 'tenure', 'gender', 'birthday', 'ethnic', 'politics', 
        'education', 'household_address', 'residence_address', 'military', 
        'license', 'security_license', 'emergency', 'uniform'
    ]


    # 搜索过滤
    if search:
        query = query.filter(
            db.or_(
                EmploymentCycle.name.ilike(f'%{search}%'),
                EmploymentCycle.id_card.ilike(f'%{search}%'),
                EmploymentCycle.phone.ilike(f'%{search}%')
            )
        )

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
    from utils import log_action  # 局部导入工具函数
    import json
    from datetime import datetime
    if request.method == 'POST':
        id_card = request.form['id_card'].strip()
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        
        if not all([name, id_card, phone]):
            flash('姓名、身份证、手机为必填项', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        if not validate_id_card(id_card):
            flash('身份证号码无效', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        if not validate_phone(phone):
            flash('手机号码格式错误', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        if EmploymentCycle.query.filter_by(id_card=id_card, status='在职').first():
            flash('该身份证当前在职，不能重复入职', 'danger')
            return redirect(url_for('hr.hr_add'))
        
        gender = get_gender_from_id_card(id_card)
        birthday = get_birthday_from_id_card(id_card)
        
        photo_path = None
        if 'photo' in request.files and request.files['photo'].filename:
            avatar_path = save_uploaded_file(request.files.get('avatar'), module='avatar')
        
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
        
        archives = None
        if other_certs:
            archives = json.dumps({'other_certificates': other_certs}, ensure_ascii=False)
        
        cycle = EmploymentCycle(
            id_card=id_card,#身份证
            name=name,#姓名
            phone=phone,#电话
            gender=gender,#性别
            birthday=birthday,#生日
            hire_date=parse_date(request.form.get('hire_date')) or datetime.today().date(),#入职日期
            status='在职',
            photo_path=photo_path,#照片路径
            ethnic=request.form.get('ethnic'),#民族
            politics=request.form.get('politics'),#政治面貌
            education=request.form.get('education'),#学历
            household_province=request.form.get('household_province'),#户籍省
            household_city=request.form.get('household_city'),#户籍市
            household_district=request.form.get('household_district'),#户籍区
            household_town=request.form.get('household_town'),#户籍镇
            household_village=request.form.get('household_village'),#户籍村/居委
            household_detail=request.form.get('household_detail'),#户籍详址
            residence_province=request.form.get('residence_province'),#居住省
            residence_city=request.form.get('residence_city'),#居住市
            residence_district=request.form.get('residence_district'),#居住区
            residence_town=request.form.get('residence_town'),#居住镇
            residence_village=request.form.get('residence_village'),#居住村/居委
            residence_detail=request.form.get('residence_detail'),#居住详址
            military_service='military_service' in request.form,#兵役情况
            enlistment_date=parse_date(request.form.get('enlistment_date')),#入伍日期
            unit_number=request.form.get('unit_number'),#部队番号
            branch=request.form.get('branch'),#兵种
            discharge_date=parse_date(request.form.get('discharge_date')),#退伍日期
            has_license='has_license' in request.form,#是否有驾照
            license_date=parse_date(request.form.get('license_date')),#领证日期
            license_type=request.form.get('license_type'),#驾照类型
            license_expiry=parse_date(request.form.get('license_expiry')),#驾照到期
            security_license_number=request.form.get('security_license_number'),#保安证号
            security_license_date=parse_date(request.form.get('security_license_date')),#保安证日期
            salary_mode=request.form['salary_mode'],#薪资模式
            emergency_name=request.form.get('emergency_name'),#紧急联系人
            emergency_relation=request.form.get('emergency_relation'),#联系人关系
            emergency_phone=request.form.get('emergency_phone'),#联系人电话
            position=request.form['position'],#职位
            post=request.form['post'],#岗位
            hat_size=request.form.get('hat_size'),#帽子尺寸
            short_sleeve=request.form.get('short_sleeve'),#短袖尺寸
            long_sleeve=request.form.get('long_sleeve'),#长袖尺寸
            winter_uniform=request.form.get('winter_uniform'),#冬装尺寸
            shoe_size=request.form.get('shoe_size'),#鞋码
            archives=archives#其他证书档案
        )
        
        db.session.add(cycle)
        db.session.flush() # 预生成 cycle.id
        
        # 自动创建账号（角色固定为 member）
        user_created_msg = ''
        if not User.query.filter_by(username=id_card).first():
            default_password = id_card[-6:]
            new_user = User(
                username=id_card,
                name=name,
                role='member'  # 固定为队员，不根据职务设置
           )
            new_user.set_password(default_password)
            db.session.add(new_user)
            user_created_msg = '（账号已自动创建）'
        # 【核心新增】记录管理员审计日志
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
    
    return render_template('hr/add.html',
                           ethnic_options=get_ethnic_options(),
                           politics_options=get_politics_options(),
                           education_options=get_education_options(),
                           salary_modes=SALARY_MODES,
                           positions=POSITIONS,
                           posts=POSTS)


# ==================== 队员自主登记 ====================
@hr_bp.route('/self_register', methods=['GET', 'POST'])
def self_register():
    from datetime import datetime
    import json
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        id_card = request.form.get('id_card', '').strip()
        phone = request.form.get('phone', '').strip()
        
        if not name or not id_card:
            flash("姓名和身份证号为必填项", "danger")
            return redirect(url_for('hr.self_register'))

        gender = get_gender_from_id_card(id_card)
        birthday = get_birthday_from_id_card(id_card)

        # --- 核心修复：扫码入职日期强控 ---
        hire_date_raw = request.form.get('hire_date')
        if hire_date_raw:
            try:
                final_hire_date = datetime.strptime(hire_date_raw, '%Y-%m-%d').date()
            except:
                final_hire_date = datetime.today().date()
        else:
            final_hire_date = datetime.today().date()

        photo_path = None
        file_obj = request.files.get('photo')
        if file_obj and file_obj.filename:
            photo_path = save_uploaded_file(file_obj, module='avatar')
        else:
            photo_path = 'uploads/default-avatar.png'

        other_certs = []
        i = 0
        while f'cert_name_{i}' in request.form:
            c_name = request.form.get(f'cert_name_{i}')
            c_num = request.form.get(f'cert_number_{i}')
            c_date = request.form.get(f'cert_date_{i}')
            if c_name and c_num:
                other_certs.append({'name': c_name, 'number': c_num, 'date': c_date})
            i += 1
        archives = json.dumps({'other_certificates': other_certs}, ensure_ascii=False) if other_certs else None

        new_emp = EmploymentCycle(
            id_card=id_card,#身份证
            name=name,#姓名
            phone=phone,#电话
            gender=gender,#性别
            birthday=birthday,#生日
            hire_date=final_hire_date,#入职日期
            status='待审核',#状态
            photo_path=photo_path,#照片路径
            ethnic=request.form.get('ethnic'),#民族
            politics=request.form.get('politics'),#政治面貌
            education=request.form.get('education'),#学历
            household_province=request.form.get('household_province'),#户籍省
            household_city=request.form.get('household_city'),#户籍市
            household_district=request.form.get('household_district'),#户籍区
            household_town=request.form.get('household_town'),#户籍镇
            household_village=request.form.get('household_village'),#户籍村/居委
            household_detail=request.form.get('household_detail'),#户籍详址
            residence_province=request.form.get('residence_province'),#居住省
            residence_city=request.form.get('residence_city'),#居住市
            residence_district=request.form.get('residence_district'),#居住区
            residence_town=request.form.get('residence_town'),#居住镇
            residence_village=request.form.get('residence_village'),#居住村/居委
            residence_detail=request.form.get('residence_detail'),#居住详址
            military_service='military_service' in request.form,#兵役情况
            enlistment_date=parse_date(request.form.get('enlistment_date')),#入伍日期
            unit_number=request.form.get('unit_number'),#部队番号
            branch=request.form.get('branch'),#兵种
            discharge_date=parse_date(request.form.get('discharge_date')),#退伍日期
            has_license='has_license' in request.form,#是否有驾照
            license_date=parse_date(request.form.get('license_date')),#领证日期
            license_type=request.form.get('license_type'),#驾照类型
            license_expiry=parse_date(request.form.get('license_expiry')),#驾照到期
            security_license_number=request.form.get('security_license_number'),#保安证号
            security_license_date=parse_date(request.form.get('security_license_date')),#保安证日期
            emergency_name=request.form.get('emergency_name'),#紧急联系人
            emergency_relation=request.form.get('emergency_relation'),#联系人关系
            emergency_phone=request.form.get('emergency_phone'),#联系人电话
            salary_mode=request.form['salary_mode'],#薪资模式
            position=request.form['position'],#职位
            post=request.form['post'],#岗位
            hat_size=request.form.get('hat_size'),#帽子尺寸
            short_sleeve=request.form.get('short_sleeve'),#短袖尺寸
            long_sleeve=request.form.get('long_sleeve'),#长袖尺寸
            winter_uniform=request.form.get('winter_uniform'),#冬装尺寸
            shoe_size=request.form.get('shoe_size'),#鞋码
            archives=archives,#其他证书档案
            
        )

        try:
            db.session.add(new_emp)
            db.session.commit()
            return render_template('hr/register_success.html')
        except Exception as e:
            db.session.rollback()
            return f"提交失败。详情: {str(e)}", 500

    from config import SALARY_MODES, POSITIONS, POSTS
    from utils import get_ethnic_options, get_politics_options, get_education_options, today_str
    return render_template('hr/self_register.html', 
                           employee=None, 
                           is_self_register=True, 
                           salary_modes=SALARY_MODES,
                           positions=POSITIONS,
                           posts=POSTS,
                           ethnic_options=get_ethnic_options(),
                           politics_options=get_politics_options(),
                           education_options=get_education_options(),
                           today_str=today_str)
# ==================== 管理员审核 (修复版) ====================
@hr_bp.route('/approve_pending/<int:id>', methods=['POST'])
@login_required
@perm.require('hr.edit')
def approve_pending(id):
    from utils import log_action # 确保导入日志工具
    emp = EmploymentCycle.query.get_or_404(id)
    
    if emp.status != '待审核':
        flash('该记录不是待审核状态，无法批准', 'warning')
        return redirect(url_for('hr.hr_list', status='待审核'))
    
    # 1. 检查冲突
    existing = EmploymentCycle.query.filter(
        EmploymentCycle.id_card == emp.id_card,
        EmploymentCycle.status == '在职'
    ).first()
    if existing:
        flash('身份证已存在于在职员工，无法批准', 'danger')
        return redirect(url_for('hr.hr_list', status='待审核'))
    
    # 2. 变更状态
    emp.status = '在职'
    if not emp.hire_date:
        emp.hire_date = datetime.today().date()
    
    # 3. 【修复】自动创建账号逻辑
    user_created_msg = ''
    # 检查 User 表中是否已有该身份证的账号
    if not User.query.filter_by(username=emp.id_card).first():
        default_password = emp.id_card[-6:]  # 身份证后六位
        new_user = User(
            username=emp.id_card,
            name=emp.name,
            role='member'  # 角色固定为队员
        )
        new_user.set_password(default_password)
        db.session.add(new_user)
        user_created_msg = f'（账号已自动创建，默认密码为身份证后6位）'
    else:
        user_created_msg = '（账号已存在，无需重复创建）'

    # 4. 记录管理员审计日志
    log_action(
        action_type='审批入职',
        target_type='Employee',
        target_id=emp.id,
        description=f"批准了自主登记的人员入职：{emp.name} (身份证:{emp.id_card}){user_created_msg}",
        **locals()
    )

    try:
        db.session.commit()
        flash(f'员工 {emp.name} 已批准入职！{user_created_msg}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'审批失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_list', status='在职'))
# ==================== 删除人员记录 ====================

@hr_bp.route('/delete_pending/<int:id>', methods=['POST'])
@login_required
@perm.require('hr.edit')
def delete_pending(id):
    # 1. 权限检查：直接判断是否为 admin 角色
    if current_user.role != 'admin':
        flash("只有系统管理员有权执行删除操作", "danger")
        return redirect(url_for('hr.hr_list'))

    # 2. 查找记录
    emp = EmploymentCycle.query.get_or_404(id)
    id_card_to_delete = emp.id_card
    old_status = emp.status
    old_name = emp.name

    # 3. 执行删除
    try:
        # 如果该员工有关联的其他表数据（如资产领用记录），建议先处理或确认数据库开启了 cascade delete
        user_account = User.query.filter_by(username=id_card_to_delete).first()
        user_deleted_msg = ""
        if user_account:
            db.session.delete(user_account)
            user_deleted_msg = "及关联登录账号"
        db.session.delete(emp)
        db.session.commit()
        flash(f"已成功彻底删除记录：{old_name}{user_deleted_msg}", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"删除失败，可能存在关联数据未清理：{str(e)}", "danger")

    # 4. 跳转回原本所属的状态列表
    return redirect(url_for('hr.hr_list', status=old_status))

# ==================== 生成二维码的接口 ====================
@hr_bp.route('/generate_qr')
@login_required
@perm.require('hr.edit')
def generate_qr():
    base_url = "http://xuxiaoxiao1992.asuscomm.com:8000"
    target_url = base_url + url_for('hr.self_register')
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(target_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return jsonify({'success': True, 'qr_code': qr_b64, 'url': target_url})

# ==================== 详情页 ====================
@hr_bp.route('/detail/<id_card>')
@login_required
def hr_detail(id_card):
    # 如果想看的人不是自己，且自己手里没有 hr.view 钥匙
    if id_card != current_user.username and not perm.can('hr.view'):
        flash('权限不足，您只能查看自己的信息', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))
    cycles = EmploymentCycle.query.filter_by(id_card=id_card).order_by(EmploymentCycle.hire_date.desc()).all()
    if not cycles:
        flash('未找到该身份证记录', 'warning')
        return redirect(url_for('hr.hr_list'))
    
    current_cycle = next((c for c in cycles if c.status == '在职'), None)

    # --- 新增：获取可发放的资产列表 ---
    available_assets = []
    if current_cycle:
        # 只查询类型为装备或服饰，且库存 > 0 的资产
        available_assets = Asset.query.filter(
            Asset.type.in_(['装备', '服饰']),
            Asset.stock_quantity > 0
        ).all()
    
    return render_template('hr/detail.html',
                           cycles=cycles,
                           current_cycle=current_cycle,
                           id_card=id_card,
                           available_assets=available_assets,
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
    from utils import log_action
    from datetime import datetime
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    
    if cycle.status != '在职':
        flash('仅在职周期可编辑', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    if request.method == 'POST':
        # --- 1. 定义字段映射（这是为了让日志显示中文，同时涵盖你所有的字段） ---
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

        # 辅助工具：统一转为字符串进行对比
        def to_str(v):
            if v is None: return ""
            if isinstance(v, bool): return "是" if v else "否"
            return str(v).strip()

        # --- 2. 核心逻辑：自动对比并【赋值】 ---
        # 这个循环代替了你原来那一长串的 cycle.xxx = request.form[...]
        for field, label in field_map.items():
            old_val_raw = getattr(cycle, field)
            
            # 根据字段类型获取新值 (逻辑完全对应你原来的代码)
            if field in ['military_service', 'has_license']:
                new_val_raw = field in request.form
            elif field in ['hire_date', 'enlistment_date', 'discharge_date', 'license_date', 'license_expiry', 'security_license_date']:
                # 日期特殊处理，如果没填则保持原样或转为 None
                parsed = parse_date(request.form.get(field))
                new_val_raw = parsed if parsed else (old_val_raw if field == 'hire_date' else None)
            else:
                new_val_raw = request.form.get(field, '').strip()

            # 比较差异
            if to_str(old_val_raw) != to_str(new_val_raw):
                changes.append(f"{label}[{to_str(old_val_raw)} -> {to_str(new_val_raw)}]")
                # 【执行赋值】—— 这一步就是你原来的 cycle.name = ... 
                setattr(cycle, field, new_val_raw)

        # --- 3. 特殊处理：头像 ---
        if 'photo' in request.files and request.files['photo'].filename:
            path = save_uploaded_file(request.files['photo'], module='avatar')
            if path:
                cycle.photo_path = path
                changes.append("更新了证件照")
        
        # 修正 nan 字符串问题
        if not cycle.photo_path or str(cycle.photo_path).lower() == 'nan':
            cycle.photo_path = 'uploads/default-avatar.png'

        # --- 4. 提交记录 ---
        try:
            # 只有当确实有变化时才记录日志
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
    
    # GET 请求返回页面
    return render_template('hr/edit.html',
                           cycle=cycle,
                           ethnic_options=get_ethnic_options(),
                           politics_options=get_politics_options(),
                           education_options=get_education_options(),
                           salary_modes=SALARY_MODES,
                           positions=POSITIONS,
                           posts=POSTS)
# ==================== 添加档案记录（奖惩、检讨书、保密协议等） ====================
@hr_bp.route('/archive/add/<int:cycle_id>', methods=['POST'])
@login_required
@perm.require('hr.add')
def add_archive(cycle_id):
    from utils import log_action  # 局部导入工具函数
    import json
    from datetime import datetime

    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    if cycle.status != '在职':
        flash('仅在职期间可添加档案记录', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    record_type = request.form['record_type']
    title = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    
    file_path = None
    if 'archive_file' in request.files and request.files['archive_file'].filename:
        # 建议此处增加子目录参数以保持目录整洁
        file_path = save_uploaded_file(
            request.files['archive_file'], 
            module='archive', 
            sub_folder=cycle.id_card
        )
    
    # 逻辑处理：解析并更新 JSON 字段
    archives = json.loads(cycle.archives or '{}')
    if 'archive_records' not in archives:
        archives['archive_records'] = []
    
    # 构建记录项
    new_record = {
        'type': record_type,
        'title': title,
        'description': description,
        'file_path': file_path,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'operator': current_user.name,
        'operator_id': current_user.id
    }
    
    archives['archive_records'].append(new_record)
    cycle.archives = json.dumps(archives, ensure_ascii=False)

    # 【核心新增】记录管理员审计日志
    file_msg = "（含附件）" if file_path else "（无附件）"
    description = (
        f"为队员【{cycle.name}】添加了档案记录 | "
        f"类型：{record_type}，标题：{title} {file_msg}，"
        f"内容简述：{description[:30]}{'...' if len(description) > 30 else ''}"
    )

    log_action(
        action_type='添加档案',
        target_type='EmployeeArchive',
        target_id=cycle.id,
        **locals()
    )

    # 提交数据库事务
    try:
        db.session.commit()
        flash('档案记录添加成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'档案保存失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))

from datetime import datetime, timedelta
import json

def is_within_hour(date_str):
    if not date_str:
        return False
    try:
        # 第一步：把中文日期格式 2026年01月07日 转换为 2026-01-07
        clean_date = str(date_str).replace('年', '-').replace('月', '-').replace('日', '')
        
        # 第二步：尝试多种可能的日期格式进行解析
        record_time = None
        formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']
        
        for fmt in formats:
            try:
                record_time = datetime.strptime(clean_date.strip(), fmt)
                break
            except:
                continue
        
        if not record_time:
            print(f"DEBUG: 无法解析日期字符串 -> {date_str}")
            return False
            
        # 第三步：计算时间差
        diff = datetime.now() - record_time
        # 如果是未来时间（比如录入错误），或者在一小时内
        return diff < timedelta(hours=1)
        
    except Exception as e:
        print(f"DEBUG: 时间判断逻辑出错 -> {e}")
        return False

@hr_bp.route('/archive/edit/<int:cycle_id>/<int:record_idx>', methods=['POST'])
@login_required
def edit_archive(cycle_id, record_idx):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    archives = json.loads(cycle.archives or '{}')
    record = archives['archive_records'][record_idx]

    # 严格校验：操作人ID必须一致 且 时间在1小时内
    if record['operator_id'] == current_user.id and is_within_hour(record['date']):
        record['type'] = request.form['record_type']
        record['title'] = request.form['title'].strip()
        record['description'] = request.form.get('description', '').strip()
        # 注意：编辑通常不建议修改原始时间，或者仅更新编辑标记
        cycle.archives = json.dumps(archives, ensure_ascii=False)
        db.session.commit()
        flash('档案已更新', 'success')
    else:
        flash('无权修改或已超时', 'danger')
    return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
# ==================== 办理离职（含资产自动核销审计） ====================
@hr_bp.route('/departure/<int:cycle_id>', methods=['POST'])
@login_required
@perm.require('hr.departure')
def departure(cycle_id):
    from utils import log_action
    import json
    from datetime import datetime

    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    if cycle.status == '离职':
        flash('已离职，无需重复操作', 'info')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    # 检查强制勾选
    if 'confirm_return' not in request.form or 'settle_utilities' not in request.form:
        flash('请确认所有离职事项', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    # 1. 离职自动归还装备（精确核销）
    user_allocations = AssetAllocation.query.filter_by(
        user_id=cycle.id, 
        return_date=None
    ).all()

    returned_assets_summary = [] # 用于审计日志的汇总

    for alloc in user_allocations:
        asset = alloc.asset
        qty = alloc.quantity
        
        alloc.return_date = datetime.today().date()
        
        asset.stock_quantity += qty
        asset.allocated_quantity -= qty
        
        if asset.allocated_quantity < 0:
            asset.allocated_quantity = 0
        
        if asset.allocated_quantity == 0:
            asset.status = '库存'
        
        # 记录归还资产摘要（供日志使用）
        returned_assets_summary.append(f"{asset.name}x{qty}")

        # 记录资产历史
        history = AssetHistory(
            asset_id=asset.id,
            action='归还（离职自动）',
            user_id=cycle.id,
            operator_id=current_user.id,
            quantity=qty,
            action_date=datetime.now(),
            note=f'{cycle.name}离职自动归还'
        )
        db.session.add(history)
    # 2. 床位占用释放（核心新增逻辑）
    room_id = cycle.room_id
    is_room_leader = cycle.is_room_leader
    
    # 清空队员床位关联
    cycle.bed_number = None  # 释放床位编号
    cycle.is_room_leader = False  # 取消宿舍长身份
    
    # 若为宿舍长，同步清理房间资产负责人
    from models import AssetInstance
    if is_room_leader and room_id:
        # 清空该房间所有资产个体的负责人
        AssetInstance.query.filter(
            AssetInstance.room_id == room_id
        ).update({AssetInstance.user_id: None})
        
        # 同步更新资产主表的当前使用人
        asset_ids = db.session.query(AssetInstance.asset_id).filter(
            AssetInstance.room_id == room_id
        ).distinct().subquery()
        Asset.query.filter(
            Asset.id.in_(asset_ids)
        ).update({Asset.current_user_id: None})

    # 2. 正常离职人事逻辑
    reason = request.form.get('departure_reason', '').strip()
    dep_date_str = request.form.get('departure_date')
    dep_date = parse_date(dep_date_str) or datetime.today().date()
    
    cycle.status = '离职'
    cycle.departure_date = dep_date
    
    # 更新档案中的原因
    archives = json.loads(cycle.archives or '{}')
    archives['departure_reason'] = reason or '无原因说明'
    cycle.archives = json.dumps(archives, ensure_ascii=False)
    
    # 3. 【核心新增】写入管理员审计日志
    bed_msg = " | 已释放床位" if cycle.bed_number else ""
    leader_msg = " | 已取消宿舍长身份" if is_room_leader else ""
    asset_msg = f" | 自动回收资产: {', '.join(returned_assets_summary)}" if returned_assets_summary else " | 无资产需回收"
    log_description = (
        f"为队员【{cycle.name}】办理了离职手续。"
        f"离职日期：{dep_date.strftime('%Y-%m-%d')}，"
        f"原因：{reason or '未填写'}"
        f"{asset_msg}"
    )

    log_action(
        action_type='人员离职',
        target_type='Employee',
        target_id=cycle.id,
        description=log_description,
        **locals()
    )

    # 4. 提交所有变更（资产 + 人事 + 日志）
    try:
        db.session.commit()
        flash(f'离职成功，已自动归还全部个人装备({len(returned_assets_summary)}项)，并释放床位', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'办理离职失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))

# ==================== 导出员工花名册 ====================
@hr_bp.route('/export')
@login_required
@perm.require('hr.export')
def hr_export():
    status_filter = request.args.get('status', '在职')
    search = request.args.get('search', '').strip()
    
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
    
    if status_filter == '在职':
        query = query.filter(EmploymentCycle.status == '在职')
    else:
        query = query.filter(EmploymentCycle.status == '离职')
    
    if search:
        query = query.filter(
            db.or_(
                EmploymentCycle.name.ilike(f'%{search}%'),
                EmploymentCycle.id_card.ilike(f'%{search}%'),
                EmploymentCycle.phone.ilike(f'%{search}%')
            )
        )
    
    employees = query.all()
    
    data = []
    for emp in employees:
        # 展开地址
        household_address = f"{emp.household_province or ''}{emp.household_city or ''}{emp.household_district or ''}{emp.household_town or ''}{emp.household_detail or ''}"
        residence_address = f"{emp.residence_province or ''}{emp.residence_city or ''}{emp.residence_district or ''}{emp.residence_town or ''}{emp.residence_detail or ''}"
        
        # 兵役情况
        military = '是' if emp.military_service else '无'
        if military == '是':
            military += f" (入伍{format_date(emp.enlistment_date)}，部队{emp.unit_number or ''}，兵种{emp.branch or ''}，退伍{format_date(emp.discharge_date)})"
        
        # 驾驶证
        license = '是' if emp.has_license else '无'
        if license == '是':
            license += f" (初领{format_date(emp.license_date)}，车型{emp.license_type or ''}，有效期{format_date(emp.license_expiry)})"
        
        # 紧急联系人
        emergency = f"{emp.emergency_name or ''} ({emp.emergency_relation or ''}) {emp.emergency_phone or ''}"
        
        # 工作服
        uniform = f"帽{emp.hat_size or ''} 短袖{emp.short_sleeve or ''} 长袖{emp.long_sleeve or ''} 冬装{emp.winter_uniform or ''} 鞋{emp.shoe_size or ''}"
        
        # 展开档案 JSON
        archives = json.loads(emp.archives or '{}')
        other_certs = '; '.join([f"{c['name']} ({c['number']}, {c['date']})" for c in archives.get('other_certificates', [])])
        archive_records = '; '.join([f"[{r['type']}] {r['title']} ({r['date']}) {r['description'] or ''}" for r in archives.get('archive_records', [])])
        departure_reason = archives.get('departure_reason', '')
        
        data.append({
            '姓名': emp.name,
            '身份证号码': emp.id_card,
            '手机号': emp.phone or '',
            '头像路径': emp.photo_path or '',
            '性别': emp.gender or '',
            '出生日期': format_date(emp.birthday),
            '入职日期': format_date(emp.hire_date),
            '离职日期': format_date(emp.departure_date),
            '状态': emp.status,
            '民族': emp.ethnic or '',
            '政治面貌': emp.politics or '',
            '学历': emp.education or '',
            '户籍省份': emp.household_province or '',
            '户籍城市': emp.household_city or '',
            '户籍区县': emp.household_district or '',
            '户籍乡镇': emp.household_town or '',
            '户籍详细地址': emp.household_detail or '',
            '居住省份': emp.residence_province or '',
            '居住城市': emp.residence_city or '',
            '居住区县': emp.residence_district or '',
            '居住乡镇': emp.residence_town or '',
            '居住详细地址': emp.residence_detail or '',
            '兵役情况': '是' if emp.military_service else '无',
            '入伍日期': format_date(emp.enlistment_date),
            '部队番号': emp.unit_number or '',
            '兵种': emp.branch or '',
            '退伍日期': format_date(emp.discharge_date),
            '是否持有驾驶证': '是' if emp.has_license else '无',
            '驾驶证初领日期': format_date(emp.license_date),
            '准驾车型': emp.license_type or '',
            '驾驶证有效期': format_date(emp.license_expiry),
            '是否持有保安员证': '是' if emp.security_license_number else '无',
            '保安员证': emp.security_license_number or '',
            '保安员证发证日期': format_date(emp.security_license_date),
            '薪资模式': emp.salary_mode or '',
            '职务': emp.position or '',
            '岗位': emp.post or '',
            '紧急联系人姓名': emp.emergency_name or '',
            '紧急联系人关系': emp.emergency_relation or '',
            '紧急联系人电话': emp.emergency_phone or '',
            '帽码': emp.hat_size or '',
            '短袖尺码': emp.short_sleeve or '',
            '长袖尺码': emp.long_sleeve or '',
            '冬装尺码': emp.winter_uniform or '',
            '鞋码': emp.shoe_size or '',
            '其他证书': other_certs,
            '档案记录': archive_records,
            '离职原因': departure_reason
        })
    
    df = pd.DataFrame(data)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='员工花名册')
    
    output.seek(0)
    
    filename = f"员工花名册_{status_filter}_{datetime.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )



# ==================== 导入员工花名册 ====================
@hr_bp.route('/import', methods=['GET', 'POST'])
@login_required
@perm.require('hr.import')
def hr_import():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('未选择文件', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('未选择文件', 'danger')
            return redirect(request.url)
        
        if file and file.filename.endswith('.xlsx'):
            try:
                df = pd.read_excel(file, dtype={'手机号': str})
                
                # 必填列
                required = ['姓名', '身份证号码', '手机号']
                missing = [col for col in required if col not in df.columns]
                if missing:
                    flash(f'缺少必填列：{", ".join(missing)}', 'danger')
                    return redirect(request.url)
                
                success = 0
                errors = []
                
                for idx, row in df.iterrows():
                    try:
                        id_card = str(row['身份证号码']).strip()
                        name = str(row['姓名']).strip()
                        phone = str(row['手机号']).strip()
                        
                        # 状态（默认在职）
                        status = str(row.get('状态', '在职')).strip()
                        if status not in ['在职', '离职']:
                            status = '在职'
                        
                        # 重复校验：同一身份证 + 同一入职日期
                        hire_date_raw = row.get('入职日期')
                        hire_date = parse_date(hire_date_raw)
                        if not hire_date:
                            errors.append(f"行{idx+2}: {name} 入职日期无效 (原始值: {hire_date_raw})")
                            continue
                        
                        if EmploymentCycle.query.filter_by(id_card=id_card, hire_date=hire_date).first():
                            errors.append(f"行{idx+2}: {name} 该周期已存在")
                            continue
                        
                        # 身份证校验
                        if not validate_id_card(id_card):
                            errors.append(f"行{idx+2}: {name} 身份证无效")
                            continue
                        # 默认头像
                        raw_photo = row.get('头像路径')
                        
                        # 2. 只有当确实是 pandas 定义的空值 (NaN) 或 None 时，才考虑设为默认
                        if pd.isna(raw_photo) or raw_photo is None:
                            photo_path = 'uploads/default-avatar.png'
                        else:
                            # 3. 处理有值的情况
                            p_str = str(raw_photo).strip()
                            # 4. 关键：排除掉可能存在的干扰字符串，剩下的全部视为有效路径
                            if p_str == "" or p_str.lower() in ['nan', 'none', 'null']:
                                photo_path = 'uploads/default-avatar.png'
                            else:
                                # 5. 只要不是上面那些，就保留 Excel 原样路径 (如: uploads/photos/xxx.jpg)
                                photo_path = p_str
                                print(f"DEBUG: 正在导入 {name} 的照片，路径是: {photo_path}")

                        gender = get_gender_from_id_card(id_card)
                        birthday = get_birthday_from_id_card(id_card)
                        
                        # 离职日期
                        departure_date = parse_date(row.get('离职日期')) if status == '离职' else None
                        
                        cycle = EmploymentCycle(
                            id_card=id_card,
                            name=name,
                            phone=phone,
                            gender=gender,
                            birthday=birthday,
                            hire_date=hire_date,
                            departure_date=departure_date,
                            status=status,
                            
                            # 基本信息
                            ethnic=str(row.get('民族', '')),
                            politics=str(row.get('政治面貌', '')),
                            education=str(row.get('学历', '')),
                            
                            # 地址拆分（支持多种列名）
                            household_province=str(row.get('户籍省份', row.get('户籍省', ''))),
                            household_city=str(row.get('户籍城市', row.get('户籍市', ''))),
                            household_district=str(row.get('户籍区县', row.get('户籍区', ''))),
                            household_town=str(row.get('户籍乡镇', row.get('户籍镇', ''))),
                            household_detail=str(row.get('户籍详细地址', '')),
                            residence_province=str(row.get('居住省份', row.get('居住省', ''))),
                            residence_city=str(row.get('居住城市', row.get('居住市', ''))),
                            residence_district=str(row.get('居住区县', row.get('居住区', ''))),
                            residence_town=str(row.get('居住乡镇', row.get('居住镇', ''))),
                            residence_detail=str(row.get('居住详细地址', '')),
                            
                            # 兵役
                            military_service=str(row.get('兵役情况', '')).strip().lower() == '是',
                            enlistment_date=parse_date(row.get('入伍日期')),
                            unit_number=str(row.get('部队番号', '')),
                            branch=str(row.get('兵种', '')),
                            discharge_date=parse_date(row.get('退伍日期')),
                            
                            # 驾驶证
                            has_license=str(row.get('是否持有驾驶证', '')).strip().lower() == '是',
                            license_date=parse_date(row.get('驾驶证初领日期')),
                            license_type=str(row.get('准驾车型', '')),
                            license_expiry=parse_date(row.get('驾驶证有效期')),
                            
                            # 保安员证
                            has_security_license=str(row.get('是否持有保安员证', '')).strip().lower() == '是',
                            security_license_number=str(row.get('保安员证', '')),
                            security_license_date=parse_date(row.get('保安员证发证日期')),
                            
                            # 薪资与岗位
                            salary_mode=str(row.get('薪资模式', '')),
                            position=str(row.get('职务', '')),
                            post=str(row.get('岗位', '')),
                            
                            # 紧急联系人
                            emergency_name=str(row.get('紧急联系人姓名', '')),
                            emergency_relation=str(row.get('紧急联系人关系', '')),
                            emergency_phone=str(row.get('紧急联系人电话', '')),
                            
                            # 工作服
                            hat_size=str(row.get('帽码', '')),
                            short_sleeve=str(row.get('短袖尺码', '')),
                            long_sleeve=str(row.get('长袖尺码', '')),
                            winter_uniform=str(row.get('冬装尺码', '')),
                            shoe_size=str(row.get('鞋码', '')),
                            
                            # 头像路径
                            photo_path=photo_path,
                        )
                        
                        # 其他证书和档案记录（暂留空，可后续扩展）
                        archives = {}
                        if row.get('其他证书'):
                            archives['other_certificates'] = []  # 可扩展
                        if row.get('档案记录'):
                            archives['archive_records'] = []  # 可扩展
                        if row.get('离职原因'):
                            archives['departure_reason'] = str(row['离职原因'])
                        cycle.archives = json.dumps(archives, ensure_ascii=False) if archives else ''
                        
                        db.session.add(cycle)
                        
                        # 自动创建账号（仅在职），角色固定为 member
                        if status == '在职' and not User.query.filter_by(username=id_card).first():
                            default_password = id_card[-6:]
                            new_user = User(
                                username=id_card,
                                name=name,
                                role='member'  # 固定为队员
                                )
                            new_user.set_password(default_password)
                            db.session.add(new_user)
                        
                        success += 1
                    except Exception as e:
                        errors.append(f"行{idx+2}: {str(e)}")
                
                db.session.commit()
                
                msg = f'导入完成：成功 {success} 条'
                if errors:
                    msg += f'，失败 {len(errors)} 条'
                    flash(msg, 'warning')
                    flash('<br>'.join(errors[:30]), 'danger')
                else:
                    flash(msg, 'success')
                
                return redirect(url_for('hr.hr_list'))
            except Exception as e:
                flash(f'文件读取失败：{str(e)}', 'danger')
    
    return render_template('hr/import.html')

# 人事模块权限列表
HR_PERMISSIONS = [
    ('view', '查看员工信息', '查看员工列表和详情'),
    ('add', '新增员工', '新增员工记录'),
    ('edit', '编辑员工', '编辑员工信息'),
    ('departure', '员工离职', '标记员工离职'),
    ('import', '批量导入员工', '从Excel导入员工'),
    ('export', '批量导出员工', '导出员工花名册'),
    ('approve', '审核员工注册', '审核待批准的员工注册请求')
]