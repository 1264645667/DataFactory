"""造数快捷工具业务服务（PRD 7.3 工具清单）。

纯内存生成逻辑，不访问 DB/Redis：
- 身份证号（GB/T 11643 校验位）、手机号（真实号段）、银行卡号（BIN + Luhn）
- 随机姓名（中英文）、统一社会信用代码（GB 32100 校验位）、纳税人识别号
- 随机地址（内置省市数据）、日期批量生成、UUID 批量生成、雪花 ID（含解析信息）
"""

import random
import uuid as uuid_module
from datetime import date, timedelta

from app.engine.strategies.pk_strategies import SnowflakeIdGenerator
from app.schemas.errors import PARAM_INVALID, BizException

# ── 内置基础数据 ─────────────────────────────────────────────────

# 省级行政区划码（前 2 位）+ 名称
_PROVINCES: list[tuple[str, str]] = [
    ("11", "北京市"), ("12", "天津市"), ("13", "河北省"), ("14", "山西省"), ("15", "内蒙古自治区"),
    ("21", "辽宁省"), ("22", "吉林省"), ("23", "黑龙江省"), ("31", "上海市"), ("32", "江苏省"),
    ("33", "浙江省"), ("34", "安徽省"), ("35", "福建省"), ("36", "江西省"), ("37", "山东省"),
    ("41", "河南省"), ("42", "湖北省"), ("43", "湖南省"), ("44", "广东省"), ("45", "广西壮族自治区"),
    ("46", "海南省"), ("50", "重庆市"), ("51", "四川省"), ("52", "贵州省"), ("53", "云南省"),
    ("54", "西藏自治区"), ("61", "陕西省"), ("62", "甘肃省"), ("63", "青海省"), ("64", "宁夏回族自治区"),
    ("65", "新疆维吾尔自治区"),
]

# 地址生成用：省份 → 城市 → 区县 → 街道（内置样例数据，覆盖常用省份）
_ADDRESS_DATA: dict[str, dict[str, list[str]]] = {
    "北京市": {"北京市": ["东城区", "西城区", "朝阳区", "海淀区", "丰台区", "通州区"]},
    "上海市": {"上海市": ["黄浦区", "徐汇区", "浦东新区", "静安区", "虹口区", "闵行区"]},
    "广东省": {
        "广州市": ["越秀区", "海珠区", "荔湾区", "天河区", "白云区", "黄埔区"],
        "深圳市": ["福田区", "罗湖区", "南山区", "宝安区", "龙岗区", "龙华区"],
        "珠海市": ["香洲区", "斗门区", "金湾区"],
    },
    "浙江省": {
        "杭州市": ["上城区", "拱墅区", "西湖区", "滨江区", "余杭区", "萧山区"],
        "宁波市": ["海曙区", "江北区", "鄞州区", "镇海区", "北仑区"],
    },
    "江苏省": {
        "南京市": ["玄武区", "秦淮区", "建邺区", "鼓楼区", "栖霞区", "雨花台区"],
        "苏州市": ["姑苏区", "虎丘区", "吴中区", "相城区", "吴江区"],
    },
    "四川省": {"成都市": ["锦江区", "青羊区", "金牛区", "武侯区", "成华区", "高新区"]},
    "湖北省": {"武汉市": ["江岸区", "江汉区", "硚口区", "武昌区", "洪山区", "汉阳区"]},
    "陕西省": {"西安市": ["新城区", "碑林区", "莲湖区", "雁塔区", "未央区", "灞桥区"]},
    "山东省": {
        "济南市": ["历下区", "市中区", "槐荫区", "天桥区", "历城区"],
        "青岛市": ["市南区", "市北区", "黄岛区", "崂山区", "城阳区"],
    },
    "湖南省": {"长沙市": ["芙蓉区", "天心区", "岳麓区", "开福区", "雨花区"]},
}
_STREETS = ["建国路", "和平街", "人民大道", "解放路", "中山路", "文化巷", "科技路", "滨江大道", "朝阳街", "学府路"]

# 手机号真实号段（PRD 7.3.2）
_PHONE_PREFIXES: dict[str, list[str]] = {
    "mobile": [  # 中国移动
        "134", "135", "136", "137", "138", "139", "147",
        "150", "151", "152", "157", "158", "159",
        "178", "182", "183", "184", "187", "188", "198",
    ],
    "unicom": [  # 中国联通
        "130", "131", "132", "145", "155", "156",
        "166", "175", "176", "185", "186",
    ],
    "telecom": [  # 中国电信
        "133", "149", "153", "173", "177",
        "180", "181", "189", "199",
    ],
}

# 银行卡 BIN（银行 → (借记卡BIN, 信用卡BIN)）
_BANK_BINS: dict[str, tuple[str, str]] = {
    "中国工商银行": ("621226", "622202"),
    "中国农业银行": ("621282", "622848"),
    "中国建设银行": ("621700", "622280"),
    "招商银行": ("621483", "622575"),
    "中国银行": ("621661", "622790"),
    "交通银行": ("621002", "622252"),
    "中国邮政储蓄银行": ("621098", "622810"),
    "上海浦东发展银行": ("621352", "622521"),
    "中信银行": ("621773", "622680"),
    "中国光大银行": ("621492", "622658"),
}

# 姓名库
_ZH_SURNAMES = "王李张刘陈杨黄赵吴周徐孙马朱胡郭何罗高林郑梁谢宋唐许韩冯邓曹彭"
_ZH_MALE_GIVEN = ["伟", "强", "磊", "军", "洋", "勇", "杰", "涛", "明", "超", "刚", "平", "辉", "鹏",
                  "华", "飞", "鑫", "波", "宇", "浩", "凯", "健", "俊杰", "志强", "建国", "文博", "子轩"]
_ZH_FEMALE_GIVEN = ["芳", "娟", "敏", "静", "丽", "艳", "娜", "霞", "玲", "婷", "雪", "琳", "晶", "妍",
                    "茜", "薇", "梦", "瑶", "欣怡", "雨欣", "诗涵", "若曦", "思琪", "雅静"]
_EN_MALE_FIRST = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph",
                  "Thomas", "Charles", "Daniel", "Matthew", "Anthony", "Mark", "Kevin"]
_EN_FEMALE_FIRST = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan",
                    "Jessica", "Sarah", "Karen", "Nancy", "Lisa", "Emily", "Emma", "Olivia"]
_EN_LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
            "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Martin", "Lee"]

# 统一社会信用代码字符集（GB 32100，不含 I/O/S/Z/V）
_CREDIT_CODE_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_CREDIT_CODE_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]
# 登记管理部门代码（PRD 7.3.5：全部/工商/机构编制/民政等）
_CREDIT_DEPARTMENTS: dict[str, str] = {
    "工商": "9", "机构编制": "1", "民政": "5", "司法行政": "3",
    "文化": "4", "外交": "7", "旅游": "8",
}

# 身份证校验位权重与映射（GB/T 11643）
_IDCARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_IDCARD_CHECK_MAP = "10X98765432"


# ── 身份证号（GB/T 11643）────────────────────────────────────────


def _idcard_check_digit(first17: str) -> str:
    """计算身份证第 18 位校验位（加权求和 mod 11）。"""
    total = sum(int(first17[i]) * _IDCARD_WEIGHTS[i] for i in range(17))
    return _IDCARD_CHECK_MAP[total % 11]


def generate_idcards(
    *, province: str | None, gender: str, birth_year_start: int, birth_year_end: int, count: int
) -> list[dict]:
    """生成身份证号（含省份/出生日期/性别/校验位）。"""
    if birth_year_start > birth_year_end:
        raise BizException(PARAM_INVALID, "出生年份范围起始不能大于结束")
    # 省份过滤
    candidates = _PROVINCES
    if province:
        candidates = [p for p in _PROVINCES if p[1] == province]
        if not candidates:
            raise BizException(PARAM_INVALID, f"不支持的省份：{province}")

    results = []
    for _ in range(count):
        code_prefix, province_name = random.choice(candidates)
        area_code = f"{code_prefix}{random.randint(0, 1)}{random.randint(0, 9)}{random.randint(0, 9):02d}"[:6]
        area_code = area_code.ljust(6, "0")
        # 出生日期：年份范围内随机
        year = random.randint(birth_year_start, birth_year_end)
        month = random.randint(1, 12)
        try:
            day = random.randint(1, 28 if month == 2 else 30 if month in (4, 6, 9, 11) else 31)
            birth = date(year, month, day)
        except ValueError:
            birth = date(year, month, 28)
        # 顺序码：第 17 位奇数=男 偶数=女
        actual_gender = gender if gender in ("male", "female") else random.choice(["male", "female"])
        while True:
            seq = random.randint(0, 9)
            if (actual_gender == "male" and seq % 2 == 1) or (actual_gender == "female" and seq % 2 == 0):
                break
        seq_code = f"{random.randint(0, 9)}{random.randint(0, 9)}{seq}"
        first17 = f"{area_code}{birth.strftime('%Y%m%d')}{seq_code}"
        check = _idcard_check_digit(first17)
        results.append({
            "id_card": first17 + check,
            "province": province_name,
            "birth_date": birth.strftime("%Y-%m-%d"),
            "gender": "男" if actual_gender == "male" else "女",
            "check_digit": check,
        })
    return results


# ── 手机号 ───────────────────────────────────────────────────────


def generate_phones(*, carrier: str, count: int) -> list[str]:
    """生成手机号（基于真实号段前缀 + 8 位随机）。"""
    if carrier == "random":
        prefixes = [p for prefixes in _PHONE_PREFIXES.values() for p in prefixes]
    else:
        prefixes = _PHONE_PREFIXES.get(carrier)
        if not prefixes:
            raise BizException(PARAM_INVALID, f"不支持的运营商：{carrier}")
    return [
        random.choice(prefixes) + "".join(random.choices("0123456789", k=8))
        for _ in range(count)
    ]


# ── 银行卡号（BIN + Luhn）─────────────────────────────────────────


def _luhn_check_digit(number_without_check: str) -> str:
    """Luhn 算法计算校验位。"""
    total = 0
    # 从右往左（不含校验位），奇数位（从右数第 1 位起）×2
    reversed_digits = number_without_check[::-1]
    for i, ch in enumerate(reversed_digits):
        digit = int(ch)
        if i % 2 == 0:  # 校验位右侧第一位开始，偶数索引位 ×2
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - total % 10) % 10)


def generate_bankcards(*, bank: str | None, card_type: str, count: int) -> list[dict]:
    """生成银行卡号（BIN 码 + 随机主体 + Luhn 校验位）。"""
    if bank:
        if bank not in _BANK_BINS:
            raise BizException(PARAM_INVALID, f"不支持的银行：{bank}")
        banks = [bank]
    else:
        banks = list(_BANK_BINS.keys())

    results = []
    for _ in range(count):
        bank_name = random.choice(banks)
        bin_code = _BANK_BINS[bank_name][0 if card_type == "debit" else 1]
        # 借记卡 19 位 / 信用卡 16 位（含校验位）
        total_length = 19 if card_type == "debit" else 16
        body_len = total_length - 6 - 1
        body = "".join(random.choices("0123456789", k=body_len))
        card_without_check = bin_code + body
        card_no = card_without_check + _luhn_check_digit(card_without_check)
        results.append({
            "card_no": card_no,
            "bank": bank_name,
            "card_type": "借记卡" if card_type == "debit" else "信用卡",
        })
    return results


# ── 随机姓名 ─────────────────────────────────────────────────────


def generate_names(*, language: str, gender: str, count: int) -> list[str]:
    """生成随机姓名（中文：百家姓 + 常用字；英文：名 + 姓）。"""
    results = []
    for _ in range(count):
        actual_gender = gender if gender in ("male", "female") else random.choice(["male", "female"])
        if language == "zh":
            surname = random.choice(_ZH_SURNAMES)
            given_pool = _ZH_MALE_GIVEN if actual_gender == "male" else _ZH_FEMALE_GIVEN
            results.append(surname + random.choice(given_pool))
        else:
            first_pool = _EN_MALE_FIRST if actual_gender == "male" else _EN_FEMALE_FIRST
            results.append(f"{random.choice(first_pool)} {random.choice(_EN_LAST)}")
    return results


# ── 统一社会信用代码（GB 32100）────────────────────────────────────


def _credit_check_char(first17: str) -> str:
    """GB 32100 校验位：加权求和 mod 31，再用 31 减余数取字符。"""
    total = sum(
        _CREDIT_CODE_CHARS.index(first17[i]) * _CREDIT_CODE_WEIGHTS[i] for i in range(17)
    )
    check_value = (31 - total % 31) % 31
    return _CREDIT_CODE_CHARS[check_value]


def generate_credit_codes(*, department: str | None, count: int) -> list[str]:
    """生成统一社会信用代码（18 位：登记部门1 + 机构类别1 + 行政区划6 + 主体标识9 + 校验位1）。"""
    if department and department != "全部":
        if department not in _CREDIT_DEPARTMENTS:
            raise BizException(PARAM_INVALID, f"不支持的登记管理部门：{department}")
        dept_codes = [_CREDIT_DEPARTMENTS[department]]
    else:
        dept_codes = list(_CREDIT_DEPARTMENTS.values())

    results = []
    for _ in range(count):
        dept = random.choice(dept_codes)
        org_type = random.choice("12349")  # 机构类别（机关/事业/企业/社团等）
        area = random.choice([p[0] for p in _PROVINCES]) + f"{random.randint(0, 99):02d}{random.randint(1, 99):02d}"
        body = "".join(random.choices(_CREDIT_CODE_CHARS, k=9))
        first17 = f"{dept}{org_type}{area}{body}"
        results.append(first17 + _credit_check_char(first17))
    return results


# ── 纳税人识别号 ──────────────────────────────────────────────────


def generate_taxpayer_ids(*, taxpayer_type: str, count: int) -> list[str]:
    """生成纳税人识别号：企业=15 位（行政区划6+组织机构9），个人=身份证号。"""
    results = []
    for _ in range(count):
        if taxpayer_type == "personal":
            # 个人纳税人识别号即身份证号
            item = generate_idcards(
                province=None, gender="random",
                birth_year_start=1960, birth_year_end=2005, count=1,
            )[0]
            results.append(item["id_card"])
        else:
            area = random.choice([p[0] for p in _PROVINCES]) + f"{random.randint(0, 99):02d}{random.randint(1, 99):02d}"
            org = "".join(random.choices("0123456789", k=9))
            results.append(area + org)
    return results


# ── 随机地址 ─────────────────────────────────────────────────────


def generate_addresses(*, province: str | None, precision: str, count: int) -> list[str]:
    """生成随机地址（省市 / 省市区 / 省市区街道+门牌号）。"""
    provinces = list(_ADDRESS_DATA.keys())
    if province:
        if province not in _ADDRESS_DATA:
            # 未内置详情的省份：退化为「省份 + 随机市区」简版
            matched = [p for _, p in _PROVINCES if p == province]
            if not matched:
                raise BizException(PARAM_INVALID, f"不支持的省份：{province}")
            results = []
            for _ in range(count):
                base = province
                if precision != "province_city":
                    base += "市辖区"
                if precision == "full":
                    base += f"{random.choice(_STREETS)}{random.randint(1, 999)}号"
                results.append(base)
            return results
        provinces = [province]

    results = []
    for _ in range(count):
        prov = random.choice(provinces)
        city = random.choice(list(_ADDRESS_DATA[prov].keys()))
        address = prov + ("" if city == prov else city)
        if precision in ("province_city_district", "full"):
            district = random.choice(_ADDRESS_DATA[prov][city])
            address += district
        if precision == "full":
            address += f"{random.choice(_STREETS)}{random.randint(1, 999)}号"
        results.append(address)
    return results


# ── 日期批量生成 ──────────────────────────────────────────────────


def generate_dates(*, start_date: str, end_date: str, fmt: str, dedup: bool, count: int) -> list:
    """在日期范围内随机生成日期（支持格式输出/去重）。"""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as e:
        raise BizException(PARAM_INVALID, "日期格式不正确，应为 yyyy-MM-dd") from e
    if start > end:
        raise BizException(PARAM_INVALID, "起始日期不能晚于结束日期")
    total_days = (end - start).days + 1
    if dedup and count > total_days:
        raise BizException(
            PARAM_INVALID, f"去重模式下数量不能超过范围内天数（共 {total_days} 天）"
        )

    def _format(d: date):
        if fmt == "yyyy-MM-dd":
            return d.strftime("%Y-%m-%d")
        if fmt == "yyyy/MM/dd":
            return d.strftime("%Y/%m/%d")
        if fmt == "yyyyMMdd":
            return d.strftime("%Y%m%d")
        # timestamp：当天 00:00 的秒级时间戳
        from datetime import datetime as dt
        return int(dt(d.year, d.month, d.day).timestamp())

    if dedup:
        offsets = random.sample(range(total_days), count)
    else:
        offsets = [random.randint(0, total_days - 1) for _ in range(count)]
    return [_format(start + timedelta(days=offset)) for offset in offsets]


# ── UUID 批量生成 ─────────────────────────────────────────────────


def generate_uuids(*, fmt: str, count: int) -> list[str]:
    """批量生成 UUID v4（hyphen=含连字符 plain=无连字符 upper=大写 lower=小写）。"""
    results = []
    for _ in range(count):
        value = uuid_module.uuid4()
        if fmt == "plain":
            text = value.hex
        elif fmt == "upper":
            text = str(value).upper()
        elif fmt == "lower":
            text = str(value).lower()
        else:  # hyphen
            text = str(value)
        results.append(text)
    return results


# ── 雪花 ID ──────────────────────────────────────────────────────


def generate_snowflakes(*, machine_id: int, datacenter_id: int, count: int) -> list[dict]:
    """生成雪花 ID 并返回解析信息（时间戳/机器位/数据中心位/序列号）。"""
    generator = SnowflakeIdGenerator(datacenter_id=datacenter_id, machine_id=machine_id)
    results = []
    for _ in range(count):
        snowflake_id = generator.next_id()
        timestamp = (snowflake_id >> SnowflakeIdGenerator.TIMESTAMP_SHIFT) + SnowflakeIdGenerator.EPOCH
        dc = (snowflake_id >> SnowflakeIdGenerator.DATACENTER_SHIFT) & SnowflakeIdGenerator.MAX_DATACENTER
        machine = (snowflake_id >> SnowflakeIdGenerator.MACHINE_SHIFT) & SnowflakeIdGenerator.MAX_MACHINE
        sequence = snowflake_id & SnowflakeIdGenerator.MAX_SEQUENCE
        results.append({
            "id": str(snowflake_id),  # 字符串承载，避免前端 JS Number 精度丢失
            "timestamp": timestamp,
            "machine_id": machine,
            "datacenter_id": dc,
            "sequence": sequence,
        })
    return results
