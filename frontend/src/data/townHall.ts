/**
 * 大本营等级 → 图标路径。
 *
 * 素材是 Fankit 上每一级大本营的建筑渲染图（透明底），由
 * ``scripts/fetch_fankit_assets.py`` 的 ``townhall`` 分类落到
 * ``public/pictures/townhall/TH{等级}.png``。
 *
 * 该目录与其它素材一样是 **gitignored** 的：本地要跑
 * ``python scripts/fetch_fankit_assets.py --only townhall``，
 * 线上要 ``./deploy/compose.sh sync-assets`` 补图（见 docs/deployment.md §14）。
 */

/** 有官方图的等级区间：1–16 是 `Building_HV_Town_Hall_*`，17/18 是整图。 */
const MIN_TOWN_HALL = 1
const MAX_TOWN_HALL = 18

/**
 * 越界 / 非整数 / 缺失一律返回 ``null``：素材库里没有这一级时宁可不显示，
 * 也别让浏览器去请求一张必然 404 的图（`/pictures/**` 会回落到 index.html）。
 */
export function townHallIcon(level: unknown): string | null {
  if (typeof level !== 'number' || !Number.isInteger(level)) return null
  if (level < MIN_TOWN_HALL || level > MAX_TOWN_HALL) return null
  return `/pictures/townhall/TH${level}.png`
}
