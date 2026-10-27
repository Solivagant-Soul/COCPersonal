/**
 * `StatGrid` 的一格。
 *
 * 单独放在 `.ts` 里而不是 `<script setup>` 里：后者不允许 ES 模块导出
 * （`export interface` 会被编译器拒绝），而页面要用它给 `stats` 标注类型。
 */
export interface StatItem {
  label: string
  value: string
  /** 可选的图标 URL（目前只有联赛用得上）。 */
  icon?: string | null
  iconAlt?: string
}
