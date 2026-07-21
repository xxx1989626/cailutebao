# 蔡路特保队队务管理系统

> 蔡路特保队队务管理系统 - 一站式人事、资金、考勤、资产综合管理平台

![系统截图](https://github.com/user-attachments/assets/c555143f-2da9-4e4b-8cbf-cca9342f813d)

## 功能模块

| 模块 | 功能说明 |
|------|---------|
| **人事管理** | 员工花名册、证件管理、档案管理、离职管理、自注册、信息变更审批 |
| **资金管理** | 收支记录、余额管理、导入导出 |
| **考勤管理** | AG-Grid矩阵排班视图、签到统计 |
| **资产管理** | 资产入库、盘点、领用、归还、台账管理 |
| **宿舍管理** | 宿舍地图、房间分配 |
| **请假管理** | 请假申请、审批、统计 |
| **通知管理** | 系统通知、审批提醒 |
| **权限管理** | 角色权限配置、操作日志 |
| **出差管理** | 出差申请、审批、记录 |
| **常用链接** | 快速访问入口 |

## 技术栈

- **框架**: Flask 3.1.2
- **数据库**: SQLite + SQLAlchemy 2.0
- **认证**: Flask-Login
- **前端**: Bootstrap 5 + Bootstrap Icons
- **表格**: AG-Grid
- **服务器**: Waitress + Nginx 反向代理
- **语言**: Python 3.10+

## 快速开始

### 环境要求

- Python 3.10+
- Windows/Linux/macOS

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动方式

**开发模式**：
```bash
python app.py
```

**生产模式**（Windows）：
```bash
auto_start.bat
```

启动后访问：`http://localhost:8000`

### 默认账号

- 管理员账号需在数据库中创建

## 项目结构

```
cailutebao/
├── .env                           # 环境变量配置
├── .gitignore                     # Git忽略规则
├── app.py                         # 主应用入口（Flask启动）
├── CHANGELOG.md                   # 变更日志
├── config.py                      # 全局配置（数据库、路径、常量）
├── models.py                      # 数据模型（SQLAlchemy）
├── README.md                      # 项目说明文档
├── requirements.txt               # Python依赖列表
├── run_server.bat                 # 启动脚本
├── utils.py                       # 工具函数（验证、文件处理、权限）
├── .vscode/                       # VSCode配置
│   ├── alias_config.json          # 别名配置
│   ├── private-folder-alias.json  # 私有文件夹别名
│   └── public-folder-alias.json   # 公共文件夹别名
├── data/                          # 数据目录
│   └── database.db                # SQLite数据库文件
├── migrations/                    # 数据库迁移
│   ├── alembic.ini                # Alembic配置
│   ├── env.py                     # 迁移环境
│   ├── README                     # 迁移说明
│   ├── script.py.mako             # 迁移脚本模板
│   └── versions/d2aa21320529_初始迁移.py  # 初始迁移版本
├── routes/                        # 路由模块
│   ├── __init__.py                # 路由包初始化
│   ├── auth.py                    # 认证路由（登录、改密码）
│   ├── chat.py                    # 聊天模块
│   ├── dorm.py                    # 宿舍管理路由
│   ├── fund.py                    # 资金管理路由
│   ├── leave.py                   # 请假管理路由
│   ├── main.py                    # 主页路由
│   ├── notification.py            # 通知管理路由
│   ├── permission.py              # 权限管理路由
│   ├── posts.py                   # 岗位管理路由
│   ├── scheduling.py              # 考勤排班路由
│   ├── trip.py                    # 出差管理路由
│   ├── asset/                     # 资产管理子模块
│   │   ├── __init__.py            # 资产路由包初始化
│   │   ├── core.py                # 资产核心逻辑
│   │   ├── import_export.py       # 资产导入导出
│   │   ├── inventory.py           # 资产盘点
│   │   ├── operations.py          # 资产操作（领用、归还）
│   │   └── views.py               # 资产视图路由
│   └── hr/                        # 人事管理子模块
│       ├── __init__.py            # 人事路由包初始化
│       ├── archive.py             # 档案管理路由
│       ├── assets.py              # 人事资产关联
│       ├── basic.py               # 人事基本CRUD（增删改查）
│       ├── departure.py           # 离职管理路由
│       ├── document.py            # 证件管理路由
│       ├── import_export.py       # 人事导入导出
│       ├── permissions.py         # 人事权限定义
│       └── self_register.py       # 员工自注册路由
├── static/                        # 静态资源
│   ├── favicon.ico                # 网站图标
│   ├── audio/beep.mp3             # 提示音
│   ├── images/dorm_plan.jpg       # 宿舍平面图
│   ├── js/main.js                 # 主脚本
│   ├── js/fullcalendar.global.min.js  # 日历组件
│   └── js/AG-Grid/                # AG-Grid表格组件
│       ├── ag-grid-community.min.js
│       ├── ag-grid.min.css
│       └── ag-theme-alpine.min.css
├── templates/                     # Jinja2模板
│   ├── base.html                  # 基础模板（布局、导航）
│   ├── index.html                 # 首页
│   ├── changyonglianjie.html      # 常用链接卡片
│   ├── _attachment.html           # 附件上传公共组件
│   ├── _common_tabs.html          # 公共标签页
│   ├── _pagination.html           # 分页公共组件
│   ├── auth/                      # 认证模板
│   │   ├── login.html             # 登录页
│   │   └── change_password.html   # 改密码页
│   ├── asset/                     # 资产模板
│   │   ├── list.html              # 资产列表
│   │   ├── add.html               # 新增资产
│   │   ├── edit.html              # 编辑资产
│   │   ├── detail.html            # 资产详情
│   │   ├── import.html            # 导入资产
│   │   ├── inventory.html         # 资产盘点
│   │   ├── asset_scan.html        # 资产扫描
│   │   ├── _partial_asset_form.html  # 资产表单片段
│   │   ├── _asset_actions.html    # 资产操作按钮
│   │   ├── _asset_history.html    # 资产变动记录
│   │   ├── _asset_js.html         # 资产JS脚本
│   │   └── _asset_modals.html     # 资产弹窗
│   ├── hr/                        # 人事模板
│   │   ├── list.html              # 员工花名册
│   │   ├── add.html               # 新增员工
│   │   ├── edit.html              # 编辑员工
│   │   ├── detail.html            # 员工详情
│   │   ├── import.html            # 导入员工
│   │   ├── pending_changes.html   # 待审批变更
│   │   ├── change_detail.html     # 变更详情
│   │   ├── self_register.html     # 自注册页
│   │   ├── register_success.html  # 注册成功页
│   │   ├── _employee_form.html    # 员工表单公共组件
│   │   └── document/              # 证件管理模板
│   │       ├── list.html          # 证件列表
│   │       ├── add.html           # 添加证件
│   │       ├── edit.html          # 编辑证件
│   │       ├── view_change.html   # 审批变更页
│   │       └── _document_form.html# 证件表单公共组件
│   ├── fund/                      # 资金模板
│   │   ├── list.html              # 资金列表
│   │   ├── add.html               # 新增收支
│   │   ├── edit.html              # 编辑收支
│   │   ├── import.html            # 导入数据
│   │   └── _partial_fund_form.html# 资金表单片段
│   ├── leave/                     # 请假模板
│   │   ├── list.html              # 请假列表
│   │   ├── add.html               # 请假申请
│   │   └── finish_confirm.html    # 销假确认
│   ├── dorm/                      # 宿舍模板
│   │   └── map.html               # 宿舍地图
│   ├── trip/                      # 出差模板
│   │   ├── list.html              # 出差列表
│   │   ├── add.html               # 出差申请
│   │   └── edit.html              # 编辑出差
│   ├── scheduling/                # 考勤模板
│   │   └── list.html              # 排班视图
│   ├── notification/              # 通知模板
│   │   └── list.html              # 通知列表
│   ├── permission/                # 权限模板
│   │   ├── manage.html            # 权限管理
│   │   └── operations.html        # 操作日志
│   └── posts/                     # 岗位模板
│       └── list.html              # 岗位列表
└── 模板文件/                      # Excel模板
    ├── 培训记录模板.xlsx           # 培训记录模板
    ├── 月培训计划模版.xlsx         # 月培训计划模板
    └── 请假单模板.xlsx             # 请假单模板

## 配置说明

### 环境变量

在 `.env` 文件中配置：

```env
# 腾讯地图API Key（可选）
TENCENT_KEY=your_key

# 高德地图API Key（可选）
AMAP_KEY=your_key
```

### 关键配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SECRET_KEY` | Flask安全密钥 | cailutebao-local-dev-secret-key-2025 |
| `UPLOAD_FOLDER` | 文件上传目录 | static/uploads |
| `MAX_CONTENT_LENGTH` | 最大上传大小 | 50MB |
| `DATABASE_PATH` | 数据库路径 | data/database.db |

## 核心特性

- ✅ **权限管理**: 基于角色的细粒度权限控制
- ✅ **审批流程**: 人事信息变更、证件管理需管理员审批
- ✅ **水平越权防护**: 普通用户只能操作自己的数据
- ✅ **操作日志**: 完整的操作记录追踪
- ✅ **文件自动清理**: 定期清理孤立文件，支持JSON嵌套路径扫描
- ✅ **再次入职引用**: 自动填充历史员工信息
- ✅ **响应式设计**: 支持移动端访问

## 运行命令

```bash
启动命令         python app.py
生成全代码txt    python merge_code.py 
数据库迁移       1、检测变化     flask db migrate -m "说明"  
                2、执行更新     flask db upgrade
                3、回滚/撤销    flask db downgrade
导出依赖：pip freeze > requirements.txt
安装依赖：pip install -r requirements.txt
```

## 许可证

MIT License

## 备注

- 首次启动会自动创建数据库表
- 建议定期备份 `data/database.db` 文件
- 文件上传目录为 `static/uploads`，系统会自动清理超过2小时的孤立文件