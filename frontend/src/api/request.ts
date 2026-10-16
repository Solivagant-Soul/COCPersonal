/**
 * 后端 API 客户端。
 *
 * 只做三件后端的规矩在前端落地：解开 `{data, meta}` 信封、把 `meta` 的蛇形键
 * 转成驼峰（组件里不该出现 `age_seconds`）、把一切失败收敛成**一种**错误类型
 * `ApiError`（`{code, message, status}`），组件只认它，不认 axios 的形状。
 *
 * `STALE` 不特判：后端在回源失败但有旧数据时返回 200 + `meta.cache='STALE'`，
 * 前端照常渲染，缓存态只用来做提示。
 */

import axios from 'axios'

import type { Envelope, Meta } from './types'

const RAW_BASE = import.meta.env.VITE_API_BASE ?? ''
const BASE_URL = String(RAW_BASE).replace(/\/+$/, '')

/** 后端没给 message、或不是 JSON 错误体时的兜底文案。 */
export const FALLBACK_MESSAGE = {
  BAD_REQUEST: '请求有误',
  UPSTREAM_UNAVAILABLE: '上游服务暂时不可用，请稍后重试',
  DEFAULT: '请求失败',
} as const

const BAD_RESPONSE_MESSAGE = '响应格式异常'
const NETWORK_ERROR_MESSAGE = '网络异常，请检查连接'

export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

/** 导出以便测试注入 mock adapter；业务代码请用 {@link request}。 */
export const apiClient = axios.create({ baseURL: BASE_URL, timeout: 15000 })

export interface RequestOptions {
  method?: 'GET' | 'POST'
  params?: Record<string, unknown>
  data?: unknown
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readErrorBody(body: unknown): { code: string; message?: string } | null {
  if (!isPlainObject(body)) return null
  const err = body.error
  if (!isPlainObject(err)) return null
  if (typeof err.code !== 'string' || err.code === '') return null
  return {
    code: err.code,
    message: typeof err.message === 'string' ? err.message : undefined,
  }
}

function normalizeByStatus(status: number): { code: string; message: string } {
  if (status >= 400 && status < 500) {
    return { code: 'BAD_REQUEST', message: FALLBACK_MESSAGE.BAD_REQUEST }
  }
  return { code: 'UPSTREAM_UNAVAILABLE', message: FALLBACK_MESSAGE.UPSTREAM_UNAVAILABLE }
}

/** undefined（后端没这个键）→ null；0 必须保留为 0。 */
function valueOrNull(value: unknown): string | number | null {
  if (value === undefined || value === null) return null
  return value as string | number
}

function toCamelMeta(meta: Record<string, unknown>): Meta {
  return {
    cache: valueOrNull(meta.cache) as string | null,
    fetchedAt: valueOrNull(meta.fetched_at) as string | null,
    ageSeconds: valueOrNull(meta.age_seconds) as number | null,
    ttlSeconds: valueOrNull(meta.ttl_seconds) as number | null,
  }
}

export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<Envelope<T>> {
  const { method = 'GET', params, data } = opts

  let response
  try {
    response = await apiClient.request({ url: path, method, params, data })
  } catch (err) {
    throw toApiError(err)
  }

  const body: unknown = response.data
  if (!isPlainObject(body) || !isPlainObject(body.meta)) {
    throw new ApiError('BAD_RESPONSE', BAD_RESPONSE_MESSAGE, response.status)
  }

  return {
    data: body.data as T,
    meta: toCamelMeta(body.meta),
  }
}

function toApiError(err: unknown): ApiError {
  if (!axios.isAxiosError(err) || !err.response) {
    return new ApiError('NETWORK_ERROR', NETWORK_ERROR_MESSAGE, 0)
  }

  const status = err.response.status
  const errorBody = readErrorBody(err.response.data)
  if (errorBody) {
    return new ApiError(
      errorBody.code,
      errorBody.message || FALLBACK_MESSAGE.DEFAULT,
      status,
    )
  }

  const normalized = normalizeByStatus(status)
  return new ApiError(normalized.code, normalized.message, status)
}
