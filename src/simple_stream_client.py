#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版流式客户端
不依赖外部库，使用标准库实现
"""

import os
import sys
import json
import time
from typing import Optional, Generator, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import ssl


def make_request(
    url: str,
    headers: Dict[str, str],
    data: bytes,
    timeout: int = 30
):
    """发送HTTP请求"""
    try:
        # 创建SSL上下文，禁用证书验证
        context = ssl._create_unverified_context()
        
        req = Request(url, data=data, headers=headers)
        response = urlopen(req, timeout=timeout, context=context)
        
        return response
    except HTTPError as e:
        raise Exception(f"HTTP错误: {e.code} - {e.reason}")
    except URLError as e:
        raise Exception(f"URL错误: {e.reason}")
    except Exception as e:
        raise Exception(f"请求错误: {str(e)}")


def stream_chat_completion(
    base_url: str,
    api_token: str,
    agent_id: str,
    question: str,
    timeout: int = 60
) -> Generator[str, None, None]:
    """
    流式聊天完成请求
    
    返回:
        生成器，返回回答内容的片段
    """
    url = f"{base_url}/api/v1/agents_openai/{agent_id}/chat/completions"
    
    payload = {
        "messages": [{"role": "user", "content": question}],
        "stream": True,
        "model": "ragflow-agent",
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream'
    }
    
    try:
        response = make_request(
            url=url,
            headers=headers,
            data=json.dumps(payload).encode('utf-8'),
            timeout=timeout
        )
        
        buffer = b""
        for line_bytes in response:
            line = line_bytes.decode('utf-8', errors='ignore')
            
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                
                if data_str:
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
        
    except Exception as e:
        yield f"[错误: {str(e)}]"


def direct_chat_completion(
    base_url: str,
    api_token: str,
    agent_id: str,
    question: str,
    timeout: int = 30
) -> str:
    """
    直接聊天完成请求（非流式）
    
    返回:
        完整的回答
    """
    url = f"{base_url}/api/v1/agents_openai/{agent_id}/chat/completions"
    
    payload = {
        "messages": [{"role": "user", "content": question}],
        "stream": False,
        "model": "ragflow-agent",
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = make_request(
            url=url,
            headers=headers,
            data=json.dumps(payload).encode('utf-8'),
            timeout=timeout
        )
        
        result_bytes = response.read()
        result = json.loads(result_bytes.decode('utf-8'))
        
        # 解析响应
        choices = result.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            answer = message.get("content", "")
            return answer.strip()
        else:
            return "[错误: 未获取到回答]"
            
    except Exception as e:
        return f"[错误: {str(e)}]"


def main():
    """主函数，用于测试"""
    question ="证券主表的作用是?"
    if len(question) > 1:
        #question = sys.argv[1]
        
        # 从环境变量获取配置
        base_url ="http://qq5273175.dsmynas.com:18002"       
        api_token="ragflow-CazklDyMsBQcEu-VMsanOqPSl_KZD71IL6Hick1kx7U"
        agent_id="456d17c026ac11f1a9876f7f200b1a45"
        stream_mode = True
        #base_url = os.environ.get('RAGFLOW_BASE_URL')
        #api_token = os.environ.get('RAGFLOW_API_TOKEN')
        #agent_id = os.environ.get('RAGFLOW_AGENT_ID')
        #stream_mode = os.environ.get('RAGFLOW_STREAM_MODE', 'true').lower() == 'true'
        
        if not all([base_url, api_token, agent_id]):
            print("错误: 请设置环境变量 RAGFLOW_BASE_URL, RAGFLOW_API_TOKEN, RAGFLOW_AGENT_ID")
            sys.exit(1)
        
        print(f"问题: {question}")
        print("=" * 50)
        
        if stream_mode:
            print("流式回答:")
            for chunk in stream_chat_completion(base_url, api_token, agent_id, question):
                print(chunk, end="", flush=True)
            print("\n" + "=" * 50)
        else:
            print("直接回答:")
            answer = direct_chat_completion(base_url, api_token, agent_id, question)
            print(answer)
            print("=" * 50)
    else:
        print("用法: python simple_stream_client.py '你的问题'")
        print("\n环境变量:")
        print("  - RAGFLOW_BASE_URL: RAGFlow服务器地址")
        print("  - RAGFLOW_API_TOKEN: API访问令牌")
        print("  - RAGFLOW_AGENT_ID: 智能体ID")
        print("  - RAGFLOW_STREAM_MODE: 是否使用流式模式 (true/false)")


if __name__ == "__main__":
    main()