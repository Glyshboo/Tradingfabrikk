from __future__ import annotations

from packages.research.export_refresh_service import ExportRefreshService


class _Exporter:
    def __init__(self, calls: list[str], fail: bool = False):
        self.calls = calls
        self.fail = fail

    def export(self):
        self.calls.append("export")
        if self.fail:
            raise RuntimeError("boom")
        return {"output_dir": "runtime/llm_exports"}


def test_refresh_respects_cooldown(tmp_path):
    calls: list[str] = []
    now = {"ts": 1000.0}
    service = ExportRefreshService(
        {
            "enabled": True,
            "output_dir": str(tmp_path / "exports"),
            "state_file": str(tmp_path / "exports" / "refresh_state.json"),
            "refresh_on_research": True,
            "min_refresh_interval_sec": 60,
        },
        now_fn=lambda: now["ts"],
        exporter_factory=lambda: _Exporter(calls),
    )

    first = service.refresh_exports(trigger="research_runner")
    now["ts"] = 1010.0
    second = service.refresh_exports(trigger="research_runner")

    assert first["refreshed"] is True
    assert second["refreshed"] is False
    assert second["skipped"] == "cooldown"
    assert calls == ["export"]


def test_refresh_fail_soft_on_export_error(tmp_path):
    service = ExportRefreshService(
        {
            "enabled": True,
            "output_dir": str(tmp_path / "exports"),
            "state_file": str(tmp_path / "exports" / "refresh_state.json"),
            "refresh_on_research": True,
            "min_refresh_interval_sec": 0,
        },
        exporter_factory=lambda: _Exporter([], fail=True),
    )

    report = service.refresh_exports(trigger="research_runner")
    assert report["refreshed"] is False
    assert report["failed"] is True
    assert "boom" in report["error"]
