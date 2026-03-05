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
Paper (default/safest):
```bash
python -m apps.paper_runner --config configs/active.yaml
```

Live (krever eksplisitt `mode: live`, API keys i miljø):
```bash
python -m apps.live_runner --config configs/active.yaml
```

Research/backtest (egen prosess):
```bash
python -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml
```

Status:
```bash
python -m apps.status_tool --status-file runtime/status.json
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

## Troubleshooting
- Hvis WS dør: engine går til `SAFE_PAUSE`. Start på nytt når feed er stabil.
- Hvis kill-switch trigges: reduser risiko i config og verifiser PnL/account state før restart.
- Hvis status mangler: sjekk `runtime/` write-permissions.
