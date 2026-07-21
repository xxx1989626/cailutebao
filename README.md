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
├── app.py                    # 主应用入口
├── config.py                 # 全局配置
├── models.py                 # 数据模型
├── utils.py                  # 工具函数
├── requirements.txt          # 依赖列表
├── CHANGELOG.md              # 变更日志
├── routes/                   # 路由模块
│   ├── hr/                   # 人事管理
│   │   ├── basic.py          # 基本CRUD
│   │   ├── document.py       # 证件管理
│   │   ├── archive.py        # 档案管理
│   │   ├── departure.py      # 离职管理
│   │   ├── self_register.py  # 自注册
│   │   └── permissions.py    # 权限定义
│   ├── asset/                # 资产管理
│   ├── fund.py               # 资金管理
│   ├── scheduling.py         # 考勤管理
│   ├── leave.py              # 请假管理
│   ├── dorm.py               # 宿舍管理
│   ├── trip.py               # 出差管理
│   └── ...
├── templates/                # 模板文件
│   ├── base.html             # 基础模板
│   ├── hr/                   # 人事模板
│   ├── asset/                # 资产模板
│   └── ...
├── static/                   # 静态资源
│   ├── js/                   # JavaScript
│   ├── images/               # 图片
│   └── uploads/              # 上传文件
└── data/                     # 数据库文件
    └── database.db
```

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
# 启动开发服务器
python app.py

# 查看命令说明
cat 命令说明.txt
```

## 许可证

MIT License

## 备注

- 首次启动会自动创建数据库表
- 建议定期备份 `data/database.db` 文件
- 文件上传目录为 `static/uploads`，系统会自动清理超过2小时的孤立文件