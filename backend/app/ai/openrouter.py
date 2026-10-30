import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import settings


class OpenRouterError(Exception):
    def __init__(self, code: str, user_message: str, *, retryable: bool = False):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.retryable = retryable


class OpenRouterClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._sleep = sleep

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not settings.openrouter_api_key:
            raise OpenRouterError("configuration_error", "The AI provider is not configured.")

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "reasoning": {"enabled": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
        retries = max(0, settings.openrouter_max_retries)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.openrouter_timeout_seconds),
            transport=self._transport,
        ) as client:
            for attempt in range(retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except httpx.TimeoutException:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("timeout", "The AI provider took too long to respond.") from None
                except httpx.RequestError:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.") from None

                if response.status_code == 401:
                    raise OpenRouterError("invalid_api_key", "The AI provider rejected its server-side credentials.")
                if response.status_code == 404:
                    raise OpenRouterError("model_unavailable", "The configured AI model is unavailable.")
                if response.status_code == 429:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("rate_limited", "The AI provider is rate limiting requests.")
                if response.status_code >= 500:
                    if attempt < retries:
                        await self._backoff(attempt)
                        continue
                    raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.")
                if response.is_error:
                    raise OpenRouterError("provider_error", "The AI provider could not process this request.")

                try:
                    body = response.json()
                    message = body["choices"][0]["message"]
                    content = message.get("content")
                    tool_calls = message.get("tool_calls", [])
                    if not isinstance(tool_calls, list):
                        raise ValueError("Tool calls must be a list")
                    if not (isinstance(content, str) and content.strip()) and not tool_calls:
                        raise ValueError("Assistant response content is missing")
                except (ValueError, KeyError, IndexError, TypeError):
                    raise OpenRouterError("invalid_response", "The AI provider returned an invalid response.") from None

                usage = body.get("usage")
                return {
                    "content": content,
                    "reasoning_details": message.get("reasoning_details"),
                    "tool_calls": tool_calls,
                    "model": body.get("model", model),
                    "usage": usage if isinstance(usage, dict) else None,
                }

        raise OpenRouterError("provider_unavailable", "The AI provider is temporarily unavailable.")

    async def _backoff(self, attempt: int) -> None:
        await self._sleep(min(2**attempt + random.random(), 5.0))
