# Tradingfabrikk MVP1

Modulær crypto futures trading-plattform (Binance Futures cross margin) med **paper/live/research** i separate apps, fail-closed og risk-first.

## Struktur
- `apps/` kjørbare entrypoints (`live_runner.py`, `paper_runner.py`, `research_runner.py`, `status_tool.py`)
- `packages/` gjenbrukbar logikk (data, risk, strategies, selector, execution, telemetry, backtest/research)
- `configs/active.yaml` primær konfig
- `strategy_ideas/` seed library med machine-friendly strategi-idéer (ikke auto-live)
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
Candidate-pipeline lagres i `runtime/candidates_registry.json` med persisted state machine:
`idea_proposed -> config_generated -> backtest_pass -> (paper_smoke_running/paper_smoke_pass) -> ready_for_review -> approved_for_micro_live -> micro_live_* -> approved_for_live_full`.

Status:
```bash
python -m apps.status_tool --status-file runtime/status.json
```

Unified web review panel (all candidates in one interface):
```bat
scripts\09_review_candidates.bat
```

This opens a local review UI (default `http://127.0.0.1:8787`) where you can approve to micro-live/full-live (when allowed), reject, hold, and inspect candidate details/artifacts.

LLM research (provider-agnostic, med fallback + budsjett):
```bat
scripts\08_llm_research.bat
```


Strategy idea library status:
```bash
python -m apps.strategy_ideas_status --ideas-dir strategy_ideas
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
- `scripts/09_review_candidates.bat`
- `scripts/10_strategy_ideas_status.bat`
- `scripts/99_stop_all.bat`

## Runbooks
- `LIVE_CHECKLIST.md`
- `TROUBLESHOOTING.md`

## Recovery, review and LLM research updates

- Master engine now persists runtime state (`runtime/engine_state.json`) and data state (`runtime/data_state.json`) and starts in `recovering` mode.
- Engine pause/resume states are: `running`, `soft_paused`, `recovering`, `auto_resumed`, `hard_paused`.
- On restart, engine registers a new session, computes downtime, backfills missing 1h/4h candles, restores risk/position state, then enters auto-resume.
- Weekly risk guardrails are enabled with `risk.max_weekly_loss` and `risk.max_drawdown_pct`.
- Unified review entrypoint: `python -m apps.review_runner --action list`.
- Review actions: `approve_micro_live`, `approve_live_full` (only after micro-live states), `reject`, `hold`, `keep_paper`.
- Review artifacts per candidate are stored in `runtime/review_artifacts/<candidate_id>/` (`summary.md`, `metrics.json`, `config_patch.yaml`, `risk_notes.md`, `provenance.json`, `validation_report.json`).
- LLM research tooling: `python -m apps.llm_research_runner --prompt "..."` with provider-agnostic config (`llm_research.provider`, `llm_research.fallback_provider`, aliases: `codex/openai`, `claude/anthropic`).
- LLM output never deploys live automatically; it only creates review-bound artifacts.

## New conservative architecture wiring

- **Micro-live is now a real runtime mode**, not just labels: approved candidates are tracked as active in engine status, enforced with tighter caps (`micro_live.max_total_exposure_notional`), lower sizing (`micro_live.risk_multiplier`), optional one-symbol scope, and pause/resume/recovery transitions across restarts.
- **Paper-smoke is now executable** via a lightweight worker that consumes `paper_smoke_running` candidates and transitions to `paper_smoke_pass` or `validation_failed` from actual short historical smoke results.
- **`hold` and `keep_paper` now have behavior**: `hold` sets a temporary hold window before smoke evaluation; `keep_paper` keeps candidates in paper-smoke track without silent promotion.
- **Backtesting is strategy-aware** for `TrendCore` and `RangeMR` using real candle OHLC simulation with walk-forward/OOS preserved.
- **LLM output is normalized to structured schema** (`summary`, `diagnosis`, `proposed_actions`, `config_patch`, `search_space_patch`, `confidence`, `warnings`) across providers and fail-closed on weak/unavailable output.
- **LLM budgets are enforced and persisted** (`max_calls_per_day`, `max_calls_per_week`) with usage history in `runtime/llm_budget.json`; budget status is included in artifacts/status.
- **State rehydration finished for practical runtime history**: symbol profiles, llm review history, strategy performance history, and paper/live trade histories are persisted/restored.
- **Optional conservative symbol scheduler** added (`scheduler.enabled`) with simple hot/cold ordering and disabled by default.
- **Strategy idea seed library wired end-to-end**: `strategy_ideas/*.json` brukes i bootstrap research/LLM bundle, mappes mot implementerte plugins (`TrendCore`, `RangeMR`) og markerer ikke-implementerte idéer som strict-track kandidater.


## Strategy idea library (seed, non-live)

- `strategy_ideas/manifest.json` is the index used for deterministic enumeration/integrity checks.
- `strategy_ideas/idea_*.json` entries are **research inputs**, not live strategies.
- `implementation_status` distinguishes `idea_only`, `partially_implemented`, `implemented_plugin`, and `deprecated`.
- Conservative mapping is explicit through `mapped_plugin` (currently only `TrendCore` and `RangeMR` when actually implemented).
- Research and LLM bundle builders consume this metadata for:
  - symbol/regime fit suggestions
  - parameter tuning priorities
  - implementation prioritization (`priority_hint`)
  - strict-track routing when code/plugin work is required.
- Promotion path remains fail-closed and manual: idea -> research -> deterministic validation -> review -> explicit approval -> optional micro-live/live.
