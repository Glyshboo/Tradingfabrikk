from __future__ import annotations

import argparse
import json
import pathlib
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from packages.research.candidate_registry import CandidateRegistry
from packages.review.review_queue import ALLOWED_ACTIONS, ReviewQueue


HTML = """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Tradingfabrikk Review Panel</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background:#f6f8fb; }
    h1 { margin-top: 0; }
    .card { background:white; padding: 14px; margin-bottom: 12px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    .row { display:flex; flex-wrap:wrap; gap:10px; margin: 8px 0; }
    .pill { font-size: 12px; padding: 4px 8px; border-radius: 999px; background:#eef2ff; }
    button { margin-right: 8px; }
    details pre { white-space: pre-wrap; }
  </style>
</head>
<body>
<h1>Unified Candidate Review</h1>
<div id=\"meta\"></div>
<div id=\"candidates\"></div>
<script>
async function loadCandidates(){
  const res = await fetch('/api/candidates');
  const data = await res.json();
  document.getElementById('meta').innerText = `Pending: ${data.pending.length}`;
  const root = document.getElementById('candidates');
  root.innerHTML = '';
  for (const c of data.pending){
    const el = document.createElement('div');
    el.className = 'card';
    const symbols = (c.symbols || []).join(', ');
    const regimes = (c.regimes || []).join(', ');
    el.innerHTML = `
      <div class='row'>
        <strong>${c.id}</strong>
        <span class='pill'>type:${c.type || 'config'}</span>
        <span class='pill'>track:${c.track || 'fast'}</span>
        <span class='pill'>provider:${c.provider || 'unknown'}</span>
      </div>
      <div>symbols: ${symbols} | regimes: ${regimes} | strategy: ${c.strategy_family || '-'}</div>
      <div>backtest: ${JSON.stringify(c.backtest_result || c.artifacts?.backtest_result || null)} </div>
      <div>oos: ${JSON.stringify(c.oos_result || c.artifacts?.oos_result || null)} | paper_smoke: ${JSON.stringify(c.paper_smoke_result || c.artifacts?.paper_smoke_result || null)}</div>
      <div>risk_notes: ${c.risk_notes || c.artifacts?.risk_notes || '-'} </div>
      <div>recommendation: ${c.recommendation || '-'} | warnings: ${(c.warnings || []).join('; ')}</div>
      <div class='row'>
        <button onclick="act('${c.id}','approve_micro_live')">Approve micro-live</button>
        <button onclick="act('${c.id}','approve_live_full')">Approve full-live</button>
        <button onclick="act('${c.id}','hold')">Hold</button>
        <button onclick="act('${c.id}','keep_paper')">Keep paper</button>
        <button onclick="act('${c.id}','reject')">Reject</button>
      </div>
      <details><summary>details</summary><pre>${JSON.stringify(c, null, 2)}</pre></details>
    `;
    root.appendChild(el);
  }
}
async function act(candidateId, action){
  const note = prompt(`Optional note for ${action}`) || '';
  const res = await fetch('/api/action', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({candidate_id:candidateId, action, note})
  });
  const payload = await res.json();
  if(!res.ok){
    alert(payload.error || 'action failed');
    return;
  }
  await loadCandidates();
}
loadCandidates();
</script>
</body>
</html>
"""


class ReviewHandler(BaseHTTPRequestHandler):
    queue = ReviewQueue()
    registry = CandidateRegistry()

    def _send(self, status: int, payload: dict | str, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _pending(self) -> list[dict]:
        pending = []
        for row in self.queue.list_ready():
            record = self.registry.get(row.get("id", "")) or {}
            merged = dict(record)
            merged.update(row)
            pending.append(merged)
        return pending

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(HTTPStatus.OK, HTML, content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/api/candidates":
            self._send(HTTPStatus.OK, {"pending": self._pending()})
            return
        if parsed.path == "/api/candidate":
            query = parse_qs(parsed.query)
            cid = (query.get("id") or [""])[0]
            row = self.registry.get(cid)
            if not row:
                self._send(HTTPStatus.NOT_FOUND, {"error": "candidate not found"})
                return
            self._send(HTTPStatus.OK, row)
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/action":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        try:
            payload = json.loads(raw.decode("utf-8"))
            candidate_id = str(payload.get("candidate_id", ""))
            action = str(payload.get("action", ""))
            note = str(payload.get("note", ""))
            if action not in ALLOWED_ACTIONS:
                raise ValueError(f"unsupported action: {action}")
            if not candidate_id:
                raise ValueError("candidate_id is required")
            record = self.registry.get(candidate_id)
            if not record:
                raise ValueError("candidate not found")
            if record.get("type") in {"risk", "execution", "code"} and record.get("track") != "strict":
                raise ValueError("protected candidate types must remain on strict track")
            if action == "approve_micro_live" and record.get("state") != "ready_for_review":
                raise ValueError("approve_micro_live requires ready_for_review state")
            if action == "approve_live_full" and record.get("state") not in {
                "approved_for_micro_live",
                "micro_live_active",
                "micro_live_resumed",
            }:
                raise ValueError("approve_live_full is only allowed after micro-live state")
            result = self.queue.apply_action(candidate_id, action, note)
            mapping = {
                "approve_micro_live": "approved_for_micro_live",
                "approve_live_full": "approved_for_live_full",
                "hold": "paper_smoke_running",
                "keep_paper": "paper_smoke_running",
                "reject": "rejected",
            }
            self.registry.transition(candidate_id, mapping[action])
            out = pathlib.Path("runtime/reviews")
            out.mkdir(parents=True, exist_ok=True)
            review_file = out / f"{candidate_id}_{action}.json"
            review_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
            self._send(HTTPStatus.OK, {"result": result, "review_file": str(review_file)})
        except Exception as exc:  # fail-closed: reject request on any validation failure
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified local candidate review interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    print(f"Review UI listening on {url}")
    server.serve_forever()


if __name__ == "__main__":
    main()
