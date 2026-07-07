# WeCom-RAGFlow-Bridge 项目架构图

## 一、项目概述

**WeCom-RAGFlow-Bridge** 是一款企业微信智能机器人桥接服务，通过 WebSocket 长连接方式接收企业微信消息，将用户请求转发至后端 AI 应用（RAGFlow 或 Dify），并将 AI 流式响应实时推送回用户。

> **核心特点**：无需公网 IP，通过长连接模式实现消息收发，大幅降低部署复杂度。

---

## 二、整体架构图

```mermaid
graph TB
    %% 微信生态侧
    subgraph WeChat["微信生态"]
        WCB["WeCom Bot\n长连接"]
        WKF["WeChat KF\n客服消息"]
        WBOT["WorkBot\n独立机器人"]
    end

    %% 桥接服务
    subgraph Bridge["WeCom-RAGFlow-Bridge 桥接服务"]
        direction TB
        
        subgraph Channels["多通道接入层"]
            WSHandler["WebSocket\n长连接处理器"]
            KFHandler["KF Webhook\n接收器"]
            WBHandler["WorkBot\nWebhook 接收器"]
        end
        
        subgraph Core["核心处理层"]
            ME["MessageExtractor\n消息提取器"]
            ChatClient["ChatClient\n统一聊天客户端"]
            SessionMgr["SessionManager\n会话管理器"]
        end
        
        subgraph Backend["后端服务层"]
            RF["RAGFlow Client\nRAGFlow API"]
            DF["Dify Client\nDify API"]
            MinerU["MinerU OCR\n图像识别"]
            MediaSvc["MediaService\n媒体文件服务"]
        end
    end

    %% AI 后端
    subgraph AIAgents["AI 应用层"]
        RAG["RAGFlow\n知识库问答"]
        DIF["Dify\n工作流编排"]
    end

    %% 外部依赖
    subgraph External["第三方服务"]
        WecomAPI["企业微信\n开放API"]
        WeChatCloud["微信\n云端服务"]
    end

    %% 数据流向
    WCB -->|"WSS 长连接"| WSHandler
    WKF -->|"HTTP Webhook"| KFHandler
    WBOT -->|"HTTP Webhook"| WBHandler

    WSHandler --> ME
    KFHandler --> ME
    WBHandler --> ME

    ME --> SessionMgr
    ME --> ChatClient
    
    ChatClient --> RF
    ChatClient --> DF
    ChatClient --> MinerU
    ChatClient --> MediaSvc
    
    RF --> RAG
    DF --> DIF

    RAG -->|流式响应| ChatClient
    DIF -->|流式响应| ChatClient
    
    MediaSvc --> WecomAPI
    MinerU --> WeChatCloud

    style Bridge fill:#e1f5fe,stroke:#01579b
    style Channels fill:#fff3e0,stroke:#e65100
    style Core fill:#e8f5e9,stroke:#2e7d32
    style Backend fill:#f3e5f5,stroke:#7b1fa2
```

---

## 三、三通道架构详解

```mermaid
graph LR
    subgraph Bot["WeCom Bot 通道\n(WebSocket 长连接)"]
        direction TB
        B1["连接企业微信长连接服务器\nwss://openws.work.weixin.qq.com"]
        B2["接收用户消息\n通过 WSS 协议"]
        B3["发送流式/非流式回复"]
    end

    subgraph KF["WeChat KF 通道\n(客服消息)"]
        direction TB
        K1["注册 Webhook 回调\n接收客服消息"]
        K2["sync_msg 轮询\n拉取消息"]
        K3["通过 KF API 回复"]
    end

    subgraph WB["WorkBot 通道\n(独立机器人)"]
        direction TB
        W1["注册 Webhook\n接收消息"]
        W2["MySQL 持久化\n消息存储"]
        W3["通过 WorkBot API 回复"]
    end

    style Bot fill:#e3f2fd,stroke:#1565c0
    style KF fill:#fce4ec,stroke:#c2185b
    style WB fill:#e8f5e9,stroke:#2e7d32
```

### 通道对比

| 通道 | 协议 | 消息获取方式 | 消息发送方式 | 特点 |
|------|------|-------------|-------------|------|
| **WeCom Bot** | WebSocket | 长连接推送 | 长连接推送 | 实时性高，无需公网 IP |
| **WeChat KF** | HTTP Webhook | 回调 + 轮询 | KF API | 支持客服功能 |
| **WorkBot** | HTTP Webhook | 回调 | WorkBot API | 支持 MySQL 持久化 |

---

## 四、消息处理流程

```mermaid
sequenceDiagram
    autonumber
    participant User as 用户
    participant Wecom as 企业微信
    participant Bridge as 桥接服务
    participant Chat as ChatClient
    participant AI as RAGFlow/Dify
    participant Session as SessionManager

    User->>Wecom: 发送消息
    Wecom->>Bridge: 消息推送 (长连接/Webhook)

    Bridge->>Bridge: MessageExtractor 解析
    alt 图片/语音消息
        Bridge->>Bridge: MediaService 下载
        Bridge->>Bridge: AES 解密
        alt 需要 OCR
            Bridge->>Bridge: MinerU OCR 识别
        end
    end

    Bridge->>Session: 获取/创建会话
    Session-->Bridge: conversation_id

    Bridge->>Chat: chat_stream() / chat_blocking()
    
    alt 流式响应模式
        Chat->>AI: 发起流式请求
        AI-->>Chat: 流式响应 chunks
        Chat-->>Bridge: incremental chunks
        Bridge-->>Wecom: 分块推送 (每5块)
        Note over Bridge: animate_waiting() 动画
    else 阻塞响应模式
        Chat->>AI: 发起阻塞请求
        AI-->>Chat: 完整响应
        Chat-->>Bridge: 完整消息
        Bridge-->>Wecom: 单条消息
    end

    Bridge->>Session: 更新会话状态
    Session-->Bridge: OK
```

---

## 五、核心组件架构

```mermaid
classDiagram
    class WeComRAGFlowBridge {
        +start()
        +_run_wecom_bot()
        +_handle_message()
        +_reply_stream()
        -_config: Config
        -_sessions: SessionManager
        -_chat_client: ChatClient
    }

    class MessageExtractor {
        +extract() MessageContent
        -_parse_text()
        -_parse_voice()
        -_parse_image()
        -_parse_mixed()
    }

    class ChatClient {
        <<interface>>
        +chat_stream() AsyncIterator
        +chat_blocking() str
    }

    class RAGFlowClient {
        +chat_stream() AsyncIterator
        +chat_blocking() str
        -_api_key: str
        -_base_url: str
    }

    class DifyClient {
        +chat_stream() AsyncIterator
        +chat_blocking() str
        -_strip_reasoning_tags()
    }

    class SessionManager {
        +get_conv_id() str
        +create_conv()
        +reset_conv()
        -_conv_cache: Dict
    }

    class MinerUClient {
        +ocr() str
        -_api_key: str
        -_method: str
    }

    class MediaService {
        +download_and_decrypt() bytes
        -_aes_cbc_decrypt()
    }

    WeComRAGFlowBridge --> MessageExtractor
    WeComRAGFlowBridge --> ChatClient
    WeComRAGFlowBridge --> SessionManager
    ChatClient <|.. RAGFlowClient
    ChatClient <|.. DifyClient
    MessageExtractor --> MinerUClient
    MessageExtractor --> MediaService
```

---

## 六、技术栈

```mermaid
mindmap
    root((技术栈))
        语言与框架
            Python 3.10+
            aiohttp
            websockets
            FastAPI
        通信协议
            WebSocket 长连接
            HTTP Webhook
            HTTPS REST
        AI 集成
            RAGFlow API
            Dify API
            流式响应 (SSE)
        工具服务
            MinerU OCR
            企业微信 API
            MySQL 持久化
        部署
            Docker Compose
            企业微信网络
```

---

## 七、部署架构

```mermaid
graph TB
    subgraph Docker["Docker Compose 部署"]
        subgraph Services["服务容器"]
            Bridge["WeCom-RAGFlow-Bridge\n桥接服务"]
            Nginx["NGINX\n反向代理"]
        end
        
        subgraph External["外部服务"]
            RFApp["RAGFlow\nAI 应用"]
            MySQL["MySQL\n消息存储"]
        end
    end

    subgraph WeChat["企业微信云端"]
        WSS["WSS 长连接服务器"]
        API["企业微信 API"]
    end

    subgraph User["用户端"]
        APP["企业微信 App"]
    end

    APP -->|"消息"| WSS
    WSS -->|"WSS"| Bridge
    Bridge -->|"HTTP API"| RFApp
    Bridge -->|"HTTP"| Nginx -->|"本地访问"| RFApp
    Bridge -->|"SQL"| MySQL

    style Bridge fill:#e1f5fe,stroke:#01579b
    style Docker fill:#fff8e1,stroke:#ff8f00
```

---

## 八、目录结构

```
wecom-ragflow-bridge/
├── config/
│   ├── .env.example          # 环境变量模板
│   └── media/                 # 媒体文件存储
├── src/
│   ├── main.py                # 入口，WeComRAGFlowBridge 主类
│   ├── config.py              # 配置加载
│   ├── protocol.py            # 协议定义，MessageBuilder
│   ├── session.py             # 会话管理
│   ├── scheduler.py           # 定时任务
│   │
│   ├── chat_client.py        # 统一聊天客户端接口
│   ├── ragflow_client.py     # RAGFlow 实现
│   ├── dify_client.py        # Dify 实现
│   │
│   ├── message_extractor.py  # 消息解析
│   ├── media_service.py      # 媒体下载与 AES 解密
│   ├── mineru_client.py       # MinerU OCR
│   ├── wecom_api.py          # 企业微信 API
│   │
│   ├── wechat_kf.py          # 微信客服通道
│   ├── workbot.py            # WorkBot 通道
│   ├── workbot_storage.py    # WorkBot MySQL 存储
│   ├── webhook_server.py     # 共享 Webhook 服务器
│   ├── service_factory.py    # 服务工厂
│   └── animation.py           # 流式响应动画
│
├── docker-compose.yml
├── requirements.txt
├── docs/
│   └── architecture.md       # 本文档
└── README.md
```

---

## 九、环境变量配置

| 变量 | 说明 | 必需 | 默认值 |
|------|------|------|--------|
| `WECOM_BOT_ENABLED` | 启用 WeCom Bot 通道 | 否 | `true` |
| `WECOM_BOT_ID` | Bot ID | 是 | - |
| `WECOM_SECRET` | Bot Secret | 是 | - |
| `WECOM_KF_ENABLED` | 启用客服通道 | 否 | `false` |
| `CHAT_PROVIDER` | 聊天后端 | 是 | `ragflow` |
| `RAGFLOW_API_KEY` | RAGFlow API Key | 是 | - |
| `RAGFLOW_API_BASE` | RAGFlow API 地址 | 是 | - |
| `DIFY_API_KEY` | Dify API Key | 是 (Dify模式) | - |
| `WECOM_CORP_ID` | 企业 ID (OCR用) | 否 | - |
| `MEDIA_DIR` | 媒体文件存储目录 | 否 | `./config/media` |

---

## 版本信息

- **文档版本**: v1.0
- **更新日期**: 2026-06-25
- **项目版本**: 参考 `git log` 最近提交
