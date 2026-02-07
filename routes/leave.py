from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from models import db, LeaveRecord, EmploymentCycle, OperationLog, Notification, User
from utils import perm, save_uploaded_file, log_action 
from datetime import datetime, date
import json

leave_bp = Blueprint('leave', __name__, url_prefix='/leave')

# 已移除旧的 record_event 函数，直接使用 utils 里的 log_action

def notify_expiring_leaves():
    """该函数应由定时任务调度，在每天 20:00 运行"""
    with current_app.app_context():
        today = date.today()
        expiring = LeaveRecord.query.filter_by(end_date=today, status='请假中').all()
        
        if expiring:
            admins = User.query.filter_by(role='admin').all()
            for leave in expiring:
                msg = f"【到期提醒】{leave.user.name} 的 {leave.leave_type} 预计今日到期，请核实是否销假。"
                for admin in admins:
                    n = Notification(
                        user_id=admin.id,
                        title="请假到期预警",
                        content=msg,
                        related_type='leave',
                        related_id=leave.id
                    )
                    db.session.add(n)
            db.session.commit()

@leave_bp.route('/list')
@perm.require('leave.view')
def leave_list():
    leaves = LeaveRecord.query.order_by(LeaveRecord.start_date.desc()).all()
    return render_template('leave/list.html', leaves=leaves)

@leave_bp.route('/add', methods=['GET', 'POST'])
@perm.require('leave.add')
def add_leave():
    if request.method == 'POST':
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        file_paths = []
        uploaded_files = request.files.getlist('files')
        for file in uploaded_files:
            if file and file.filename:
                path = save_uploaded_file(file, module='leave')
                if path: file_paths.append(path)

        if end_date < start_date:
            flash('错误：结束日期不能早于开始日期', 'danger')
            employees = EmploymentCycle.query.filter_by(status='在职').all()
            return render_template('leave/add.html', employees=employees)
        
        total_days_raw = request.form.get('total_days')
        t_days = float(total_days_raw) if total_days_raw else (end_date - start_date).days + 1

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
        db.session.flush()

        # 修复点：使用统一的 log_action
        desc = f"为 {new_leave.user.name} 登记了 {new_leave.leave_type}，周期：{new_leave.start_date} 至 {new_leave.end_date}"
        log_action(
            action_type="新增请假",
            target_type="LeaveRecord",
            target_id=new_leave.id,
            description=desc,
            user_id=new_leave.user_id
        )

        db.session.commit()
        flash('请假登记成功', 'success')
        return redirect(url_for('leave.leave_list'))
    
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('leave/add.html', employees=employees, form_default_date=current_date)

@leave_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@perm.require('leave.edit')
def edit_leave(id):
    leave = LeaveRecord.query.get_or_404(id)
    employees = EmploymentCycle.query.filter_by(status='在职').all()
    
    if request.method == 'POST':
        old_type = leave.leave_type
        old_end = leave.end_date
        leave.leave_type = request.form.get('leave_type')
        leave.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        leave.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        leave.reason = request.form.get('reason')
        
        current_attachments = list(leave.attachments) if leave.attachments else []
        file_change_note = ""
        
        delete_data = request.form.get('delete_attachments')
        if delete_data:
            paths_to_delete = json.loads(delete_data)
            if paths_to_delete:
                current_attachments = [p for p in current_attachments if p not in paths_to_delete]
                file_change_note += f" 删除了{len(paths_to_delete)}个附件;"
        
        new_files = request.files.getlist('files')
        new_count = 0
        for file in new_files:
            if file and file.filename:
                path = save_uploaded_file(file, module='leave')
                if path:
                    current_attachments.append(path)
                    new_count += 1
        if new_count > 0: file_change_note += f" 新增了{new_count}个附件;"
        
        leave.attachments = current_attachments 
        desc = f"修改了 {leave.user.name} 的请假记录。"
        if old_type != leave.leave_type: desc += f" 类型从 {old_type} 改为 {leave.leave_type};"
        if old_end != leave.end_date: desc += f" 结束日期从 {old_end} 改为 {leave.end_date};"
        desc += file_change_note
        
        # 修复点：使用统一的 log_action
        log_action(
            action_type="修改请假",
            target_type="LeaveRecord",
            target_id=leave.id,
            description=desc,
            user_id=leave.user_id
        )
        
        db.session.commit()
        flash('记录更新成功', 'success')
        return redirect(url_for('leave.leave_list'))

    return render_template('leave/add.html', employees=employees, leave=leave)

@leave_bp.route('/finish/<int:id>', methods=['GET', 'POST'])
@perm.require('leave.edit')
def finish_leave(id):
    leave = LeaveRecord.query.get_or_404(id)
    
    if request.method == 'POST':
        # 从表单获取实际销假日期
        actual_end_str = request.form.get('actual_end_date')
        if not actual_end_str:
            flash('错误：必须选择实际销假日期', 'danger')
            return redirect(url_for('leave.leave_list'))
            
        actual_end_date = datetime.strptime(actual_end_str, '%Y-%m-%d').date()
        
        # 更新记录
        leave.status = '已销假'
        leave.actual_end_date = actual_end_date
        
        # 记录日志
        desc = f"{leave.user.name} 已办理销假，实际结束日期：{actual_end_date}"
        log_action(
            action_type="办理销假",
            target_type="LeaveRecord",
            target_id=leave.id,
            description=desc,
            user_id=leave.user_id
        )
        
        db.session.commit()
        flash(f'{leave.user.name} 的销假手续已完成。', 'success')
        return redirect(url_for('leave.leave_list'))

    return render_template('leave/finish_confirm.html', leave=leave, today=date.today())

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