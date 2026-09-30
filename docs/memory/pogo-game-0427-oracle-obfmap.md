---
name: pogo-game-0427-oracle-obfmap
description: "HISTORICAL (2026-09-08): the game was 0.427.0 -- it is 0.429.1 as of 2026-09-20 and Pokemod is 13.3.3. the il2cpp oracle dump IS 0.427.0; Pokemod's September agent embeds per-version obfuscation maps and its resolver is obfuscated->friendly applied per class from the live member list. Extracted maps + multimap live in pogo_extract/system/analysis/pokemod/fresh_20260908/."
metadata: 
  node_type: memory
  type: project
  originSessionId: 565701b0-1a11-42dd-894a-3bb423b9a491
  modified: 2026-09-09T01:03:55.862Z
---

> **VERIFIED STALE 2026-09-20.** The game is now **0.429.1** live (`dumpsys package` on the phone) and the
> installed Pokemod is **13.3.3**, running fine on it -- so Pokemod ships its own newer map and updated itself.
> Everything below is the 2026-09-08 investigation and still describes HOW the resolver works; the version
> numbers and the `fresh_20260908/` extraction are a snapshot of the 0.425.1/0.427.0 era, not today.
> The oracle `il2cpp_meta.jsonl.gz` is two versions behind -- reflect for offsets, never hardcode from it.

Verified 2026-09-08 21:0x via `dumpsys package com.nianticlabs.pokemongo`: **versionName=0.427.0, versionCode=2026082702** (built 2026-08-27). Every "game 0.425.1" written earlier in this session was stale: the game had already auto-updated. The oracle `system/analysis/clone/il2cpp_meta.jsonl.gz` (dumped 2026-09-06) matches Pokemod's **0.427.0** map exactly (`bfza`->RocketHideoutMapGUIController, `bgwj`->MapPlaceDecoratorService), so the oracle IS 0.427.0. 319 stale citations across 79 clone files were bulk-corrected on 2026-09-08; the 23 remaining `0.425.1` mentions are Pokemod's own version-list literals (`'0.425.1,0.427.0'`, `Eu={"0.425.1":hG,"0.427.0":gG}`) and are correct as quotes.

**Pokemod's obfuscation maps are IN the agent bundle** (September build `agent_game_20260908.js`): `var Eu={"0.425.1":hG,"0.427.0":gG}` at byte 2,276,780; hG = `Wde` at 2,267,072 (217 pairs), gG = `Xde` at 2,271,938 (216 pairs). Selected by `pG(version)` ("trySetObfuscationMap") which toasts + memcpy-NOPs + throws on an unsupported version. Extracted verbatim to `fresh_20260908/obfuscation_maps_sept.json` and as friendly->[tokens] per version in `obfuscation_multimap_sept.json`.

**Resolver semantics (class `Mr`, stamped "ObfuscationMap", `xi` alias, at ~892,000):** `set(map)` fills `obf_to_lex: Map<obfuscated, friendly>`. `getUnObfuscated(name)` returns `obf_to_lex.get(name)` if present, else tokenises on `<>[],/+ .`*&` and de-obfuscates each token. Direction is OBFUSCATED -> FRIENDLY, applied when Dittolib builds a class wrapper from the LIVE member list. So one friendly name can have several tokens (20 of 167 friendly names do on 0.427.0, e.g. `HandleTargetChanged` -> `xdk` AND `xgp`); there is no ambiguity because each class only carries the token that exists on it (`PgpActivityMonitor.xdk`, argc=2; `xgp` is PgpMapMarkerGuiController's). The clone core's `methodOf(klass, name, argc)` must mirror this: literal name first, else any live method whose de-obfuscated name equals `name` (argc-filtered). That single change resolves every "obfuscated on this build" gap the modules disclosed (EnhancedRadar pins, InstantSpin ckkl.., PgpActivityMonitor.HandleTargetChanged).

**Why:** Dittolib is Pokemod's il2cpp bridge; copying Pokemod exactly means copying its resolver, not re-deriving names per module. The "0.425.1" drift cost a whole pass of headers being labelled with the wrong build.

**How to apply:** read the live version with `dumpsys package ... | grep versionName` before citing any build; cite the oracle as 0.427.0; use `obfuscation_multimap_sept.json["0.427.0"]` for friendly->token lookups; when the game updates past 0.427.0, Pokemod's map for the new version must be re-extracted from a fresh in-memory agent (see [[pokemod-launch-path]] for the scan) before any obfuscated target is trusted.

Related: [[pogo-clone-crash-classes]], [[pokemod-launch-path]], [[user-phone-setup]].

**Resolver now IMPLEMENTED in the clone (2026-09-09):** `pogo_clone/agent/A_Obfuscation.js` carries Pokemod's `ObfuscationMap` class verbatim plus BOTH maps they ship (217 + 216 pairs, generated from the extracted JSON) and REBINDS the core's `methodOf` -- literal name first, then on a miss walk the class's live methods and take the one whose `getUnObfuscated(raw)` matches. That closes the "obfuscated on this build" gap every module had documented. It also adds `fieldOffsetOf`, `enumValues` (enum literals read LIVE, never assumed), and **`findClassQ`** for qualified `"Namespace.Outer/Nested"` lookup -- the core's `findClass` matches the SIMPLE name only and first-hit-wins, so nested types (`PokemonInventoryGuiService/Data`) and ambiguous ones (`Object`, `Data`, `Image`) could never resolve right; use `findClassQ` for anything nested or namespace-ambiguous. Deviation: an unknown game version logs and falls back to literal names instead of Pokemod's memcpy-NOP + toast-and-exit + throw.
