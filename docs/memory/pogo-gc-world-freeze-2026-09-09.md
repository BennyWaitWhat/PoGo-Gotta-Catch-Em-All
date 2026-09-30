---
name: pogo-gc-world-freeze-2026-09-09
description: "THE cause of \"you froze the game\" -- il2cpp_stop_gc_world + a managed call inside the stopped world deadlocks the game (ANR traces show every Unity thread in sigsuspend); bdwgc is NON-moving so the walk never needed the stop; probe = UnityMain wchan sigsuspend >= 3 s; rescue = forceStartWorld / unfreeze_game.py; ApplicationExitInfo + dropbox ANR are the evidence path"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9f2eff52-4f4a-4130-a61e-420ac1dd82ff
  modified: 2026-09-09T04:55:46.043Z
---

**What froze the game (2026-09-08/09, three times).** `pogo_il2cpp._bag_walk_core` called `il2cpp_stop_gc_world`
and then `il2cpp_runtime_invoke(PokemonBagImpl.get_AllPokemon)` INSIDE the stopped world. A managed call that must
allocate under heap pressure (the game sat at 2.9-3.2 GB RSS) triggers a collection, the collection waits for a
world that only our thread can restart, and every Unity thread sits in `sigsuspend` inside libil2cpp until the
user kills the app. Evidence: `dumpsys activity exit-info com.nianticlabs.pokemongo` (reason=6 ANR, "Broadcast
of Intent GeofenceTransition", user request after error) and the dropbox `data_app_anr@*.txt.gz` traces
(`/data/system/dropbox`, root): "UnityMain" native stack `__rt_sigsuspend <- libil2cpp`, Java "main" idle in
epoll, 935 binder transactions pending. The recrawl's `pipelineWalk` never stopped the world and never froze;
every path that used the helper walk (prune, preflight live read, verify, retire) could.

**Why the stop was there:** a 2026-09-02 comment claimed IL2CPP has a MOVING collector. It does not -- IL2CPP
uses bdwgc, which never relocates objects. Partial walks came from concurrent list mutation, which the
declared/walked/truncated check + re-walk already handles.

**Fix (2026-09-09):** the helper walk no longer stops the world; the liveness singleton scan (the one
remaining stop) runs once per game pid (`system/analysis/singleton_cache.json`, validated by a klass-pointer read
via `checkInstance`); after every scan `pg.rescue_frozen_world()` probes `/proc/<pid>/task/*/wchan` for UnityMain
in `sigsuspend` across 3 samples 1 s apart and calls the `forceStartWorld` export if so; `unfreeze_game.py`
does the same by hand (`--probe` never attaches). A real GC pause is milliseconds, so >= 3 s in sigsuspend is
always an abandoned stop.

**How to apply:** never run managed code (runtime_invoke, allocation) inside a stopped world; prefer no stop at
all plus verify-and-retry; after any world-stopping call, probe. When the user says "frozen", read exit-info and
the dropbox ANR before theorising -- "You should know this." Also: DeleteTag was not the culprit (15 shells
deleted fine), and neither was the user's screen (they were idle on the map).
Related: [[feedback-one-phone-pass-not-three]], [[pogo-frida-stability]], [[pogo-clone-crash-classes]], [[feedback-no-app-restart-while-playing]].

**2026-09-24 correction -- LIVENESS is not the bag walk.** Unity's liveness walk marks objects by setting the low bit of
`obj->klass` and clears it in finalize, so `find_singleton` MUST keep its world stop (without it a network thread read a
marked object and PoGo SIGSEGV'd on a pointer one byte off). The freeze risk is a stopped world waiting on a Frida JS
lock: never run liveness while another script of the SAME gadget session can be mid-call on that lock (the catcher's
pump, a pending RPC). Culls pause the catcher first via `/data/local/tmp/pogo_pause`. See [[pogo-on-phone-catcher]].
