# -*- coding: utf-8 -*-
"""AstrBot 原神角色面板查询插件

数据源与云崽Bot、早柚核心同源，均为 Enka.Network 公开接口。
接口与字段解析严格遵循官方文档：https://api.enka.network/#/api_chs

命令：/查询角色 原神UID 角色名
示例：/查询角色 100085620 奥黛塔
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from astrbot.api.event import AstrMessageEvent, filter

try:
    # StarTools 自 AstrBot v3.5.10 起由 astrbot.api.star 导出
    from astrbot.api.star import Star, StarTools, register
except ImportError:  # pragma: no cover - 兼容更早版本的 AstrBot
    from astrbot.api.star import Star, register  # type: ignore[no-redef]

    StarTools = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 接口地址
# ---------------------------------------------------------------------------

# 玩家数据接口：Enka.Network 主站
ENKA_API_LIST = [
    "https://enka.network/api/uid/",
]

# 官方静态数据表目录（角色 / 名称 / 圣遗物套装 / 武器），多镜像自动重试
DATA_BASE_LIST = [
    "https://cdn.jsdelivr.net/gh/EnkaNetwork/API-docs@master/store/gi/",
    "https://fastly.jsdelivr.net/gh/EnkaNetwork/API-docs@master/store/gi/",
    "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/gi/",
]

STATIC_FILES = ("avatars.json", "locs.json", "relics.json", "weapons.json")

# 插件名：用于确定数据目录 data/plugin_data/<PLUGIN_NAME>
PLUGIN_NAME = "genshin_panel"

# 插件版本
PLUGIN_VERSION = "1.3.3"

# ---------------------------------------------------------------------------
# 字段映射
# ---------------------------------------------------------------------------

# 圣遗物部位
ARTIFACT_SLOT = {
    "EQUIP_BRACER": "生之花",
    "EQUIP_NECKLACE": "死之羽",
    "EQUIP_SHOES": "时之沙",
    "EQUIP_RING": "空之杯",
    "EQUIP_DRESS": "理之冠",
}

# 面板属性：fightPropMap 的数字键 -> (中文名, 是否按百分比显示)
#
# 编号依据 Enka / 原神官方 FightProp 枚举：
#   2000 生命值上限  2001 攻击力  2002 防御力
#   20 暴击率  22 暴击伤害  23 元素充能效率  28 元素精通  26 治疗加成  30 物理伤害加成
#   40 火  41 雷  42 水  43 草  44 风  45 岩  46 冰（元素伤害加成）
PANEL_PROPS: List[Tuple[int, str, bool]] = [
    (2000, "生命值上限", False),
    (2001, "攻击力", False),
    (2002, "防御力", False),
    (20, "暴击率", True),
    (22, "暴击伤害", True),
    (23, "元素充能效率", True),
    (28, "元素精通", False),
    (26, "治疗加成", True),
    (30, "物理伤害加成", True),
    (40, "火元素伤害加成", True),
    (41, "雷元素伤害加成", True),
    (42, "水元素伤害加成", True),
    (43, "草元素伤害加成", True),
    (44, "风元素伤害加成", True),
    (45, "岩元素伤害加成", True),
    (46, "冰元素伤害加成", True),
]

# 百分比类词条键。圣遗物 / 武器返回的这类数值本身已是百分数（如 46.6 表示 46.6%）
PERCENT_PROP_KEYS = {
    "FIGHT_PROP_HP_PERCENT",
    "FIGHT_PROP_ATTACK_PERCENT",
    "FIGHT_PROP_DEFENSE_PERCENT",
    "FIGHT_PROP_CRITICAL",
    "FIGHT_PROP_CRITICAL_HURT",
    "FIGHT_PROP_CHARGE_EFFICIENCY",
    "FIGHT_PROP_HEAL_ADD",
    "FIGHT_PROP_HEALED_ADD",
    "FIGHT_PROP_SHIELD_COST_MINUS_RATIO",
    "FIGHT_PROP_PHYSICAL_ADD_HURT",
    "FIGHT_PROP_FIRE_ADD_HURT",
    "FIGHT_PROP_ELEC_ADD_HURT",
    "FIGHT_PROP_WATER_ADD_HURT",
    "FIGHT_PROP_GRASS_ADD_HURT",
    "FIGHT_PROP_WIND_ADD_HURT",
    "FIGHT_PROP_ROCK_ADD_HURT",
    "FIGHT_PROP_ICE_ADD_HURT",
}

# 词条中文名兜底表（官方中文表中缺失时使用）
PROP_NAME_FALLBACK = {
    "FIGHT_PROP_BASE_ATTACK": "基础攻击力",
    "FIGHT_PROP_BASE_HP": "基础生命值",
    "FIGHT_PROP_BASE_DEFENSE": "基础防御力",
    "FIGHT_PROP_HP": "生命值",
    "FIGHT_PROP_HP_PERCENT": "生命值",
    "FIGHT_PROP_ATTACK": "攻击力",
    "FIGHT_PROP_ATTACK_PERCENT": "攻击力",
    "FIGHT_PROP_DEFENSE": "防御力",
    "FIGHT_PROP_DEFENSE_PERCENT": "防御力",
    "FIGHT_PROP_CRITICAL": "暴击率",
    "FIGHT_PROP_CRITICAL_HURT": "暴击伤害",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "元素充能效率",
    "FIGHT_PROP_ELEMENT_MASTERY": "元素精通",
    "FIGHT_PROP_HEAL_ADD": "治疗加成",
    "FIGHT_PROP_HEALED_ADD": "受治疗加成",
    "FIGHT_PROP_SHIELD_STRENGTH": "护盾强效",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "物理伤害加成",
    "FIGHT_PROP_FIRE_ADD_HURT": "火元素伤害加成",
    "FIGHT_PROP_ELEC_ADD_HURT": "雷元素伤害加成",
    "FIGHT_PROP_WATER_ADD_HURT": "水元素伤害加成",
    "FIGHT_PROP_GRASS_ADD_HURT": "草元素伤害加成",
    "FIGHT_PROP_WIND_ADD_HURT": "风元素伤害加成",
    "FIGHT_PROP_ROCK_ADD_HURT": "岩元素伤害加成",
    "FIGHT_PROP_ICE_ADD_HURT": "冰元素伤害加成",
}

# 角色常用别名，仅用于辅助匹配，不影响官方名称解析
ALIAS_MAP: Dict[str, List[str]] = {
    "芙宁娜": ["芙芙", "水神", "芙卡洛斯"],
    "那维莱特": ["龙王", "那维", "水龙"],
    "雷电将军": ["雷神", "雷电影", "影", "雷军"],
    "钟离": ["岩神", "帝君", "钟大爷", "老爷子"],
    "胡桃": ["胡堂主", "胡小桃"],
    "流浪者": ["散兵", "伞兵", "国崩"],
    "纳西妲": ["草神", "小吉祥草王", "妲妲"],
    "温迪": ["风神", "巴巴托斯", "温蒂"],
    "枫原万叶": ["万叶", "叶天帝"],
    "神里绫华": ["凌华", "神里", "白鹭公主", "绫华"],
    "夜兰": ["夜天后", "夜阑", "兰姐"],
    "奥黛塔": ["奥黛", "天鹅", "白天鹅", "雪鹄", "莱莱可"],
    "阿蕾奇诺": ["仆人", "爷爷"],
    "克洛琳德": ["决斗代理人", "克洛"],
    "希格雯": ["护士长"],
    "艾梅莉埃": ["调香师"],
    "玛薇卡": ["火神", "马薇卡"],
    "茜特菈莉": ["茜奶奶"],
    "恰斯卡": ["恰姐"],
    "基尼奇": ["基哥"],
    "玛拉妮": ["鲨鱼妹"],
    "希诺宁": ["希希"],
    "丝柯克": ["师父"],
    "爱可菲": ["大厨", "厨子"],
}


# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------


@register(
    PLUGIN_NAME,
    "astrbot-contrib",
    "原神角色面板查询（Enka 数据源）",
    PLUGIN_VERSION,
)
class GenshinPanelPlugin(Star):
    """原神角色面板查询插件

    通过 Enka.Network 公开接口，按 UID + 角色名查询该角色在游戏内
    角色展柜中的面板属性、武器与圣遗物详情。
    """

    def __init__(self, context, config: dict = None):
        try:
            super().__init__(context, config)
        except TypeError:
            # 兼容不支持 config 参数的旧版本
            super().__init__(context)

        self._session: Optional[aiohttp.ClientSession] = None
        self._data_lock: Optional[asyncio.Lock] = None
        self._data_ready = False

        self.avatars: Dict[str, Any] = {}
        self.locs: Dict[str, str] = {}
        self.relic_sets: Dict[str, Any] = {}
        self.weapons: Dict[str, Any] = {}

        # 持久化数据目录：data/plugin_data/genshin_panel
        self.cache_dir = self._resolve_data_dir()

    # ------------------------------ 数据目录 ------------------------------

    @staticmethod
    def _resolve_data_dir() -> str:
        """返回插件数据目录 data/plugin_data/genshin_panel 的绝对路径。

        优先调用框架官方接口 StarTools.get_data_dir()，由框架保证落点符合
        「持久化数据必须保存到 data/plugin_data/<plugin_name>」的规范；
        若当前 AstrBot 版本未提供该接口，则按标准目录结构推导出同一目录，
        保证新旧版本行为一致。返回值只指向 data/plugin_data 下，
        不会写入插件自身目录。
        """
        # 1) 框架官方接口（AstrBot v3.5.26 起提供）
        if StarTools is not None and hasattr(StarTools, "get_data_dir"):
            try:
                path = str(StarTools.get_data_dir(PLUGIN_NAME))
                os.makedirs(path, exist_ok=True)
                return path
            except Exception:
                pass

        # 2) 回退：按 data/plugins/<插件>/main.py 的标准结构推导
        #    data/plugin_data/<插件>
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        plugins_dir = os.path.dirname(plugin_dir)   # .../data/plugins
        data_root = os.path.dirname(plugins_dir)    # .../data
        if (
            os.path.basename(plugins_dir) == "plugins"
            and os.path.basename(data_root) == "data"
        ):
            path = os.path.join(data_root, "plugin_data", PLUGIN_NAME)
        else:
            # 3) 非常规布局：退到插件目录上一级的 plugin_data 下，仍不写回插件目录
            path = os.path.join(plugins_dir, "plugin_data", PLUGIN_NAME)

        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        return path

    # ------------------------------ 基础工具 ------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": f"AstrBot-GenshinPanel/{PLUGIN_VERSION}"},
            )
        return self._session

    @staticmethod
    def _num(value: Any) -> str:
        """把数值格式化为简洁字符串（整数不带小数点）。"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        if abs(v - round(v)) < 1e-6:
            return str(int(round(v)))
        return f"{round(v, 1)}"

    def prop_name(self, prop_key: Any) -> str:
        """词条键（FIGHT_PROP_*）-> 中文名。"""
        if not prop_key:
            return "未知词条"
        key = str(prop_key)
        return self.locs.get(key) or PROP_NAME_FALLBACK.get(key, key)

    def prop_value_text(self, prop_key: Any, value: Any) -> str:
        """格式化圣遗物 / 武器词条数值（这类数值已是百分数）。"""
        key = str(prop_key) if prop_key else ""
        if key in PERCENT_PROP_KEYS:
            return f"{self._num(value)}%"
        return self._num(value)

    # ------------------------------ 静态数据 ------------------------------

    async def _fetch_json(self, url: str, timeout: int = 40) -> Any:
        session = await self._get_session()
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with session.get(url, timeout=client_timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            text = await resp.text()
            return json.loads(text)

    async def _load_static_file(self, filename: str) -> Any:
        """优先读本地缓存，缺失时从镜像下载并缓存。"""
        cache_path = os.path.join(self.cache_dir, filename)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as fp:
                    return json.load(fp)
            except Exception:
                pass

        last_err: Optional[Exception] = None
        for base in DATA_BASE_LIST:
            try:
                data = await self._fetch_json(base + filename)
                try:
                    os.makedirs(self.cache_dir, exist_ok=True)
                    with open(cache_path, "w", encoding="utf-8") as fp:
                        json.dump(data, fp, ensure_ascii=False)
                except Exception:
                    pass
                return data
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        if last_err is not None:
            raise last_err
        return None

    async def ensure_data(self) -> None:
        """确保官方静态数据已加载（懒加载，首次查询时执行）。"""
        if self._data_ready:
            return
        if self._data_lock is None:
            self._data_lock = asyncio.Lock()
        async with self._data_lock:
            if self._data_ready:
                return

            avatars = await self._load_static_file("avatars.json")
            locs_all = await self._load_static_file("locs.json")
            relics = await self._load_static_file("relics.json")
            weapons = await self._load_static_file("weapons.json")

            self.avatars = avatars or {}
            if isinstance(locs_all, dict):
                self.locs = locs_all.get("zh-cn") or {}
            self.relic_sets = (relics or {}).get("Sets") or {}
            self.weapons = weapons or {}

            self._data_ready = True

    async def initialize(self) -> None:
        """插件激活时预热数据，失败不影响后续懒加载。"""
        try:
            await self.ensure_data()
        except Exception:
            pass

    # ------------------------------ 名称解析 ------------------------------

    def avatar_info(self, char: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """取角色基础信息（兼容旅行者等带 skillDepotId 的变体）。"""
        avatar_id = str(char.get("avatarId", ""))
        info = self.avatars.get(avatar_id)
        if info is None and char.get("skillDepotId") is not None:
            info = self.avatars.get(f"{avatar_id}-{char.get('skillDepotId')}")
        return info

    def avatar_name(self, char: Dict[str, Any]) -> str:
        """角色名：avatarId -> NameTextMapHash -> 官方中文名。"""
        info = self.avatar_info(char)
        if info:
            name = self.locs.get(str(info.get("NameTextMapHash")))
            if name:
                return name
        return f"未知角色(ID:{char.get('avatarId', 0)})"

    def set_name(self, set_id: Any) -> str:
        """圣遗物套装名：setId -> 官方中文名。"""
        if set_id is None:
            return "未知套装"
        info = self.relic_sets.get(str(set_id))
        if isinstance(info, dict):
            name = self.locs.get(str(info.get("Name")))
            if name:
                return name
        return f"未知套装(ID:{set_id})"

    # ------------------------------ 角色匹配 ------------------------------

    def match_character(
        self, characters: List[Dict[str, Any]], target: str
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """按 序号 -> 全名 -> 别名 -> 包含 的顺序匹配角色。"""
        target = (target or "").strip()
        if not target:
            return None, "请提供要查询的角色名。"

        # 1) 纯数字视为展柜序号
        if target.isdigit():
            idx = int(target) - 1
            if 0 <= idx < len(characters):
                return characters[idx], ""
            return None, f"序号超出范围，当前展柜共有 {len(characters)} 个公开角色。"

        low = target.lower()

        # 2) 全名精确匹配
        for char in characters:
            if self.avatar_name(char).lower() == low:
                return char, ""

        # 3) 别名精确匹配
        for char in characters:
            aliases = [a.lower() for a in ALIAS_MAP.get(self.avatar_name(char), [])]
            if low in aliases:
                return char, ""

        # 4) 包含匹配（名称与别名）
        for char in characters:
            name = self.avatar_name(char)
            name_low = name.lower()
            if low in name_low or name_low in low:
                return char, ""
            for alias in ALIAS_MAP.get(name, []):
                alias_low = alias.lower()
                if low in alias_low or alias_low in low:
                    return char, ""

        names_all = "、".join(self.avatar_name(c) for c in characters)
        return None, f"未匹配到角色「{target}」，当前展柜公开角色：{names_all}"

    # ------------------------------ 数据请求 ------------------------------

    async def fetch_player(self, uid: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """按 UID 拉取玩家数据，返回 (数据, 错误信息)。"""
        session = await self._get_session()
        last_err = "网络请求失败，请稍后重试。"
        for base in ENKA_API_LIST:
            try:
                async with session.get(f"{base}{uid}") as resp:
                    if resp.status == 200:
                        return await resp.json(content_type=None), ""
                    if resp.status == 400:
                        return None, "UID 格式不正确。"
                    if resp.status == 404:
                        return None, "未找到该玩家，请确认 UID 正确且已在游戏中公开角色展柜。"
                    if resp.status == 424:
                        return None, "游戏版本更新或维护中，暂时无法查询，请稍后再试。"
                    if resp.status == 429:
                        last_err = "查询过于频繁，已被限流，请稍后再试。"
                        continue
                    if resp.status in (500, 503):
                        last_err = "Enka 服务器繁忙，请稍后再试。"
                        continue
                    last_err = f"接口返回异常状态码 {resp.status}。"
            except asyncio.TimeoutError:
                last_err = "请求超时，请检查网络后重试。"
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = f"网络异常：{exc}"
                continue
        return None, last_err

    # ------------------------------ 结果整理 ------------------------------

    def format_character(self, char: Dict[str, Any]) -> str:
        """把单个角色数据整理为可读文本。"""
        name = self.avatar_name(char)

        prop_map = char.get("propMap") or {}
        level = 1
        entry = prop_map.get("4001") or prop_map.get(4001)
        if isinstance(entry, dict):
            level = entry.get("ival", 1)
        elif entry is not None:
            level = entry

        constellation = len(char.get("talentIdList") or [])
        fetter = char.get("fetterInfo") or {}
        friendship = fetter.get("expLevel", 0)

        # 天赋等级：按官方 SkillOrder（普攻 / 战技 / 爆发）顺序取
        skill_map = char.get("skillLevelMap") or {}
        info = self.avatar_info(char) or {}
        skill_order = info.get("SkillOrder") or []
        if skill_order:
            talents = [str(skill_map.get(str(sid), "-")) for sid in skill_order]
        else:
            talents = [str(v) for _, v in sorted(skill_map.items())][:3]
        talent_text = "/".join(talents) if talents else "-"

        lines: List[str] = []
        lines.append(f"===== {name} 角色面板 =====")
        lines.append(
            f"▫ 等级：Lv.{level}　命之座：{constellation} 命　好感度：{friendship} 级"
        )
        lines.append(f"▫ 天赋等级（普攻/战技/爆发）：{talent_text}")

        # 面板属性
        fight_props = char.get("fightPropMap") or {}
        lines.append("")
        lines.append("—— 面板属性 ——")
        has_prop = False
        for prop_id, prop_label, is_percent in PANEL_PROPS:
            raw = fight_props.get(str(prop_id))
            if raw is None:
                continue
            value = float(raw)
            if value == 0:
                continue
            has_prop = True
            if is_percent:
                lines.append(f"▫ {prop_label}：{round(value * 100, 1)}%")
            else:
                lines.append(f"▫ {prop_label}：{self._num(value)}")
        if not has_prop:
            lines.append("▫ 暂无可展示的面板属性")

        equip_list = char.get("equipList") or []

        # 武器
        lines.append("")
        lines.append("—— 武器 ——")
        weapon_text = "▫ 未装备武器"
        for equip in equip_list:
            if "weapon" not in equip:
                continue
            flat = equip.get("flat") or {}
            weapon = equip.get("weapon") or {}

            weapon_name = self.locs.get(str(flat.get("nameTextMapHash"))) or "未知武器"
            star = flat.get("rankLevel", 0)
            weapon_level = weapon.get("level", 0)
            affix = list((weapon.get("affixMap") or {}).values())
            refine = (affix[0] + 1) if affix else 1

            base_atk = None
            sub_text = ""
            for stat in flat.get("weaponStats") or []:
                prop_key = stat.get("appendPropId")
                stat_value = stat.get("statValue")
                if prop_key == "FIGHT_PROP_BASE_ATTACK":
                    base_atk = stat_value
                else:
                    sub_text = (
                        f"\n▫ 副属性：{self.prop_name(prop_key)} "
                        f"{self.prop_value_text(prop_key, stat_value)}"
                    )
            atk_text = self._num(base_atk) if base_atk is not None else "-"
            weapon_text = (
                f"▫ {weapon_name}　{'★' * int(star)}\n"
                f"▫ 等级：Lv.{weapon_level}　精炼：{refine} 阶\n"
                f"▫ 基础攻击力：{atk_text}{sub_text}"
            )
            break
        lines.append(weapon_text)

        # 圣遗物
        lines.append("")
        lines.append("—— 圣遗物 ——")
        has_artifact = False
        for equip in equip_list:
            if "reliquary" not in equip:
                continue
            has_artifact = True
            flat = equip.get("flat") or {}
            reliquary = equip.get("reliquary") or {}

            slot = ARTIFACT_SLOT.get(flat.get("equipType"), "未知部位")
            set_name = self.set_name(flat.get("setId"))
            star = flat.get("rankLevel", 0)
            art_level = max(0, int(reliquary.get("level", 1)) - 1)

            main_stat = flat.get("reliquaryMainstat") or {}
            main_key = main_stat.get("mainPropId") or main_stat.get("appendPropId")
            main_text = (
                f"{self.prop_name(main_key)} "
                f"{self.prop_value_text(main_key, main_stat.get('statValue'))}"
            )

            sub_list = []
            for sub in flat.get("reliquarySubstats") or []:
                sub_key = sub.get("appendPropId")
                sub_list.append(
                    f"{self.prop_name(sub_key)} "
                    f"{self.prop_value_text(sub_key, sub.get('statValue'))}"
                )
            sub_text = "　|　".join(sub_list) if sub_list else "无"

            lines.append(f"▫ {slot}　{set_name}　{'★' * int(star)} +{art_level}")
            lines.append(f"　　主词条：{main_text}")
            lines.append(f"　　副词条：{sub_text}")
        if not has_artifact:
            lines.append("▫ 未装备圣遗物")

        return "\n".join(lines)

    # ------------------------------ 命令入口 ------------------------------

    @filter.command("查询角色", alias={"查角色", "角色面板", "原神面板"})
    async def query_character(
        self,
        event: AstrMessageEvent,
        uid: str = None,
        character_name: str = None,
    ):
        """查询原神角色面板：/查询角色 原神UID 角色名"""
        uid_text = str(uid).strip() if uid is not None else ""
        name = str(character_name).strip() if character_name is not None else ""

        if not uid_text:
            yield event.plain_result(
                "【原神角色面板查询】\n"
                "用法：/查询角色 原神UID 角色名\n"
                "示例：/查询角色 100085620 奥黛塔\n"
                "说明：只填 UID 时会列出该账号展柜中的全部公开角色。"
            )
            return

        if not (uid_text.isdigit() and 9 <= len(uid_text) <= 10):
            yield event.plain_result("UID 格式不正确，请输入 9~10 位纯数字的原神 UID。")
            return

        try:
            await self.ensure_data()
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"数据初始化失败：{exc}\n请检查网络后重试。")
            return

        yield event.plain_result(f"正在查询 UID {uid_text} 的数据，请稍候……")

        player, err = await self.fetch_player(uid_text)
        if err:
            yield event.plain_result(f"查询失败：{err}")
            return

        characters = (player or {}).get("avatarInfoList") or []
        if not characters:
            yield event.plain_result(
                "查询失败：该玩家未公开角色展柜，或展柜中没有角色。\n"
                "请在游戏内「资料展示 → 角色展柜」中公开展柜，并放入要查询的角色。"
            )
            return

        if not name:
            names_all = "、".join(self.avatar_name(c) for c in characters)
            yield event.plain_result(
                f"UID {uid_text} 展柜公开角色（共 {len(characters)} 个）：\n{names_all}\n"
                f"使用「/查询角色 {uid_text} 角色名」查询对应角色面板。"
            )
            return

        target, match_err = self.match_character(characters, name)
        if target is None:
            yield event.plain_result(match_err)
            return

        yield event.plain_result(self.format_character(target))

    async def terminate(self) -> None:
        """插件卸载 / 重载时关闭请求会话。"""
        if self._session is not None and not self._session.closed:
            await self._session.close()
