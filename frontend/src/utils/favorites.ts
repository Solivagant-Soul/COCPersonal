/**
 * 关注列表（玩家 / 部落）：存在浏览器 localStorage 里，**不进后端**。
 *
 * 为什么不是后端：后端目前没有账号体系（`users` 与 `user_clan_subscriptions` 只是
 * 二期地基，AGENTS.md 明确说账号功能前不要写它们的读写逻辑）。关注是纯个人的
 * 收藏，换设备不带过去可以接受；硬要做服务端就得先解决"这条关注属于哪个匿名用户"。
 *
 * 与 `searchHistory` 同样的容错原则：localStorage 可能被禁用、内容可能被改坏 ——
 * 任何一种情况都只表现为"没有关注"，绝不能让详情页崩掉。
 */

/** localStorage 的键名。加前缀避免与同域其它应用撞车。 */
export const FAVORITES_KEY = 'cocpersonal.favorites'

/** 最多保留多少条：再多就不是"关注"而是"收藏夹"了。 */
export const FAVORITES_LIMIT = 50

export type FavoriteKind = 'player' | 'clan'

export interface FavoriteEntry {
  /** 归一化后的标签（`#ABC`，大写）。 */
  tag: string
  kind: FavoriteKind
  /** 关注时的显示名，列表里优先用它。 */
  name?: string | null
  /** 毫秒时间戳，用于倒序展示。 */
  at: number
}

function isEntry(value: unknown): value is FavoriteEntry {
  if (typeof value !== 'object' || value === null) return false
  const e = value as Record<string, unknown>
  return (
    typeof e.tag === 'string' &&
    e.tag.length > 0 &&
    (e.kind === 'player' || e.kind === 'clan') &&
    typeof e.at === 'number'
  )
}

/** 读关注列表，**最新的在前**。存储损坏时返回空数组而不是抛异常。 */
export function readFavorites(): FavoriteEntry[] {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(FAVORITES_KEY)
  } catch {
    return []
  }
  if (!raw) return []

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return []
  }
  if (!Array.isArray(parsed)) return []

  return parsed.filter(isEntry).sort((a, b) => b.at - a.at)
}

function writeFavorites(entries: FavoriteEntry[]): void {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(entries))
  } catch {
    // 写不进去（配额满 / 隐私模式）—— 关注是锦上添花，失败就算了
  }
}

export function isFavorite(tag: string, kind: FavoriteKind): boolean {
  return readFavorites().some((e) => e.tag === tag && e.kind === kind)
}

/**
 * 切换关注状态，返回**切换后**是否已关注。
 *
 * 同一个标签重复关注不会产生多条 —— 先按 (tag, kind) 去重再插入。
 */
export function toggleFavorite(entry: {
  tag: string
  kind: FavoriteKind
  name?: string | null
}): boolean {
  const existing = readFavorites()
  const found = existing.some((e) => e.tag === entry.tag && e.kind === entry.kind)
  if (found) {
    writeFavorites(existing.filter((e) => !(e.tag === entry.tag && e.kind === entry.kind)))
    return false
  }
  const next: FavoriteEntry[] = [
    { tag: entry.tag, kind: entry.kind, name: entry.name ?? null, at: Date.now() },
    ...existing,
  ]
  writeFavorites(next.slice(0, FAVORITES_LIMIT))
  return true
}

export function removeFavorite(tag: string, kind: FavoriteKind): void {
  writeFavorites(readFavorites().filter((e) => !(e.tag === tag && e.kind === kind)))
}

export function clearFavorites(): void {
  writeFavorites([])
}
