# ============================================
# Stride28 前端 Dockerfile
# 多阶段构建：Node 构建 → nginx 托管
# ============================================

# --- 构建阶段 ---
FROM node:18-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# --- 生产阶段 ---
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
