#D:\cailu\cailutebao\routes\hr\document.py
import os
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from . import hr_bp
from models import EmployeeDocument, EmploymentCycle, db
from utils import save_uploaded_file, perm, log_action, format_date, parse_date

DOC_TYPES = ['身份证', '保安员证', '消防证', '驾驶证', '上岗证', '健康证', '其他']

def get_doc_status(expire_date):
    if not expire_date:
        return ('', '长期有效')
    days_left = (expire_date - date.today()).days
    if days_left < 0:
        return ('expired', '已过期')
    elif days_left <= 30:
        return ('warning', f'即将过期（{days_left}天后）')
    elif days_left <= 90:
        return ('info', f'{days_left}天后过期')
    return ('', format_date(expire_date))

@hr_bp.route('/document/list')
@login_required
def document_list():
    if not perm.can('hr.view'):
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))
    
    status_filter = request.args.get('status', '')
    doc_type_filter = request.args.get('doc_type', '')
    search = request.args.get('search', '').strip()
    
    query = EmployeeDocument.query.join(EmploymentCycle)
    
    if status_filter:
        if status_filter == 'expired':
            query = query.filter(EmployeeDocument.expire_date < date.today())
        elif status_filter == 'warning':
            query = query.filter(
                EmployeeDocument.expire_date >= date.today(),
                EmployeeDocument.expire_date <= date.today() + timedelta(days=30)
            )
    
    if doc_type_filter:
        query = query.filter(EmployeeDocument.doc_type == doc_type_filter)
    
    if search:
        query = query.filter(
            EmploymentCycle.name.like(f'%{search}%') |
            EmploymentCycle.id_card.like(f'%{search}%') |
            EmployeeDocument.doc_number.like(f'%{search}%')
        )
    
    documents = query.order_by(
        EmployeeDocument.expire_date.is_(None),
        EmployeeDocument.expire_date.asc(),
        EmployeeDocument.created_at.desc()
    ).all()
    
    for doc in documents:
        doc.status_info = get_doc_status(doc.expire_date)
    
    return render_template('hr/document/list.html',
                          documents=documents,
                          doc_types=DOC_TYPES,
                          status_filter=status_filter,
                          doc_type_filter=doc_type_filter,
                          search=search)

@hr_bp.route('/document/add/<int:cycle_id>', methods=['GET', 'POST'])
@login_required
def document_add(cycle_id):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)
    
    if request.method == 'POST':
        doc_type = request.form['doc_type']
        doc_number = request.form.get('doc_number', '').strip()
        issue_date = parse_date(request.form.get('issue_date'))
        expire_date = parse_date(request.form.get('expire_date'))
        note = request.form.get('note', '').strip()
        
        front_image = None
        if 'front_image' in request.files:
            front_file = request.files['front_image']
            if front_file and front_file.filename:
                front_image = save_uploaded_file(front_file, module='document', sub_folder=cycle.id_card)
        
        back_image = None
        if 'back_image' in request.files:
            back_file = request.files['back_image']
            if back_file and back_file.filename:
                back_image = save_uploaded_file(back_file, module='document', sub_folder=cycle.id_card)
        
        document = EmployeeDocument(
            cycle_id=cycle.id,
            doc_type=doc_type,
            doc_number=doc_number,
            issue_date=issue_date,
            expire_date=expire_date,
            front_image=front_image,
            back_image=back_image,
            note=note,
            created_by=current_user.id
        )
        
        db.session.add(document)
        
        try:
            db.session.commit()
            log_action(
                action_type='添加证件',
                target_type='EmployeeDocument',
                target_id=document.id,
                cycle_id=cycle.id,
                description=f"为队员【{cycle.name}】添加了{doc_type}"
            )
            flash(f'{doc_type}添加成功', 'success')
        except Exception as e:
            db.session.rollback()
            if front_image and os.path.exists(front_image):
                os.remove(front_image)
            if back_image and os.path.exists(back_image):
                os.remove(back_image)
            flash(f'保存失败：{str(e)}', 'danger')
        
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    return render_template('hr/document/add.html',
                          cycle=cycle,
                          doc_types=DOC_TYPES)

@hr_bp.route('/document/edit/<int:doc_id>', methods=['GET', 'POST'])
@login_required
@perm.require('hr.cert_edit')
def document_edit(doc_id):
    document = EmployeeDocument.query.get_or_404(doc_id)
    cycle = document.cycle
    
    if request.method == 'POST':
        document.doc_type = request.form['doc_type']
        document.doc_number = request.form.get('doc_number', '').strip()
        document.issue_date = parse_date(request.form.get('issue_date'))
        document.expire_date = parse_date(request.form.get('expire_date'))
        document.note = request.form.get('note', '').strip()
        
        if 'front_image' in request.files:
            front_file = request.files['front_image']
            if front_file and front_file.filename:
                if document.front_image and os.path.exists(document.front_image):
                    os.remove(document.front_image)
                document.front_image = save_uploaded_file(front_file, module='document', sub_folder=cycle.id_card)
        
        if 'back_image' in request.files:
            back_file = request.files['back_image']
            if back_file and back_file.filename:
                if document.back_image and os.path.exists(document.back_image):
                    os.remove(document.back_image)
                document.back_image = save_uploaded_file(back_file, module='document', sub_folder=cycle.id_card)
        
        try:
            db.session.commit()
            log_action(
                action_type='编辑证件',
                target_type='EmployeeDocument',
                target_id=document.id,
                cycle_id=cycle.id,
                description=f"修改了队员【{cycle.name}】的{document.doc_type}"
            )
            flash('证件信息已更新', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'保存失败：{str(e)}', 'danger')
        
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))
    
    return render_template('hr/document/edit.html',
                          document=document,
                          doc_types=DOC_TYPES)

@hr_bp.route('/document/delete/<int:doc_id>')
@login_required
@perm.require('hr.cert_delete')
def document_delete(doc_id):
    document = EmployeeDocument.query.get_or_404(doc_id)
    cycle = document.cycle
    doc_type = document.doc_type
    
    try:
        if document.front_image and os.path.exists(document.front_image):
            os.remove(document.front_image)
        if document.back_image and os.path.exists(document.back_image):
            os.remove(document.back_image)
        
        db.session.delete(document)
        db.session.commit()
        
        log_action(
            action_type='删除证件',
            target_type='EmployeeDocument',
            target_id=doc_id,
            cycle_id=cycle.id,
            description=f"删除了队员【{cycle.name}】的{doc_type}"
        )
        flash('证件已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败：{str(e)}', 'danger')
    
    return redirect(url_for('hr.document_list'))