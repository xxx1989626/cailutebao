import json
from datetime import datetime, timedelta
from flask import request, redirect, url_for, flash
from flask_login import login_required, current_user

from . import hr_bp
from models import EmploymentCycle, db
from utils import save_uploaded_file, perm, log_action

# ==================== 添加档案记录（奖惩、检讨书、保密协议等） ====================
@hr_bp.route('/archive/add/<int:cycle_id>', methods=['POST'])
@login_required
@perm.require('hr.add')
def add_archive(cycle_id):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    
    # 仅在职周期可添加档案
    if cycle.status != '在职':
        flash('仅在职期间可添加档案记录', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    # 获取表单数据
    record_type = request.form['record_type']
    title = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    
    # 处理附件上传
    file_path = None
    if 'archive_file' in request.files and request.files['archive_file'].filename:
        file_path = save_uploaded_file(
            request.files['archive_file'], 
            module='archive', 
            sub_folder=cycle.id_card
        )
    
    # 解析并更新档案JSON
    archives = json.loads(cycle.archives or '{}')
    if 'archive_records' not in archives:
        archives['archive_records'] = []
    
    # 构建新记录
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

    # 记录审计日志
    file_msg = "（含附件）" if file_path else "（无附件）"
    description_log = (
        f"为队员【{cycle.name}】添加了档案记录 | "
        f"类型：{record_type}，标题：{title} {file_msg}，"
        f"内容简述：{description[:30]}{'...' if len(description) > 30 else ''}"
    )

    log_action(
        action_type='添加档案',
        target_type='EmployeeArchive',
        target_id=cycle.id,
        description=description_log,** locals()
    )

    # 提交变更
    try:
        db.session.commit()
        flash('档案记录添加成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'档案保存失败：{str(e)}', 'danger')

    return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))

# 辅助函数：判断时间是否在1小时内
def is_within_hour(date_str):
    if not date_str:
        return False
    try:
        # 清理中文日期格式
        clean_date = str(date_str).replace('年', '-').replace('月', '-').replace('日', '')
        
        # 尝试多种日期格式解析
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
        
        # 计算时间差
        diff = datetime.now() - record_time
        return diff < timedelta(hours=1)
        
    except Exception as e:
        print(f"DEBUG: 时间判断逻辑出错 -> {e}")
        return False

# ==================== 编辑档案记录 ====================
@hr_bp.route('/archive/edit/<int:cycle_id>/<int:record_idx>', methods=['POST'])
@login_required
def edit_archive(cycle_id, record_idx):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    archives = json.loads(cycle.archives or '{}')
    
    # 校验记录是否存在
    if 'archive_records' not in archives or record_idx >= len(archives['archive_records']):
        flash('档案记录不存在', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    record = archives['archive_records'][record_idx]

    # 权限校验：仅创建者1小时内可编辑
    if record['operator_id'] == current_user.id and is_within_hour(record['date']):
        record['type'] = request.form['record_type']
        record['title'] = request.form['title'].strip()
        record['description'] = request.form.get('description', '').strip()
        cycle.archives = json.dumps(archives, ensure_ascii=False)
        db.session.commit()
        flash('档案已更新', 'success')
    else:
        flash('无权修改或已超时（仅创建者1小时内可编辑）', 'danger')
    
    return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))