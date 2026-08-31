# ---- 构建阶段 ----
FROM node:20-alpine AS builder
WORKDIR /app

# 优先复制依赖清单，充分利用 Docker 层缓存
COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

# ---- Nginx 运行时镜像 ----
FROM nginx:alpine

# 复制构建产物与 Nginx 配置
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -qO- http://localhost/ > /dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
