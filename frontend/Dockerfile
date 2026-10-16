# 前端镜像：多阶段。builder 出 dist/，runtime 只带 nginx + 静态文件。
#
# 最终镜像里没有 Node、没有 node_modules、没有源码 —— 只有编译产物。
#
# 基础镜像选 node:24-alpine 而不是 node:22：Vite 8 的 engines 是
# `^20.19.0 || >=22.12.0`，24 是当前 LTS，且与本机开发用的 Node 版本一致
# （见 backend/AGENTS.md 同类记录），npm ci 对 lockfile 的解析行为可复现。

# --------------------------------------------------------------------------- #
# builder：装依赖 + 构建
# --------------------------------------------------------------------------- #
FROM node:24-alpine AS build

WORKDIR /app

# 先只拷清单，让依赖层能被 Docker 缓存住（改源码不必重装依赖）。
# 用 npm ci 而不是 npm install：lockfile 是权威，缺/不一致要报错而不是悄悄升级。
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# --------------------------------------------------------------------------- #
# runtime：nginx 托管静态文件
# --------------------------------------------------------------------------- #
FROM nginx:1.27-alpine

# 默认站点配置由 compose 从 ./deploy/nginx.conf 挂到
# /etc/nginx/conf.d/default.conf（本文件不含 ${} 变量，故无需 templates 机制）。
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
