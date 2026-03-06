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
Status-output inkluderer også `score_components` per kandidat for forklarbar seleksjon og et sammendrag av kandidat-registerets state machine.

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
Hvis historiske Binance-data ikke er tilgjengelig returneres tom serie (ingen syntetisk fallback), slik at research/backtest feiler lukket.
Candidate-pipeline lagres i `runtime/candidates_registry.json` med states:
`candidate -> backtest_pass -> paper_pass -> ready_for_review -> live_approved`.

Status:
```bash
python -m apps.status_tool --status-file runtime/status.json
```

Guardrail self-check (returnerer exit code 1 hvis en guardrail-check feiler):
```bash
python -m apps.self_check_runner --config configs/active.yaml
```

## Sikkerhetsnoter
- Fail-closed: hvis datafeed/account-state er usikker pauser engine automatisk.
- Live-path oppdaterer account/position konservativt fra user stream; kun paper-path simulerer fills lokalt.
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
- `scripts/99_stop_all.bat`

## Runbooks
- `LIVE_CHECKLIST.md`
- `TROUBLESHOOTING.md`

## Recovery, review and LLM research updates

- Master engine now persists runtime state (`runtime/engine_state.json`) and data state (`runtime/data_state.json`) and starts in `recovering` mode.
- Engine pause/resume states are: `running`, `soft_paused`, `recovering`, `auto_resumed`, `hard_paused`.
- On restart, engine registers a new session, computes downtime, backfills missing 1h/4h candles, restores risk/position state, then enters auto-resume.
- Weekly risk guardrails are enabled with `risk.max_weekly_loss` and `risk.max_drawdown_pct`.
- Unified review entrypoint: `python -m apps.review_runner --action list` (approve/reject/hold/micro_live via flags).
- LLM research tooling: `python -m apps.llm_research_runner --prompt "..."` with provider-agnostic config (`llm.provider`, `llm.fallback_provider`).
- LLM output never deploys live automatically; it only creates review-bound artifacts.
