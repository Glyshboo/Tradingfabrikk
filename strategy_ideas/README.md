# Strategy Idea Library

This folder contains **research seed ideas**, not automatically tradable live strategies.

Lifecycle (fail-closed):

`idea -> research -> deterministic validation -> review -> explicit approval -> paper/micro-live/live (where allowed)`

## Files
- `manifest.json`: machine-readable index for enumeration and integrity checks.
- `idea_*.json`: individual strategy idea specs used by research and LLM context building.

## Safety
- `implementation_status=idea_only` means no plugin implementation exists.
- `strict_track_required=true` means any promotion requires strict/manual review and usually code changes.
- No entry in this folder can auto-promote to live.
