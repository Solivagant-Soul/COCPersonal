/**
 * 查询历史：存在浏览器 localStorage 里，**不进后端**。
 *
 * 为什么是本地而不是后端：后端目前没有账号体系（`users` 表只是二期地基，
 * AGENTS.md 明确说账号功能前不要写它的读写逻辑），而搜索历史是**纯个人**
 * 的临时数据 —— 换设备不带过去完全合理，存服务端反而要处理"这条历史属于
 * 哪个匿名用户"的问题。
 *
 * **所有读写都必须容错**：localStorage 在隐私模式/禁用 cookie 下会抛，
 * 存的内容也可能是用户手动改坏的 JSON。任何一种情况都只该表现为"没有历史"，
 * 绝不能让查询页崩掉 —— 查询是本站的主功能，不能被一个装饰性功能拖垮。
 */

/** localStorage 的键名。加前缀避免与同域其它应用撞车。 */
export const HISTORY_KEY = 'cocpersonal.searchHistory'

/** 最多保留多少条。多了就变成一堵墙，反而难用。 */
export const HISTORY_LIMIT = 10

export type HistoryKind = 'player' | 'clan'

export interface HistoryEntry {
  /** 归一化后的标签（`#ABC`，大写）。 */
  tag: string
  kind: HistoryKind
  /** 毫秒时间戳，用于倒序展示。 */
  at: number
}

function isEntry(value: unknown): value is HistoryEntry {
  if (typeof value !== 'object' || value === null) return false
  const e = value as Record<string, unknown>
  return (
    typeof e.tag === 'string' &&
    e.tag.length > 0 &&
    (e.kind === 'player' || e.kind === 'clan') &&
    typeof e.at === 'number'
  )
}

/**
 * 读历史。返回**最新的在前**。
 *
 * 存储被改坏时返回空数组而不是抛异常：损坏的本地数据不该让整站报错。
 */
export function readHistory(): HistoryEntry[] {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(HISTORY_KEY)
  } catch {
    // localStorage 不可用（隐私模式等）—— 当作没有历史
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

  // 逐条校验：数组里混进一条坏数据不该拖垮其余的
  return parsed.filter(isEntry).sort((a, b) => b.at - a.at)
}

function writeHistory(entries: HistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries))
  } catch {
    // 写不进去（配额满/隐私模式）—— 历史是锦上添花，失败就算了
  }
}

/**
 * 记一条查询历史。
 *
 * 同一 (tag, kind) 再次查询**移到最前**而不是新增一条 —— 否则连查十次同一个
 * 标签就把它剩下的九种查询方式挤掉了。
 */
export function addHistory(tag: string, kind: HistoryKind): void {
  const existing = readHistory().filter((e) => !(e.tag === tag && e.kind === kind))
  const next: HistoryEntry[] = [{ tag, kind, at: Date.now() }, ...existing]
  writeHistory(next.slice(0, HISTORY_LIMIT))
}

/** 删掉一条历史。 */
export function removeHistory(tag: string, kind: HistoryKind): void {
  writeHistory(readHistory().filter((e) => !(e.tag === tag && e.kind === kind)))
}

/** 清空全部历史。 */
export function clearHistory(): void {
  writeHistory([])
}
