# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WeCom-RAGFLOW-Bridge is a bridge service connecting WeChat Work (企业微信) intelligent bots via WebSocket long connection to RAGFLOW AI application. The service receives user messages through WeChat Work's long connection mode (no public IP required) and forwards them to RAGFLOW, streaming AI responses back in real-time.

## Commands

### Development
```bash
# Run locally (requires environment variables)
python app/main.py

# Run with Docker
docker compose up -d --build
docker compose logs -f

# Test RAGFLOW connection standalone
python app/simple_stream_client.py
```

### Environment Variables
Configure in `.env` file (copy from `.env.example`):
- `WECOM_BOT_ID` - WeChat Work bot BotID
- `WECOM_SECRET` - WeChat Work long connection secret
- `RAGFLOW_API_KEY` - RAGFLOW API key (starts with `app-`)
- `RAGFLOW_API_BASE` - RAGFLOW API URL (default: `http://nginx/v1` for Docker network access)
- `STREAM_MODE` - Enable streaming responses (default: `true`)
- `HEARTBEAT_INTERVAL` - Heartbeat interval in seconds (default: `30`)
- `LOG_LEVEL` - Log level: DEBUG/INFO/WARNING/ERROR

## Architecture

### Main Service (`app/main.py`)
- `WeComRAGFLOWBridge` class handles all WebSocket communication
- Lifecycle: connect → subscribe → heartbeat + message loop → reconnect on disconnect
- Two reply modes:
  - **Stream mode** (`_reply_stream`): Sends incremental updates as RAGFLOW streams responses, providing typewriter effect
  - **Blocking mode** (`_reply_blocking`): Waits for complete response before sending

### Message Flow
1. WeChat Work sends `aibot_msg_callback` command with user message
2. `_handle_message` extracts content and routes to RAGFLOW
3. RAGFLOW conversation ID is stored in `conversation_map` (chat_id → conversation_id) for multi-turn conversations
4. Response streams back via `aibot_respond_msg` command with `msgtype: "stream"`

### Session Management
- `conversation_map: dict[str, str]` maps WeChat Work `chatid` to RAGFLOW `conversation_id`
- Sending `#reset` clears the conversation for current chat

### Special Commands
- `#reset` - Clears conversation history and starts fresh dialogue

### Standalone Client (`app/simple_stream_client.py`)
- Test utility using only standard library (no external dependencies)
- Uses `/api/v1/agents_openai/{agent_id}/chat/completions` endpoint
- Hardcoded test configuration in `main()` function for manual testing

## Deployment

Service runs in Docker, connecting to WeChat Work's WebSocket server (`wss://openws.work.weixin.qq.com`). It must be connected to the same Docker network as RAGFLOW (`RAGFLOW_network`) to access the RAGFLOW API at `http://nginx/v1`.