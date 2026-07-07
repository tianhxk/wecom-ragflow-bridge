# WeCom-RAGFLOW-Bridge

当前正式版本：**1.0**。版本变更见 [CHANGELOG.md](CHANGELOG.md)。

企业微信智能机器人 ↔ RAGFLOW 桥接服务。
本服务基于https://github.com/ApakohZzz/wecom-dify-bridge 的基础上做的RagFlow 桥接服务的改造，感谢大佬的支持
通过 **WebSocket 长连接** 方式对接企业微信智能机器人，将用户消息转发到 RAGFLOW 应用，并将 AI 回复实时返回给用户。

## 为什么需要这个服务？

企业微信智能机器人的传统回调模式要求：
- 服务器必须有**公网 IP**
- IP 必须在企业微信的**可信 IP 列表**中
- 需要配置回调 URL 并通过验证

而 **长连接模式** 由客户端主动连接企业微信服务器，**无需公网 IP、无需可信域名、无需回调 URL**，部署在任何能访问外网的机器上即可运行。

## 跟WeCom-OpenClaw-RagFlow-Bridge对比
##优势
1.安全,链路简单，任何消息都是转发给RAGFlow进行知识库查询,OpenClaw会自我发挥，安全问题超级大
2.模型调用节省,基本上耗用的token减少60%
##劣势
1.扩展性受限,skill不支持,工具不支持，也不能自主对话
2.任何新特性都需要编码,在claude的支持下，编码支持了MinerU

## 架构

```
企业微信服务器
    ↕ WebSocket 长连接（服务主动连接，无需公网 IP）
WeCom-RAGFLOW-Bridge（本服务）
    ↕ HTTP API（Docker 内部网络）
RAGFLOW 应用
```

## 功能特性

- ✅ **无需公网 IP** — 长连接模式，绕过可信 IP 限制
- ✅ **流式回复** — 打字机效果，实时输出 AI 回答
- ✅ **多轮对话** — 自动维护会话上下文
- ✅ **自动重连** — 连接断开后自动恢复
- ✅ **心跳保活** — 定时心跳防止断连
- ✅ **新对话指令** — 发送 `#reset` 开启全新对话
- ✅ **Docker 部署** — 一键启动，与 RAGFLOW 共享网络

## 前置条件

- 已部署 [RAGFLOW](https://github.com/infiniflow/ragflow) 并创建了一个**聊天助手**或 **Chatflow** 应用
- 企业微信管理后台已创建**智能机器人**并开启 **API 长连接模式**

## 快速部署

### 1. 克隆仓库

```bash
git clone https://github.com/tianhxk/wecom-ragflow-bridge.git
cd wecom-RAGFLOW-bridge
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下配置：

| 变量 | 必填 | 说明 | 来源 |
|------|------|------|------|
| `WECOM_BOT_ID` | ✅ | 机器人 BotID | 企业微信后台 → 应用管理 → 智能机器人 → API 模式 |
| `WECOM_SECRET` | ✅ | 长连接 Secret | 同上 |
| `WECOM_BOT_ENABLED` | ❌ | 是否启用企业微信智能机器人长连接通道 | 默认 `true` |
| `RAGFLOW_API_KEY` | ✅ | RAGFLOW 应用 API Key（`app-` 开头） | RAGFLOW 控制台 → 你的应用 → API 访问 |
| `RAGFLOW_AGENT_ID` | ✅ | RAGFLOW 应用  | RAGFLOW 应用的 API Key（在 RAGFLOW 控制台 -> agent应用 -> 具体的智能体-右上角-管理-嵌入网站中获得 访问 中获取） |
| `RAGFLOW_API_BASE` | ✅ | RAGFLOW API 地址 | 默认 `http://127.0.0.1/v1`（与 RAGFLOW 同机部署时） |
| `WECOM_KF_ENABLED` | ❌ | 是否启用微信客服通道 | 默认 `false` |
| `WECOM_KF_SECRET` | 启用微信客服时必填 | 微信客服 Secret | 企业微信后台 → 微信客服 → API |
| `WECOM_KF_CALLBACK_TOKEN` | 启用微信客服时必填 | 微信客服回调 Token | 企业微信后台 → 微信客服 → API 接收消息 |
| `WECOM_KF_ENCODING_AES_KEY` | 启用微信客服时必填 | 微信客服回调 EncodingAESKey | 同上 |
| `WECOM_KF_OPEN_KFID` | ❌ | 指定客服账号的 `open_kfid`，为空则不限制 | 企业微信后台或客服账号 API |
| `WECOM_KF_WEBHOOK_HOST` | ❌ | 微信客服 webhook 监听地址 | 默认 `0.0.0.0` |
| `WECOM_KF_WEBHOOK_PORT` | ❌ | 微信客服 webhook 监听端口 | 默认 `8080` |
| `WECOM_KF_WEBHOOK_PATH` | ❌ | 微信客服 webhook 路径 | 默认 `/wechat-kf/callback` |
| `MINERU_API_BASE` | ❌ | MinerU API 地址（用于图片 OCR 识别） | 默认 `https://mineru.net`（调用云端服务） |
| `MINERU_API_KEY` | ❌ | MinerU API KEY（用于图片 OCR 识别） | 官网申请token,用于支持V4batch |
| `MINERU_OCR_METHOD` | ❌ | MinerU OCR 调用模式 | V1parse:  Agent 轻量解析 API，适合单张图片，但是会限流,已支持；V4batch: 使用 v4/batch 接口解析,精准解析 API,需要token,待测试 |
| `MEDIA_DIR` | ❌ | 企业微信媒体文件保存目录 | 默认 `./config/media` |
| `STREAM_MODE` | ❌ | 流式回复开关 | 默认 `true` |
| `HEARTBEAT_INTERVAL` | ❌ | 心跳间隔（秒） | 默认 `30` |
| `LOG_LEVEL` | ❌ | 日志级别 | 默认 `INFO` |
| `LOG_FILE` | ❌ | 文件日志路径 | 默认 `logs/wecom-ragflow-bridge.log` |
| `LOG_RETENTION_DAYS` | ❌ | 日志保留天数，每天午夜轮转 | 默认 `30` |

### 3. 启动服务

```bash
docker compose up -d --build
```

默认同时生成固定版本和最新版标签：

- `wecom-ragflow-bridge:1.0` 与 `wecom-ragflow-bridge:latest`
- `wecom-workbot-query-ui:1.0` 与 `wecom-workbot-query-ui:latest`

同一组内的两个标签指向相同镜像，容器固定使用 `:1.0`。如需覆盖构建版本，可在
执行 Compose 前设置 `APP_VERSION` 环境变量。

### 4. 查看日志

```bash
docker compose logs -f
```

日志会同时写入宿主机的 `./logs/wecom-ragflow-bridge.log`，每天午夜自动轮转为
`wecom-ragflow-bridge.log.YYYY-MM-DD`，只保留最近 30 天；也可以直接跟踪当前文件：

```bash
tail -f logs/wecom-ragflow-bridge.log
```

看到以下输出说明连接成功：

```
✅ 订阅认证成功，开始接收消息
```

## 使用指令

| 指令 | 说明 |
|------|------|
| `#reset` | 清除当前对话历史，开启全新对话 |

## 微信客服接入

微信客服通道与当前企业微信智能机器人长连接通道可以同时开启。开启后，服务会启动一个 webhook 接收微信客服回调，解密回调事件中的 `Token`，再通过微信客服 `sync_msg` 拉取客户消息，复用同一个 RAGFLOW/Dify 聊天后端生成回复，并通过微信客服 `send_msg` 发给客户。

最小配置示例：

```env
WECOM_KF_ENABLED=true
WECOM_KF_SECRET=你的微信客服Secret
WECOM_KF_CALLBACK_TOKEN=你的微信客服回调Token
WECOM_KF_ENCODING_AES_KEY=你的微信客服回调EncodingAESKey
WECOM_KF_OPEN_KFID=可选，指定某个客服账号
WECOM_KF_WEBHOOK_PORT=8080
WECOM_KF_WEBHOOK_PATH=/wechat-kf/callback
```

在企业微信后台配置的回调 URL 应指向：

```text
https://你的域名/wechat-kf/callback
```

Docker Compose 默认把容器 `8080` 端口映射到宿主机 `8080`。生产环境通常还需要在 Nginx/Caddy/网关上配置 HTTPS 反向代理到 `http://宿主机:8080/wechat-kf/callback`。

如果只想运行微信客服，不运行智能机器人长连接：

```env
WECOM_BOT_ENABLED=false
WECOM_KF_ENABLED=true
```

当前微信客服通道已支持文字消息与 `#reset`，图片和语音会提示用户改发文字。

## WorkBot 消息查询 API

设置 `WORKBOT_QUERY_API_TOKEN` 后，会在现有 webhook 端口启用两个只读接口：

- `GET /api/workbot/messages`：查询 `message` 表。
- `GET /api/workbot/callback-logs`：查询 `callback_log` 表。
- `GET /api/workbot/logs`：列出当前日志和按天轮转的历史日志。
- `GET /api/workbot/logs/{filename}/content`：浏览日志尾部内容。
- `GET /api/workbot/logs/{filename}/download`：下载原始日志文件。

请求需使用 `Authorization: Bearer <token>`，并必须提供 `robotid`、`start_time`、
`end_time` 三个查询参数。默认每次返回 100 条、最多 200 条，单次时间范围不超过
31 天。完整参数、分页方法和 curl 示例见 `src/对接WorkBot.md`。

仓库同时包含 Vue 3 可视化查询界面。执行 `docker compose up -d --build` 后访问：

```text
http://服务器地址:8091
```

前端由 Nginx 独立提供服务，并在容器网络内把 `/api/workbot/*` 转发到 Python
查询 API。界面中的“服务日志”数据源支持浏览和下载日志；开发方式见
`frontend/README.md`。

## 网络说明

本服务通过 Docker 网络 `docker_default` 与 RAGFLOW 通信。如果你的 RAGFLOW 使用了不同的网络名称，请修改 `docker-compose.yml` 中的网络配置：

```yaml
networks:
  RAGFLOW_network:
    external: true
    name: 你的RAGFLOW网络名  # 通过 docker network ls 查看
```

如果 RAGFLOW 部署在其他服务器上，修改 `.env` 中的 `RAGFLOW_API_BASE` 为 RAGFLOW 的实际地址：

```env
RAGFLOW_API_BASE=http://你的RAGFLOW地址
```

## 常见问题

**Q: 启动后提示订阅认证失败？**
A: 检查 `WECOM_BOT_ID` 和 `WECOM_SECRET` 是否正确，确认智能机器人已开启 API 长连接模式。

**Q: 消息收到了但没有回复？**
A: 检查 RAGFLOW 应用是否已发布，模型是否已配置。查看日志中的具体错误信息。

**Q: 提示 `Workflow not published`？**
A: 在 RAGFLOW 控制台点击应用右上角的"发布"按钮。

**Q: 提示 `Model is not configured`？**
A: 在 RAGFLOW 应用编排页面中，确保 LLM 节点已选择可用的模型。

## License

MIT
