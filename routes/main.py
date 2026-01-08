# routes/main.py
# 首页及通用路由

from datetime import datetime
import json
from flask import Blueprint, render_template
from flask_login import login_required
from models import Asset, EmploymentCycle, FundsRecord, db

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    # 人事数据
    active_count = EmploymentCycle.query.filter_by(status='在职').count()
    departed_count = EmploymentCycle.query.filter_by(status='离职').count()
    total_unique = EmploymentCycle.query.with_entities(EmploymentCycle.id_card).distinct().count()
    
    # 资产数据
    total_assets = Asset.query.count()
    stock_quantity = db.session.query(db.func.sum(Asset.stock_quantity)).scalar() or 0
    allocated_quantity = db.session.query(db.func.sum(Asset.allocated_quantity)).scalar() or 0
    
    # 资金数据
    current_balance = db.session.query(db.func.sum(FundsRecord.amount)).scalar() or 0.0
    
    # 本月收支
    this_month = datetime.today().strftime('%Y-%m')
    month_income = db.session.query(db.func.sum(FundsRecord.amount))\
        .filter(FundsRecord.date.like(f'{this_month}%'), FundsRecord.amount > 0).scalar() or 0.0
    month_expense = abs(db.session.query(db.func.sum(FundsRecord.amount))\
        .filter(FundsRecord.date.like(f'{this_month}%'), FundsRecord.amount < 0).scalar() or 0.0)
    
    # 新增：生日提醒（本月生日在职员工）
    current_month = datetime.today().month
    birthday_employees = EmploymentCycle.query.filter(
        EmploymentCycle.status == '在职',
        db.extract('month', EmploymentCycle.birthday) == current_month
    ).order_by(db.extract('day', EmploymentCycle.birthday)).all()
    
    # 新增：户籍地分布（省份统计 + 地图数据）
    province_stats = db.session.query(
        EmploymentCycle.household_province,
        db.func.count('*').label('count')
    ).filter(
        EmploymentCycle.status == '在职',
        EmploymentCycle.household_province.isnot(None),
        EmploymentCycle.household_province != ''
    ).group_by(EmploymentCycle.household_province).all()

# 省份名称映射（ECharts 中国地图要求标准名称）
    province_name_map = {
    '北京市': '北京',
    '天津市': '天津',
    '河北省': '河北',
    '山西省': '山西',
    '内蒙古自治区': '内蒙古',
    '辽宁省': '辽宁',
    '吉林省': '吉林',
    '黑龙江省': '黑龙江',
    '上海市': '上海',
    '江苏省': '江苏',
    '浙江省': '浙江',
    '安徽省': '安徽',
    '福建省': '福建',
    '江西省': '江西',
    '山东省': '山东',
    '河南省': '河南',
    '湖北省': '湖北',
    '湖南省': '湖南',
    '广东省': '广东',
    '广西壮族自治区': '广西',
    '海南省': '海南',
    '重庆市': '重庆',
    '四川省': '四川',
    '贵州省': '贵州',
    '云南省': '云南',
    '西藏自治区': '西藏',
    '陕西省': '陕西',
    '甘肃省': '甘肃',
    '青海省': '青海',
    '宁夏回族自治区': '宁夏',
    '新疆维吾尔自治区': '新疆',
    '台湾省': '台湾',
    '香港特别行政区': '香港',
    '澳门特别行政区': '澳门'
}

    map_data = []
    for row in province_stats:
        raw_name = row.household_province.strip()
        standard_name = province_name_map.get(raw_name, None)  # 只映射已知全称
        if standard_name:  # 如果匹配到标准简称
            map_data.append({'name': standard_name, 'value': row.count})
    
    return render_template('index.html',
                           active_count=active_count,
                           departed_count=departed_count,
                           total_unique=total_unique,
                           total_assets=total_assets,
                           stock_quantity=stock_quantity,
                           allocated_quantity=allocated_quantity,
                           current_balance=current_balance,
                           month_income=month_income,
                           month_expense=month_expense,
                           birthday_employees=birthday_employees,
                           province_map_data=json.dumps(map_data, ensure_ascii=False))
