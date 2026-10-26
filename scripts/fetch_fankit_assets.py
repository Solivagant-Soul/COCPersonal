#!/usr/bin/env python3
"""从 Supercell Fankit 下载《部落冲突》主世界（HV）图标素材，按中文名落盘。

数据来源：https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets

Fankit 是 Frontify 品牌门户，页面由 JS 渲染，HTML 里拿不到图，所以直接走门户
自带的接口：

* 资源列表：``GET /api/assets/search/338?limit=100&page=N&order=NEWEST``
  （门户搜索框里的 ``q=icon_hv`` 只是把全量结果按相关性筛一遍，本脚本改成先抓
  全量、再按 ``CATALOG`` 里的标题精确匹配，结果更可控）
* 原图：返回的 ``generic_url`` 形如 ``...png?width={width}``，把占位符换成足够
  大的值，CDN 就会回原始文件而不是缩略图

图片按 army / equipment / hero / pet / spell / workshop 六类落到仓库根的
``pictures/``，文件名用国服官方译名（译名表见 ``CATALOG``）。该目录已在
``.gitignore`` 中忽略，不要提交进库。

用法::

    python scripts/fetch_fankit_assets.py --list       # 只打印计划，不下载
    python scripts/fetch_fankit_assets.py              # 下载缺失的（已存在则跳过）
    python scripts/fetch_fankit_assets.py --force      # 全部重下
    python scripts/fetch_fankit_assets.py --only army,spell

只用标准库（urllib + ThreadPoolExecutor），不需要装依赖。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://fankit.supercell.com"
DOCUMENT_ID = 338  # 门户里 "Game assets" 这个资源库的 document id
PAGE_LIMIT = 100
WIDTH_PLACEHOLDER = "9999"  # 大到超过任何原图宽度，CDN 就回原图
WORKERS = 6
RETRIES = 3

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "pictures"
CACHE = OUT_ROOT / ".fankit-assets.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# 分类 -> [(图片中文名, [候选资源标题…])]
#
# 候选标题按优先级列出：脚本会取「第一个命中的标题」，同一标题下有多个尺寸时
# 取像素面积最大的那张。译名以国服（bilibili WIKI）为准，例如
# Royal Champion=飞盾战神、Super Ice Hound=寒冰猎犬、Log Launcher=攻城滚木车。
CATALOG: dict[str, list[tuple[str, list[str]]]] = {
    "army": [
        ("弓箭手", ["Icon_HV_Archer"]),
        ("飞龙宝宝", ["Icon_HV_Baby_Dragon"]),
        ("气球兵", ["Icon_HV_Balloon"]),
        ("野蛮人", ["Icon_HV_Barbarian"]),
        ("巨石投手", ["Icon_HV_Bowler"]),
        ("飞龙", ["Icon_HV_Dragon"]),
        ("龙骑士", ["Icon_HV_Dragon_Rider"]),
        ("雷电飞龙", ["Icon_HV_Electro_Dragon"]),
        ("雷霆泰坦", ["Icon_HV_Electro_Titan"]),
        ("烈焰熔炉", ["Icon_HV_Furnace"]),
        ("巨人", ["Icon_HV_Giant"]),
        ("哥布林", ["Icon_HV_Goblin"]),
        ("戈仑石人", ["Icon_HV_Golem"]),
        ("英雄猎手", ["Icon_HV_Headhunter"]),
        ("天使", ["Icon_HV_Healer"]),
        ("野猪骑士", ["Icon_HV_Hog_Rider"]),
        ("戈仑冰人", ["Icon_HV_Ice_Golem"]),
        ("熔岩猎犬", ["Icon_HV_Lava_Hound"]),
        ("掘地矿工", ["Icon_HV_Miner"]),
        ("亡灵", ["Icon_HV_Minion"]),
        ("皮卡超人", ["Icon_HV_P.E.K.K.A"]),
        ("根蔓骑士", ["Icon_HV_Root_Rider"]),
        ("隐秘哥布林", ["Icon_HV_Sneaky_Goblin"]),
        ("瓦基丽武神", ["Icon_HV_Valkyrie"]),
        ("炸弹人", ["Icon_HV_Wall_Breaker"]),
        ("女巫", ["Icon_HV_Witch"]),
        ("法师", ["Icon_HV_Wizard"]),
        ("大雪怪", ["Icon_HV_Yeti"]),
        ("守护者学徒", ["Icon_HV_Apprentice_Warden"]),
        ("超级弓箭手", ["Icon_HV_Super_Archer"]),
        ("超级野蛮人", ["Icon_HV_Super_Barbarian"]),
        ("超级巨石投手", ["Icon_HV_Super_Bowler"]),
        ("超级飞龙", ["Icon_HV_Super_Dragon"]),
        ("超级巨人", ["Icon_HV_Super_Giant"]),
        ("超级野猪骑士", ["Icon_HV_Super_Hog_Rider"]),
        ("寒冰猎犬", ["Icon_HV_Super_Ice_Hound"]),
        ("地狱飞龙", ["Icon_HV_Super_Inferno_Dragon"]),
        ("超级矿工", ["Icon_HV_Super_Miner"]),
        ("超级亡灵", ["Icon_HV_Super_Minion"]),
        ("火箭气球兵", ["Icon_HV_Super_Rocket_Balloon"]),
        ("超级瓦基丽武神", ["Icon_HV_Super_Valkyrie"]),
        ("超级炸弹人", ["Icon_HV_Super_Wall_Breaker"]),
        ("超级女巫", ["Icon_HV_Super_Witch"]),
        ("超级法师", ["Icon_HV_Super_Wizard"]),
        # 以下兵种 Fankit 还没出 icon_hv，只能取整图（按游戏内尺寸优先）
        ("巨矛投手", ["Thrower_lvl_4", "Thrower_08_noShadow"]),
        ("陨石戈仑", ["MeteoriteGolem_withGrassbase_f61_3k"]),
        ("废墟女巫", ["Ruinwitch_f109_4k_withoutGroundshadows", "Ruinwitch_f109_4k"]),
        ("德鲁伊", ["Troop_HV_Druid_lvl6", "Druid_HV_05"]),
        ("超级大雪怪", ["icon_super_yeti", "SuperYeti_InfoScreen_InGameSize"]),
    ],
    "hero": [
        ("野蛮人之王", ["Icon_HV_Hero_Barbarian_King"]),
        ("弓箭女皇", ["Icon_HV_Hero_Archer_Queen"]),
        ("大守护者", ["Icon_HV_Hero_Grand_Warden"]),
        ("飞盾战神", ["Icon_HV_Hero_Royal_Champion"]),
        ("野蛮人之王_头像", ["Icon_HV_Barbarian_King_face"]),
        ("弓箭女皇_头像", ["Icon_HV_Archer_Queen_face"]),
        ("大守护者_头像", ["Icon_HV_Grand_Warden_face"]),
        # 新英雄同样没有 icon_hv，取整图（无阴影版更干净）
        ("飞龙公爵", ["DragonDuke_f011_4k"]),
        ("亡灵王子", ["Hero_Minion_Prince_01_NoShadow"]),
    ],
    "pet": [
        ("莱希", ["Icon_HV_Hero_Pets_LASSI"]),
        ("闪枭", ["Icon_HV_Hero_Pets_Electro_Owl"]),
        ("大牦", ["Icon_HV_Hero_Pets_Mighty_Yak"]),
        ("独角", ["Icon_HV_Hero_Pets_Unicorn"]),
        ("冰牙", ["Icon_HV_Hero_Pets_Frosty"]),
        ("地兽", ["Icon_HV_Hero_Pets_Diggy"]),
        ("猛蜥", ["Icon_HV_Hero_Pets_Poison_Lizard"]),
        ("凤凰", ["Icon_HV_Hero_Pets_Phoenix"]),
        ("灵狐", ["Icon_HV_Hero_Pets_Spirit_Fox"]),
        ("阿啾", ["Icon_HV_Hero_Pets_Sneezy_1"]),
        # 新战宠暂无 120px 图标，取整图
        ("贪婪渡鸦", ["pet_Greedy_Raven_1_grasspng"]),
        ("愤怒水母", ["Hero_Pet_HV_Angry_Jelly_01"]),
    ],
    "spell": [
        ("雷电法术", ["Icon_HV_Spell_Lightning_new"]),
        ("雷电法术_旧版", ["Icon_HV_Spell_Lightning_old"]),
        ("疗伤法术", ["Icon_HV_Spell_Heal"]),
        ("狂暴法术", ["Icon_HV_Spell_Rage"]),
        ("弹跳法术", ["Icon_HV_Spell_Jump"]),
        ("冰冻法术", ["Icon_HV_Spell_Freeze_new"]),
        ("冰冻法术_旧版", ["Icon_HV_Spell_Freeze_old"]),
        ("镜像法术", ["Icon_HV_Spell_Clone"]),
        ("隐形法术", ["Icon_HV_Spell_Invisibility"]),
        ("回溯法术", ["Icon_HV_Spell_Recall"]),
        ("复苏法术", ["Icon_HV_Spell_Revive"]),
        ("图腾法术", ["Icon_HV_Spell_totem"]),
        ("伤害药水法术", ["Icon_HV_Dark_Spell_Poison"]),
        ("地震法术", ["Icon_HV_Dark_Spell_Earthquake"]),
        ("急速法术", ["Icon_HV_Dark_Spell_Haste"]),
        ("骷髅法术", ["Icon_HV_Dark_Spell_Skeleton"]),
        ("蝙蝠法术", ["Icon_HV_Dark_Spell_Bat"]),
        ("疯狂蔓生法术", ["Icon_HV_Dark_Spell_Overgrowth"]),
        ("冰障法术", ["Icon_HV_Dark_Spell_Ice_block"]),
        ("生日爆炸法术", ["Icon_HV_Spell_Birthday_Boom"]),
        ("生日爆炸法术_横版", ["Icon_HV_Spell_Birthday_Boom_2"]),
        ("圣诞奇袭法术", ["Icon_HV_Spell_Santas_Surprise"]),
        ("黄牌法术", ["Icon_HV_Spell_Yellow_Card"]),
        ("霜虫袋法术", ["Icon_HV_Spell_Bag_of_Frostmites"]),
        ("愤怒法术", ["icon_angry_spell"]),
    ],
    "workshop": [
        ("攻城战车", ["Icon_HV_Siege_Machine_Wall_Wrecker"]),
        ("攻城飞艇", ["Icon_HV_Siege_Machine_Battle_Blimp"]),
        ("攻城训练营", ["Icon_HV_Siege_Machine_Siege_Barracks"]),
        ("攻城滚木车", ["Icon_HV_Siege_Machine_Log_Launcher"]),
        ("攻城烈焰车", ["Icon_HV_Siege_Machine_Flame_Flinger"]),
        ("攻城钻机", ["Icon_HV_Siege_Machine_Battle_Drill"]),
        ("攻城气球", ["Siege_Machine_HV_Stone_Slammer_1"]),
        ("部队发射器", ["icon_troop_launcher", "Troop_Launcher_NoGrass_NoShadow"]),
        ("空中战车", ["Siege_Machine_Sky_wagon_01"]),
    ],
    "equipment": [
        ("野蛮人木偶", ["Hero_Equipment_BK_Barbarian_Puppet"]),
        ("狂暴药水瓶", ["Hero_Equipment_BK_Rage_Vial"]),
        ("地震金靴", ["Hero_Equipment_BK_Earthquake_Boots"]),
        ("治疗胡须", ["Hero_Equipment_BK_Vampstache"]),
        ("巨型手套", ["Hero_Equipment_BQ_Giant_Gauntlet"]),
        ("尖刺足球", ["Hero_Equipment_BK_Spiky_Ball"]),
        ("灵蛇手镯", ["Hero_Equipment_BK_SnakeBracelet"]),
        ("木棍马驹", ["HeroGear_BK_StickFireHorse"]),
        ("弓箭手木偶", ["Hero_Equipment_AQ_Archer_Puppet"]),
        ("隐形药水瓶", ["Hero_Equipment_AQ_Invisibility_Vial"]),
        ("巨型箭矢", ["Hero_Equipment_AQ_Giant_Arrow"]),
        ("天使木偶", ["Hero_Equipment_AQ_Healer_Puppet"]),
        ("冰封箭矢", ["Hero_Equipment_AQ_Frozen_Arrow"]),
        ("擎天箭矢", ["Hero_Equipment_AQ_MonolithArrow"]),
        ("克隆魔镜", ["Hero_Equipment_AQ_Magic_Mirror"]),
        ("动作人偶", ["Hero_Equipment_AQ_WWEActionFigure"]),
        ("护卫玩偶", ["Hero_Equipment_MP_Henchman"]),
        ("暗黑魔球", ["Hero_Equipment_MP_DarkOrb"]),
        ("铁甲短裤", ["HeroEquipment_MP_IronPants"]),
        ("贵族哑铃", ["Hero_Equipment_MP_PowerPump"]),
        ("暗黑皇冠", ["HeroGear_MP_DarkCrown_2k"]),
        ("陨石法杖", ["HeroGear_MP_MeteoriteSceptre"]),
        ("永恒书卷", ["Hero_Equipment_GW_Eternal_Tome"]),
        ("生命宝石", ["Hero_Equipment_GW_Life_Gem"]),
        ("狂暴宝石", ["Hero_Equipment_GW_Rage_Gem"]),
        ("治疗书卷", ["Hero_Equipment_GW_Healing_Tome"]),
        ("巨大火球", ["Hero_Equipment_GW_Fireball"]),
        # 大图只放了 psd，退一步用官方的 332px 装备图标
        ("熔岩气球玩偶", ["HeroGear_LavaloonDoll", "icon_gear_GW_LavaloonPuppet"]),
        ("英雄火炬", ["HeroGear_GW_Olympic_Torch_hh0000"]),
        ("寻踪飞盾", ["Hero_Equipment_RC_Seeking_Shield"]),
        ("皇家宝石", ["Hero_Equipment_RC_Royal_Gem"]),
        ("野猪骑士玩偶", ["Hero_Equipment_RC_Hog_Rider_Doll"]),
        ("急速药水瓶", ["Hero_Equipment_RC_Haste_Vial"]),
        (
            "火箭飞矛",
            [
                "HeroGear_RoyalChampion_RocketSpear_Equipment_02",
                "HeroGear_RoyalChampion_RocketSpear_Equipment_03",
                "HeroGear_RoyalChampion_RocketSpear_Equipment_01",
            ],
        ),
        ("雷电战靴", ["Hero_Equipment_RC_ElectroBoots"]),
        ("冷冽冰晶", ["Hero_Equipment_rc_frost_flake"]),
        # 飞龙公爵六件套：Fankit 用 HG_DD_ 前缀，标题里带空格，别手抖改成下划线
        ("烈焰之心", ["HG_DD_Fire Heart"]),
        ("助燃器", ["HG_DD_Flame Blower"]),
        ("爆震器", ["HG_DD_StunBlast"]),
        ("雷电獠牙", ["HG_DD_Electro_Fangs"]),
        ("火箭背包", ["HG_DD_Rocket_BackPack"]),
        ("反击卡组", ["HG_DD_reverse_card"]),
        # 亡灵王子的史诗装备 Portal Pendant，Fankit 上连 psd 都没有，长期缺源
        ("传送吊坠", ["Hero_Equipment_MP_PortalPendant"]),
        # icon_hv 里唯一的两个装备图标，补进来
        ("弓箭女皇_弓", ["Icon_HV_Hero_Archer_Queen_Bow"]),
        ("野蛮人之王_拳", ["Icon_HV_Hero_Barbarian_King_Fist"]),
    ],
}


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, image/*",
            "Referer": f"{BASE}/d/vkEdmkUCngKw/game-assets",
        },
    )


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(_request(url), timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_assets(*, refresh: bool) -> list[dict]:
    """抓全量资源元数据；默认复用上次的缓存，``refresh=True`` 时重新抓。"""
    if not refresh and CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            if cached:
                print(f"复用缓存 {CACHE.relative_to(ROOT)}（{len(cached)} 条，--refresh 可重抓）")
                return cached
        except (OSError, ValueError):
            pass

    assets: dict[int, dict] = {}
    page = 1
    while True:
        url = (
            f"{BASE}/api/assets/search/{DOCUMENT_ID}"
            f"?limit={PAGE_LIMIT}&page={page}&order=NEWEST"
        )
        payload = fetch_json(url)
        batch = payload.get("data") or []
        for item in batch:
            assets[item["id"]] = item
        print(f"  第 {page} 页：{len(batch)} 条（累计 {len(assets)}）")
        if not batch or not payload.get("hasMore"):
            break
        page += 1

    result = list(assets.values())
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def pick(by_title: dict[str, list[dict]], titles: list[str]) -> dict | None:
    """按候选顺序取第一个存在的标题；同标题多尺寸时取面积最大的 png。"""
    for title in titles:
        variants = by_title.get(title)
        if not variants:
            continue
        # 只认位图：psd 跳过并试下一个候选（熔岩气球玩偶就是靠这条退回图标的）
        rasters = [v for v in variants if v.get("ext") != "psd"]
        if not rasters:
            continue
        rasters.sort(
            key=lambda v: (v.get("width", 0) * v.get("height", 0), v.get("file_size", 0)),
            reverse=True,
        )
        return rasters[0]
    return None


def build_plan(assets: list[dict], only: set[str] | None) -> tuple[list[dict], list[tuple]]:
    by_title: dict[str, list[dict]] = {}
    for item in assets:
        by_title.setdefault((item.get("title") or "").strip(), []).append(item)

    plan: list[dict] = []
    missing: list[tuple] = []
    for category, rows in CATALOG.items():
        if only and category not in only:
            continue
        for cn_name, titles in rows:
            asset = pick(by_title, titles)
            if asset is None:
                missing.append((category, cn_name, titles))
                continue
            plan.append(
                {
                    "category": category,
                    "cn": cn_name,
                    "title": (asset.get("title") or "").strip(),
                    "ext": asset.get("ext", "png"),
                    "width": asset.get("width", 0),
                    "height": asset.get("height", 0),
                    "url": asset["generic_url"].replace("{width}", WIDTH_PLACEHOLDER),
                }
            )
    return plan, missing


def sniff_ext(data: bytes, fallback: str) -> str:
    """CDN 偶尔用 .png 的 URL 回 JPEG，按文件头纠正扩展名。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"8BPS":
        return "psd"
    return fallback


def existing(target_dir: Path, cn_name: str) -> Path | None:
    for candidate in target_dir.glob(f"{cn_name}.*"):
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def download(job: dict, *, force: bool) -> tuple[dict, str]:
    target_dir = OUT_ROOT / job["category"]
    target_dir.mkdir(parents=True, exist_ok=True)

    if not force:
        found = existing(target_dir, job["cn"])
        if found:
            return job, f"跳过（已有 {found.name}）"

    last_error = ""
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(_request(job["url"]), timeout=180) as resp:
                data = resp.read()
            if len(data) < 100:
                raise OSError(f"文件过小（{len(data)} 字节）")
            ext = sniff_ext(data, job["ext"])
            path = target_dir / f"{job['cn']}.{ext}"
            # 换过扩展名时清掉旧文件，避免同图两份
            for stale in target_dir.glob(f"{job['cn']}.*"):
                if stale != path and stale.is_file():
                    stale.unlink()
            path.write_bytes(data)
            return job, f"ok {len(data) // 1024} KB"
        except (urllib.error.URLError, OSError) as exc:
            last_error = str(exc)
            if attempt + 1 < RETRIES:
                time.sleep(1.5 * (attempt + 1))
    return job, f"失败：{last_error}"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="下载 Fankit 部落冲突图标素材")
    parser.add_argument("--list", action="store_true", help="只打印计划，不下载")
    parser.add_argument("--force", action="store_true", help="已存在的文件也重下")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存，重新抓资源列表")
    parser.add_argument(
        "--only",
        default="",
        help="只处理指定分类，逗号分隔：army,equipment,hero,pet,spell,workshop",
    )
    args = parser.parse_args()

    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    unknown = (only or set()) - set(CATALOG)
    if unknown:
        print(f"未知分类：{sorted(unknown)}；可选 {sorted(CATALOG)}", file=sys.stderr)
        return 2

    print("抓取资源列表…")
    assets = collect_assets(refresh=args.refresh)
    plan, missing = build_plan(assets, only)

    for category, cn_name, titles in missing:
        print(f"缺源：{category}/{cn_name} <- {titles}")

    if args.list:
        for job in sorted(plan, key=lambda j: (j["category"], j["cn"])):
            print(
                f"{job['category']:10} {job['cn']:16} <- {job['title']:52} "
                f"{job['width']}x{job['height']} {job['ext']}"
            )
        print(f"共 {len(plan)} 张，缺失 {len(missing)} 张")
        return 0

    if not plan:
        print("没有可下载的条目")
        return 0

    print(f"开始下载 {len(plan)} 张（并发 {WORKERS}）…")
    failures: list[tuple[dict, str]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for job, status in pool.map(lambda j: download(j, force=args.force), plan):
            done += 1
            print(f"[{done}/{len(plan)}] {job['category']}/{job['cn']}.{job['ext']} -> {status}")
            if not status.startswith(("ok", "跳过")):
                failures.append((job, status))

    print(
        f"完成：{len(plan) - len(failures)} 成功，{len(failures)} 失败，{len(missing)} 缺源"
    )
    for job, status in failures:
        print(f"  {job['category']}/{job['cn']} {status}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
