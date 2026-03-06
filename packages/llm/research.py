from __future__ import annotations

import json
import pathlib
import time
import uuid

from packages.llm.providers import AnthropicProvider, LLMResponse, OpenAIProvider


class LLMResearchService:
    def __init__(self, cfg: dict, out_dir: str = "runtime/llm") -> None:
        self.cfg = cfg
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _provider(self, name: str):
        if name == "openai":
            return OpenAIProvider(self.cfg.get("openai_model", "gpt-4o-mini"))
        if name == "anthropic":
            return AnthropicProvider(self.cfg.get("anthropic_model", "claude-3-5-sonnet-latest"))
        raise ValueError(f"unsupported provider: {name}")

    def research(self, prompt: str) -> dict:
        primary = self.cfg.get("provider", "openai")
        fallback = self.cfg.get("fallback_provider", "anthropic")
        errors = []
        response: LLMResponse | None = None
        for provider_name in [primary, fallback]:
            try:
                response = self._provider(provider_name).run_research(prompt)
                break
            except Exception as exc:
                errors.append({"provider": provider_name, "error": str(exc)})
        if response is None:
            response = LLMResponse(provider="none", summary="LLM unavailable; no automated deployment or config changes were applied.")

        rid = str(uuid.uuid4())
        artifact = {
            "id": rid,
            "ts": time.time(),
            "provider": response.provider,
            "errors": errors,
            "summary": response.summary,
            "allowed_outputs": [
                "research summaries",
                "diagnosis",
                "strategy ideas",
                "config candidate proposals",
                "search-space suggestions",
                "optional strict-review code proposals",
            ],
            "auto_deploy": False,
        }
        path = self.out_dir / f"{rid}.json"
        path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        artifact["artifact_path"] = str(path)
        return artifact
