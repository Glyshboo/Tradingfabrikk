# LIVE_CHECKLIST

## API key hygiene
- Bruk separat Binance Futures-nøkkel for live.
- Aktiver kun nødvendige permissions (futures trade/read), ingen unødige scopes.
- Rotér nøkkel ved mistanke om lekkasje.
- Hold nøkler i miljøvariabler, aldri i repo.

## Pre-flight
- Bekreft `configs/active.yaml` er bevisst satt til `mode: live` før live-start.
- Kjør `python -m apps.self_check_runner --config configs/active.yaml` og bekreft:
  - `daily_loss_cap.reason = kill_switch_triggered`
  - `max_exposure_cap.reason = max_total_exposure`
  - `panic_flatten.orders[*].reduceOnly = true`
- Kjør paper først med samme configprofil (`scripts\02_paper.bat`) for sanity.

## Micro-risk start
- Start med lav `sizing.base_qty` og begrenset symbols-liste.
- Verifiser at `risk.max_daily_loss` er konservativ.
- Verifiser caps: `max_total_exposure_notional`, `max_open_positions`, `max_leverage`.

## Kill switch / daily loss cap
- Bekreft at kill-switch gir safe pause + reduce-only.
- Ved trigger: stopp nye entries, sjekk account state før eventuell restart.

## Panic flatten test
- Kjør panic flatten i paper via self-check før live-dag.
- Bekreft at flatten sender reduce-only for alle åpne posisjoner.

## Operasjonell drift
- Følg status via `scripts\05_status.bat`.
- Verifiser `account_sync_health.last_event_age_sec` og `current_regime` før du tillater nye entries.
- Hvis ws/user stream er ustabil: hold system i pause (fail-closed) til feed er stabil.
- Bruk `scripts\99_stop_all.bat` for rask stopp av runner-vinduer.
