from __future__ import annotations

import json

import requests


class OllamaClient:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def build_rag_prompt(self, title: str, contexts: list[dict], question: str) -> str:
        context_text = "\n\n".join(
            f"片段 {index + 1}（{item.get('time_range', '未知时间')}）：{item.get('text', '')}"
            for index, item in enumerate(contexts)
        )
        if not context_text:
            context_text = "未检索到可用课程片段。"

        return f"""你是一个本地录播课教学辅助助手。请严格基于给定课程上下文回答问题。

规则：
1. 只能使用课程上下文中的信息回答。
2. 如果上下文不足以回答，请直接说明“当前视频上下文中没有足够信息”。
3. 回答要适合学生复习，优先给出清晰步骤、概念解释和必要例子。
4. 如果引用了课程内容，请在句末标注参考时间点，例如“参考 12:03 - 13:20”。

课程标题：{title or "未知课程"}

课程上下文：
{context_text}

用户问题：{question}

请用中文回答。"""

    def generate_stream(self, prompt: str):
        try:
            with requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": True},
                stream=True,
                timeout=300,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    try:
                        payload = json.loads(raw_line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if "response" in payload:
                        yield {"response": payload["response"]}
                    if payload.get("done"):
                        yield {"done": True}
        except requests.exceptions.ConnectionError:
            yield {"error": "无法连接 Ollama 服务，请确认已运行 ollama serve"}
        except requests.exceptions.HTTPError as exc:
            yield {"error": f"Ollama 请求失败：{exc}"}
        except requests.exceptions.Timeout:
            yield {"error": "Ollama 响应超时，请稍后重试或换用更小模型"}
        except Exception as exc:
            yield {"error": f"本地模型调用失败：{exc}"}


class OpenAICompatibleClient:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def build_rag_prompt(self, title: str, contexts: list[dict], question: str) -> str:
        return OllamaClient("", "").build_rag_prompt(title, contexts, question)

    def generate_stream(self, prompt: str):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            with requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                    "temperature": 0.2,
                },
                stream=True,
                timeout=300,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8").strip()
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        yield {"done": True}
                        break
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = payload.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield {"response": content}
        except requests.exceptions.ConnectionError:
            yield {"error": f"无法连接本地 API Server，请确认 Anaconda AI Navigator 的 API Server 已启动：{self.base_url}"}
        except requests.exceptions.HTTPError as exc:
            yield {"error": f"本地 API Server 请求失败：{exc}"}
        except requests.exceptions.Timeout:
            yield {"error": "本地 API Server 响应超时，请稍后重试"}
        except Exception as exc:
            yield {"error": f"本地模型调用失败：{exc}"}


def create_llm_client(settings):
    provider = settings.llm_provider.lower().strip()
    if provider in {"openai", "openai-compatible", "anaconda", "anaconda-ai"}:
        return OpenAICompatibleClient(settings.openai_base_url, settings.openai_model, settings.openai_api_key)
    return OllamaClient(settings.ollama_base_url, settings.ollama_model)
