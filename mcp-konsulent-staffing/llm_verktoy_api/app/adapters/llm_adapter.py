from __future__ import annotations

import json
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple

import httpx
from openai import AsyncOpenAI

from app.core.models import Ok, Err, ErrorCode, Result, ServiceError


class LLMAdapter(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def generate_json(self, *, prompt: str, schema: Dict[str, Any]) -> Result[Tuple[Dict[str, Any], Dict[str, Any]], ServiceError]: ...


class OpenRouterAdapter(LLMAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int = 30,
        max_tokens: int = 220,
        temperature: float = 0.4,
        structured_outputs: bool = True,
        app_name: str = "",
        referer: str = "",
        response_healing: bool = False,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.structured_outputs = structured_outputs
        self.app_name = app_name
        self.referer = referer
        self.response_healing = response_healing

    @property
    def provider_name(self) -> str:
        return f"openrouter:{self.model}"

    async def generate_json(self, *, prompt: str, schema: Dict[str, Any]) -> Result[Tuple[Dict[str, Any], Dict[str, Any]], ServiceError]:
        headers = {}
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.app_name:
            headers["X-Title"] = self.app_name

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout, default_headers=headers)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.structured_outputs:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "konsulent_sammendrag", "schema": schema, "strict": True},
            }
        if self.response_healing:
            # OpenRouter plugin (best-effort). If unsupported, OpenRouter ignores unknown plugins.
            extra = kwargs.get("extra_body") or {}
            extra["plugins"] = [{"id": "response-healing"}]
            kwargs["extra_body"] = extra

        try:
            resp = await client.chat.completions.create(**kwargs)
            resp_dict = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)

            content = (resp_dict.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""
            obj = json.loads(content)

            usage_meta = _extract_usage_meta(resp_dict)
            return Ok((obj, usage_meta))
        except Exception as e:
            return Err(ServiceError(code=ErrorCode.LLM_API_ERROR, message=f"{type(e).__name__}: {e}", details={"status_code": 502}))


class LlamaCppServerAdapter(LLMAdapter):
    """OpenAI-compatible llama.cpp server adapter.

    Expected base_url like: http://llama_cpp:8080/v1
    """

    def __init__(self, *, base_url: str, timeout: int = 5, max_tokens: int = 220, temperature: float = 0.4):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def provider_name(self) -> str:
        return "local_gguf"

    
    async def generate_json(self, *, prompt: str, schema: Dict[str, Any]) -> Result[Tuple[Dict[str, Any], Dict[str, Any]], ServiceError]:

        """Call llama.cpp OpenAI-compatible server with retries.


        Retries help with transient 503 during warm-up / slot contention, and longer local inference times.

        """

        url = f"{self.base_url}/chat/completions"


        payload: Dict[str, Any] = {

            "model": "local",

            "messages": [{"role": "user", "content": prompt}],

            "temperature": self.temperature,

            "max_tokens": self.max_tokens,

            "response_format": {"type": "json_object"},

        }


        retries = 3

        backoff = 0.6

        last_err: Exception | None = None


        for attempt in range(1, retries + 1):

            try:

                timeout = httpx.Timeout(connect=10.0, read=float(self.timeout), write=30.0, pool=10.0)

                async with httpx.AsyncClient(timeout=timeout) as client:

                    r = await client.post(url, json=payload)

                    r.raise_for_status()

                    data = r.json()

                    content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

                    if not str(content).strip():

                        raise ValueError("Empty LLM response content")

                    try:

                        obj = json.loads(content)

                    except Exception as je:

                        raise ValueError(f"JSONDecodeError: {je}") from je

                    usage_meta = _extract_usage_meta(data)

                    return Ok((obj, usage_meta))

            except Exception as e:

                last_err = e

                transient = isinstance(e, (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError))

                status_code = getattr(getattr(e, "response", None), "status_code", None)

                if status_code in (500, 502, 503, 504):

                    transient = True

                if attempt < retries and transient:

                    await asyncio.sleep(backoff * attempt)

                    continue

                break


        return Err(ServiceError(code=ErrorCode.LLM_API_ERROR, message=f"{type(last_err).__name__}: {last_err}", details={"status_code": 502}))

class NoopAdapter(LLMAdapter):
    """Fallback adapter when no LLM provider is configured.

    Important for a "first try" run: if OpenRouter is enabled but the key isn't set,
    and the local llama.cpp server isn't enabled, we should fail fast and let the service
    return the deterministic summary instead of timing out on a missing dependency.
    """

    @property
    def provider_name(self) -> str:
        return "noop"

    async def generate_json(self, *, prompt: str, schema: Dict[str, Any]) -> Result[Tuple[Dict[str, Any], Dict[str, Any]], ServiceError]:
        return Err(ServiceError(code=ErrorCode.LLM_API_ERROR, message="No LLM configured", details={"status_code": 503}))


def _extract_usage_meta(resp: Dict[str, Any]) -> Dict[str, Any]:
    usage = resp.get("usage") or {}
    # OpenRouter often includes usage.cost (credits) and cached_tokens.
    meta = {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "cached_tokens": int(usage.get("cached_tokens", 0) or 0),
        "cost": float(usage.get("cost", resp.get("cost", 0.0)) or 0.0),
        "cache_hit": bool(usage.get("cached_tokens", 0) or 0),
    }
    return meta
