# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WeCom-RAGFLOW-Bridge is a bridge service connecting WeChat Work (企业微信) intelligent bots via WebSocket long connection to RAGFLOW AI application. The service receives user messages through WeChat Work's long connection mode (no public IP required) and forwards them to RAGFLOW, streaming AI responses back in real-time.

## Commands

### Development
```bash
# Run locally (requires environment variables in config/.env)
python -m src.main

# Run with Docker
docker compose up -d --build
docker compose logs -f

# Test RAGFLOW connection standalone
python src/simple_stream_client.py
```

### Environment Variables
Configure in `config/.env` (copy from `config/.env.example`):

**Channels (at least one must be enabled):**
- `WECOM_BOT_ENABLED` - Enable WeCom Bot WebSocket long connection (default: `true`)
- `WECOM_BOT_ID` - WeCom Bot BotID
- `WECOM_SECRET` - WeCom Bot long connection secret
- `WECOM_KF_ENABLED` - Enable WeChat KF channel (default: `false`)
- `WECOM_KF_SECRET` - WeChat KF Secret
- `WECOM_KF_CALLBACK_TOKEN` / `WECOM_KF_ENCODING_AES_KEY` - KF callback verification
- `WORKBOT_ENABLED` - Enable WorkBot channel (default: `false`)
- `WORKBOT_ROBOT_ID` / `WORKBOT_BASE_URL` / `WORKBOT_CALLBACK_URL` - WorkBot config

**Chat backend (required):**
- `CHAT_PROVIDER` - `ragflow` (default) or `dify`
- `RAGFLOW_API_KEY` / `RAGFLOW_API_BASE` / `RAGFLOW_AGENT_ID` — RAGFLOW config
- `DIFY_API_BASE` / `DIFY_API_KEY` — Dify config (when `CHAT_PROVIDER=dify`)

**Shared:**
- `WECOM_CORP_ID` - WeCom Corp ID (required for image OCR and KF)
- `MINERU_API_KEY` / `MINERU_OCR_METHOD` / `MINERU_API_BASE` - MinerU OCR (optional)
- `MEDIA_DIR` - WeCom media file storage (default: `./config/media`)
- `STREAM_MODE` - Streaming responses (default: `true`)
- `HEARTBEAT_INTERVAL` - WebSocket heartbeat interval seconds (default: `30`)
- `LOG_LEVEL` - DEBUG/INFO/WARNING/ERROR
- `MYSQL_HOST/PORT/USER/PASSWORD/DBNAME` - WorkBot message persistence

## Architecture

### Three-Channel Design
The service bridges **multiple WeChat channels** to a **unified chat backend** (RAGFLOW or Dify):

```
WeCom Bot WebSocket (长连接) ─┐
WeChat KF (客服 webhook)     ─┼─→ ChatClient (unified) ─→ RAGFLOW or Dify
WorkBot (独立机器人 webhook) ─┘
```

Each channel is independent and can run concurrently. When WeChat KF and WorkBot share the same host/port, they use a **shared webhook server** (one aiohttp AppRunner) to avoid duplicate port binding.

### Core Components (`src/`)

| File | Purpose |
|------|---------|
| `main.py` | `WeComRAGFLOWBridge` — WebSocket lifecycle, message routing, coordinates all channels |
| `chat_client.py` | `ChatClient` protocol + `create_chat_client()` factory — unifies RAGFLOW/Dify backends |
| `ragflow_client.py` | RAGFLOW API client — `chat_stream` (streaming) and `chat_blocking` methods |
| `dify_client.py` | Dify API client — `chat_stream` and `chat_blocking`, strips `<think>` tags |
| `session.py` | `SessionManager` — maps channel-scoped `chat_id` to backend `conversation_id` |
| `message_extractor.py` | `MessageExtractor` — parses WeCom message content (text/voice/image/mixed) |
| `media_service.py` | `WeComImageService` — downloads and AES-decrypts WeCom media files |
| `mineru_client.py` | MinerU OCR client — image text extraction via `ocr()` unified entry |
| `wecom_api.py` | WeCom API client — media file downloads |
| `protocol.py` | WeCom protocol definitions, `MessageBuilder` for outbound messages |
| `wechat_kf.py` | `WeChatKFBridge` + `WeChatKFClient` — KF webhook receiver + sync_msg polling |
| `workbot.py` | `WorkBotBridge` + `WorkBotClient` — WorkBot webhook receiver |
| `workbot_storage.py` | `WorkBotMessageStore` — MySQL-backed message persistence for WorkBot |
| `scheduler.py` | `PeriodicTaskManager` — manages recurring heartbeat tasks |
| `config.py` | `Config` dataclass — loads and validates env vars from `config/.env` |
| `animation.py` | `animate_waiting()` — "正在思考..." dot animation during streaming |

### Message Flow (WeCom Bot channel)
1. WeCom WebSocket → `_message_loop()` → `_handle_message()`
2. `MessageExtractor.extract()` parses content (text/voice/image/mixed), runs MinerU OCR if image
3. `ChatClient.chat_stream()` or `chat_blocking()` called (RAGFLOW or Dify based on `CHAT_PROVIDER`)
4. Response sent back via `aibot_respond_msg` with `msgtype: "stream"` or `"text"`

### Stream Mode
- `_reply_stream()` generates a `stream_id` and manages the `animate_waiting()` coroutine
- First content chunk cancels the animation, then sends incremental updates every 5 chunks
- The WeCom client uses `stream.id` to track/display the conversation

### Session Management
- `SessionManager` maintains `conv_key → conversation_id` mapping per channel
- Conv key format: `{chat_id}:{user_id}` for WeCom Bot, `kf:{open_kfid}:{external_userid}` for KF
- `#reset` command clears a chat's conversation for fresh dialogue

### MinerU OCR Integration
- Methods: `file` (default, uses `agent/parse/file` API), `V1parse`, `V4batch`
- WeCom images are AES/CBC decrypted in `media_service.py` — no PKCS7 unpad (Wecom uses custom padding)
- Decrypted images saved to `$MEDIA_DIR` (`./config/media`), auto-cleaned after 3 days

## Utilities

### `expiredtable.py`
Tool for checking if user messages reference deprecated table names. Run directly:
```bash
python expiredtable.py
```
Define expired→new table mappings in `expired_list` tuple array. Matching uses word boundary regex (`(?<![a-zA-Z0-9])table_name(?![a-zA-Z0-9])`) to avoid partial matches.

## Deployment

The service bridges multiple WeChat channels to RAGFLOW/Dify:
- **WeCom Bot**: WebSocket long connection to `wss://openws.work.weixin.qq.com` (no public IP required)
- **WeChat KF**: Webhook receiver (`/wechat-kf/callback`) with AES验签 + `sync_msg` polling
- **WorkBot**: Webhook receiver (`/workbot/callback`) with MySQL-backed message storage

KF and WorkBot webhook listeners can share the same port (one aiohttp AppRunner) when host/port/path differ — if paths collide, startup raises `ValueError`.

Service must be on the same Docker network as RAGFLOW to reach `http://nginx/v1`.