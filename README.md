# WeCom-RAGFLOW-Bridge

企业微信智能机器人 ↔ RAGFLOW 桥接服务。
本服务基于https://github.com/ApakohZzz/wecom-dify-bridge 的基础上做的RagFlow 桥接服务的改造，感谢大佬的支持
通过 **WebSocket 长连接** 方式对接企业微信智能机器人，将用户消息转发到 RAGFLOW 应用，并将 AI 回复实时返回给用户。

## 为什么需要这个服务？

企业微信智能机器人的传统回调模式要求：
- 服务器必须有**公网 IP**
- IP 必须在企业微信的**可信 IP 列表**中
- 需要配置回调 URL 并通过验证

而 **长连接模式** 由客户端主动连接企业微信服务器，**无需公网 IP、无需可信域名、无需回调 URL**，部署在任何能访问外网的机器上即可运行。

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
| `RAGFLOW_API_KEY` | ✅ | RAGFLOW 应用 API Key（`app-` 开头） | RAGFLOW 控制台 → 你的应用 → API 访问 |
| `RAGFLOW_AGENT_ID` | ✅ | RAGFLOW 应用  | RAGFLOW 应用的 API Key（在 RAGFLOW 控制台 -> agent应用 -> 具体的智能体-右上角-管理-嵌入网站中获得 访问 中获取） |
| `RAGFLOW_API_BASE` | ✅ | RAGFLOW API 地址 | 默认 `http://127.0.0.1/v1`（与 RAGFLOW 同机部署时） |
| `MINERU_API_BASE` | ❌ | MinerU API 地址（用于图片 OCR 识别） | 默认 `https://mineru.net`（调用云端服务） |
| `MINERU_API_KEY` | ❌ | MinerU API KEY（用于图片 OCR 识别） | 官网申请token,用于支持V4batch |
| `MINERU_OCR_METHOD` | ❌ | MinerU OCR 调用模式 | V1parse:  Agent 轻量解析 API，适合单张图片，但是会限流,已支持；V4batch: 使用 v4/batch 接口解析,精准解析 API,需要token,待测试 |
| `MEDIA_DIR` | ❌ | 企业微信媒体文件保存目录 | 默认 `./config/media` |
| `STREAM_MODE` | ❌ | 流式回复开关 | 默认 `true` |
| `HEARTBEAT_INTERVAL` | ❌ | 心跳间隔（秒） | 默认 `30` |
| `LOG_LEVEL` | ❌ | 日志级别 | 默认 `INFO` |

### 3. 启动服务

```bash
docker compose up -d --build
```

### 4. 查看日志

```bash
docker compose logs -f
```

看到以下输出说明连接成功：

```
✅ 订阅认证成功，开始接收消息
```

## 使用指令

| 指令 | 说明 |
|------|------|
| `#reset` | 清除当前对话历史，开启全新对话 |

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
