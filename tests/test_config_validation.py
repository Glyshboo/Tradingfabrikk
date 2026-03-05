import pytest

from packages.core.config import load_config


def test_load_config_rejects_missing_top_level_keys(tmp_path):
    cfg = tmp_path / "invalid.yaml"
    cfg.write_text("mode: paper\nsymbols: [BTCUSDT]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing keys"):
        load_config(str(cfg))


def test_load_config_rejects_missing_strategy_profile_for_symbol(tmp_path):
    cfg = tmp_path / "invalid.yaml"
    cfg.write_text(
        """
mode: paper
symbols: [BTCUSDT]
account: {equity: 10000}
engine: {stale_after_sec: 15, decision_interval_sec: 2, profile_update_sec: 30}
sizing: {base_qty: 0.01}
risk: {max_daily_loss: 100, max_total_exposure_notional: 1000, max_leverage: 2, max_open_positions: 1, per_symbol_exposure_cap: {BTCUSDT: 1000}, correlation_clusters: {}, correlation_direction_cap: 1}
selector: {base_edge: {TrendCore: 0.1}}
strategy_configs: {TrendCore: {tc_safe: {base_confidence: 0.6}}}
strategy_profiles: {}
telemetry: {audit_db: runtime/audit.db, status_file: runtime/status.json}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="strategy_profiles missing symbols"):
        load_config(str(cfg))
