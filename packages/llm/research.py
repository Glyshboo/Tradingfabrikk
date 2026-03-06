from __future__ import annotations

import json
import pathlib
import time
import uuid

from packages.llm.providers import AnthropicProvider, LLMResponse, OpenAIProvider


_PROVIDER_ALIASES = {
    "codex": "openai",
    "openai": "openai",
    "claude": "anthropic",
    "anthropic": "anthropic",
}


class LLMResearchService:
    def __init__(self, cfg: dict, out_dir: str = "runtime/llm") -> None:
        self.cfg = cfg
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_provider_name(self, name: str | None) -> str:
        resolved = _PROVIDER_ALIASES.get((name or "").strip().lower())
        if not resolved:
            raise ValueError(f"unsupported provider: {name}")
        return resolved

    def _provider(self, name: str):
        resolved = self._resolve_provider_name(name)
        if resolved == "openai":
            return OpenAIProvider(self.cfg.get("openai_model", "gpt-4o-mini"))
        if resolved == "anthropic":
            return AnthropicProvider(self.cfg.get("anthropic_model", "claude-3-5-sonnet-latest"))
        raise ValueError(f"unsupported provider: {name}")

    def research(self, prompt: str, bundle: dict | None = None) -> dict:
        primary = self.cfg.get("provider", "codex")
        fallback = self.cfg.get("fallback_provider", "claude")
        tried = []
        for provider_name in [primary, fallback]:
            resolved = self._resolve_provider_name(provider_name)
            if resolved not in tried:
                tried.append(resolved)

        errors = []
        response: LLMResponse | None = None
        for provider_name in tried:
            try:
                final_prompt = prompt
                if bundle:
                    final_prompt = f"{prompt}\n\nResearch bundle:\n{json.dumps(bundle, indent=2)[:12000]}"
                response = self._provider(provider_name).run_research(final_prompt)
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
            "primary_provider": self._resolve_provider_name(primary),
            "fallback_provider": self._resolve_provider_name(fallback),
            "errors": errors,
            "summary": response.summary,
            "bundle": bundle or {},
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
