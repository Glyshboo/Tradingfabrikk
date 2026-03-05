import asyncio

from apps.self_check_runner import run_self_check


def test_self_check_runner_reports_ok_and_expected_guardrails():
    result = asyncio.run(run_self_check("configs/active.yaml"))

    assert result["ok"] is True
    assert result["checks"]["daily_loss_cap"] is True
    assert result["checks"]["max_exposure_cap"] is True
    assert result["checks"]["panic_flatten_reduce_only"] is True
