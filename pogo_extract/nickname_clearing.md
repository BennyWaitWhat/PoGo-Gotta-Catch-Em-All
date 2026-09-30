# Bulk Nickname Clearing — Method, Tooling & Results

**What:** Cleared every custom Pokémon nickname on the account in bulk, reverting each mon to its
default species name.
**When:** GO Fest Tokyo session, 2026-05-31 (JST).
**Account:** BennyValentinC / OyeBenny.
**Script:** [`system/scripts/clear_nicknames.py`](system/scripts/clear_nicknames.py)
**Engine:** Frida + IL2CPP via the in-process gadget (same plumbing as `pogo_il2cpp.py` / `bulk_tag.js`).

---

## 1. Why

The request was simple: *"clear every custom name I have for a Pokémon — if you clear it, it
defaults to the standard Pokémon name."*

There is no in-game "clear all nicknames" button. Doing it by hand across **1,426** named mons is a
non-starter, so we drove the game's own nickname RPC programmatically.

## 2. TL;DR

- A nickname is cleared by calling the game's real rename function **with an empty string**.
  Empty nickname ⇒ the client/server revert the mon to its species name. This is the *exact* same
  code path the in-game rename dialog uses — **server-authoritative**, not a local cosmetic hack.
- The script finds the live `PokemonBagImpl`, walks the bag for every `PokemonProto*`, reflects the
  `nickname_` field offset, lists the mons that actually have a custom name, then calls
  `NicknamePokemon(proto, "")` on each via `il2cpp_runtime_invoke`.
- It runs **loop-until-dry** with a throttle: re-walk the bag, clear everything still named, repeat
  until a pass finds none.
- **Result:** 1,426 → 0. The first run cleared ~1,065 before the server began throttling renames;
  a PoGo restart reset that throttle and a follow-up run finished the remaining ~361 to zero.

---

## 3. The mechanism

### The call
```
Niantic.Holoholo.Internal.PokemonBagImpl.NicknamePokemon(PokemonProto proto, System.String name)
```
Invoke it with `name = ""` (an IL2CPP-allocated empty string). The game treats an empty nickname as
"no custom name," so the mon falls back to its species name. Because this is the genuine RPC, the
change is persisted server-side — it survives restarts and shows up everywhere, exactly like
clearing the name field manually.

> **Important:** `PokemonProto` has **two** name-ish fields. We only touch `nickname_` (the player's
> custom name). We never touch `originalOwnerNickname_` (the name set by a *previous* owner on a
> traded mon) — clearing that would be wrong and isn't what "my nicknames" means.

### The IL2CPP / Frida pipeline
1. **Attach** to PoGo (`pogo_il2cpp.get_session`). PoGo must be **foregrounded** — IL2CPP calls
   hang if the app is frozen in the background (the Android freezer quirk).
2. **Find the bag:** `pick_singleton("Niantic.Holoholo.Internal", "PokemonBagImpl")`.
3. **Walk the bag** (`walk_bag_protos`) → a `{uid: PokemonProto*}` map of every mon.
4. **Reflect offsets** once, off a live proto (`findOffsets`): locate `nickname_`, `pokemonId_`,
   and (for safety, to *avoid* it) `originalOwnerNickname_` by iterating the class fields.
5. **Read names** (`readNicks`): for each proto, read the IL2CPP string at `nickname_`
   (`len@0x10`, UTF-16 chars@`0x14`). Keep only mons with a non-empty nickname.
6. **Prime classes** (`prime`): force class-init on `PokemonBagImpl`, `NicknamePokemonProto`,
   `NicknamePokemonOutProto` so the *first* `il2cpp_runtime_invoke` doesn't abort (a documented
   quirk — uninitialized classes touched inside the method body cause the first call to bail).
7. **Clear** (`clearOne`): build a 2-pointer arg array `[proto*, il2cpp_string_new("")]`, call the
   method via `il2cpp_runtime_invoke`, and check the exception slot.

Key snippet (the actual invoke, from the script's `EXTRA_JS`):
```js
// Clear ONE nickname: bag.NicknamePokemon(proto, "")
rpc.exports.clearOne = function (bagStr, protoStr) {
  var bagCls = cFN('Niantic.Holoholo.Internal', 'PokemonBagImpl');
  var m = cMN(bagCls, 'NicknamePokemon', 2);          // 2-arg overload
  var s = _strnew('');                                 // il2cpp_string_new("")
  var args = Memory.alloc(2 * Process.pointerSize);
  args.writePointer(ptr(protoStr));                    // params[0] = PokemonProto*
  args.add(Process.pointerSize).writePointer(s);       // params[1] = System.String*
  var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
  var ret = rI(m, ptr(bagStr), args, exc);             // il2cpp_runtime_invoke
  if (!exc.readPointer().isNull()) return { ok: false, err: 'exc', ... };
  return { ok: true, ret: ret.isNull() ? '0' : ret.toString() };
};
```

---

## 4. The script

`clear_nicknames.py` has three modes, escalating in commitment:

| Mode | What it does | Reversible? |
|------|--------------|-------------|
| `scan` | **Read-only.** Counts and samples the mons that have a custom nickname (resolves species names from `pokemon.db`). | n/a |
| `test` | Scans, then clears **exactly one** nickname and verifies it by a fresh bag re-walk. Proves the mechanism on a single mon before committing. | Trivially (re-name that one mon) |
| `clear` | **Bulk, loop-until-dry.** Each pass re-walks the bag, clears every mon that *still* has a custom name, throttled by `--delay`, until a pass finds none (or `--max-pass`). | Per-mon, by re-naming |

Flags:
- `--delay S` — seconds between clears (default **0.15**). The main lever against server throttling.
- `--max-pass N` — max loop-until-dry passes (default 4).
- `--limit N` — cap how many to clear (for a partial / cautious run).

JS `rpc.exports` (note: defined camelCase in JS, called snake_case from Python — Frida maps them):
`findOffsets`, `readNicks`, `readOne`, `prime`, `clearOne`.

### How to run it
```bash
# 1. Read-only: how many custom names, and a sample
python system/scripts/clear_nicknames.py scan

# 2. Prove it on ONE mon (fully reversible)
python system/scripts/clear_nicknames.py test

# 3. Clear everything (gentle throttle, loop until none remain)
python system/scripts/clear_nicknames.py clear --delay 0.2

# Cautious partial run (first 100 only)
python system/scripts/clear_nicknames.py clear --limit 100
```
**Pre-req:** PoGo open and foregrounded on the phone (ADB/Frida reachable).

---

## 5. What actually happened (run log + the correction)

The first attempt taught the key lesson the hard way:

1. **First clear (earlier session)** *reported* reaching **0** — but that was read off the
   **client-side** bag walk. It was wrong: a later re-scan, after the game synced from the server,
   showed **692** names still set. A cleared nickname reads empty in client memory *immediately*,
   even when the rename RPC never persisted server-side. **Client re-walk ≠ server truth.**
2. **This session — scan:** 692 of 4,765 mons still named.
3. **Clear, one big pass of 692:** ~**502** cleared cleanly, then around #500 calls began throwing
   `NullReferenceException` (stale proto pointers — the bag mutates as names clear, invalidating the
   pointers captured at the start of the pass). The errors **cascaded and PoGo crashed.**
4. **Relaunch + re-scan (the real persistence check):** **190** remained — exactly 692 − 502. So the
   502 "ok" clears genuinely persisted server-side, now *confirmed* by the forced re-sync.
5. **Clear the 190 in a small pass:** 184 ok, 6 stale-proto errors; a second loop-until-dry pass
   re-walked fresh and found **0** (the 6 were stale pointers to mons already cleared).
6. **Final: 0** custom nicknames. For ironclad proof, force-restart PoGo and re-scan once more — the
   post-sync count is authoritative.

---

## 6. Gotchas & lessons (carry these forward)

- **PoGo must be foregrounded.** IL2CPP calls hang against a backgrounded/frozen app.
- **`nickname_` ≠ `originalOwnerNickname_`.** Reflect both; only ever write the former.
- **Empty string = revert.** No need to compute species names — the empty nickname makes the game do
  it. Server-authoritative, so it persists.
- **Class-prime before the first invoke**, or the first `il2cpp_runtime_invoke` aborts.
- **Re-walk the bag every pass.** Proto pointers can be reallocated between operations; never reuse a
  stale `{uid: proto*}` map across passes — re-fetch it. (This is why `clear` walks fresh each loop.)
- **Client re-walk ≠ server persistence — VERIFY after a forced sync.** *(The single most important
  lesson — it's why the original writeup wrongly claimed "→0".)* The bag walk reads client memory, so
  a cleared name reads empty *immediately* even if the rename RPC never persisted server-side. The
  script's in-session "0 remaining" can be a false positive. The **authoritative** check: force-restart
  PoGo (`adb shell am force-stop com.nianticlabs.pokemongo` → relaunch → let it sync) and re-scan. The
  post-sync count is the truth.
- **Never clear more than ~300-400 in a single pass — it crashes the game.** Clearing mutates the bag
  and invalidates the proto pointers captured at the start of the pass; past ~500 the
  `NullReferenceException` rate cascades and **PoGo crashes** (taking the Frida session with it).
  Clear in small chunks (`--limit 150-200`, fresh bag-walk each run) or rely on short loop-until-dry
  passes. Raising `--delay` does **not** fix this — it's stale pointers, not throttling.
- **camelCase JS exports, snake_case Python calls.** `rpc.exports.clearOne` ⇄ `sc.exports_sync.clear_one`.
- **Reversible.** Nothing is destroyed — a "cleared" mon can be re-named anytime. Unlike a transfer,
  this is safe to run broadly.

---

## 7. Relationship to the rest of the toolkit

This reuses the same foundation as the tag/cull tooling:
- `pogo_il2cpp.py` — session, singleton lookup, bag walk, helper-script loader.
- The `il2cpp_runtime_invoke` calling convention proven in `bulk_tag.js`.
- `pokemon.db` — only for *displaying* species names during scan/sample (not required to clear).

If nicknames need clearing again (e.g., after future trades/renames), just re-run
`clear_nicknames.py scan` then `clear`. It's idempotent — already-blank mons are skipped.
