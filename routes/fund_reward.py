#D:\cailu\cailutebao\routes\fund_reward.py
# 抓狗奖励费模块：出勤登记、交付/损耗登记、经费分账、留存并入总账
# 说明：本模块只引用资金记录，绝不自动写入资金总账（并入总账由用户手动操作）

from io import BytesIO
from datetime import datetime

import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from sqlalchemy import func, extract

from models import (
    db, DogCatch, DogCatchPerson, DogDelivery, DogDeliveryCatch, DogLoss,
    DogSettlement, DogSettlementShare, EmploymentCycle, FundsRecord
)
from utils import perm, log_action, parse_datetime, save_uploaded_file, delete_physical_file

reward_bp = Blueprint('reward', __name__, url_prefix='/fund/reward')

UNIT_PRICE = 20  # 每人每只奖励标准（元）

# 权限定义：查看对全员开放，新增/编辑/删除分别授权
REWARD_PERMISSIONS = [
    ('add', '新增抓狗奖励登记', '新增抓狗出勤、交付、损耗记录及生成分账批次'),
    ('edit', '编辑抓狗奖励登记', '修改出勤/交付/损耗、标记发放、留存并入总账'),
    ('delete', '删除抓狗奖励登记', '删除出勤、交付、损耗记录及分账批次'),
]


def can_add():
    """是否有新增权限（admin 或拥有 reward.add 权限）"""
    return current_user.role == 'admin' or perm.can('reward.add')


def can_edit():
    """是否有编辑权限（admin 或拥有 reward.edit 权限）"""
    return current_user.role == 'admin' or perm.can('reward.edit')


def can_delete():
    """是否有删除权限（admin 或拥有 reward.delete 权限）"""
    return current_user.role == 'admin' or perm.can('reward.delete')


def pool_stats():
    """笼存池统计：抓捕 - 交付 - 损耗 = 笼存"""
    total_catch = db.session.query(func.coalesce(func.sum(DogCatch.dog_count), 0)).scalar() or 0
    total_delivered = db.session.query(func.coalesce(func.sum(DogDelivery.dog_count), 0)).scalar() or 0
    total_loss = db.session.query(func.coalesce(func.sum(DogLoss.dog_count), 0)).scalar() or 0
    return {
        'catch': int(total_catch),
        'delivered': int(total_delivered),
        'loss': int(total_loss),
        'cage': int(total_catch - total_delivered - total_loss),
    }


def catch_years():
    """出勤记录中出现过的年份（降序）"""
    rows = db.session.query(DogCatch.catch_date).all()
    years = sorted({r[0].year for r in rows if r[0]}, reverse=True)
    return years or [datetime.now().year]


def employee_options():
    """参与人候选：仅花名册在职人员（不允许手工填写姓名）"""
    return EmploymentCycle.query.filter(
        EmploymentCycle.status == '在职'
    ).order_by(EmploymentCycle.name).all()


def settlements_of_year(year):
    """按经费到账年份取分账批次；未关联资金记录的批次按创建时间归属"""
    return DogSettlement.query.outerjoin(
        FundsRecord, DogSettlement.fund_record_id == FundsRecord.id
    ).filter(
        db.or_(
            extract('year', FundsRecord.date) == year,
            db.and_(
                DogSettlement.fund_record_id.is_(None),
                extract('year', DogSettlement.created_at) == year,
            ),
        )
    )


# ==================== 出勤登记 ====================
@reward_bp.route('/catch', methods=['GET'])
@login_required
def catch_list():
    year = request.args.get('year', datetime.now().year, type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 20
    query = DogCatch.query.filter(
        extract('year', DogCatch.catch_date) == year
    ).order_by(DogCatch.catch_date.desc(), DogCatch.id.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    catches = pagination.items

    return render_template(
        'fund/reward/catch_list.html',
        active='catch',
        catches=catches,
        pagination=pagination,
        years=catch_years(),
        selected_year=year,
        employees=employee_options(),
        stats=pool_stats(),
        can_add=can_add(),
        can_edit=can_edit(),
        can_delete=can_delete(),
    )


@reward_bp.route('/catch/add', methods=['POST'])
@login_required
def catch_add():
    if not can_add():
        flash('权限不足，无法登记抓狗出勤', 'danger')
        return redirect(url_for('reward.catch_list'))

    catch_date = parse_datetime(request.form.get('catch_date'))
    dog_count = request.form.get('dog_count', type=int) or 0
    employee_ids = sorted({int(x) for x in request.form.getlist('employee_ids') if str(x).isdigit()})

    if not catch_date:
        flash('请选择出勤日期', 'warning')
        return redirect(url_for('reward.catch_list'))
    if dog_count <= 0:
        flash('抓捕只数必须大于 0', 'warning')
        return redirect(url_for('reward.catch_list'))
    if not employee_ids:
        flash('请至少选择一名参与人', 'warning')
        return redirect(url_for('reward.catch_list'))

    employees = EmploymentCycle.query.filter(EmploymentCycle.id.in_(employee_ids)).all()
    if not employees:
        flash('参与人不存在，请重新选择', 'danger')
        return redirect(url_for('reward.catch_list'))

    new_catch = DogCatch(
        catch_date=catch_date,
        dog_count=dog_count,
        remark=request.form.get('remark', '').strip(),
        status='未结算',
        created_by=current_user.id,
    )
    for emp in employees:
        new_catch.persons.append(DogCatchPerson(employee_id=emp.id))

    db.session.add(new_catch)
    db.session.flush()

    names = '、'.join(e.name for e in employees)
    log_action(
        action_type='抓狗出勤登记',
        target_type='DogCatch',
        target_id=new_catch.id,
        description=f"登记 {catch_date} 抓狗出勤，抓捕 {dog_count} 只，参与人：{names}",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash('出勤记录已登记', 'success')
    return redirect(url_for('reward.catch_list', year=catch_date.year))


@reward_bp.route('/catch/edit/<int:catch_id>', methods=['POST'])
@login_required
def catch_edit(catch_id):
    if not can_edit():
        flash('权限不足，无法修改抓狗出勤', 'danger')
        return redirect(url_for('reward.catch_list'))

    c = db.session.get(DogCatch, catch_id)
    if not c:
        flash('出勤记录不存在', 'danger')
        return redirect(url_for('reward.catch_list'))
    if c.status == '已结算':
        flash('该出勤已结算，不能修改', 'warning')
        return redirect(url_for('reward.catch_list'))

    catch_date = parse_datetime(request.form.get('catch_date'))
    dog_count = request.form.get('dog_count', type=int) or 0
    employee_ids = sorted({int(x) for x in request.form.getlist('employee_ids') if str(x).isdigit()})

    if not catch_date or dog_count <= 0 or not employee_ids:
        flash('日期、抓捕只数、参与人均不能为空', 'warning')
        return redirect(url_for('reward.catch_list'))

    # 修改后的抓捕只数不能小于 已损耗 + 已交付（已被交付单占用的狗不能凭空消失）
    min_count = c.loss_count + c.delivered_count
    if dog_count < min_count:
        flash(f'抓捕只数不能小于 已损耗 {c.loss_count} + 已交付 {c.delivered_count} = {min_count} 只', 'warning')
        return redirect(url_for('reward.catch_list'))

    employees = EmploymentCycle.query.filter(EmploymentCycle.id.in_(employee_ids)).all()

    c.catch_date = catch_date
    c.dog_count = dog_count
    c.remark = request.form.get('remark', '').strip()
    c.persons.clear()
    for emp in employees:
        c.persons.append(DogCatchPerson(employee_id=emp.id))

    log_action(
        action_type='抓狗出勤修改',
        target_type='DogCatch',
        target_id=c.id,
        description=f"修改 {catch_date} 抓狗出勤，抓捕 {dog_count} 只，参与人：{'、'.join(e.name for e in employees)}",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash('出勤记录已更新', 'success')
    return redirect(url_for('reward.catch_list', year=catch_date.year))


@reward_bp.route('/catch/delete/<int:catch_id>', methods=['POST'])
@login_required
def catch_delete(catch_id):
    if not can_delete():
        flash('权限不足，无法删除抓狗出勤', 'danger')
        return redirect(url_for('reward.catch_list'))

    c = db.session.get(DogCatch, catch_id)
    if not c:
        flash('出勤记录不存在', 'danger')
        return redirect(url_for('reward.catch_list'))
    if c.status == '已结算':
        flash('该出勤已结算，不能删除', 'warning')
        return redirect(url_for('reward.catch_list'))
    if c.delivered_count > 0:
        flash('该出勤已有交付记录关联（已交付 %d 只），请先删除对应交付单' % c.delivered_count, 'warning')
        return redirect(url_for('reward.catch_list'))

    log_action(
        action_type='抓狗出勤删除',
        target_type='DogCatch',
        target_id=c.id,
        description=f"删除 {c.catch_date} 抓狗出勤记录（抓捕 {c.dog_count} 只）",
        cycle_id=current_user.id,
    )
    db.session.delete(c)
    db.session.commit()
    flash('出勤记录已删除（归属损耗一并删除）', 'warning')
    return redirect(url_for('reward.catch_list'))


# ==================== 交付与损耗 ====================
@reward_bp.route('/delivery', methods=['GET'])
@login_required
def delivery_list():
    year = request.args.get('year', datetime.now().year, type=int)
    deliveries = DogDelivery.query.filter(
        extract('year', DogDelivery.delivery_date) == year
    ).order_by(DogDelivery.delivery_date.desc(), DogDelivery.id.desc()).all()
    losses = DogLoss.query.filter(
        extract('year', DogLoss.loss_date) == year
    ).order_by(DogLoss.loss_date.desc(), DogLoss.id.desc()).all()

    # 损耗可归属的出勤：未结算出勤（损耗只发生在笼中的狗）
    lossable_catches = DogCatch.query.filter(
        DogCatch.status == '未结算'
    ).order_by(DogCatch.catch_date.desc()).all()

    # 可关联交付的出勤：未结算且有未交付结余
    allocatable_catches = [c for c in lossable_catches if c.undelivered_count > 0]

    # 交付结算状态：delivery_id -> 分账批次（被引用即视为经费已到账结算）
    delivery_settle_map = {}
    for s in DogSettlement.query.all():
        for did in (s.delivery_ids or []):
            delivery_settle_map[did] = s

    rows = db.session.query(DogDelivery.delivery_date).all() + db.session.query(DogLoss.loss_date).all()
    years = sorted({r[0].year for r in rows if r[0]}, reverse=True) or [year]

    return render_template(
        'fund/reward/delivery_list.html',
        active='delivery',
        deliveries=deliveries,
        losses=losses,
        lossable_catches=lossable_catches,
        allocatable_catches=allocatable_catches,
        delivery_settle_map=delivery_settle_map,
        years=years,
        selected_year=year,
        stats=pool_stats(),
        can_add=can_add(),
        can_edit=can_edit(),
        can_delete=can_delete(),
    )


@reward_bp.route('/delivery/add', methods=['POST'])
@login_required
def delivery_add():
    if not can_add():
        flash('权限不足，无法登记交付记录', 'danger')
        return redirect(url_for('reward.delivery_list'))

    delivery_date = parse_datetime(request.form.get('delivery_date'))
    dog_count = request.form.get('dog_count', type=int) or 0
    if not delivery_date or dog_count <= 0:
        flash('交付日期与交付只数必须填写，且只数大于 0', 'warning')
        return redirect(url_for('reward.delivery_list'))

    # 解析出勤分配：alloc_{catch_id} = 该出勤贡献的只数
    allocs = {}
    for key in request.form:
        if key.startswith('alloc_') and key[6:].isdigit():
            cnt = request.form.get(key, type=int) or 0
            if cnt > 0:
                allocs[int(key[6:])] = cnt
    if not allocs:
        flash('请勾选本次交付的狗来自哪些出勤，并逐条填写分配只数', 'warning')
        return redirect(url_for('reward.delivery_list'))

    # 校验：出勤存在且未结算（分配只数不做限制，交付只数以送狗单据为准）
    catch_map = {c.id: c for c in DogCatch.query.filter(DogCatch.id.in_(allocs.keys())).all()}
    for cid, cnt in allocs.items():
        c = catch_map.get(cid)
        if not c:
            flash('关联的出勤记录不存在，请刷新后重试', 'danger')
            return redirect(url_for('reward.delivery_list'))
        if c.status == '已结算':
            flash(f'{c.catch_date} 的出勤已结算，不能再关联交付', 'warning')
            return redirect(url_for('reward.delivery_list'))
    total_alloc = sum(allocs.values())
    if total_alloc != dog_count:
        flash(f'各出勤分配合计 {total_alloc} 只，与交付只数（单据）{dog_count} 不一致（已按单据 {dog_count} 只登记，分配仅供参考，后续可自行排查）', 'warning')

    is_reward_flag = request.form.get('is_reward') is not None  # checkbox 未勾选时字段不存在 → False

    attachment_paths = []
    for file in request.files.getlist('attachment'):
        if file and file.filename:
            path = save_uploaded_file(file, module='reward', sub_folder='delivery')
            if path:
                attachment_paths.append(path)

    record = DogDelivery(
        delivery_date=delivery_date,
        dog_count=dog_count,  # 以送狗单据为准
        receiver=request.form.get('receiver', '').strip(),
        remark=request.form.get('remark', '').strip(),
        attachment=attachment_paths,
        is_reward=is_reward_flag,
        created_by=current_user.id,
    )
    for cid, cnt in allocs.items():
        record.delivery_links.append(DogDeliveryCatch(catch_id=cid, dog_count=cnt))
    db.session.add(record)
    db.session.flush()

    alloc_desc = '、'.join(
        f"{catch_map[cid].catch_date}({cnt}只)" for cid, cnt in sorted(allocs.items())
    )
    log_action(
        action_type='狗只交付登记',
        target_type='DogDelivery',
        target_id=record.id,
        description=f"登记 {delivery_date} 交付 {dog_count} 只，接收方：{record.receiver or '未填写'}，来源出勤：{alloc_desc}，凭证 {len(attachment_paths)} 张",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash('交付记录已登记', 'success')
    return redirect(url_for('reward.delivery_list', year=delivery_date.year))


@reward_bp.route('/delivery/delete/<int:delivery_id>', methods=['POST'])
@login_required
def delivery_delete(delivery_id):
    if not can_delete():
        flash('权限不足，无法删除交付记录', 'danger')
        return redirect(url_for('reward.delivery_list'))

    record = db.session.get(DogDelivery, delivery_id)
    if not record:
        flash('交付记录不存在', 'danger')
        return redirect(url_for('reward.delivery_list'))

    # 已被分账批次引用（经费已到账结算）的交付不能删除
    for s in DogSettlement.query.all():
        if record.id in (s.delivery_ids or []):
            flash(f'该交付已被分账批次 #{s.id} 引用（经费已结算），不能删除', 'warning')
            return redirect(url_for('reward.delivery_list'))

    # 一并清理凭证文件
    for path in (record.attachment or []):
        delete_physical_file(path)

    log_action(
        action_type='狗只交付删除',
        target_type='DogDelivery',
        target_id=record.id,
        description=f"删除 {record.delivery_date} 交付记录（{record.dog_count} 只）",
        cycle_id=current_user.id,
    )
    db.session.delete(record)
    db.session.commit()
    flash('交付记录已删除', 'warning')
    return redirect(url_for('reward.delivery_list'))


@reward_bp.route('/delivery/edit/<int:delivery_id>', methods=['POST'])
@login_required
def delivery_edit(delivery_id):
    """交付编辑：允许修改日期、只数、接收方、凭证、is_reward、重新分配来源出勤"""
    if not can_edit():
        flash('权限不足，无法修改交付记录', 'danger')
        return redirect(url_for('reward.delivery_list'))

    record = db.session.get(DogDelivery, delivery_id)
    if not record:
        flash('交付记录不存在', 'danger')
        return redirect(url_for('reward.delivery_list'))

    # 已被分账批次引用的交付不能编辑（经费已结算）
    for s in DogSettlement.query.all():
        if record.id in (s.delivery_ids or []):
            flash(f'该交付已被分账批次 #{s.id} 引用（经费已结算），不能编辑', 'warning')
            return redirect(url_for('reward.delivery_list'))

    delivery_date = parse_datetime(request.form.get('delivery_date'))
    if not delivery_date:
        flash('请选择交付时间', 'warning')
        return redirect(url_for('reward.delivery_list'))

    # 解析出勤分配
    dog_count = request.form.get('dog_count', type=int) or 0
    if dog_count <= 0:
        flash('请填写交付只数（单据为准）', 'warning')
        return redirect(url_for('reward.delivery_list'))

    allocs = {}
    for key in request.form:
        if key.startswith('alloc_') and key[6:].isdigit():
            cnt = request.form.get(key, type=int) or 0
            if cnt > 0:
                allocs[int(key[6:])] = cnt
    if not allocs:
        flash('请勾选本次交付的狗来自哪些出勤，并逐条填写分配只数', 'warning')
        return redirect(url_for('reward.delivery_list'))

    # 校验：出勤存在且未结算（分配只数不做限制，交付只数以送狗单据为准）
    catch_map = {c.id: c for c in DogCatch.query.filter(DogCatch.id.in_(allocs.keys())).all()}
    for cid, cnt in allocs.items():
        c = catch_map.get(cid)
        if not c:
            flash('关联的出勤记录不存在，请刷新后重试', 'danger')
            return redirect(url_for('reward.delivery_list'))
        if c.status == '已结算':
            flash(f'{c.catch_date} 的出勤已结算，不能再关联交付', 'warning')
            return redirect(url_for('reward.delivery_list'))

    is_reward_flag = request.form.get('is_reward') is not None
    total_alloc = sum(allocs.values())
    if total_alloc != dog_count:
        flash(f'各出勤分配合计 {total_alloc} 只，与交付只数（单据）{dog_count} 不一致（已按单据 {dog_count} 只登记，分配仅供参考）', 'warning')

    # 保留未删除的已有凭证
    existing_attachments = list(record.attachment or [])
    remove_paths = request.form.getlist('remove_attachment')
    for p in remove_paths:
        if p in existing_attachments:
            existing_attachments.remove(p)
            delete_physical_file(p)

    # 新增上传的凭证
    for file in request.files.getlist('attachment'):
        if file and file.filename:
            path = save_uploaded_file(file, module='reward', sub_folder='delivery')
            if path:
                existing_attachments.append(path)

    record.delivery_date = delivery_date
    record.dog_count = dog_count  # 以送狗单据为准
    record.receiver = request.form.get('receiver', '').strip()
    record.remark = request.form.get('remark', '').strip()
    record.is_reward = is_reward_flag
    record.attachment = existing_attachments

    # 重新写入分配明细
    record.delivery_links.clear()
    for cid, cnt in allocs.items():
        record.delivery_links.append(DogDeliveryCatch(catch_id=cid, dog_count=cnt))

    alloc_desc = '、'.join(
        f"{catch_map[cid].catch_date}({cnt}只)" for cid, cnt in sorted(allocs.items())
    )
    log_action(
        action_type='狗只交付修改',
        target_type='DogDelivery',
        target_id=record.id,
        description=f"修改 {delivery_date} 交付 {total_alloc} 只，接收方：{record.receiver or '未填写'}，来源出勤：{alloc_desc}，计酬：{'是' if is_reward_flag else '否'}",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash('交付记录已更新', 'success')
    return redirect(url_for('reward.delivery_list', year=delivery_date.year))


@reward_bp.route('/loss/add', methods=['POST'])
@login_required
def loss_add():
    if not can_add():
        flash('权限不足，无法登记损耗', 'danger')
        return redirect(url_for('reward.delivery_list'))

    loss_date = parse_date(request.form.get('loss_date'))
    dog_count = request.form.get('dog_count', type=int) or 0
    catch_id = request.form.get('catch_id', type=int)

    if not loss_date or dog_count <= 0 or not catch_id:
        flash('损耗日期、只数、归属出勤均不能为空', 'warning')
        return redirect(url_for('reward.delivery_list'))

    c = db.session.get(DogCatch, catch_id)
    if not c:
        flash('归属的出勤记录不存在', 'danger')
        return redirect(url_for('reward.delivery_list'))
    if c.status == '已结算':
        flash('该出勤已结算，不能再登记损耗', 'warning')
        return redirect(url_for('reward.delivery_list'))
    # 笼中剩余 = 抓捕 - 已交付 - 已损耗；损耗不能超过笼中剩余
    cage_remain = c.dog_count - c.delivered_count - c.loss_count
    if dog_count > cage_remain:
        flash(f'{c.catch_date} 出勤笼中剩余 {max(cage_remain, 0)} 只（抓捕 {c.dog_count} − 已交付 {c.delivered_count} − 已损耗 {c.loss_count}），本次损耗 {dog_count} 只超出', 'warning')
        return redirect(url_for('reward.delivery_list'))

    record = DogLoss(
        loss_date=loss_date,
        dog_count=dog_count,
        reason=request.form.get('reason', '其他'),
        catch_id=catch_id,
        remark=request.form.get('remark', '').strip(),
        created_by=current_user.id,
    )
    db.session.add(record)
    db.session.flush()

    log_action(
        action_type='狗只损耗登记',
        target_type='DogLoss',
        target_id=record.id,
        description=f"登记 {loss_date} 损耗 {dog_count} 只（{record.reason}），归属出勤：{c.catch_date}",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash('损耗记录已登记，该次出勤计酬只数已同步调整', 'success')
    return redirect(url_for('reward.delivery_list', year=loss_date.year))


@reward_bp.route('/loss/delete/<int:loss_id>', methods=['POST'])
@login_required
def loss_delete(loss_id):
    if not can_delete():
        flash('权限不足，无法删除损耗记录', 'danger')
        return redirect(url_for('reward.delivery_list'))

    record = db.session.get(DogLoss, loss_id)
    if not record:
        flash('损耗记录不存在', 'danger')
        return redirect(url_for('reward.delivery_list'))
    if record.catch and record.catch.status == '已结算':
        flash('该损耗归属的出勤已结算，不能删除', 'warning')
        return redirect(url_for('reward.delivery_list'))

    log_action(
        action_type='狗只损耗删除',
        target_type='DogLoss',
        target_id=record.id,
        description=f"删除 {record.loss_date} 损耗记录（{record.dog_count} 只）",
        cycle_id=current_user.id,
    )
    db.session.delete(record)
    db.session.commit()
    flash('损耗记录已删除', 'warning')
    return redirect(url_for('reward.delivery_list'))


# ==================== 经费分账 ====================
@reward_bp.route('/settle', methods=['GET', 'POST'])
@login_required
def settle_list():
    if request.method == 'POST':
        if not can_add():
            flash('权限不足，无法生成分账', 'danger')
            return redirect(url_for('reward.settle_list'))

        # ---------- 链式选择：交付单（必选其一入口） ----------
        delivery_ids = sorted({int(x) for x in request.form.getlist('delivery_ids') if str(x).isdigit()})
        # 兜底直选出勤（用于没有交付记录的历史出勤）
        direct_catch_ids = sorted({int(x) for x in request.form.getlist('catch_ids') if str(x).isdigit()})
        if not delivery_ids and not direct_catch_ids:
            flash('请勾选交付记录，或直接勾选未结算出勤', 'warning')
            return redirect(url_for('reward.settle_list'))

        # 校验所选交付单存在且未被其他批次引用（经费只结算一次）
        deliveries = DogDelivery.query.filter(DogDelivery.id.in_(delivery_ids)).all() if delivery_ids else []
        if len(deliveries) != len(delivery_ids):
            flash('部分交付记录不存在，请刷新后重试', 'danger')
            return redirect(url_for('reward.settle_list'))
        referenced_ids = set()
        for s in DogSettlement.query.all():
            referenced_ids.update(s.delivery_ids or [])
        dup = referenced_ids.intersection(delivery_ids)
        if dup:
            flash('所选交付中已有被其他分账批次结算过的，请刷新后重试', 'warning')
            return redirect(url_for('reward.settle_list'))

        # 由交付链路推导出勤（已结算的出勤跳过，其奖励已随先前批次发放）
        derived_catch_ids = set()
        for d in deliveries:
            for link in d.delivery_links:
                if link.catch and link.catch.status == '未结算':
                    derived_catch_ids.add(link.catch_id)

        # 合并直选出勤（同样只允许未结算）
        all_catch_ids = sorted(derived_catch_ids.union(direct_catch_ids))
        if not all_catch_ids:
            flash('交付关联的出勤均已结算，且未直选其他未结算出勤，无可结算对象', 'warning')
            return redirect(url_for('reward.settle_list'))

        catches = DogCatch.query.filter(DogCatch.id.in_(all_catch_ids)).all()
        if len(catches) != len(all_catch_ids):
            flash('部分出勤记录不存在，请刷新后重试', 'danger')
            return redirect(url_for('reward.settle_list'))
        if any(c.status == '已结算' for c in catches):
            flash('所选出勤中存在已结算记录，请刷新后重试', 'warning')
            return redirect(url_for('reward.settle_list'))

        # 关联资金记录（可空）
        fund_record_id = request.form.get('fund_record_id', type=int)
        fund_record = db.session.get(FundsRecord, fund_record_id) if fund_record_id else None

        # 到账金额：优先表单输入，未填写时取关联资金记录金额
        raw_received = request.form.get('total_received', '').strip()
        if raw_received:
            try:
                total_received = float(raw_received)
            except ValueError:
                flash('到账金额格式不正确', 'warning')
                return redirect(url_for('reward.settle_list'))
        else:
            total_received = float(fund_record.amount) if fund_record else 0.0

        # 服务端重新计算每人计酬只数（不信任前端）
        person_counts = {}
        for c in catches:
            for p in c.persons:
                person_counts[p.employee_id] = person_counts.get(p.employee_id, 0) + c.payable_count

        if not person_counts:
            flash('所选出勤没有参与人，无法生成分账', 'warning')
            return redirect(url_for('reward.settle_list'))

        # 每人金额：默认 计酬只数 × 20，可按人单独修改
        total_paid = 0.0
        share_rows = []
        for emp_id, count in person_counts.items():
            raw_amount = request.form.get(f'amount_{emp_id}', '').strip()
            try:
                amount = float(raw_amount) if raw_amount else count * UNIT_PRICE
            except ValueError:
                amount = count * UNIT_PRICE
            amount = round(max(amount, 0), 2)
            total_paid += amount
            share_rows.append(DogSettlementShare(
                employee_id=emp_id,
                dog_count=count,
                amount=amount,
                is_paid=False,
            ))

        total_paid = round(total_paid, 2)
        retained = round(total_received - total_paid, 2)

        settlement = DogSettlement(
            fund_record_id=fund_record.id if fund_record else None,
            total_received=round(total_received, 2),
            total_paid=total_paid,
            retained=retained,
            is_transferred=False,
            catch_ids=all_catch_ids,
            delivery_ids=delivery_ids,
            created_by=current_user.id,
        )
        for row in share_rows:
            settlement.shares.append(row)

        # 标记出勤为已结算
        for c in catches:
            c.status = '已结算'

        db.session.add(settlement)
        db.session.flush()

        log_action(
            action_type='抓狗经费分账',
            target_type='DogSettlement',
            target_id=settlement.id,
            description=(
                f"生成分账批次：交付 {len(deliveries)} 单、出勤 {len(catches)} 次，"
                f"到账 {settlement.total_received:.2f} 元，"
                f"分账合计 {settlement.total_paid:.2f} 元，留存 {settlement.retained:.2f} 元"
            ),
            cycle_id=current_user.id,
        )
        db.session.commit()
        flash('分账批次已生成', 'success')
        return redirect(url_for('reward.settle_detail', settlement_id=settlement.id))

    # ---------- GET ----------
    unsettled = DogCatch.query.filter_by(status='未结算').order_by(
        DogCatch.catch_date.asc(), DogCatch.id.asc()
    ).all()

    # 供页面 JS 计算用的数据
    catch_data = {}
    for c in unsettled:
        catch_data[str(c.id)] = {
            'date': c.catch_date.isoformat() if c.catch_date else '',
            'count': c.dog_count,
            'loss': c.loss_count,
            'payable': c.payable_count,
            'persons': [
                {'id': p.employee_id,
                 'name': (p.employee.name if p.employee else '未知') +
                         ('（离职）' if p.employee and p.employee.status == '离职' else '')}
                for p in c.persons
            ],
        }

    fund_records = FundsRecord.query.filter(
        FundsRecord.amount > 0
    ).order_by(FundsRecord.date.desc(), FundsRecord.id.desc()).limit(300).all()

    # 可结算交付单：未被任何分账批次引用 + 走奖励费通道（不计酬交付不进分账）
    referenced_ids = set()
    for s in DogSettlement.query.all():
        referenced_ids.update(s.delivery_ids or [])
    deliveries_open = [d for d in DogDelivery.query.order_by(
        DogDelivery.delivery_date.asc(), DogDelivery.id.asc()).all()
        if d.id not in referenced_ids and d.is_reward is not False]

    # 交付单 JS 数据：含来源出勤明细（链式带出参与人）
    delivery_data = {}
    for d in deliveries_open:
        delivery_data[str(d.id)] = {
            'date': d.delivery_date.isoformat() if d.delivery_date else '',
            'count': d.dog_count,
            'receiver': d.receiver or '',
            'catches': [
                {
                    'id': l.catch_id,
                    'date': l.catch.catch_date.isoformat() if l.catch and l.catch.catch_date else '',
                    'payable': l.catch.payable_count if l.catch else 0,
                    'settled': bool(l.catch and l.catch.status == '已结算'),
                    'persons': [
                        {'id': p.employee_id,
                         'name': (p.employee.name if p.employee else '未知') +
                                 ('（离职）' if p.employee and p.employee.status == '离职' else '')}
                        for p in (l.catch.persons if l.catch else [])
                    ],
                }
                for l in d.delivery_links if l.catch
            ],
        }

    settlements = DogSettlement.query.order_by(DogSettlement.id.desc()).limit(50).all()

    pending_retained = db.session.query(
        func.coalesce(func.sum(DogSettlement.retained), 0)
    ).filter(DogSettlement.is_transferred.is_(False)).scalar() or 0

    return render_template(
        'fund/reward/settle.html',
        active='settle',
        unsettled=unsettled,
        catch_data=catch_data,
        deliveries_open=deliveries_open,
        delivery_data=delivery_data,
        fund_records=fund_records,
        settlements=settlements,
        pending_retained=pending_retained,
        unit_price=UNIT_PRICE,
        can_add=can_add(),
        can_edit=can_edit(),
        can_delete=can_delete(),
    )


@reward_bp.route('/settle/<int:settlement_id>')
@login_required
def settle_detail(settlement_id):
    settlement = db.session.get(DogSettlement, settlement_id)
    if not settlement:
        flash('分账批次不存在', 'danger')
        return redirect(url_for('reward.settle_list'))

    # 归属出勤（本批包含的）
    catch_ids = settlement.catch_ids or []
    catches = DogCatch.query.filter(DogCatch.id.in_(catch_ids)).order_by(DogCatch.catch_date).all() if catch_ids else []

    # 本批关联的交付单
    d_ids = settlement.delivery_ids or []
    deliveries = DogDelivery.query.filter(DogDelivery.id.in_(d_ids)).order_by(DogDelivery.delivery_date).all() if d_ids else []

    return render_template(
        'fund/reward/settle_detail.html',
        active='settle',
        settlement=settlement,
        catches=catches,
        deliveries=deliveries,
        can_add=can_add(),
        can_edit=can_edit(),
        can_delete=can_delete(),
    )


@reward_bp.route('/settle/<int:settlement_id>/share/<int:employee_id>/toggle_paid', methods=['POST'])
@login_required
def settle_toggle_paid(settlement_id, employee_id):
    if not can_edit():
        flash('权限不足，无法修改发放状态', 'danger')
        return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))

    share = DogSettlementShare.query.filter_by(
        settlement_id=settlement_id, employee_id=employee_id
    ).first()
    if not share:
        flash('分账明细不存在', 'danger')
        return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))

    share.is_paid = not share.is_paid
    share.paid_date = datetime.now().date() if share.is_paid else None

    name = share.employee.name if share.employee else '未知'
    log_action(
        action_type='抓狗分账发放确认' if share.is_paid else '抓狗分账发放撤销',
        target_type='DogSettlement',
        target_id=settlement_id,
        description=f"{name} 分账 {share.amount:.2f} 元{'已发放' if share.is_paid else '改为未发放'}",
        cycle_id=current_user.id,
    )
    db.session.commit()
    return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))


@reward_bp.route('/settle/<int:settlement_id>/pay_all', methods=['POST'])
@login_required
def settle_pay_all(settlement_id):
    if not can_edit():
        flash('权限不足，无法修改发放状态', 'danger')
        return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))

    settlement = db.session.get(DogSettlement, settlement_id)
    if not settlement:
        flash('分账批次不存在', 'danger')
        return redirect(url_for('reward.settle_list'))

    today = datetime.now().date()
    count = 0
    for share in settlement.shares:
        if not share.is_paid:
            share.is_paid = True
            share.paid_date = today
            count += 1

    log_action(
        action_type='抓狗分账批量发放',
        target_type='DogSettlement',
        target_id=settlement.id,
        description=f"批次 {settlement.id} 共 {count} 人标记为已发放",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash(f'已标记 {count} 人为已发放', 'success')
    return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))


@reward_bp.route('/settle/<int:settlement_id>/transfer', methods=['POST'])
@login_required
def settle_transfer(settlement_id):
    """留存并入总账标记（仅标记，不写入资金记录；归零后不再计入未并入留存）"""
    if not can_edit():
        flash('权限不足，无法修改并入状态', 'danger')
        return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))

    settlement = db.session.get(DogSettlement, settlement_id)
    if not settlement:
        flash('分账批次不存在', 'danger')
        return redirect(url_for('reward.settle_list'))

    settlement.is_transferred = not settlement.is_transferred
    settlement.transferred_at = datetime.now() if settlement.is_transferred else None

    action = '留存并入总账' if settlement.is_transferred else '取消并入总账'
    log_action(
        action_type=action,
        target_type='DogSettlement',
        target_id=settlement.id,
        description=f"批次 {settlement.id} 留存 {settlement.retained:.2f} 元{action}",
        cycle_id=current_user.id,
    )
    db.session.commit()
    flash(f'{action}成功' + ('，该笔留存已从未并入合计中归零' if settlement.is_transferred else ''), 'success')
    return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))


@reward_bp.route('/settle/<int:settlement_id>/delete', methods=['POST'])
@login_required
def settle_delete(settlement_id):
    if not can_delete():
        flash('权限不足，无法删除分账批次', 'danger')
        return redirect(url_for('reward.settle_detail', settlement_id=settlement_id))

    settlement = db.session.get(DogSettlement, settlement_id)
    if not settlement:
        flash('分账批次不存在', 'danger')
        return redirect(url_for('reward.settle_list'))

    # 释放出勤记录，恢复为未结算
    for cid in (settlement.catch_ids or []):
        c = db.session.get(DogCatch, cid)
        if c:
            c.status = '未结算'

    log_action(
        action_type='抓狗分账删除',
        target_type='DogSettlement',
        target_id=settlement.id,
        description=f"删除分账批次 {settlement.id}，关联出勤已恢复为未结算",
        cycle_id=current_user.id,
    )
    db.session.delete(settlement)
    db.session.commit()
    flash('分账批次已删除，关联出勤已恢复为未结算', 'warning')
    return redirect(url_for('reward.settle_list'))


# ==================== 年度汇总 ====================
@reward_bp.route('/list')
@login_required
def reward_list():
    year = request.args.get('year', datetime.now().year, type=int)

    catches = DogCatch.query.filter(
        extract('year', DogCatch.catch_date) == year
    ).order_by(DogCatch.catch_date.asc()).all()
    deliveries = DogDelivery.query.filter(
        extract('year', DogDelivery.delivery_date) == year
    ).all()
    losses = DogLoss.query.filter(
        extract('year', DogLoss.loss_date) == year
    ).all()
    settlements = settlements_of_year(year).order_by(DogSettlement.id.desc()).all()

    # 个人统计：出勤参与次数 + 分账金额（含已发/未发）
    stats_map = {}

    def ensure(emp_id, name, status=''):
        if emp_id not in stats_map:
            stats_map[emp_id] = {
                'name': name, 'status': status, 'times': 0, 'dog_count': 0,
                'amount': 0.0, 'paid': 0.0, 'unpaid': 0.0,
            }
        elif status and not stats_map[emp_id]['status']:
            stats_map[emp_id]['status'] = status
        return stats_map[emp_id]

    for c in catches:
        for p in c.persons:
            emp = p.employee
            st = ensure(p.employee_id, emp.name if emp else '未知', emp.status if emp else '')
            st['times'] += 1

    for s in settlements:
        for sh in s.shares:
            emp = sh.employee
            st = ensure(sh.employee_id, emp.name if emp else '未知', emp.status if emp else '')
            st['dog_count'] += sh.dog_count or 0
            st['amount'] += sh.amount or 0
            if sh.is_paid:
                st['paid'] += sh.amount or 0
            else:
                st['unpaid'] += sh.amount or 0

    person_stats = sorted(stats_map.values(), key=lambda x: x['amount'], reverse=True)

    summary = {
        'catch': sum(c.dog_count or 0 for c in catches),
        'delivered': sum(d.dog_count or 0 for d in deliveries),
        'loss': sum(l.dog_count or 0 for l in losses),
        'received': sum(s.total_received or 0 for s in settlements),
        'paid': sum(s.total_paid or 0 for s in settlements),
        'retained': sum(s.retained or 0 for s in settlements),
        'pending_retained': sum((s.retained or 0) for s in settlements if not s.is_transferred),
        'paid_out': sum(sh.amount or 0 for s in settlements for sh in s.shares if sh.is_paid),
    }

    years = sorted(set(catch_years()) | {datetime.now().year}, reverse=True)

    return render_template(
        'fund/reward/list.html',
        active='list',
        selected_year=year,
        years=years,
        catches=catches,
        deliveries=deliveries,
        losses=losses,
        settlements=settlements,
        person_stats=person_stats,
        summary=summary,
        can_add=can_add(),
        can_edit=can_edit(),
        can_delete=can_delete(),
    )


@reward_bp.route('/export')
@login_required
def reward_export():
    year = request.args.get('year', datetime.now().year, type=int)

    catches = DogCatch.query.filter(
        extract('year', DogCatch.catch_date) == year
    ).order_by(DogCatch.catch_date.asc()).all()
    deliveries = DogDelivery.query.filter(
        extract('year', DogDelivery.delivery_date) == year
    ).order_by(DogDelivery.delivery_date.asc()).all()
    losses = DogLoss.query.filter(
        extract('year', DogLoss.loss_date) == year
    ).order_by(DogLoss.loss_date.asc()).all()
    settlements = settlements_of_year(year).order_by(DogSettlement.id.asc()).all()

    catch_rows = []
    for c in catches:
        catch_rows.append({
            '日期': c.catch_date.strftime('%Y-%m-%d') if c.catch_date else '',
            '抓捕只数': c.dog_count,
            '参与人': '、'.join(
                (p.employee.name if p.employee else '未知') +
                ('（离职）' if p.employee and p.employee.status == '离职' else '')
                for p in c.persons
            ),
            '本次损耗': c.loss_count,
            '已交付': c.delivered_count,
            '计酬只数': c.payable_count,
            '状态': c.status,
            '备注': c.remark or '',
        })

    delivery_rows = [{
        '交付日期': d.delivery_date.strftime('%Y-%m-%d') if d.delivery_date else '',
        '交付只数': d.dog_count,
        '接收单位': d.receiver or '',
        '凭证': '、'.join(d.attachment or []) or '无',
        '备注': d.remark or '',
    } for d in deliveries]

    loss_rows = [{
        '损耗日期': l.loss_date.strftime('%Y-%m-%d') if l.loss_date else '',
        '损耗只数': l.dog_count,
        '原因': l.reason or '',
        '归属出勤': l.catch.catch_date.strftime('%Y-%m-%d') if l.catch and l.catch.catch_date else '',
        '备注': l.remark or '',
    } for l in losses]

    settlement_rows = []
    share_rows = []
    for s in settlements:
        settlement_rows.append({
            '批次号': s.id,
            '关联资金记录': (f"{s.fund_record.date.strftime('%Y-%m-%d')} {s.fund_record.item}"
                            if s.fund_record else '未关联'),
            '到账金额': s.total_received,
            '分账合计': s.total_paid,
            '留存': s.retained,
            '是否并入总账': '已并入' if s.is_transferred else '未并入',
            '并入时间': s.transferred_at.strftime('%Y-%m-%d %H:%M') if s.transferred_at else '',
            '创建时间': s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else '',
        })
        for sh in s.shares:
            share_rows.append({
                '批次号': s.id,
                '姓名': sh.employee.name if sh.employee else '未知',
                '人员状态': (sh.employee.status if sh.employee else '') or '',
                '计酬只数': sh.dog_count,
                '分账金额': sh.amount,
                '发放状态': '已发' if sh.is_paid else '未发',
                '发放日期': sh.paid_date.strftime('%Y-%m-%d') if sh.paid_date else '',
            })

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(catch_rows).to_excel(writer, index=False, sheet_name='出勤登记')
        pd.DataFrame(delivery_rows).to_excel(writer, index=False, sheet_name='交付记录')
        pd.DataFrame(loss_rows).to_excel(writer, index=False, sheet_name='损耗记录')
        pd.DataFrame(settlement_rows).to_excel(writer, index=False, sheet_name='分账批次')
        pd.DataFrame(share_rows).to_excel(writer, index=False, sheet_name='个人分账')
    output.seek(0)

    filename = f"抓狗奖励费_{year}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
