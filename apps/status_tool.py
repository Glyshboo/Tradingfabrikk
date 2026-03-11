from __future__ import annotations

import argparse
import json
import pathlib
import time
from datetime import datetime, timezone
from json import JSONDecodeError

from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue


def _safe_read_json(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (JSONDecodeError, OSError):
        return None


def _fmt_ts(ts: float | int | None) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_age(ts: float | int | None) -> str:
    if not ts:
        return "unknown"
    age = max(0.0, time.time() - float(ts))
    if age < 60:
        return f"{int(age)}s ago"
    if age < 3600:
        return f"{int(age // 60)}m ago"
    return f"{int(age // 3600)}h {int((age % 3600) // 60)}m ago"


def _candidate_counts(registry_report: dict) -> dict[str, int]:
    counts = registry_report.get("counts") if isinstance(registry_report, dict) else {}
    return counts if isinstance(counts, dict) else {}


def _render_operator_view(status: dict, research_last_run: dict | None, status_file: pathlib.Path) -> str:
    mode = status.get("mode") or "unknown"
    state = status.get("state") or "unknown"
    ws_status = status.get("ws_status") if isinstance(status.get("ws_status"), dict) else {}
    status_ts = status.get("ts")

    registry_report = status.get("candidate_registry") if isinstance(status.get("candidate_registry"), dict) else CandidateRegistry().report()
    counts = _candidate_counts(registry_report)
    review_queue_size = int(status.get("review_queue_size") or len(ReviewQueue().list_ready()) or 0)

    exports_path = pathlib.Path("runtime/llm_exports/paste_to_llm.md")
    export_ts = exports_path.stat().st_mtime if exports_path.exists() else None

    lines = []
    lines.append("=" * 76)
    lines.append("👑 Lord Heibø Tradingfabrikk Operator Dashboard (paper-first)")
    lines.append("=" * 76)
    lines.append(f"Engine mode : {mode}")
    lines.append(f"Engine state: {state}")
    lines.append(f"Status file : {status_file}")
    lines.append(f"Last status : {_fmt_ts(status_ts)} ({_fmt_age(status_ts)})")

    if mode == "paper":
        lines.append("✅ Lab mode is safe: paper engine mode is active.")
    elif mode == "live":
        lines.append("⚠️ Engine reports LIVE mode. Lab mode should stay paper-first.")
    else:
        lines.append("⚠️ Engine mode unknown in status payload.")

    ws_market = ws_status.get("market")
    ws_user = ws_status.get("user")
    lines.append("\n📈 Paper engine health")
    lines.append(f"- Websocket market feed: {ws_market if ws_market is not None else 'unknown'}")
    lines.append(f"- User/account stream   : {ws_user if ws_user is not None else 'unknown'}")
    lines.append(f"- Safe pause           : {status.get('safe_pause')}")
    lines.append(f"- Reduce-only          : {status.get('reduce_only')}")

    lines.append("\n🧠 Research (batch job)")
    if research_last_run:
        failed = bool(research_last_run.get("failed"))
        run_ts = research_last_run.get("completed_ts") or research_last_run.get("started_ts")
        lines.append(f"- Last run             : {_fmt_ts(run_ts)} ({_fmt_age(run_ts)})")
        lines.append(f"- Result               : {'FAILED' if failed else 'COMPLETED'}")
        lines.append(f"- Candidates generated : {research_last_run.get('generated_candidates', 0)}")
        lines.append(f"- Artifacts            : {research_last_run.get('artifact_root', 'runtime/review_artifacts')}")
    else:
        lines.append("- Last run             : none recorded yet (research may not have run)")
    lines.append("- Workflow note        : Research is batch-based and currently idle between runs.")

    lines.append("\n📄 Candidate pipeline")
    lines.append(f"- Total candidates             : {registry_report.get('total', 0)}")
    lines.append(f"- backtest_pass                : {counts.get('backtest_pass', 0)}")
    lines.append(f"- paper_smoke_running          : {counts.get('paper_smoke_running', 0)}")
    lines.append(f"- challenger_active            : {counts.get('challenger_active', 0)}")
    lines.append(f"- challenger_evaluated         : {counts.get('challenger_evaluated', 0)}")
    lines.append(f"- paper_candidate_active       : {counts.get('paper_candidate_active', 0)}")
    lines.append(f"- paper_candidate_winning      : {counts.get('paper_candidate_winning', 0)}")
    lines.append(f"- paper_candidate_fading       : {counts.get('paper_candidate_fading', 0)}")
    lines.append(f"- ready_for_review             : {counts.get('ready_for_review', 0)}")
    lines.append(f"- needs_revalidation           : {counts.get('needs_revalidation', 0)}")
    lines.append(f"- review queue size            : {review_queue_size}")

    if review_queue_size == 0:
        incubation = (
            counts.get("paper_smoke_running", 0)
            + counts.get("challenger_active", 0)
            + counts.get("challenger_evaluated", 0)
            + counts.get("paper_candidate_active", 0)
            + counts.get("paper_candidate_winning", 0)
            + counts.get("paper_candidate_fading", 0)
            + counts.get("needs_revalidation", 0)
        )
        if incubation > 0:
            lines.append("- Review note                  : No candidates are ready for review yet; incubation/challenger is still running.")
        elif registry_report.get("total", 0) == 0:
            lines.append("- Review note                  : Candidate pool is empty. Run research to generate candidates.")
        else:
            lines.append("- Review note                  : Queue is currently empty.")

    lines.append("\n🧪 Challenger / no-trade diagnostics")
    no_trade = status.get("no_trade_diagnostics") if isinstance(status.get("no_trade_diagnostics"), dict) else {}
    reason = no_trade.get("reason") or "none"
    lines.append(f"- Latest no-trade reason       : {reason}")

    lines.append("\n🤖 Manual LLM export")
    lines.append(f"- Last export refresh          : {_fmt_ts(export_ts)} ({_fmt_age(export_ts)})")
    lines.append("- paste_to_llm.md              : runtime/llm_exports/paste_to_llm.md")
    lines.append("\nTip: pending=0 does NOT always mean idle; candidates may still be incubating before review.")
    lines.append("=" * 76)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", default="runtime/status.json")
    parser.add_argument("--research-run-file", default="runtime/research_last_run.json")
    parser.add_argument("--watch", action="store_true", help="Refresh status continuously")
    parser.add_argument("--interval", type=float, default=5.0, help="Watch refresh interval in seconds")
    parser.add_argument("--json", action="store_true", help="Print compact json view")
    args = parser.parse_args()

    status_path = pathlib.Path(args.status_file)
    if not status_path.exists():
        print("⚠️ Status file not found.")
        print(f"Expected: {status_path}")
        print("Start paper engine first (scripts\\02_paper.bat), then run status again.")
        return

    def render_once() -> None:
        status = _safe_read_json(status_path)
        if status is None:
            print("⚠️ Could not parse status JSON. File may be empty or mid-write.")
            print(f"File: {status_path}")
            return

        research_last_run = _safe_read_json(pathlib.Path(args.research_run_file))

        if args.json:
            payload = {
                "mode": status.get("mode"),
                "state": status.get("state"),
                "review_queue_size": status.get("review_queue_size"),
                "candidate_registry": status.get("candidate_registry", CandidateRegistry().report()),
                "research_last_run": research_last_run,
                "ts": status.get("ts"),
            }
            print(json.dumps(payload, indent=2))
            return

        print(_render_operator_view(status, research_last_run, status_path))

    if args.watch:
        try:
            while True:
                print("\x1bc", end="")
                render_once()
                time.sleep(max(1.0, float(args.interval)))
        except KeyboardInterrupt:
            print("\nStopped status watch.")
        return

    render_once()


if __name__ == "__main__":
    main()
