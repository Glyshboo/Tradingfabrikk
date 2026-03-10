# Manual LLM workflow (standard/default)

Dette er den **offisielle standard-workflowen**: botten gjør research/backtesting/incubation selv, eksporterer filer, og brukeren gjør manuell LLM roundtrip via copy/paste.

Kort flyt:
1. Kjør paper/research
2. Botten eksporterer til `runtime/llm_exports/`
3. Bruker copy-paster `paste_to_llm.md` inn i en LLM manuelt
4. Bruker sender LLM-svaret tilbake til Codex for trygg implementasjon


## Automatisk refresh (nytt)

`runtime/llm_exports/` oppdateres nå også automatisk når systemet gjør meningsfulle endringer (research fullført, auto-research, challenger-/candidate-state-endringer), styrt av `exports` i `configs/active.yaml`.

For manuell tvangskjøring kan du fortsatt bruke `apps.export_research_bundle`.

## 1) Generer eksportfiler

Kjør:

```bash
python -m apps.export_research_bundle --config configs/active.yaml
```

Entry-pointen for eksporten ligger i `apps/export_research_bundle.py`.

Dette skriver filer til `runtime/llm_exports/`, inkludert:
- `runtime/llm_exports/paste_to_llm.md`
- `runtime/llm_exports/llm_response_template.md`
- `runtime/llm_exports/research_bundle.json`

## 2) Hva brukeren copy-paster til LLM

Åpne og kopier hele innholdet i:
- `runtime/llm_exports/paste_to_llm.md`

Denne filen inneholder:
- research-kontekst (executive summary + top candidates + failure patterns)
- eksplisitt instruks om fast svarformat
- tydelig skille mellom forslagstyper som er enkle å bruke videre i bot/Codex

## 3) Hva brukeren ber LLM om

Brukeren ber LLM svare i det påkrevde formatet i `paste_to_llm.md`.

Referanse-mal finnes i:
- `runtime/llm_exports/llm_response_template.md`

Viktig: Vi parser ikke svaret automatisk i denne sprinten. Det er fortsatt manuell copy/paste.

## 4) Hvordan tolke svaret

LLM-svaret er delt i seksjoner:

- `config_changes`: forslag som normalt kan gjøres som rene config-endringer.
- `search_space_changes`: forslag som endrer research-space (grenser, parametre, univers).
- `regime_or_selector_changes`: forslag på regime/selector-adferd (ofte kode, men kan også være tuning).
- `new_strategy_ideas`: nye idéer/hypoteser som ofte starter som research-hypoteser.
- `why_this_may_have_edge`: hvorfor forslaget kan ha netto edge etter kostnader.
- `how_to_validate`: hvordan vi verifiserer med backtest + OOS + paper.
- `requires_code`: eksplisitt markering av hva som krever kode.

## 5) Hvordan sende svaret videre til Codex

Når LLM har svart:

1. Kopier hele LLM-svaret.
2. Lim inn i ny Codex-prompt.
3. Be Codex gjøre én av disse:
   - implementere kun `config_changes`
   - oppdatere kun `search_space_changes`
   - lage konkret kodeoppgave for `requires_code=true`
4. Be om liten, trygg diff og tester for hver endring.

Praktisk prompt til Codex kan være:

```text
Her er strukturert LLM-svar. Implementer kun config-only forslag først.
Ignorer alt som krever kode i denne runden.
Legg ved tester og vis hvilke filer som ble endret.
```

## 6) Forskjell på forslagstyper

### Config-only forslag
- Endrer typisk YAML/JSON-verdier.
- Krever normalt ikke ny Python-logikk.
- Lav friksjon og rask validering.

### Search-space-only forslag
- Endrer hvilke kombinasjoner/områder research utforsker.
- Kan ofte gjøres uten ny strategi-kode.
- Nyttig for å styre optimizer mot mer robuste kandidater.

### Code-level forslag
- Krever endringer i strategi-, regime- eller selector-logikk.
- Skal håndteres som egne kodeoppgaver med tester.
- Må holdes fail-closed og ikke svekke live-stabilitet.

## 7) Begrensning i denne sprinten

- Ingen LLM-API integrasjon.
- Ingen automatisk parsing/import av LLM-svar.
- Workflowen er bevisst enkel: copy/paste + strukturert format + manuell vurdering.

## Legacy/optional intern LLM-API

Intern LLM-API research finnes fortsatt for kompatibilitet, men er **ikke standard drift** og er deaktivert som default i `configs/active.yaml` (`llm_research.enabled: false`, `auto_research.llm.enabled: false`).

Hvis du likevel aktiverer den, skal output fortsatt behandles som review-gated forslag (ingen auto-live deploy).
