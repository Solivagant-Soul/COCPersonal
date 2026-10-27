/**
 * 官方 API 的英文单位名 → 本地素材库的中文文件名。
 *
 * 为什么要这张表：``/players/{tag}`` 返回的是 ``"Barbarian"`` / ``"Lightning Spell"``
 * 这类英文名，而 ``frontend/public/pictures/`` 下的图是用国服译名落盘的
 * （``army/野蛮人.png``、``spell/雷电法术.png``，见 ``scripts/fetch_fankit_assets.py``
 * 的 ``CATALOG``）。两边不打通就只能显示英文或空白。
 *
 * 约定：
 *   - 只收录**主村**单位。夜世界（``village: "builderBase"``）的单位素材库里没有，
 *     详情页按 ``village`` 过滤掉。
 *   - 查不到的名字（官方新加单位）返回 ``null``，由组件退化成文字兜底 ——
 *     **绝不因为多了一个新兵种就白屏**。
 *   - 攻城机器在 API 里也算 ``troops``，但图在 ``workshop`` 目录，故每条都带 folder。
 */

export type UnitFolder = 'army' | 'spell' | 'hero' | 'workshop'

export interface UnitAsset {
  /** 国服译名，同时也是图片文件名（不带扩展名）。 */
  zh: string
  /** ``public/pictures`` 下的子目录。 */
  folder: UnitFolder
}

const troop = (zh: string): UnitAsset => ({ zh, folder: 'army' })
const siege = (zh: string): UnitAsset => ({ zh, folder: 'workshop' })
const spell = (zh: string): UnitAsset => ({ zh, folder: 'spell' })
const hero = (zh: string): UnitAsset => ({ zh, folder: 'hero' })

/** ``troops[]``（含攻城机器与已激活的超级兵）。 */
export const TROOP_ASSETS: Record<string, UnitAsset> = {
  Archer: troop('弓箭手'),
  'Baby Dragon': troop('飞龙宝宝'),
  Balloon: troop('气球兵'),
  Barbarian: troop('野蛮人'),
  Bowler: troop('巨石投手'),
  Dragon: troop('飞龙'),
  'Dragon Rider': troop('龙骑士'),
  'Electro Dragon': troop('雷电飞龙'),
  'Electro Titan': troop('雷霆泰坦'),
  Furnace: troop('烈焰熔炉'),
  Giant: troop('巨人'),
  Goblin: troop('哥布林'),
  Golem: troop('戈仑石人'),
  Headhunter: troop('英雄猎手'),
  Healer: troop('天使'),
  'Hog Rider': troop('野猪骑士'),
  'Ice Golem': troop('戈仑冰人'),
  'Lava Hound': troop('熔岩猎犬'),
  Miner: troop('掘地矿工'),
  Minion: troop('亡灵'),
  'P.E.K.K.A': troop('皮卡超人'),
  'Root Rider': troop('根蔓骑士'),
  'Sneaky Goblin': troop('隐秘哥布林'),
  Valkyrie: troop('瓦基丽武神'),
  'Wall Breaker': troop('炸弹人'),
  Witch: troop('女巫'),
  Wizard: troop('法师'),
  Yeti: troop('大雪怪'),
  'Apprentice Warden': troop('守护者学徒'),
  // 超级兵
  'Super Archer': troop('超级弓箭手'),
  'Super Barbarian': troop('超级野蛮人'),
  'Super Bowler': troop('超级巨石投手'),
  'Super Dragon': troop('超级飞龙'),
  'Super Giant': troop('超级巨人'),
  'Super Hog Rider': troop('超级野猪骑士'),
  'Super Ice Hound': troop('寒冰猎犬'),
  'Inferno Dragon': troop('地狱飞龙'),
  'Super Miner': troop('超级矿工'),
  'Super Minion': troop('超级亡灵'),
  'Rocket Balloon': troop('火箭气球兵'),
  'Super Valkyrie': troop('超级瓦基丽武神'),
  'Super Wall Breaker': troop('超级炸弹人'),
  'Super Witch': troop('超级女巫'),
  'Super Wizard': troop('超级法师'),
  Thrower: troop('巨矛投手'),
  'Meteor Golem': troop('陨石戈仑'),
  'Ruin Witch': troop('废墟女巫'),
  Druid: troop('德鲁伊'),
  'Super Yeti': troop('超级大雪怪'),
  // 攻城机器：API 归在 troops 里，素材在 workshop 目录
  'Wall Wrecker': siege('攻城战车'),
  'Battle Blimp': siege('攻城飞艇'),
  'Siege Barracks': siege('攻城训练营'),
  'Log Launcher': siege('攻城滚木车'),
  'Flame Flinger': siege('攻城烈焰车'),
  'Battle Drill': siege('攻城钻机'),
  'Stone Slammer': siege('攻城气球'),
  'Troop Launcher': siege('部队发射器'),
  'Sky Wagon': siege('空中战车'),
}

/** ``spells[]``。 */
export const SPELL_ASSETS: Record<string, UnitAsset> = {
  'Lightning Spell': spell('雷电法术'),
  'Healing Spell': spell('疗伤法术'),
  'Rage Spell': spell('狂暴法术'),
  'Jump Spell': spell('弹跳法术'),
  'Freeze Spell': spell('冰冻法术'),
  'Clone Spell': spell('镜像法术'),
  'Invisibility Spell': spell('隐形法术'),
  'Recall Spell': spell('回溯法术'),
  'Revive Spell': spell('复苏法术'),
  'Poison Spell': spell('伤害药水法术'),
  'Earthquake Spell': spell('地震法术'),
  'Haste Spell': spell('急速法术'),
  'Skeleton Spell': spell('骷髅法术'),
  'Bat Spell': spell('蝙蝠法术'),
  'Overgrowth Spell': spell('疯狂蔓生法术'),
  'Ice Block Spell': spell('冰障法术'),
  'Totem Spell': spell('图腾法术'),
  'Angry Spell': spell('愤怒法术'),
}

/** ``heroes[]``。 */
export const HERO_ASSETS: Record<string, UnitAsset> = {
  'Barbarian King': hero('野蛮人之王'),
  'Archer Queen': hero('弓箭女皇'),
  'Grand Warden': hero('大守护者'),
  'Royal Champion': hero('飞盾战神'),
  'Minion Prince': hero('亡灵王子'),
  'Dragon Duke': hero('飞龙公爵'),
}

/**
 * 按分组查素材。分组名与 API 字段同名，避免再发明一套名字。
 *
 * 找不到返回 ``null`` —— 调用方据此退化成文字格子，而不是渲染一个必然 404 的 img。
 */
export function lookupUnitAsset(
  group: 'troops' | 'spells' | 'heroes',
  name: string,
): UnitAsset | null {
  const table =
    group === 'troops' ? TROOP_ASSETS : group === 'spells' ? SPELL_ASSETS : HERO_ASSETS
  return Object.prototype.hasOwnProperty.call(table, name) ? table[name] : null
}

/** 主村单位。缺 ``village`` 时按主村算（官方对老单位偶发不发）。 */
export function isHomeVillage(village: unknown): boolean {
  return village === undefined || village === null || village === '' || village === 'home'
}
