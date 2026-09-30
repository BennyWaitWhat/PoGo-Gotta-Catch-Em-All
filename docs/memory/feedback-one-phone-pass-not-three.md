---
name: feedback-one-phone-pass-not-three
description: "Back-to-back pipeline passes (a 2,963-mon tag rewrite, then two more attaches while the user was restarting the game) froze PoGo twice on 2026-09-09; batch phone work into ONE pass, wait for attach-safety, and never re-run a failed pass while the game is restarting"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-22T08:47:40.442Z
---

On 2026-09-09 00:03-00:10 I ran full_audit three times in a row: pass 1 rewrote tags on 2,963 mons in 20 RPCs
(its verify tripped on one cache-lagged Transfer add), pass 2 attached while the user was restarting a frozen game,
pass 3 attached again (preflight's live read hung ~160 s on a game that was mid-restart). The user: "The game
froze and I restarted it, now it's frozen again." A tap opened the menu fine three minutes later -- the freezes were
stalls caused by attaching to / writing into a loading game, not a dead process.

**Why (corrected 2026-09-09, see [[pogo-gc-world-freeze-2026-09-09]]):** the freezes were NOT the user's screen
or the attach count -- the helper bag walk stopped the IL2CPP GC world and ran a managed call inside it, which
deadlocks under heap pressure. More passes = more rolls of that die. Retrying a failed pass immediately turns one
stall into three. `wait_ready_to_attach` (`pogo_il2cpp._adb_ready_to_attach`) gates ONLY on libil2cpp.so mapped +
process age >= 45 s. Nothing in pogo_extract checks pool-floyd, and preflight_transfer.py:514's comment claiming a
pool-floyd-free wait is wrong. pool-floyd is Pokemod's injector thread. It lives in the game for the whole Pokemod
session (seen live 2026-09-20 in a 65-min-old PoGo), and the recrawl/cull attaches alongside it routinely, so it is
NOT an attach-safety signal for pogo_extract. It is the Pokemod-is-injected detector for the CLONE (never attach the
clone on top of Pokemod; see [[pogo-clone-crash-classes]]: `ss -xp | grep pokemod-injecto`).

**`full_audit.py` has no help/usage:** it only knows `--audits-only`, `--skip-crawl`, `--no-sync`; ANY other arg
(even `--help`) runs the whole cycle, phone walk included -- that cost an unplanned pass 2026-09-22. Read the
source (`main()`), never probe it with flags.

**How to apply:** one phone pass per user "go"; if it fails, READ the log, let the game settle, and let
wait_ready_to_attach gate any re-attach; a verify that only lags on freshly-added mons is not a failure worth
a second attach -- reconcile later. Big tag rewrites happen once, off-peak, and are announced. Every script that
attaches (preflight's live deployment read included) must call wait_ready_to_attach first.
Related: [[feedback-tell-me-what-to-expect]], [[feedback-no-app-restart-while-playing]], [[pogo-frida-stability]].
