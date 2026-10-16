/** 后端统一响应体（规格 §10）。 */

export interface Meta {
  cache: string | null
  fetchedAt: string | null
  ageSeconds: number | null
  ttlSeconds: number | null
}

export interface Envelope<T> {
  data: T
  meta: Meta
}
