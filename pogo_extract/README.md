# pogo_extract — bag curation

The Pokémon GO bag pipeline: read every Pokémon out of the live game, decide what to keep under
[`LAW.md`](LAW.md), prove the decision, and tag the rest. **It only tags — Benny releases by hand.**
Sessions: the operating manual is [`CLAUDE.md`](CLAUDE.md); this page is the overview.

## One command
```bash
python ../tools/pogo_data.py pull        # the game data lives on the phone
python full_audit.py                     # the whole cull (~1–2 min)
python ../tools/pogo_data.py push --group inventory
```
`full_audit.py --audits-only` runs the 11-audit gate with no phone contact (after a pull). Unknown flags stop it (rc 2).

## The pipeline
| Stage | Entry point | Output |
|---|---|---|
| Game master freshness (monthly) | `system/scripts/refresh_gamemaster.py` | `pvpoke_gamemaster.json` reconciled against the game's own |
| Walk the live bag | `pogo_pipeline.py` + `pogo_il2cpp.py` (Frida/IL2CPP) | `pokemon.db`, candy, items, Pokédex, player state |
| Walk tripwires | `walk_tripwires.py` | STOP (rc 8) on a frozen or impossible read |
| Keep engine | `system/scripts/keep_policy.py` | `policy_reasons.json`, `tagsets/6_Transfer.txt`, `pile_provenance.json` |
| Tag sets | `system/scripts/build_tagsets.py`, `granular_tags.py` | `system/analysis/tagsets/*.txt` |
| **11 audits (hard gate)** | `full_audit.AUDITS` | PASS/FAIL per audit — any FAIL stops the sync |
| Preflight + sync | `system/scripts/preflight_transfer.py` → `prune_tags.py --atomic` | tags on the phone, server answers recorded |
| Report + pages | `cull_report.py`, `gen_artifacts.py`, `gen_bag_pulse.py` | the report, Bag Pulse |

## The 11 audits
8-layer cull · tag membership · evo comb-up · law re-derivation · label law · promises · game master · rank tags ·
tag truth · structural invariants · PvP keeper fixtures. Each re-derives the answer independently; `AUDIT GATE FAILED`
is the gate working — find the cause, never work around it.

## Where the rules live
- [`LAW.md`](LAW.md) — the keep law in words (edit it first for any policy change).
- `keep_config.json` — the numbers (per account; in the phone data store, not git).
- [`CLAUDE.md`](CLAUDE.md) — hard rules, the map of entry points, the offline gate.
- [`RUNBOOK.md`](RUNBOOK.md) — stamp, gate and trap details.

Most other `*.py` files here are one-off research and older iterations kept for reference; the entry points above are
the maintained path.
