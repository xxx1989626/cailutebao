#D:\cailu\cailutebao\routes\hr\document.py
import os
import json
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from . import hr_bp
from models import EmployeeDocument, EmploymentCycle, db
from utils import save_uploaded_file, perm, log_action, format_date, parse_date

DOC_TYPES = ['身份证', '保安员证', '消防证', '驾驶证', '上岗证', '健康证', '其他']

# 证件字段中文映射
FIELD_MAP = {
    'doc_type': '证件类型', 'doc_number': '证件号码',
    'issue_date': '发证日期', 'expire_date': '有效期至',
    'front_image': '正面照片', 'back_image': '反面照片',
    'note': '备注'
}

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

def is_admin():
    """判断当前用户是否为管理员（有证件审批权限）"""
    return perm.can('hr.cert_edit') or perm.can('hr.cert_delete')

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
        elif status_filter == 'pending':
            query = query.filter(EmployeeDocument.pending_status == 'pending')

    if doc_type_filter:
        query = query.filter(EmployeeDocument.doc_type == doc_type_filter)

    if search:
        query = query.filter(
            EmploymentCycle.name.like(f'%{search}%') |
            EmploymentCycle.id_card.like(f'%{search}%') |
            EmployeeDocument.doc_number.like(f'%{search}%')
        )

    documents = query.order_by(
        EmployeeDocument.pending_status.asc(),
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
                          search=search,
                          is_admin=is_admin())

@hr_bp.route('/document/add/<int:cycle_id>', methods=['GET', 'POST'])
@login_required
def document_add(cycle_id):
    cycle = EmploymentCycle.query.get_or_404(cycle_id)

    # 水平越权：非管理员只能给自己添加证件
    if cycle.id_card != current_user.username and not perm.can('hr.add'):
        flash('无权为他人添加证件', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))

    if request.method == 'POST':
        doc_type = request.form['doc_type']
        doc_number = request.form.get('doc_number', '').strip()
        issue_date = parse_date(request.form.get('issue_date'))
        expire_date = parse_date(request.form.get('expire_date'))
        note = request.form.get('note', '').strip()

        front_image = None
        if 'front_image' in request.files:
            front_files = request.files.getlist('front_image')
            for front_file in front_files:
                if front_file and front_file.filename:
                    front_image = save_uploaded_file(front_file, module='document', sub_folder=cycle.id_card)
                    break

        back_image = None
        if 'back_image' in request.files:
            back_files = request.files.getlist('back_image')
            for back_file in back_files:
                if back_file and back_file.filename:
                    back_image = save_uploaded_file(back_file, module='document', sub_folder=cycle.id_card)
                    break

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

        # OA流程：管理员直接生效，普通队员需审批
        if is_admin():
            document.pending_status = 'none'
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
        else:
            # 普通队员：新增的证件标记为待审批
            document.pending_status = 'pending'
            db.session.add(document)
            try:
                db.session.commit()
                log_action(
                    action_type='申请添加证件',
                    target_type='EmployeeDocument',
                    target_id=document.id,
                    cycle_id=cycle.id,
                    description=f"队员【{cycle.name}】申请添加{doc_type}，等待审批"
                )
                flash(f'{doc_type}已提交，等待管理员审批', 'info')
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
                          doc_types=DOC_TYPES,
                          is_admin=is_admin())

@hr_bp.route('/document/edit/<int:doc_id>', methods=['GET', 'POST'])
@login_required
def document_edit(doc_id):
    document = EmployeeDocument.query.get_or_404(doc_id)
    cycle = document.cycle

    # 水平越权：非管理员只能编辑自己的证件
    if cycle.id_card != current_user.username and not perm.can('hr.cert_edit'):
        flash('无权编辑他人的证件', 'danger')
        return redirect(url_for('hr.hr_detail', id_card=current_user.username))

    # 正在审批中不允许再次编辑
    if document.pending_status == 'pending':
        flash('该证件有变更正在审批中，暂时无法编辑', 'warning')
        return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))

    if request.method == 'POST':
        # 管理员直接修改生效
        if is_admin():
            document.doc_type = request.form['doc_type']
            document.doc_number = request.form.get('doc_number', '').strip()
            document.issue_date = parse_date(request.form.get('issue_date'))
            document.expire_date = parse_date(request.form.get('expire_date'))
            document.note = request.form.get('note', '').strip()

            if 'front_image' in request.files:
                front_files = request.files.getlist('front_image')
                for front_file in front_files:
                    if front_file and front_file.filename:
                        if document.front_image and os.path.exists(document.front_image):
                            os.remove(document.front_image)
                        document.front_image = save_uploaded_file(front_file, module='document', sub_folder=cycle.id_card)
                        break

            if 'back_image' in request.files:
                back_files = request.files.getlist('back_image')
                for back_file in back_files:
                    if back_file and back_file.filename:
                        if document.back_image and os.path.exists(document.back_image):
                            os.remove(document.back_image)
                        document.back_image = save_uploaded_file(back_file, module='document', sub_folder=cycle.id_card)
                        break

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

        else:
            # 普通队员：将变更存入pending_changes，原数据不动
            new_data = {
                'doc_type': request.form['doc_type'],
                'doc_number': request.form.get('doc_number', '').strip(),
                'issue_date': request.form.get('issue_date'),
                'expire_date': request.form.get('expire_date'),
                'note': request.form.get('note', '').strip(),
                'submitter_name': current_user.name,
            }

            # 处理新上传的图片
            if 'front_image' in request.files:
                front_files = request.files.getlist('front_image')
                for front_file in front_files:
                    if front_file and front_file.filename:
                        new_data['front_image'] = save_uploaded_file(front_file, module='document', sub_folder=cycle.id_card)
                        break

            if 'back_image' in request.files:
                back_files = request.files.getlist('back_image')
                for back_file in back_files:
                    if back_file and back_file.filename:
                        new_data['back_image'] = save_uploaded_file(back_file, module='document', sub_folder=cycle.id_card)
                        break

            # 记录变更对比
            changes = {}
            for field in ['doc_type', 'doc_number', 'issue_date', 'expire_date', 'note']:
                old_val = getattr(document, field)
                new_val = new_data.get(field, '')
                old_str = str(old_val) if old_val else ''
                if old_str != new_val:
                    changes[field] = {'old': old_str, 'new': new_val}

            if 'front_image' in new_data:
                changes['front_image'] = {'old': document.front_image or '', 'new': new_data['front_image']}
            if 'back_image' in new_data:
                changes['back_image'] = {'old': document.back_image or '', 'new': new_data['back_image']}

            if not changes:
                # 清理未使用的上传文件
                for img_key in ['front_image', 'back_image']:
                    if img_key in new_data and new_data[img_key] and os.path.exists(new_data[img_key]):
                        os.remove(new_data[img_key])
                flash('没有检测到变更', 'info')
                return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))

            pending_data = {
                'changes': changes,
                'submitter_name': current_user.name,
                'is_edit': True
            }
            document.pending_changes = json.dumps(pending_data, ensure_ascii=False)
            document.pending_status = 'pending'

            try:
                db.session.commit()
                log_action(
                    action_type='申请修改证件',
                    target_type='EmployeeDocument',
                    target_id=document.id,
                    cycle_id=cycle.id,
                    description=f"队员【{cycle.name}】申请修改{document.doc_type}，等待审批"
                )
                flash('证件变更已提交，等待管理员审批', 'info')
            except Exception as e:
                db.session.rollback()
                flash(f'提交失败：{str(e)}', 'danger')

            return redirect(url_for('hr.hr_detail', id_card=cycle.id_card))

    return render_template('hr/document/edit.html',
                          document=document,
                          doc_types=DOC_TYPES,
                          is_admin=is_admin())

# ==================== 审批路由 ====================

@hr_bp.route('/document/view_change/<int:doc_id>')
@login_required
def document_view_change(doc_id):
    """查看证件变更详情（管理员审批页面）"""
    if not is_admin():
        flash('无权查看审批详情', 'danger')
        return redirect(url_for('hr.document_list'))

    document = EmployeeDocument.query.get_or_404(doc_id)

    if document.pending_status != 'pending':
        flash('该证件没有待审批的变更', 'warning')
        return redirect(url_for('hr.document_list'))

    # 判断是新增还是编辑
    is_add = True
    changes = []
    pending_data = {}

    if document.pending_changes:
        try:
            pending_data = json.loads(document.pending_changes)
            is_add = not pending_data.get('is_edit', False)

            # 构建变更对比列表
            for field, vals in pending_data.get('changes', {}).items():
                label = FIELD_MAP.get(field, field)
                old_val = vals.get('old', '')
                new_val = vals.get('new', '')
                # 图片字段特殊处理
                if field in ('front_image', 'back_image'):
                    old_val = '有照片' if old_val else '无'
                    new_val = '新照片' if new_val else '无'
                changes.append((label, old_val, new_val))
        except:
            pass

    return render_template('hr/document/view_change.html',
                          document=document,
                          doc_types=DOC_TYPES,
                          is_add=is_add,
                          changes=changes,
                          is_admin=True)

@hr_bp.route('/document/approve/<int:doc_id>', methods=['POST'])
@login_required
def document_approve(doc_id):
    """批准证件变更"""
    if not is_admin():
        flash('无权审批', 'danger')
        return redirect(url_for('hr.document_list'))

    document = EmployeeDocument.query.get_or_404(doc_id)
    cycle = document.cycle

    if document.pending_status != 'pending':
        flash('该证件没有待审批的变更', 'warning')
        return redirect(url_for('hr.document_list'))

    try:
        if document.pending_changes:
            # 编辑变更：应用变更到实际字段
            pending_data = json.loads(document.pending_changes)
            for field, vals in pending_data.get('changes', {}).items():
                new_val = vals.get('new', '')
                if field in ('issue_date', 'expire_date'):
                    parsed = parse_date(new_val)
                    setattr(document, field, parsed)
                else:
                    setattr(document, field, new_val)
        # 无论是新增还是编辑，批准后都标记为none（已生效）
        document.pending_status = 'approved'
        document.pending_approved_by = current_user.id
        document.pending_approved_at = datetime.now()
        # 清理旧图片文件（编辑变更中被替换的照片）
        if document.pending_changes:
            try:
                pending_data = json.loads(document.pending_changes)
                for field in ('front_image', 'back_image'):
                    if field in pending_data.get('changes', {}):
                        old_path = pending_data['changes'][field].get('old', '')
                        if old_path and os.path.exists(old_path):
                            os.remove(old_path)
            except:
                pass
        document.pending_changes = None

        db.session.commit()
        log_action(
            action_type='审批证件',
            target_type='EmployeeDocument',
            target_id=document.id,
            cycle_id=cycle.id,
            description=f"批准了队员【{cycle.name}】的{document.doc_type}变更"
        )
        flash(f'已批准 {cycle.name} 的{document.doc_type}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'审批失败：{str(e)}', 'danger')

    return redirect(url_for('hr.document_list'))

@hr_bp.route('/document/reject/<int:doc_id>', methods=['POST'])
@login_required
def document_reject(doc_id):
    """拒绝证件变更"""
    if not is_admin():
        flash('无权审批', 'danger')
        return redirect(url_for('hr.document_list'))

    document = EmployeeDocument.query.get_or_404(doc_id)
    cycle = document.cycle

    if document.pending_status != 'pending':
        flash('该证件没有待审批的变更', 'warning')
        return redirect(url_for('hr.document_list'))

    try:
        if document.pending_changes:
            # 编辑变更被拒绝：清理新上传的图片文件
            try:
                pending_data = json.loads(document.pending_changes)
                for field in ('front_image', 'back_image'):
                    if field in pending_data.get('changes', {}):
                        new_path = pending_data['changes'][field].get('new', '')
                        if new_path and os.path.exists(new_path):
                            os.remove(new_path)
            except:
                pass
            document.pending_changes = None
            document.pending_status = 'rejected'
        else:
            # 新增被拒绝：直接删除记录和图片
            if document.front_image and os.path.exists(document.front_image):
                os.remove(document.front_image)
            if document.back_image and os.path.exists(document.back_image):
                os.remove(document.back_image)
            db.session.delete(document)

        document.pending_approved_by = current_user.id
        document.pending_approved_at = datetime.now()

        db.session.commit()
        log_action(
            action_type='拒绝证件',
            target_type='EmployeeDocument',
            target_id=document.id if document.id else doc_id,
            cycle_id=cycle.id,
            description=f"拒绝了队员【{cycle.name}】的证件变更"
        )
        flash(f'已拒绝 {cycle.name} 的证件变更', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败：{str(e)}', 'danger')

    return redirect(url_for('hr.document_list'))

@hr_bp.route('/document/delete/<int:doc_id>')
@login_required
def document_delete(doc_id):
    document = EmployeeDocument.query.get_or_404(doc_id)
    cycle = document.cycle

    # 水平越权：非管理员只能删除自己的证件
    if cycle.id_card != current_user.username and not perm.can('hr.cert_delete'):
        flash('无权删除他人的证件', 'danger')
        return redirect(url_for('hr.document_list'))
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
