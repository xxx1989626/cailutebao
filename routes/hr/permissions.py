#D:\cailu\cailutebao\routes\hr\permissions.py
# 人事模块权限列表
HR_PERMISSIONS = [
    ('view', '查看员工信息', '查看员工列表和详情'),
    ('add', '新增员工', '新增员工记录'),
    ('edit', '编辑员工', '编辑员工信息（含离职办理、注册审核、证件编辑）'),
    ('delete', '删除员工', '删除员工记录及证件资料'),
    ('import', '批量导入员工', '从Excel导入员工'),
    ('export', '批量导出员工', '导出员工花名册'),
]