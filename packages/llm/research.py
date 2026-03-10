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

REQUIRED_STRUCTURED_KEYS = [
    "summary",
    "diagnosis",
    "edge_hypothesis",
    "failure_mode_target",
    "expected_market_regime",
    "proposed_actions",
    "config_patch",
    "strategy_profile_patch",
    "search_space_patch",
    "validation_plan",
    "risk_to_overfit",
    "confidence",
    "warnings",
]


def empty_structured() -> dict:
    return {
        "summary": "",
        "diagnosis": "",
        "edge_hypothesis": "",
        "failure_mode_target": "",
        "expected_market_regime": "",
        "proposed_actions": [],
        "config_patch": {},
        "strategy_profile_patch": {},
        "search_space_patch": {},
        "validation_plan": "",
        "risk_to_overfit": "",
        "confidence": 0.0,
        "warnings": ["llm_unavailable_or_invalid"],
    }


class LLMBudgetTracker:
    def __init__(self, path: str = "runtime/llm_budget.json") -> None:
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"calls": []}, indent=2), encoding="utf-8")

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _window_counts(self, calls: list[dict]) -> tuple[int, int]:
        now = time.time()
        day = sum(1 for x in calls if now - float(x.get("ts", 0)) <= 86400)
        week = sum(1 for x in calls if now - float(x.get("ts", 0)) <= 7 * 86400)
        return day, week

    def allow(self, budgets: dict) -> tuple[bool, dict]:
        payload = self._load()
        calls = payload.get("calls", [])[-1000:]
        day_count, week_count = self._window_counts(calls)
        max_day = int(budgets.get("max_calls_per_day", 0) or 0)
        max_week = int(budgets.get("max_calls_per_week", 0) or 0)
        allowed = (max_day <= 0 or day_count < max_day) and (max_week <= 0 or week_count < max_week)
        return allowed, {
            "used_day": day_count,
            "used_week": week_count,
            "remaining_day": max(0, max_day - day_count) if max_day > 0 else None,
            "remaining_week": max(0, max_week - week_count) if max_week > 0 else None,
            "max_day": max_day,
            "max_week": max_week,
        }

    def record_call(self, provider: str, success: bool) -> dict:
        payload = self._load()
        payload.setdefault("calls", []).append({"ts": time.time(), "provider": provider, "success": bool(success)})
        payload["calls"] = payload["calls"][-1000:]
        self._save(payload)
        return payload


class LLMResearchService:
    def __init__(self, cfg: dict, out_dir: str = "runtime/llm") -> None:
        self.cfg = cfg
        self.out_dir = pathlib.Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.budget_tracker = LLMBudgetTracker(cfg.get("budget_file", "runtime/llm_budget.json"))

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

    def _normalize(self, response: LLMResponse | None) -> dict:
        if response is None or not response.raw_text:
            return empty_structured()
        try:
            parsed = json.loads(response.raw_text)
            if not isinstance(parsed, dict):
                return empty_structured()
            missing = [k for k in REQUIRED_STRUCTURED_KEYS if k not in parsed]
            if missing:
                normalized = empty_structured()
                normalized["warnings"] = [f"missing_required_keys:{','.join(missing)}"]
                return normalized
            return {
                "summary": str(parsed.get("summary", ""))[:2000],
                "diagnosis": str(parsed.get("diagnosis", ""))[:4000],
                "edge_hypothesis": str(parsed.get("edge_hypothesis", ""))[:3000],
                "failure_mode_target": str(parsed.get("failure_mode_target", ""))[:2500],
                "expected_market_regime": str(parsed.get("expected_market_regime", ""))[:1200],
                "proposed_actions": parsed.get("proposed_actions") if isinstance(parsed.get("proposed_actions"), list) else [],
                "config_patch": parsed.get("config_patch") if isinstance(parsed.get("config_patch"), dict) else {},
                "strategy_profile_patch": parsed.get("strategy_profile_patch") if isinstance(parsed.get("strategy_profile_patch"), dict) else {},
                "search_space_patch": parsed.get("search_space_patch") if isinstance(parsed.get("search_space_patch"), dict) else {},
                "validation_plan": str(parsed.get("validation_plan", ""))[:2500],
                "risk_to_overfit": str(parsed.get("risk_to_overfit", ""))[:2500],
                "confidence": float(parsed.get("confidence", 0.0) or 0.0),
                "warnings": parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else [],
            }
        except Exception:
            return empty_structured()

    def research(self, prompt: str, bundle: dict | None = None) -> dict:
        budgets = self.cfg.get("budgets", {})
        budget_ok, budget_status = self.budget_tracker.allow(budgets)
        primary = self.cfg.get("provider", "codex")
        fallback = self.cfg.get("fallback_provider", "claude")

        if not budget_ok:
            response = None
            errors = [{"provider": "budget", "error": "llm_budget_exceeded"}]
            provider = "none"
        else:
            tried = []
            for provider_name in [primary, fallback]:
                resolved = self._resolve_provider_name(provider_name)
                if resolved not in tried:
                    tried.append(resolved)

            errors = []
            response: LLMResponse | None = None
            for provider_name in tried:
                try:
                    final_prompt = (
                        f"Return ONLY strict JSON with keys: {', '.join(REQUIRED_STRUCTURED_KEYS)}. "
                        f"No markdown, no prose outside JSON.\n\n{prompt}"
                    )
                    if bundle:
                        final_prompt += f"\n\nResearch bundle:\n{json.dumps(bundle, indent=2)[:12000]}"
                    response = self._provider(provider_name).run_research(final_prompt)
                    break
                except Exception as exc:
                    errors.append({"provider": provider_name, "error": str(exc)})
            provider = response.provider if response else "none"

        structured = self._normalize(response if budget_ok else None)
        if not budget_ok:
            structured["warnings"] = list(structured.get("warnings", [])) + ["budget_exceeded"]

        rid = str(uuid.uuid4())
        artifact = {
            "id": rid,
            "ts": time.time(),
            "provider": provider,
            "primary_provider": self._resolve_provider_name(primary),
            "fallback_provider": self._resolve_provider_name(fallback),
            "errors": errors,
            "summary": structured.get("summary", ""),
            "structured": structured,
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
            "budget": budget_status,
        }
        if budget_ok:
            self.budget_tracker.record_call(provider=provider, success=provider != "none")
            _, artifact["budget"] = self.budget_tracker.allow(budgets)
        path = self.out_dir / f"{rid}.json"
        path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        artifact["artifact_path"] = str(path)
        return artifact
