---
name: project-pogo-extract
description: "What the pogo_extract project is — Frida/IL2CPP bag extraction into pokemon.db, the cull, and the server-tag system."
metadata: 
  node_type: memory
  type: project
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

`pogo_extract` (in `C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract`) is a Pokémon GO memory-extraction toolkit. It uses **Frida + IL2CPP** against the running PoGo app (`com.nianticlabs.pokemongo`) on the rooted Pixel 9 Pro (see [[user-phone-setup]], [[wireless-adb-via-tailscale]]) to walk the in-memory Pokémon bag and reconcile it into a local SQLite DB, `pokemon.db`.

The **canonical pipeline is `pogo_pipeline.py` + `pogo_il2cpp.py`** — one Frida attach, one bag walk, reused cached singletons across every step. Always reuse and extend these rather than writing one-offs (see [[feedback-pogo-session-conduct]]). The pipeline order is load-bearing: attach → cache singletons (PokemonBagImpl, TaggingRpcService, PokedexImpl via the liveness API) → walk bag → reconcile DB (insert new UIDs, refresh `fresh_*` + size, mark `in_bag`) → refresh server tags → read dex hundos → compute ranks + legacy (fill NULLs) → cull_v9 (advisory) → sanity check → keep_policy + build_tagsets → detach → summary → preflight_transfer → audit_tags. Flags: `--dry-run` = skip `refresh_tag_bindings` only. No tag-write flag exists; the only route to the pile is keep_policy → build_tagsets → preflight_transfer → `prune_tags --atomic` (`full_audit.py`).

The **cull**: `keep_policy.py` decides keep/transfer (`policy_reasons.json` + `6_Transfer.txt`/`Transfer.txt`); cull_v9 only fills an advisory column. `references.py` holds the untouchable-category ID sets (legendary, mythical, ultra-beast, paradox, mega, primal, gigantamax, adventure-effect). Note two known accuracy caveats in `references.py`: its `LEGACY_MOVE_IDS` over-matches (use `detect_legacy.py`, which checks gamemaster `eliteMoves`/movepool, as the authority), and the legacy keep-rule is intentionally over-protective (conservative, harmless). Evolution reachability and caught-species come from `pvpoke_gamemaster.json` + live `PokedexImpl`.

The **server-tag system**: the user maintains server-side tags (the managed vocabulary in `granular_tags` — see [[pogo-tag-vocabulary-2026-09-09]]). These DRIFT and must never be trusted as inventory truth — query the DB by rule instead (see [[pogo-source-of-truth-db-rules]]). `audit_tags.py` compares each tag to its rule (rule−tag = adds, tag−rule = surplus).

Hard constraints for this project: never cull/transfer on incomplete data (see [[pogo-data-completeness-before-destructive-actions]]); treat server state as authoritative (see [[pogo-server-authority]]); build self-healing into Frida drivers (see [[pogo-frida-stability]]).
