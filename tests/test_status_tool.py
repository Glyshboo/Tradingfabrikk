import json
import subprocess
import sys

from packages.research.candidate_registry import CandidateRegistry


def test_status_tool_includes_candidate_registry_summary(tmp_path):
    status_file = tmp_path / "status.json"
    registry_file = tmp_path / "registry.json"

    status_file.write_text(
        json.dumps(
            {
                "mode": "paper",
                "state": "RUNNING",
                "symbols": ["BTCUSDT"],
                "open_positions": {},
                "last_decision": {},
                "ws_status": {},
                "account_sync_health": {},
                "current_regime": {},
                "risk_caps_status": {},
                "safe_pause": False,
                "reduce_only": False,
                "ts": 1,
            }
        ),
        encoding="utf-8",
    )

    reg = CandidateRegistry(path=str(registry_file))
    reg.register("cand_1", 1.0, {"symbol": "BTCUSDT"})

    out = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "apps.status_tool",
            "--status-file",
            str(status_file),
            "--registry",
            str(registry_file),
        ],
        text=True,
    )
    parsed = json.loads(out)
    assert parsed["candidate_registry"]["total"] == 1
