# TROUBLESHOOTING

## Rate limits
- Symptomer: ordre/cancel blir trege eller feiler sporadisk.
- Tiltak:
  - Reduser polling, behold WS-first dataflyt.
  - Unngå unødige retries i tett loop.
  - Verifiser at research kjører separat fra live/paper.

## WS drops / user stream død
- Symptomer: `state=SAFE_PAUSE`, `ws_status.user_stream_alive=false` eller stale market age.
- Forventet adferd: fail-closed (pause + reduce-only), ingen nye risikofylte entries.
- Tiltak:
  - Restart paper/live runner når stream er stabil.
  - Hvis logger viser `market_stream_drop` med `[Errno 101] Network is unreachable` og `proxy_env_present=true`: verifiser `HTTP_PROXY`/`HTTPS_PROXY` og nettverkstilgang til Binance WS-endepunkt før restart.
  - Valider status med `scripts\05_status.bat`.

## Rask smoke-test (paper + research)
- Bruk disse kommandoene for å verifisere at appene starter uten å gå live:
  - `python -m apps.paper_runner --config configs/active.yaml`
  - `python -m apps.research_runner --config configs/active.yaml --space configs/research_space.yaml`
- For paper-mode er `SAFE_PAUSE` forventet hvis datastream er utilgjengelig; dette er fail-closed og betyr at systemet ikke tar nye entries.

## Partial fills
- Symptomer: delvis fylt ordre gir mismatch i forventet posisjon.
- Tiltak:
  - Verifiser oppdatert account/position state fra user stream.
  - Bruk reduce-only ved nedskalering/lukking.
  - Ved usikker state: hold pause til konsistent account state er bekreftet.

## Kill switch trigger
- Symptomer: decisions blokkeres med `kill_switch_triggered`.
- Tiltak:
  - Ikke restart blindt. Bekreft faktisk daglig PnL og eksponering.
  - Reduser risiko-parametre før ny oppstart.
  - Kjør self-check før videre drift.
