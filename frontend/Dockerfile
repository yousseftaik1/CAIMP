# Stage 1 — build
FROM node:20-alpine AS builder

WORKDIR /app

COPY frontend/package.json ./
RUN npm install --legacy-peer-deps

COPY frontend/ .
RUN npm run build

# Stage 2 — serve
FROM nginx:1.25-alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# SPA fallback + API proxy so the app works on port 3000 standalone.
# /auth/ and /admin/ proxy to admin-api; /api/v1/ proxies to query-api;
# /ws/ proxies to ws-gateway.
RUN printf 'server {\n\
  listen 3000;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
\n\
  location /health { return 200 "ok\\n"; add_header Content-Type text/plain; }\n\
\n\
  location /auth/ {\n\
    proxy_pass http://admin-api:8001/auth/;\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Real-IP $remote_addr;\n\
  }\n\
\n\
  location /admin/v1/ {\n\
    proxy_pass http://admin-api:8001/;\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Real-IP $remote_addr;\n\
  }\n\
\n\
  location /api/v1/ {\n\
    proxy_pass http://query-api:8002/;\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Real-IP $remote_addr;\n\
  }\n\
\n\
  location /api/ai/ {\n\
    proxy_pass http://ai-orchestrator:8010/;\n\
    proxy_http_version 1.1;\n\
    proxy_set_header Connection "";\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Real-IP $remote_addr;\n\
    proxy_read_timeout 120s;\n\
    proxy_buffering off;\n\
    proxy_cache off;\n\
    add_header X-Accel-Buffering no always;\n\
  }\n\
\n\
  location /ws/ {\n\
    proxy_pass http://ws-gateway:8080/;\n\
    proxy_http_version 1.1;\n\
    proxy_set_header Upgrade $http_upgrade;\n\
    proxy_set_header Connection "upgrade";\n\
    proxy_set_header Host $host;\n\
    proxy_read_timeout 3600s;\n\
  }\n\
\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
