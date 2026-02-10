# routes/posts.py
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_login import login_required
from models import db, ShiftPost, ShiftSchedule
from utils import perm
import pandas as pd
import io

posts_bp = Blueprint('posts', __name__, url_prefix='/posts')

@posts_bp.route('/list', methods=['GET', 'POST'])
@login_required
def list():
    """岗位管理主页"""
    if not perm.can('scheduling.post'):
        flash("权限不足", "danger")
        return redirect(url_for('scheduling.schedule_list'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        color = request.form.get('color', '#007bff')
        start = request.form.get('default_start', '08:30')
        end = request.form.get('default_end', '17:30')
        if name:
            new_post = ShiftPost(name=name, color=color, default_start=start, default_end=end)
            db.session.add(new_post)
            db.session.commit()
            flash(f"岗位 {name} 添加成功", "success")
        return redirect(url_for('posts.list'))

    posts = ShiftPost.query.all()
    return render_template('scheduling/posts.html', posts=posts)

@posts_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    """删除岗位（含关联检查）"""
    if not perm.can('scheduling.post'):
        flash("无权操作", "danger")
        return redirect(url_for('posts.list'))
        
    post = ShiftPost.query.get_or_404(id)
    if ShiftSchedule.query.filter_by(post_id=id).first():
        flash("该岗位已有排班记录，无法直接删除", "warning")
    else:
        db.session.delete(post)
        db.session.commit()
        flash("岗位已删除", "success")
    return redirect(url_for('posts.list'))

@posts_bp.route('/export')
@login_required
def export_config():
    """导出岗位配置清单"""
    posts = ShiftPost.query.all()
    data = [{
        "岗位名称": p.name, 
        "代表颜色": p.color,
        "默认开始时间": p.default_start,
        "默认结束时间": p.default_end
    } for p in posts]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    return send_file(output, download_name="岗位配置导出.xlsx", as_attachment=True)

@posts_bp.route('/import', methods=['POST'])
@login_required
def import_config():
    """从Excel导入岗位配置"""
    file = request.files.get('file')
    if not file: return jsonify({'success': False, 'message': '未选择文件'})
    try:
        df = pd.read_excel(file)
        count = 0
        for _, row in df.iterrows():
            name = str(row['岗位名称']).strip()
            if not ShiftPost.query.filter_by(name=name).first():
                new_post = ShiftPost(
                    name=name, 
                    color=str(row.get('代表颜色', '#0d6efd')),
                    default_start=str(row.get('默认开始时间', '08:30')),
                    default_end=str(row.get('默认结束时间', '17:30'))
                )
                db.session.add(new_post)
                count += 1
        db.session.commit()
        return jsonify({'success': True, 'message': f'成功导入 {count} 个新岗位'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'})