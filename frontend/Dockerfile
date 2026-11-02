# LakeWatch frontend - Vite + React + TypeScript, served by nginx.
#
# Build context is the repository root:
#   docker build -f frontend/Dockerfile -t lakewatch-frontend \
#     --build-arg VITE_API_BASE_URL=/api/v1 .

FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

COPY frontend/ ./

# Same-origin default: nginx proxies /api to the backend service.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
