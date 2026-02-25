import json
from datetime import datetime
from io import BytesIO
import pandas as pd
from flask import request, redirect, url_for, flash, send_file,render_template
from flask_login import login_required

from . import hr_bp
from models import EmploymentCycle, User, db
from utils import (
    validate_id_card, get_gender_from_id_card, get_birthday_from_id_card,
    parse_date, format_date, perm
)

# ==================== 导出员工花名册 ====================
@hr_bp.route('/export')
@login_required
@perm.require('hr.export')
def hr_export():
    status_filter = request.args.get('status', '在职')
    search = request.args.get('search', '').strip()
    
    # 子查询：获取最新入职记录
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
    if status_filter == '在职':
        query = query.filter(EmploymentCycle.status == '在职')
    else:
        query = query.filter(EmploymentCycle.status == '离职')
    
    # 搜索过滤
    if search:
        query = query.filter(
            db.or_(
                EmploymentCycle.name.ilike(f'%{search}%'),
                EmploymentCycle.id_card.ilike(f'%{search}%'),
                EmploymentCycle.phone.ilike(f'%{search}%')
            )
        )
    
    employees = query.all()
    
    # 构建导出数据
    data = []
    for emp in employees:
        # 拼接地址
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
        
        # 工作服尺寸
        uniform = f"帽{emp.hat_size or ''} 短袖{emp.short_sleeve or ''} 长袖{emp.long_sleeve or ''} 冬装{emp.winter_uniform or ''} 鞋{emp.shoe_size or ''}"
        
        # 解析档案JSON
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
            '兵役情况': military,
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
    
    # 生成Excel
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='员工花名册')
    
    output.seek(0)
    
    # 返回文件
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
        # 校验文件
        if 'file' not in request.files:
            flash('未选择文件', 'danger')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('未选择文件', 'danger')
            return redirect(request.url)
        
        if file and file.filename.endswith('.xlsx'):
            try:
                # 读取Excel文件
                df = pd.read_excel(file, dtype={'手机号': str})
                
                # 必填列校验
                required = ['姓名', '身份证号码', '手机号']
                missing = [col for col in required if col not in df.columns]
                if missing:
                    flash(f'缺少必填列：{", ".join(missing)}', 'danger')
                    return redirect(request.url)
                
                success = 0
                errors = []
                
                # 逐行处理
                for idx, row in df.iterrows():
                    try:
                        id_card = str(row['身份证号码']).strip()
                        name = str(row['姓名']).strip()
                        phone = str(row['手机号']).strip()
                        
                        # 处理状态
                        status = str(row.get('状态', '在职')).strip()
                        if status not in ['在职', '离职']:
                            status = '在职'
                        
                        # 处理入职日期
                        hire_date_raw = row.get('入职日期')
                        hire_date = parse_date(hire_date_raw)
                        if not hire_date:
                            errors.append(f"行{idx+2}: {name} 入职日期无效 (原始值: {hire_date_raw})")
                            continue
                        
                        # 重复周期校验
                        if EmploymentCycle.query.filter_by(id_card=id_card, hire_date=hire_date).first():
                            errors.append(f"行{idx+2}: {name} 该周期已存在")
                            continue
                        
                        # 身份证校验
                        if not validate_id_card(id_card):
                            errors.append(f"行{idx+2}: {name} 身份证无效")
                            continue
                        
                        # 处理头像路径
                        raw_photo = row.get('头像路径')
                        if pd.isna(raw_photo) or raw_photo is None:
                            photo_path = 'uploads/default-avatar.png'
                        else:
                            p_str = str(raw_photo).strip()
                            if p_str == "" or p_str.lower() in ['nan', 'none', 'null']:
                                photo_path = 'uploads/default-avatar.png'
                            else:
                                photo_path = p_str

                        # 从身份证提取信息
                        gender = get_gender_from_id_card(id_card)
                        birthday = get_birthday_from_id_card(id_card)
                        
                        # 处理离职日期
                        departure_date = parse_date(row.get('离职日期')) if status == '离职' else None
                        
                        # 创建入职记录
                        cycle = EmploymentCycle(
                            id_card=id_card,
                            name=name,
                            phone=phone,
                            gender=gender,
                            birthday=birthday,
                            hire_date=hire_date,
                            departure_date=departure_date,
                            status=status,
                            ethnic=str(row.get('民族', '')),
                            politics=str(row.get('政治面貌', '')),
                            education=str(row.get('学历', '')),
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
                            military_service=str(row.get('兵役情况', '')).strip().lower() == '是',
                            enlistment_date=parse_date(row.get('入伍日期')),
                            unit_number=str(row.get('部队番号', '')),
                            branch=str(row.get('兵种', '')),
                            discharge_date=parse_date(row.get('退伍日期')),
                            has_license=str(row.get('是否持有驾驶证', '')).strip().lower() == '是',
                            license_date=parse_date(row.get('驾驶证初领日期')),
                            license_type=str(row.get('准驾车型', '')),
                            license_expiry=parse_date(row.get('驾驶证有效期')),
                            has_security_license=str(row.get('是否持有保安员证', '')).strip().lower() == '是',
                            security_license_number=str(row.get('保安员证', '')),
                            security_license_date=parse_date(row.get('保安员证发证日期')),
                            salary_mode=str(row.get('薪资模式', '')),
                            position=str(row.get('职务', '')),
                            post=str(row.get('岗位', '')),
                            emergency_name=str(row.get('紧急联系人姓名', '')),
                            emergency_relation=str(row.get('紧急联系人关系', '')),
                            emergency_phone=str(row.get('紧急联系人电话', '')),
                            hat_size=str(row.get('帽码', '')),
                            short_sleeve=str(row.get('短袖尺码', '')),
                            long_sleeve=str(row.get('长袖尺码', '')),
                            winter_uniform=str(row.get('冬装尺码', '')),
                            shoe_size=str(row.get('鞋码', '')),
                            photo_path=photo_path,
                        )
                        
                        # 处理档案信息
                        archives = {}
                        if row.get('其他证书'):
                            archives['other_certificates'] = []
                        if row.get('档案记录'):
                            archives['archive_records'] = []
                        if row.get('离职原因'):
                            archives['departure_reason'] = str(row['离职原因'])
                        cycle.archives = json.dumps(archives, ensure_ascii=False) if archives else ''
                        
                        db.session.add(cycle)
                        
                        # 自动创建账号（仅在职）
                        if status == '在职' and not User.query.filter_by(username=id_card).first():
                            default_password = id_card[-6:]
                            new_user = User(
                                username=id_card,
                                name=name,
                                role='member'
                            )
                            new_user.set_password(default_password)
                            db.session.add(new_user)
                        
                        success += 1
                    except Exception as e:
                        errors.append(f"行{idx+2}: {str(e)}")
                
                # 提交批量导入
                db.session.commit()
                
                # 返回结果
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
    
    # GET请求返回导入页面
    return render_template('hr/import.html')