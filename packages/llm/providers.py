from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol
from urllib import request


@dataclass
class LLMResponse:
    provider: str
    summary: str


class LLMProvider(Protocol):
    def run_research(self, prompt: str) -> LLMResponse: ...


class OpenAIProvider:
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY", "")

    def run_research(self, prompt: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("missing OPENAI_API_KEY")
        body = {
            "model": self.model,
            "input": prompt,
        }
        req = request.Request(
            "https://api.openai.com/v1/responses",
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            data=json.dumps(body).encode("utf-8"),
        )
        with request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload.get("output_text") or ""
        return LLMResponse(provider="openai", summary=text.strip())


class AnthropicProvider:
    def __init__(self, model: str = "claude-3-5-sonnet-latest") -> None:
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")

    def run_research(self, prompt: str) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("missing ANTHROPIC_API_KEY")
        body = {
            "model": self.model,
            "max_tokens": 700,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = request.Request(
            "https://api.anthropic.com/v1/messages",
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            data=json.dumps(body).encode("utf-8"),
        )
        with request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = ""
        for item in payload.get("content", []):
            if item.get("type") == "text":
                text += item.get("text", "")
        return LLMResponse(provider="anthropic", summary=text.strip())
