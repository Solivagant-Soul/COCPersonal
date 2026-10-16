/**
 * 纯格式化工具（移植自小程序 `COC/utils/format.js`）。不发请求、不碰全局。
 *
 * 约定：
 *   - 缺失值一律返回 `'-'`，不返回 `'undefined'` / `'null'` / `'NaN'`
 *   - 未知枚举值原样返回（后端加新枚举时不至于整屏 undefined）
 */

const PLACEHOLDER = '-'

const SEC = 1000
const MIN = 60 * SEC
const HOUR = 60 * MIN
const DAY = 24 * HOUR

const WAN = 10000
const YI = 100000000

// toFixed 在 |x| >= 1e21 时会输出科学计数法，这个量级的小数位已是浮点噪声，直接取整
const MAX_EXACT_FIXED = 1e21

/** 可被格式化工具接受的原始值。 */
export type Formattable = number | string | null | undefined

/**
 * 把任意输入收敛成有限 number，收敛不了返回 null。
 * 注意 `Number(null) === 0`，null 必须先短路。
 */
function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'boolean') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/** 展开 `String(1e21)` → `"1e+21"` 这类科学计数法，还原普通十进制字符串。 */
function expandExponential(str: string): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?e\+?(\d+)$/i.exec(str)
  if (!m) return str
  const sign = m[1]
  const intPart = m[2]
  const fracPart = m[3] ?? ''
  const exp = Number(m[4])
  const digits = intPart + fracPart
  const pointAt = intPart.length + exp
  if (pointAt >= digits.length) {
    return sign + digits + '0'.repeat(pointAt - digits.length)
  }
  if (pointAt > 0) {
    return sign + digits.slice(0, pointAt) + '.' + digits.slice(pointAt)
  }
  return sign + '0.' + '0'.repeat(-pointAt) + digits
}

/** 千分位分隔。非整数输入保留小数部分。 */
function groupThousands(plain: string): string {
  const neg = plain.charAt(0) === '-'
  const body = neg ? plain.slice(1) : plain
  const dot = body.indexOf('.')
  const intPart = dot === -1 ? body : body.slice(0, dot)
  const fracPart = dot === -1 ? '' : body.slice(dot)
  return (neg ? '-' : '') + intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + fracPart
}

/**
 * 缩到 1 位小数并按需要去尾零。两条分支的串形态不同，去尾零的做法必须分开：
 *
 *   toFixed 分支：串里必定有小数点且恰好 1 位小数，尾零只可能来自 ".0"，剥它安全。
 *   Math.floor 分支：产出的是纯整数串，**不能剥尾零** —— 那是有效数字。
 *     曾在这里统一跑 `replace(/0+$/, '')`，`formatCompact(3e29)` 直接从
 *     `"3000000000000000000000亿"` 变成 `"3亿"`，凭空差 21 个数量级。
 */
function oneDecimal(x: number): string {
  if (Math.abs(x) < MAX_EXACT_FIXED) return x.toFixed(1).replace(/\.0$/, '')
  // |x| >= 1e21 时小数位本身已是浮点噪声，取整即可，但一个有效数字都不能少
  return expandExponential(String(Math.floor(x)))
}

/** 千分位。null / undefined / NaN / 非数字 → `'-'`。 */
export function formatNumber(n: Formattable): string {
  const v = toFiniteNumber(n)
  if (v === null) return PLACEHOLDER
  return groupThousands(expandExponential(String(v)))
}

/** 中文缩写：< 1万 原样千分位，< 1亿 用「万」，否则用「亿」。 */
export function formatCompact(n: Formattable): string {
  const v = toFiniteNumber(n)
  if (v === null) return PLACEHOLDER
  if (v < WAN) return formatNumber(v)
  if (v < YI) return oneDecimal(v / WAN) + '万'
  return oneDecimal(v / YI) + '亿'
}

/**
 * `nowMs` 必传（页面自己取，避免在工具层依赖环境时钟）。
 * < 1 分钟「刚刚」，< 1 小时「N 分钟前」，< 1 天「N 小时前」，否则「N 天前」。
 */
export function formatRelativeTime(
  isoStr: string | Date | null | undefined,
  nowMs: number,
): string {
  if (isoStr === null || isoStr === undefined || isoStr === '') return PLACEHOLDER
  const t = isoStr instanceof Date ? isoStr.getTime() : Date.parse(isoStr)
  if (!Number.isFinite(t)) return PLACEHOLDER
  const diff = Number(nowMs) - t
  if (!Number.isFinite(diff)) return PLACEHOLDER
  // 未来时间（服务器时钟超前 / 官方时间还没到）落「刚刚」，不显示「-1 分钟前」
  if (diff < MIN) return '刚刚'
  if (diff < HOUR) return Math.floor(diff / MIN) + ' 分钟前'
  if (diff < DAY) return Math.floor(diff / HOUR) + ' 小时前'
  return Math.floor(diff / DAY) + ' 天前'
}

// 与后端 app/coc/tags.py 的 _TAG_RE 对齐：#? + 3–10 位字母数字
const TAG_RE = /^[0-9A-Z]{3,10}$/
const FULLWIDTH_HASH = /\uFF03/g

/**
 * 全角＃→#，去前缀 #，大写，校验。不合法返回 null —— 不发注定 400 的请求。
 */
export function normalizeTag(input: unknown): string | null {
  if (input === null || input === undefined) return null
  const s = String(input)
    .trim()
    .replace(FULLWIDTH_HASH, '#')
    .replace(/^#+/, '')
    .toUpperCase()
  if (!s) return null
  return TAG_RE.test(s) ? '#' + s : null
}

/**
 * 枚举中文表。group 的取值域以规格 §5 + 后端为准。
 */
export const ENUM_LABELS: Record<string, Record<string, string>> = {
  role: {
    leader: '首领',
    coLeader: '副首领',
    admin: '长老',
    member: '成员',
  },
  warFrequency: {
    always: '始终开战',
    moreThanOncePerWeek: '每周多次开战',
    oncePerWeek: '每周开战一次',
    lessThanOncePerWeek: '少于每周一次',
    never: '不开战',
    unknown: '未知',
  },
  warState: {
    notInWar: '未开战',
    preparation: '备战日',
    inWar: '战斗日',
    warEnded: '战争结束',
    ended: '已结束', // CWL 的联赛战状态
  },
  warResult: {
    win: '胜',
    lose: '负',
    tie: '平',
  },
  upgradeCategory: {
    building: '建筑',
    troop: '兵种',
    spell: '法术',
    hero: '英雄',
    equipment: '装备',
  },
  village: {
    home: '主村',
    builderBase: '基地',
  },
  announceCategory: {
    notice: '公告',
    maintenance: '维护',
    event: '活动',
  },
}

/** 查不到返回原值（不显示 undefined），null / undefined / 空串返回 `'-'`。 */
export function enumLabel(group: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return PLACEHOLDER
  const table = Object.prototype.hasOwnProperty.call(ENUM_LABELS, group)
    ? ENUM_LABELS[group]
    : null
  const key = String(value)
  if (table && Object.prototype.hasOwnProperty.call(table, key)) return table[key]
  return key
}
