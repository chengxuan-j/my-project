# 多阶段构建：依赖 → 构建 → 运行（standalone）
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# 构建期确定后端代理地址（Next rewrites 在构建期固化）
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=$BACKEND_URL
# SSE 基址：同域部署时留空走同源（Nginx 反代）；跨域时填后端域名
ARG NEXT_PUBLIC_SSE_BASE=""
ENV NEXT_PUBLIC_SSE_BASE=$NEXT_PUBLIC_SSE_BASE
# Docker 构建需要 standalone 产物（本地构建不需要，见 next.config.js）
ENV BUILD_STANDALONE=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
