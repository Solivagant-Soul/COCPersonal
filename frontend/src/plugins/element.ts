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
  // `size: 'large'` 是全局的：按钮、输入框、分页、单选组一起放大，
  // 与新版更宽松的页面排版保持一致。只在安装处配一次，页面里别再各自传 size。
  app.use(ElementPlus, { locale: zhCn, size: 'large' })
}
