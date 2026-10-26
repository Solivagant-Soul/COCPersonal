/**
 * 配兵分享码（armyShareCode / armyLink 的 ``army`` 参数）解析。
 *
 * 官方格式按段拼接，每段以类型字母开头：
 *
 * - ``h``：英雄，形如 ``0p9e14_32``（英雄 id / 战宠 id / 两件装备 id）
 * - ``i``：城堡援军（部队）
 * - ``d``：城堡援军（法术）
 * - ``u``：部队（含攻城机器）
 * - ``s``：法术
 *
 * 段内条目是 ``<数量>x<id>``，用 ``-`` 分隔。这里的 id 是游戏数据的尾号
 * （例如 4000132 → 132），与名称表的键一一对应。解析失败时**不抛异常**：
 * 一张卡片的分享码坏了不该让整页白屏，拿不到的部分直接略过。
 */

export type ArmyUnitKind = 'troop' | 'siege' | 'spell' | 'hero' | 'pet' | 'equipment'

export type ArmyGroupKey = 'troops' | 'spells' | 'heroes' | 'castle'

export interface ArmyUnit {
  kind: ArmyUnitKind
  id: number
  name: string
  count: number
}

export interface ArmyGroup {
  key: ArmyGroupKey
  label: string
  units: ArmyUnit[]
}

const TROOP_NAMES: Record<number, string> = {
  0: '野蛮人',
  1: '弓箭手',
  2: '哥布林',
  3: '巨人',
  4: '炸弹人',
  5: '气球兵',
  6: '法师',
  7: '天使',
  8: '飞龙',
  9: '皮卡超人',
  10: '亡灵',
  11: '野猪骑士',
  12: '瓦基丽武神',
  13: '戈仑石人',
  15: '女巫',
  17: '熔岩猎犬',
  22: '巨石投手',
  23: '飞龙宝宝',
  24: '掘地矿工',
  26: '超级野蛮人',
  27: '超级弓箭手',
  28: '超级炸弹人',
  29: '超级巨人',
  53: '大雪怪',
  55: '隐秘哥布林',
  56: '超级矿工',
  57: '火箭气球兵',
  58: '戈仑冰人',
  59: '雷电飞龙',
  63: '地狱飞龙',
  64: '超级瓦基丽武神',
  65: '龙骑士',
  66: '超级女巫',
  76: '寒冰猎犬',
  80: '超级巨石投手',
  81: '超级飞龙',
  82: '英雄猎手',
  83: '超级法师',
  84: '超级亡灵',
  95: '雷霆泰坦',
  97: '守护者学徒',
  98: '超级野猪骑士',
  109: '废墟女巫',
  110: '根蔓骑士',
  123: '德鲁伊',
  132: '巨矛投手',
  147: '超级大雪怪',
  150: '烈焰熔炉',
  177: '陨石戈仑',
}

const SIEGE_NAMES: Record<number, string> = {
  51: '攻城战车',
  52: '攻城飞艇',
  62: '攻城槌',
  75: '攻城训练营',
  87: '攻城滚木车',
  91: '攻城烈焰车',
  92: '攻城钻机',
  135: '部队发射器',
  188: '空中战车',
}

const SPELL_NAMES: Record<number, string> = {
  0: '雷电法术',
  1: '疗伤法术',
  2: '狂暴法术',
  3: '弹跳法术',
  5: '冰冻法术',
  9: '伤害药水法术',
  10: '地震法术',
  11: '急速法术',
  16: '镜像法术',
  17: '骷髅法术',
  28: '蝙蝠法术',
  35: '隐形法术',
  53: '回溯法术',
  70: '疯狂蔓生法术',
  98: '复苏法术',
  109: '冰障法术',
  120: '图腾法术',
  123: '愤怒法术',
}

const HERO_NAMES: Record<number, string> = {
  0: '野蛮人之王',
  1: '弓箭女皇',
  2: '大守护者',
  4: '飞盾战神',
  6: '亡灵王子',
  7: '飞龙公爵',
}

const PET_NAMES: Record<number, string> = {
  0: '莱希',
  1: '大牦',
  2: '闪枭',
  3: '独角',
  4: '凤凰',
  7: '猛蜥',
  8: '地兽',
  9: '冰牙',
  10: '灵狐',
  11: '愤怒水母',
  16: '阿啾',
  17: '贪婪渡鸦',
}

const EQUIPMENT_NAMES: Record<number, string> = {
  0: '野蛮人木偶',
  1: '狂暴药水瓶',
  2: '弓箭手木偶',
  3: '隐形药水瓶',
  4: '永恒书卷',
  5: '生命宝石',
  6: '寻踪飞盾',
  7: '皇家宝石',
  8: '地震金靴',
  9: '野猪骑士玩偶',
  10: '巨型手套',
  11: '治疗胡须',
  12: '急速药水瓶',
  13: '火箭飞矛',
  14: '尖刺足球',
  15: '冰封箭矢',
  16: '擎天箭矢',
  17: '巨型箭矢',
  19: '英雄火炬',
  20: '天使木偶',
  22: '巨大火球',
  24: '狂暴宝石',
  32: '灵蛇手镯',
  34: '治疗书卷',
  35: '暗黑皇冠',
  39: '克隆魔镜',
  40: '雷电战靴',
  41: '熔岩气球玩偶',
  42: '护卫玩偶',
  43: '暗黑魔球',
  44: '铁甲短裤',
  47: '贵族哑铃',
  48: '动作人偶',
  49: '陨石法杖',
  50: '冷冽冰晶',
  51: '木棍马驹',
  52: '烈焰之心',
  53: '火箭背包',
  56: '眩晕冲击波',
  57: '烈焰喷射器',
  59: '雷电獠牙',
  60: '反击卡组',
  61: '传送吊坠',
}

/** 图片目录（frontend/public/pictures 下的子目录）。 */
export const UNIT_IMAGE_FOLDER: Record<ArmyUnitKind, string> = {
  troop: 'army',
  siege: 'workshop',
  spell: 'spell',
  hero: 'hero',
  pet: 'pet',
  equipment: 'equipment',
}

/**
 * 阵容标题的中文名。War Report 的 ``name`` 是英文，直接展示会与站内其余
 * 中文文案割裂。没收录的新阵容保留原名；组合名按 ``&`` / ``+`` 拆开翻译。
 */
const ARMY_TITLE_ZH: Record<string, string> = {
  Thrower: '巨矛投手',
  'Super Bowler': '超级巨石投手',
  'Dragon & Dragon Rider': '飞龙 + 龙骑士',
  'Dragon Rider': '龙骑士',
  'Rocket Balloon': '火箭气球兵',
  'Balloon & Ice Hound': '气球兵 + 寒冰猎犬',
  'Super Yeti': '超级大雪怪',
  'Balloon & Dragon': '气球兵 + 飞龙',
  'Apprentice Warden': '守护者学徒',
  'Ruin Witch': '废墟女巫',
  'Healer & Thrower': '天使 + 巨矛投手',
  'Super Minion': '超级亡灵',
  'Meteor Golem': '陨石戈仑',
}

export function armyTitleZh(name: string): string {
  const trimmed = name.trim()
  const direct = ARMY_TITLE_ZH[trimmed]
  if (direct) return direct

  const parts = trimmed.split(/\s*(?:&|\+)\s*/).filter(Boolean)
  if (parts.length > 1) {
    return parts.map((part) => ARMY_TITLE_ZH[part] ?? part).join(' + ')
  }
  return trimmed
}

function lookupName(kind: ArmyUnitKind, id: number): string {
  const table: Record<ArmyUnitKind, Record<number, string>> = {
    troop: TROOP_NAMES,
    siege: SIEGE_NAMES,
    spell: SPELL_NAMES,
    hero: HERO_NAMES,
    pet: PET_NAMES,
    equipment: EQUIPMENT_NAMES,
  }
  const found = table[kind][id]
  if (found) return found
  const label = kind === 'hero' ? '英雄' : kind === 'pet' ? '战宠' : kind === 'equipment' ? '装备' : '单位'
  return `未知${label} #${id}`
}

function addUnit(
  group: ArmyGroup,
  kind: ArmyUnitKind,
  id: number,
  count: number,
): void {
  if (!Number.isFinite(id) || !Number.isFinite(count) || count <= 0) return
  // 同一段里偶尔会重复出现同一个 id，合并而不是显示两个图标
  const existing = group.units.find((unit) => unit.kind === kind && unit.id === id)
  if (existing) {
    existing.count += count
    return
  }
  group.units.push({ kind, id, name: lookupName(kind, id), count })
}

/** ``9x132-5x7`` → ``[{ id: 132, count: 9 }, { id: 7, count: 5 }]`` */
function parseUnits(payload: string): Array<{ id: number; count: number }> {
  const result: Array<{ id: number; count: number }> = []
  for (const item of payload.split('-')) {
    const match = /^(\d+)x(\d+)$/.exec(item.trim())
    if (!match) continue
    result.push({ count: Number(match[1]), id: Number(match[2]) })
  }
  return result
}

const HERO_ENTRY = /^(\d+)(?:m\d+)?(?:p(\d+))?(?:e(\d+)(?:_(\d+))?)?$/

function addHeroEntry(group: ArmyGroup, entry: string): void {
  const match = HERO_ENTRY.exec(entry.trim())
  if (!match) return
  const heroId = Number(match[1])
  addUnit(group, 'hero', heroId, 1)
  if (match[2]) addUnit(group, 'pet', Number(match[2]), 1)
  if (match[3]) addUnit(group, 'equipment', Number(match[3]), 1)
  if (match[4]) addUnit(group, 'equipment', Number(match[4]), 1)
}

/**
 * 解析分享码。返回按界面顺序排好的四组（部队 / 法术 / 英雄 / 城堡），
 * 空组会被省略。坏输入返回空数组。
 */
export function parseArmyShareCode(code: string): ArmyGroup[] {
  if (!code) return []

  const groups: Record<ArmyGroupKey, ArmyGroup> = {
    troops: { key: 'troops', label: '部队', units: [] },
    spells: { key: 'spells', label: '法术', units: [] },
    heroes: { key: 'heroes', label: '英雄', units: [] },
    castle: { key: 'castle', label: '城堡', units: [] },
  }

  // 段首字母只可能是 h/i/d/u/s；内容里不会再出现这些字母
  for (const match of code.matchAll(/([hidus])([^hidus]*)/g)) {
    const section = match[1]
    const payload = match[2] ?? ''
    if (!payload) continue

    if (section === 'h') {
      for (const entry of payload.split('-')) {
        if (entry) addHeroEntry(groups.heroes, entry)
      }
      continue
    }

    for (const { id, count } of parseUnits(payload)) {
      if (section === 'u') {
        const kind: ArmyUnitKind = SIEGE_NAMES[id] ? 'siege' : 'troop'
        addUnit(groups.troops, kind, id, count)
      } else if (section === 's') {
        addUnit(groups.spells, 'spell', id, count)
      } else if (section === 'i') {
        const kind: ArmyUnitKind = SIEGE_NAMES[id] ? 'siege' : 'troop'
        addUnit(groups.castle, kind, id, count)
      } else if (section === 'd') {
        addUnit(groups.castle, 'spell', id, count)
      }
    }
  }

  return (Object.values(groups) as ArmyGroup[]).filter((group) => group.units.length > 0)
}
