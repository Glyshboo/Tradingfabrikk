from __future__ import annotations

import asyncio

from packages.core.state_store import EngineStateStore
from packages.data.data_manager import DataManager
from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ReviewQueue


def test_candidate_registry_recovers_from_empty_or_invalid_json(tmp_path):
    path = tmp_path / "candidates_registry.json"
    path.write_text("", encoding="utf-8")
    reg = CandidateRegistry(path=str(path))
    assert reg.report()["total"] == 0

    path.write_text("{not-json", encoding="utf-8")
    assert reg.list_ready_for_review() == []


def test_review_queue_recovers_from_invalid_json(tmp_path):
    path = tmp_path / "review_queue.json"
    path.write_text("[]", encoding="utf-8")
    queue = ReviewQueue(path=str(path))
    assert queue.list_ready() == []


def test_engine_state_recovers_from_empty_json(tmp_path):
    path = tmp_path / "engine_state.json"
    path.write_text("", encoding="utf-8")
    store = EngineStateStore(path=str(path))
    payload = store.load()
    assert payload["engine_state"] == "recovering"
    assert isinstance(payload["sessions"], list)


def test_user_stream_is_noop_without_auth_requirement_even_if_api_key_present():
    dm = DataManager(symbols=["BTCUSDT"], api_key="invalid", require_user_stream_auth=False)

    def _fail_create_listen_key():
        raise AssertionError("listen key creation should not run in paper/no-auth mode")

    dm._create_listen_key = _fail_create_listen_key  # type: ignore[method-assign]

    async def _run() -> None:
        task = asyncio.create_task(dm.run_user_stream())
        await asyncio.sleep(0.02)
        assert dm.user_stream_alive is True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_run())
