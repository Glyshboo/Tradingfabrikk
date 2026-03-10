from __future__ import annotations

from packages.core.candidate_runtime import validate_runtime_patch


def validate_llm_candidate_payload(cfg: dict, structured: dict) -> tuple[bool, list[str], dict]:
    errors: list[str] = []
    critical_text_fields = [
        "summary",
        "diagnosis",
        "edge_hypothesis",
        "failure_mode_target",
        "expected_market_regime",
        "validation_plan",
        "risk_to_overfit",
    ]
    for field in critical_text_fields:
        value = structured.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing_or_invalid_{field}")

    proposed_actions = structured.get("proposed_actions")
    if not isinstance(proposed_actions, list) or len(proposed_actions) == 0:
        errors.append("missing_or_invalid_proposed_actions")

    confidence = structured.get("confidence")
    try:
        conf_value = float(confidence)
        if conf_value < 0.0 or conf_value > 1.0:
            errors.append("confidence_out_of_range")
    except Exception:
        errors.append("missing_or_invalid_confidence")

    config_patch = structured.get("config_patch") or {}
    search_space_patch = structured.get("search_space_patch") or {}
    strategy_profile_patch = structured.get("strategy_profile_patch") or {}
    if not isinstance(config_patch, dict):
        errors.append("config_patch_not_dict")
        config_patch = {}
    if not isinstance(search_space_patch, dict):
        errors.append("search_space_patch_not_dict")
        search_space_patch = {}
    if not isinstance(strategy_profile_patch, dict):
        errors.append("strategy_profile_patch_not_dict")
        strategy_profile_patch = {}

    has_runtime_payload = bool(config_patch) or bool(strategy_profile_patch)
    has_research_payload = bool(search_space_patch)
    if not has_runtime_payload and not has_research_payload:
        errors.append("no_executable_patch_payload")

    if has_runtime_payload:
        ok, runtime_errors = validate_runtime_patch(cfg, config_patch=config_patch, strategy_profile_patch=strategy_profile_patch)
        if not ok:
            errors.extend(runtime_errors)

    if search_space_patch:
        allowed_root = {"strategy_configs", "selector", "symbols", "regimes"}
        unsupported = sorted(set(search_space_patch.keys()) - allowed_root)
        if unsupported:
            errors.append(f"unsupported_search_space_patch_keys:{','.join(unsupported)}")

    normalized = {
        "config_patch": config_patch,
        "search_space_patch": search_space_patch,
        "strategy_profile_patch": strategy_profile_patch,
    }
    return len(errors) == 0, errors, normalized
