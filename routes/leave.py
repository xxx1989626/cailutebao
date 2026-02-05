# routes/leave.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, LeaveRecord, EmploymentCycle
from utils import perm, save_uploaded_file
from datetime import datetime

leave_bp = Blueprint('leave', __name__, url_prefix='/leave')

@leave_bp.route('/list')
@perm.require('leave.view')
def leave_list():
    leaves = LeaveRecord.query.order_by(LeaveRecord.start_date.desc()).all()
    return render_template('leave/list.html', leaves=leaves)

@leave_bp.route('/add', methods=['GET', 'POST'])
@perm.require('leave.add')
def add_leave():
    if request.method == 'POST':
        # 1. 获取字符串数据
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')
        
        # 2. 转换日期并校验
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        # 3. 上传附件
        file_paths = []
        uploaded_files = request.files.getlist('files')
        for file in uploaded_files:
            if file and file.filename:
                path = save_uploaded_file(file, module='leave')
                if path:
                    file_paths.append(path)

        if end_date < start_date:
            flash('错误：结束日期不能早于开始日期', 'danger')
            # 失败后返回，保留当前填写的 employees 数据供重新渲染
            employees = EmploymentCycle.query.filter_by(status='在职').all()
            return render_template('leave/add.html', employees=employees)
        total_days_raw = request.form.get('total_days')
        if total_days_raw:
            t_days = float(total_days_raw)
        else:
            t_days = (end_date - start_date).days + 1  # 包括开始和结束日期
        # 3. 创建记录
        new_leave = LeaveRecord(
            user_id=request.form.get('user_id'),
            leave_type=request.form.get('leave_type'),
            start_date=start_date,
            end_date=end_date,
            total_days=t_days,
            reason=request.form.get('reason'),
            attachments=file_paths,
            status='请假中'
        )
        db.session.add(new_leave)
        db.session.commit()
        flash('请假登记成功', 'success')
        return redirect(url_for('leave.leave_list'))
    
    # --- GET 请求逻辑 ---
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    # 记得传入 today_str 供页面初始化默认日期
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('leave/add.html', employees=employees, form_default_date=current_date)

@leave_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@perm.require('leave.edit')
def edit_leave(id):
    leave = LeaveRecord.query.get_or_404(id)
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    
    if request.method == 'POST':
        leave.leave_type = request.form.get('leave_type')
        leave.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        leave.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        leave.reason = request.form.get('reason')
        
        # --- 编辑模式也需要处理文件上传 ---
        new_files = request.files.getlist('files')
        current_attachments = list(leave.attachments) if leave.attachments else []
        
        for file in new_files:
            if file and file.filename:
                path = save_uploaded_file(file, module='leave')
                if path:
                    current_attachments.append(path)
        
        leave.attachments = current_attachments # 更新附件列表
        # -------------------------------
        
        db.session.commit()
        flash('记录更新成功', 'success')
        return redirect(url_for('leave.leave_list'))

    return render_template('leave/add.html', employees=employees, leave=leave)

# 销假功能：更新状态和实际结束日期
@leave_bp.route('/finish/<int:id>')
@perm.require('leave.edit')
def finish_leave(id):
    leave = LeaveRecord.query.get_or_404(id)
    leave.status = '已销假'
    leave.actual_end_date = datetime.now().date()
    db.session.commit()
    flash(f'{leave.user.name} 的请假已登记销假。', 'success')
    return redirect(url_for('leave.leave_list'))

# 删除功能
@leave_bp.route('/delete/<int:id>')
@perm.require('leave.edit')
def delete_leave(id):
    leave = LeaveRecord.query.get_or_404(id)
    db.session.delete(leave)
    db.session.commit()
    flash('记录已删除', 'info')
    return redirect(url_for('leave.leave_list'))

LEAVE_PERMISSIONS = [
    ('view', '查看请假', '查看全员请假记录'),
    ('add', '登记请假', '新增请假申请'),
    ('edit', '审核销假', '修改记录或办理销假'),
    ('delete', '删除请假', '删除请假记录'),
]
