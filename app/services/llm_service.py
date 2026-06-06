import json
import re
from abc import ABC, abstractmethod

from openai import OpenAI

from app.config import get_settings


class LLMServiceError(Exception):
    pass


class BaseLLMService(ABC):
    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float | None = None) -> str:
        ...

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float | None = None) -> dict:
        text = self.chat(system_prompt, user_prompt, max_tokens, temperature)
        return _extract_json(text)


class DeepSeekService(BaseLLMService):
    def __init__(self, api_key: str, base_url: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = "deepseek-chat"

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float | None = None) -> str:
        try:
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature if temperature is not None else 0.1,
                max_tokens=max_tokens,
            )
            if temperature is not None and temperature > 0.3:
                kwargs["presence_penalty"] = 0.4
                kwargs["frequency_penalty"] = 0.3
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            raise LLMServiceError(f"DeepSeek API 调用失败: {e}")


class QwenService(BaseLLMService):
    def __init__(self, api_key: str):
        import dashscope
        self.api_key = api_key
        self.model = "qwen-plus"

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float | None = None) -> str:
        from dashscope import Generation
        try:
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                result_format="message",
                temperature=temperature if temperature is not None else 0.1,
                max_tokens=max_tokens,
            )
            if temperature is not None and temperature > 0.3:
                kwargs["top_p"] = 0.9
                kwargs["enable_search"] = False
            response = Generation.call(**kwargs)
            if response.status_code != 200:
                raise LLMServiceError(f"Qwen API 返回错误: {response.message}")
            return response.output.choices[0].message.content or ""
        except Exception as e:
            raise LLMServiceError(f"Qwen API 调用失败: {e}")


class OpenAIService(BaseLLMService):
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o"

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float | None = None) -> str:
        try:
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature if temperature is not None else 0.1,
                max_tokens=max_tokens,
            )
            if temperature is not None and temperature > 0.3:
                kwargs["presence_penalty"] = 0.4
                kwargs["frequency_penalty"] = 0.3
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            raise LLMServiceError(f"OpenAI API 调用失败: {e}")


def get_llm_service() -> BaseLLMService:
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "deepseek":
        if not settings.deepseek_api_key:
            raise LLMServiceError("未配置 DEEPSEEK_API_KEY，请检查 .env 文件")
        return DeepSeekService(settings.deepseek_api_key, settings.deepseek_base_url)

    if provider == "qwen":
        if not settings.dashscope_api_key:
            raise LLMServiceError("未配置 DASHSCOPE_API_KEY，请检查 .env 文件")
        return QwenService(settings.dashscope_api_key)

    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMServiceError("未配置 OPENAI_API_KEY，请检查 .env 文件")
        return OpenAIService(settings.openai_api_key)

    raise LLMServiceError(f"不支持的 LLM Provider: {provider}，可选: deepseek, qwen, openai")


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ``` block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    # Try finding first { ... } block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise LLMServiceError(f"无法从LLM响应中解析JSON: {text[:500]}")
