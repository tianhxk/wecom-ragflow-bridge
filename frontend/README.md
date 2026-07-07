# WorkBot Query UI

Vue 3 + Vite 实现的 WorkBot 数据查询界面。

当前项目发布版本：`1.0`（npm 包内部使用语义版本 `1.0.0`）。

## 本地开发

后端查询 API 需运行在 `http://127.0.0.1:8090`：

```bash
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`。Vite 会把 `/api/workbot/*` 代理到后端。

## 生产部署

项目根目录执行：

```bash
docker compose up -d --build
```

访问 `http://服务器地址:8091`。生产镜像使用 Nginx 托管构建产物，并将查询 API
反向代理到 Python 服务。
