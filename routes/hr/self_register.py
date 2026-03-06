import json
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from . import hr_bp
from models import EmploymentCycle, User, db
from utils import (
    validate_id_card, get_gender_from_id_card, get_birthday_from_id_card,
    save_uploaded_file, get_ethnic_options, get_politics_options, get_education_options,
    parse_date, today_str, perm, log_action
)
from config import SALARY_MODES, POSITIONS, POSTS

# ==================== 队员自主登记 ====================
@hr_bp.route('/self_register', methods=['GET', 'POST'])
def self_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        id_card = request.form.get('id_card', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # 必填项校验
        if not name or not id_card:
            flash("姓名和身份证号为必填项", "danger")
            return redirect(url_for('hr.self_register'))

        # 从身份证提取信息
        gender = get_gender_from_id_card(id_card)
        birthday = get_birthday_from_id_card(id_card)

        # 处理入职日期
        hire_date_raw = request.form.get('hire_date')
        if hire_date_raw:
            try:
                final_hire_date = datetime.strptime(hire_date_raw, '%Y-%m-%d').date()
            except:
                final_hire_date = datetime.today().date()
        else:
            final_hire_date = datetime.today().date()

        # 处理头像
        photo_path = None
        file_obj = request.files.get('photo')
        if file_obj and file_obj.filename:
            photo_path = save_uploaded_file(file_obj, module='avatar')
        else:
            photo_path = 'uploads/default-avatar.png'

        # 收集其他证书
        other_certs = []
        i = 0
        while f'cert_name_{i}' in request.form:
            c_name = request.form.get(f'cert_name_{i}')
            c_num = request.form.get(f'cert_number_{i}')
            c_date = request.form.get(f'cert_date_{i}')
            if c_name and c_num:
                other_certs.append({'name': c_name, 'number': c_num, 'date': c_date})
            i += 1
        
        # 处理档案JSON
        archives = json.dumps({'other_certificates': other_certs}, ensure_ascii=False) if other_certs else None

        # 创建待审核的入职记录
        new_emp = EmploymentCycle(
            id_card=id_card,
            name=name,
            phone=phone,
            gender=gender,
            birthday=birthday,
            hire_date=final_hire_date,
            status='待审核',
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
            emergency_name=request.form.get('emergency_name'),
            emergency_relation=request.form.get('emergency_relation'),
            emergency_phone=request.form.get('emergency_phone'),
            salary_mode=request.form['salary_mode'],
            position=request.form['position'],
            post=request.form['post'],
            hat_size=request.form.get('hat_size'),
            short_sleeve=request.form.get('short_sleeve'),
            long_sleeve=request.form.get('long_sleeve'),
            winter_uniform=request.form.get('winter_uniform'),
            shoe_size=request.form.get('shoe_size'),
            archives=archives
        )

        try:
            db.session.add(new_emp)
            db.session.commit()
            return render_template('hr/register_success.html')
        except Exception as e:
            db.session.rollback()
            return f"提交失败。详情: {str(e)}", 500

    # GET请求返回登记页面
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

# ==================== 管理员审核 ====================
@hr_bp.route('/approve_pending/<int:id>', methods=['POST'])
@login_required
@perm.require('hr.edit')
def approve_pending(id):
    emp = EmploymentCycle.query.get_or_404(id)
    
    # 状态校验
    if emp.status != '待审核':
        flash('该记录不是待审核状态，无法批准', 'warning')
        return redirect(url_for('hr.hr_list', status='待审核'))
    
    # 重复入职校验
    existing = EmploymentCycle.query.filter(
        EmploymentCycle.id_card == emp.id_card,
        EmploymentCycle.status == '在职'
    ).first()
    if existing:
        flash('身份证已存在于在职员工，无法批准', 'danger')
        return redirect(url_for('hr.hr_list', status='待审核'))
    
    # 变更状态为在职
    emp.status = '在职'
    if not emp.hire_date:
        emp.hire_date = datetime.today().date()
    
    # 自动创建账号
    user_created_msg = ''
    if not User.query.filter_by(username=emp.id_card).first():
        default_password = emp.id_card[-6:]
        new_user = User(
            username=emp.id_card,
            name=emp.name,
            role='member'
        )
        new_user.set_password(default_password)
        db.session.add(new_user)
        user_created_msg = f'（账号已自动创建，默认密码为身份证后6位）'
    else:
        user_created_msg = '（账号已存在，无需重复创建）'

    # 记录审计日志
    log_action(
        action_type='审批入职',
        target_type='Employee',
        target_id=emp.id,
        description=f"批准了自主登记的人员入职：{emp.name} (身份证:{emp.id_card}){user_created_msg}",
        **locals()
    )

    # 提交变更
    try:
        db.session.commit()
        flash(f'员工 {emp.name} 已批准入职！{user_created_msg}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'审批失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_list', status='在职'))

# ==================== 删除待审核记录 ====================
@hr_bp.route('/delete_pending/<int:id>', methods=['POST'])
@login_required
@perm.require('hr.edit')
def delete_pending(id):
    # 仅管理员可删除
    if current_user.role != 'admin':
        flash("只有系统管理员有权执行删除操作", "danger")
        return redirect(url_for('hr.hr_list'))

    # 查找记录
    emp = EmploymentCycle.query.get_or_404(id)
    id_card_to_delete = emp.id_card
    old_status = emp.status
    old_name = emp.name

    # 执行删除
    try:
        # 删除关联账号（如果存在）
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

    return redirect(url_for('hr.hr_list', status=old_status))