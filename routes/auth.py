# routes/auth.py
# 认证相关路由

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from models import User, EmploymentCycle, db
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # 检查该账号是否已离职
            latest_cycle = EmploymentCycle.query.filter_by(id_card=username)\
                .order_by(EmploymentCycle.hire_date.desc()).first()
            
            if latest_cycle and latest_cycle.status == '离职':
                flash('该账号已离职，无法登录系统', 'danger')
                return redirect(url_for('auth.login'))
            
            login_user(user)
            if user.check_password('123456'):
                flash('您的账户使用的是初始密码，请立即修改！', 'warning')
                return redirect(url_for('auth.change_password'))
            flash('登录成功', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('用户名或密码错误', 'danger')
    
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    logout_user()
    flash('已安全登出', 'info')
    return redirect(url_for('auth.login'))


#修改密码
@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # 1. 验证旧密码
        if not current_user.check_password(old_password):
            flash('原密码错误', 'danger')
            return redirect(url_for('auth.change_password'))

        # 2. 验证两次新密码是否一致
        if new_password != confirm_password:
            flash('两次输入的新密码不一致', 'danger')
            return redirect(url_for('auth.change_password'))
        
        # 3. 验证新密码长度（可选）
        if len(new_password) < 6:
            flash('新密码长度不能少于6位', 'danger')
            return redirect(url_for('auth.change_password'))

        # 4. 更新密码
        current_user.set_password(new_password)
        db.session.commit()
        
        flash('密码修改成功！', 'success')
        return redirect(url_for('main.index')) # 修改成功后跳回首页

    return render_template('auth/change_password.html')

@auth_bp.route('/reset_user_password/<int:user_id>', methods=['POST'])
@login_required
def reset_user_password(user_id):
    # 1. 严格权限检查
    if current_user.role != 'admin':
        flash('权限不足，只有管理员可以重置密码', 'danger')
        return redirect(url_for('main.index'))
        
    # 2. 获取目标用户
    user = User.query.get_or_404(user_id)
    
    # 3. 执行重置
    user.set_password('123456')
    db.session.commit()
    
    # 注意：根据你的 User 模型，这里使用的是 user.name
    flash(f'用户 {user.name} 的密码已重置为 123456', 'success')
    
    # 4. 安全返回：如果 referrer 不存在，回退到主页
    next_page = request.referrer or url_for('main.index')
    return redirect(next_page)