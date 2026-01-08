# config.py
# 项目全局配置文件

import os
from datetime import datetime

# 项目根目录绝对路径（用于文件上传、数据库定位）
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# SQLite 数据库路径（会自动在 data 文件夹生成 database.db）
DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'database.db')

# 文件上传相关配置
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}

# 上传文件夹最大大小（50MB）
MAX_CONTENT_LENGTH = 50 * 1024 * 1024

# Flask Secret Key（用于表单安全，随机生成即可，本地使用无所谓）
SECRET_KEY = 'cailutebao-local-dev-secret-key-2025'

# 分页配置
PER_PAGE = 20

# 外部API（用于动态获取选项）
API_ENDPOINTS = {
    # 高德行政区划 API（省市区镇四级联动）
    'amap_division': 'https://restapi.amap.com/v3/config/district',

    # 中国56个民族
    'ethnic': 'https://api.example.com/ethnic',

    # 政治面貌
    'politics': 'https://api.example.com/politics',

    # 学历
    'education': 'https://api.example.com/education',
}

# 高德 API KEY
AMAP_KEY = "156d9a978ac9aaa01d7ad802a433e073"


# 内置兜底数据（如果网络不可用或API失效，使用本地列表）
FALLBACK_DATA = {
    'ethnic': [
        "汉族", "蒙古族", "回族", "藏族", "维吾尔族", "苗族", "彝族", "壮族", "布依族", "朝鲜族",
        "满族", "侗族", "瑶族", "白族", "土家族", "哈尼族", "哈萨克族", "傣族", "黎族", "傈僳族",
        "佤族", "畲族", "高山族", "拉祜族", "水族", "东乡族", "纳西族", "景颇族", "柯尔克孜族",
        "土族", "达斡尔族", "仫佬族", "羌族", "布朗族", "撒拉族", "毛南族", "仡佬族", "锡伯族",
        "阿昌族", "普米族", "塔吉克族", "怒族", "乌孜别克族", "俄罗斯族", "鄂温克族", "德昂族",
        "保安族", "裕固族", "京族", "塔塔尔族", "独龙族", "鄂伦春族", "赫哲族", "门巴族", "珞巴族", "基诺族"
    ],
    'politics': [
        "中共党员", "中共预备党员", "共青团员", "民革党员", "民盟盟员", "民建会员", 
        "民进会员", "农工党党员", "致公党党员", "九三学社社员", "台盟盟员", 
        "无党派人士", "群众"
    ],
    'education': [
        "博士研究生", "硕士研究生", "大学本科", "大学专科", "中等专科", 
        "高中", "初中", "小学", "文盲或半文盲"
    ]
}

# 薪资计算模式选项
SALARY_MODES = [
    "月工时制",
    "220元/天制",
    "200元/天制"
]

# 职位身份选项
POSITIONS = [
    "队长",
    "副队长",
    "领班",
    "队员"
]

# 岗位选项
POSTS = [
    "机动",
    "内勤",
    "外口",
    "监控",
    "窗口"
]

# 资产类型选项
ASSET_TYPES = [
    "装备",
    "服饰",
    "消耗品",
    "固定资产",
    "工具",
]

# 资产状态选项
ASSET_STATUS = [
    "正常",
    "损坏",
    "维修",
    "报废"
]

# 资产归属选项
ASSET_OWNERSHIP = [
    "公司",
    "派出所",
    "个人",
    "特保队"
]

# 资产分配模式 (对应你代码里的逻辑)
ALLOCATION_MODES = [
    ("personal", "个人领用"),
    ("group", "公用")
]

# 房间号列表
ROOM_NUMBERS = [
        "101室", "102室", "103室", "104室", "105室", 
        "106室", "107室", "108室", "109室", "110室", 
        "111室", "112室","113室"
    ]

    # 房间属性/功能类型
ROOM_TYPES = [
        "宿舍", "备勤室", "队长办公室", "仓库", 
        "机房", "洗浴间", "盥洗室", "卫生间", "走廊"
    ]

SILENT_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'system_cache/v1/temp')