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
- `WECOM_BOT_ID` - WeChat Work bot BotID
- `WECOM_SECRET` - WeChat Work long connection secret
- `WECOM_CORP_ID` - WeChat Work Corp ID (required for image OCR)
- `RAGFLOW_API_KEY` - RAGFLOW API key (starts with `app-`)
- `RAGFLOW_API_BASE` - RAGFLOW API URL (default: `http://nginx/v1` for Docker network access)
- `RAGFLOW_AGENT_ID` - RAGFLOW agent ID
- `MINERU_API_KEY` - MinerU API key for image OCR (optional)
- `MINERU_OCR_METHOD` - MinerU OCR method: `file` (default), `V1parse`, `V4batch`
- `STREAM_MODE` - Enable streaming responses (default: `true`)
- `HEARTBEAT_INTERVAL` - Heartbeat interval in seconds (default: `30`)
- `LOG_LEVEL` - Log level: DEBUG/INFO/WARNING/ERROR

## Architecture

### Core Components (`src/`)

| File | Purpose |
|------|---------|
| `main.py` | `WeComRAGFLOWBridge` class - WebSocket lifecycle, message routing, RAGFLOW integration |
| `ragflow_client.py` | RAGFLOW API client - `chat_stream` (streaming) and `chat_blocking` methods |
| `mineru_client.py` | MinerU OCR client - image text extraction via `ocr()` unified entry |
| `wecom_api.py` | WeChat Work API client for media file downloads |
| `protocol.py` | WeCom protocol definitions, `MessageBuilder` for constructing outbound messages |
| `session.py` | `SessionManager` - maps WeChat Work `chatid` to RAGFLOW `conversation_id` |
| `config.py` | `Config` dataclass - loads environment variables from `config/.env` |
| `animation.py` | `animate_waiting()` - "正在思考..." dot animation during streaming |

### Message Flow
1. WeChat Work WebSocket → `_message_loop()` → `_handle_message()`
2. `_extract_message()` parses content (text/voice/image/mixed), runs OCR via MinerU if image
3. RAGFLOW `chat_stream()` or `chat_blocking()` called based on `stream_mode`
4. Response sent back via `aibot_respond_msg` with `msgtype: "stream"` or `"text"`

### Stream Mode Specifics
- `_reply_stream()` generates a unique `stream_id` and manages `animate_waiting()` task
- First content chunk cancels the animation task, then sends incremental updates
- The client uses the `stream.id` to track/display the conversation

### Session Management
- `SessionManager` maintains `chat_id → conversation_id` mapping
- `#reset` command clears a chat's conversation for fresh dialogue

### MinerU OCR Integration
- Supported methods: `file` (default, uses agent/parse/file API), `V1parse` (agent/parse/file), `V4batch` (v4/batch)
- Image decryption in `_decrypt_wecom_image()` uses AES/CBC, no PKCS7 unpad (Wecom uses custom padding)
- Decrypted images saved to `$MEDIA_DIR` (default: system temp dir), auto-cleaned after 3 days

## Utilities

### `expiredtable.py`
Tool for checking if user messages reference deprecated table names. Run directly:
```bash
python expiredtable.py
```
Define expired→new table mappings in `expired_list` tuple array. Matching uses word boundary regex (`(?<![a-zA-Z0-9])table_name(?![a-zA-Z0-9])`) to avoid partial matches.

## Deployment

Service runs in Docker, connecting to WeChat Work WebSocket (`wss://openws.work.weixin.qq.com`). Must be on same Docker network as RAGFLOW to access `http://nginx/v1`.