# Tradingfabrikk MVP1

Modulær crypto futures trading-plattform (Binance Futures cross margin) med **paper/live/research** i separate apps, fail-closed og risk-first.

## Struktur
- `apps/` kjørbare entrypoints (`live_runner.py`, `paper_runner.py`, `research_runner.py`, `status_tool.py`)
- `packages/` gjenbrukbar logikk (data, risk, strategies, selector, execution, telemetry, backtest/research)
- `configs/active.yaml` primær konfig
- `scripts/*.bat` start/stop/status for Windows

## Install
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Kjøring
### Quickstart (Paper)
Paper er default/safest (`configs/active.yaml` har `mode: paper`):
```bash
python -m apps.paper_runner --config configs/active.yaml
```

Windows:
```bat
scripts\02_paper.bat
```

Sjekk status (mode, symbols, open positions, last decision, ws status, account sync health, regime per symbol, risk caps):
```bat
scripts\05_status.bat
```

### Going Live (Safe)
Live krever eksplisitt `mode: live` + egne API keys i miljø. `live_runner` nekter oppstart hvis config ikke er live.

Kjør live:
```bash
python -m apps.live_runner --config configs/active.yaml
```

Windows:
```bat
scripts\01_live.bat
```

Før live: følg `LIVE_CHECKLIST.md`.

Research/backtest (egen prosess):
```bash
python -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml
```

Research/backtest henter nå Binance historical klines og cacher automatisk i `runtime/data_cache/`.
Hvis Binance-data ikke er tilgjengelig, stopper research/backtest for den symbol/regime-bøtten (fail-closed, ingen syntetisk fallback).
Candidate-pipeline lagres i `runtime/candidates_registry.json` med states:
`candidate -> backtest_pass -> paper_pass -> ready_for_review -> live_approved`.

Status:
```bash
python -m apps.status_tool --status-file runtime/status.json
```

Candidate status:
```bash
python -m apps.candidate_status_tool --registry runtime/candidates_registry.json
```

Candidate paper evaluation update (manuell, ingen auto-live):
```bash
python -m apps.candidate_status_tool --registry runtime/candidates_registry.json --paper-eval-id <candidate_id> --paper-eval-passed true --paper-eval-pnl 120.5 --paper-eval-max-dd 15.2 --paper-eval-notes "stable"
```

Guardrail self-check (returnerer exit code 1 hvis en guardrail-check feiler):
```bash
python -m apps.self_check_runner --config configs/active.yaml
```

## Sikkerhetsnoter
- Fail-closed: hvis datafeed/account-state er usikker pauser engine automatisk.
- Trading decisions krever aktiv risk engine + decision logging.
- `panic flatten` er tilgjengelig via engine API og brukes av kill-switch.
- Paper er default. Sett live bevisst i config + miljøvariabler.

## Hva du typisk endrer i `configs/active.yaml`
- `symbols`
- `risk` caps/terskler
- `strategy_profiles` (hvilken configvariant brukes for symbol/regime)
- `selector.base_edge`

## Scripts
- `scripts/01_live.bat`
- `scripts/02_paper.bat`
- `scripts/03_research.bat`
- `scripts/04_all.bat`
- `scripts/05_status.bat`
- `scripts/06_self_check.bat`
- `scripts/07_candidate_status.bat`
- `scripts/99_stop_all.bat`

## Runbooks
- `LIVE_CHECKLIST.md`
- `TROUBLESHOOTING.md`
