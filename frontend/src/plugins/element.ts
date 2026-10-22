import type { App } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

/**
 * 全站统一安装 Element Plus。
 *
 * **必须带中文语言包**：不带的话分页会渲染成 `Total 100` / `20/page`，
 * 空态、日期选择器等也会跟着变英文（2026-10-23 线上截图里分页就是英文的）。
 *
 * 语言包只在这一处配置 —— 页面里各自传 `locale` 迟早会漏，测试也用同一个
 * 安装函数，否则「测试里是中文、线上是英文」这种偏差永远发现不了。
 */
export function installElementPlus(app: App): void {
  app.use(ElementPlus, { locale: zhCn })
}
