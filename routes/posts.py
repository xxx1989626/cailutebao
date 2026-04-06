#D:\cailu\cailutebao\routes\posts.py
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import login_required
from models import db, ShiftPost, ShiftSchedule
from utils import perm
import pandas as pd
import io
from datetime import datetime, timedelta

posts_bp = Blueprint('posts', __name__, url_prefix='/posts')

# 原有list路由（新增岗位）- 无需修改
@posts_bp.route('/list', methods=['GET', 'POST'])
@login_required
def posts_list():
    """岗位管理主页"""
    if not perm.can('scheduling.post'):
        flash("权限不足", "danger")
        return redirect(url_for('scheduling.schedule_list'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        color = request.form.get('color', '#007bff')
        start = request.form.get('default_start', '08:30')
        end = request.form.get('default_end', '17:30')
        hours = float(request.form.get('default_hours', 12))

        if name:
            # 新增：时间逻辑校验（适配前端）
            if start >= end:
                flash("下班时间必须晚于上班时间", "warning")
                return redirect(url_for('posts.posts_list'))
            new_post = ShiftPost(name=name, color=color, default_start=start, default_end=end, default_hours=hours)
            db.session.add(new_post)
            db.session.commit()
            flash(f"岗位 {name} 添加成功", "success")
        return redirect(url_for('posts.posts_list'))

    posts = ShiftPost.query.all()
    return render_template('posts/list.html', posts=posts)


# 原有delete路由 - 无需修改
@posts_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    """删除岗位（含关联检查）"""
    if not perm.can('scheduling.post'):
        flash("无权操作", "danger")
        return redirect(url_for('posts.posts_list'))
        
    post = ShiftPost.query.get_or_404(id)
    if ShiftSchedule.query.filter_by(post_id=id).first():
        flash("该岗位已有排班记录，无法直接删除", "warning")
    else:
        db.session.delete(post)
        db.session.commit()
        flash("岗位已删除", "success")
    return redirect(url_for('posts.posts_list'))

# 原有export路由 - 无需修改
@posts_bp.route('/export')
@login_required
def export_config():
    """导出岗位配置清单"""
    posts = ShiftPost.query.all()
    data = [{
        "岗位名称": p.name, 
        "代表颜色": p.color,
        "默认开始时间": p.default_start,
        "默认结束时间": p.default_end,
        "默认排班时长": p.default_hours
    } for p in posts]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name="岗位配置导出.xlsx", as_attachment=True)

# ====================== 修复版：导入路由（支持夜班跨天 20:00→08:00）======================
@posts_bp.route('/import', methods=['POST'])
@login_required
def import_config():
    """从Excel导入岗位配置（修复跨天夜班、时间格式兼容）"""
    file = request.files.get('file')
    if not file:
        return jsonify({'success': False, 'message': '未选择文件'})
    
    try:
        df = pd.read_excel(file)
        count = 0
        skip_list = []

        for idx, row in df.iterrows():
            # 1. 岗位名校验
            name = str(row['岗位名称']).strip()
            if not name:
                skip_list.append(f"第{idx+2}行：岗位名为空")
                continue
            if ShiftPost.query.filter_by(name=name).first():
                skip_list.append(f"第{idx+2}行：{name} 已存在")
                continue

            # 2. 读取时间字符串
            start_str = str(row.get('默认开始时间', '08:30')).strip()
            end_str = str(row.get('默认结束时间', '17:30')).strip()

            # 3. 兼容两种时间格式：HH:mm 或 HH:mm:ss
            start_time = None
            end_time = None
            for fmt in ["%H:%M:%S", "%H:%M"]:
                try:
                    start_time = datetime.strptime(start_str, fmt)
                    end_time = datetime.strptime(end_str, fmt)
                    break
                except ValueError:
                    continue

            if not start_time or not end_time:
                skip_list.append(f"第{idx+2}行：{name} 时间格式错误")
                continue

            # 4. 核心修复：支持跨天班次（夜班 20:00 → 次日08:00）
            if end_time <= start_time:
                end_time += timedelta(days=1)

            excel_hours = row.get('默认排班时长')
            if pd.notna(excel_hours):
                hours = float(excel_hours)    
            else:
                hours = round((end_time - start_time).total_seconds() / 3600, 1)


            # 6. 颜色处理
            color = str(row.get('代表颜色', '#0d6efd')).strip()
            if not color.startswith("#"):
                color = "#0d6efd"

            # 7. 创建岗位
            new_post = ShiftPost(
                name=name,
                color=color,
                default_start=start_str,
                default_end=end_str,
                default_hours=hours
            )
            db.session.add(new_post)
            count += 1

        db.session.commit()

        msg = f"成功导入 {count} 个岗位"
        if skip_list:
            msg += f" | 跳过 {len(skip_list)} 个"

        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f"导入失败：{str(e)}"})