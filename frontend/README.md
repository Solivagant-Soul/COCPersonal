# frontend

COCPersonal 的网页前端：Vue 3 + Vite + TypeScript + Element Plus + Vue Router + Pinia。

```bash
npm install
npm run dev     # http://localhost:5173，/api 已反代到本机后端 :8000
npm run test    # Vitest
npm run build   # vue-tsc 类型检查 + 产物到 dist/
npm run preview # 用 dist/ 产物起本地预览（同样带 /api 代理）
```

起后端、部署、以及本机环境的坑，见仓库根 **`README.md`**；
后端自身的硬约束见 **`backend/AGENTS.md`**。

约定：所有后端 URL 与查询参数名只出现在 `src/api/endpoints.ts` 一处，页面不拼字符串。
