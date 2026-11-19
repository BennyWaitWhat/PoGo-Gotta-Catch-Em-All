# Request: the catcher's failed-attach loop is what crashes the game

**Status: OPEN.** **From** Pokemon Inventory · **to** AutoCatcher (owner of `AutoCatcher/`) · found 2026-11-15 while
observing a cull for Benny ("Observe and improve and fix"). Read-only findings; nothing on the phone was changed. Any
deploy to the phone needs Benny's `go`.

## What the phone shows
- `/data/tombstones` holds 32 crash records from 11-08 14:06 to 11-15 00:10. **26 of them are the same crash**: thread
  `gdbus`, SIGSEGV, abort message `libsoup ... soup-server-connection.c:716: could not get remote address: Transport
  endpoint is not connected` (the Frida gadget's listen server dying on a connection that was already hung up). Process
  uptime 341 s to 9027 s. No pass from the PC was running in the two traced below (the other 24 were not traced).
- The catcher log (`~/pogo/system/analysis/pokemod/catch_loop.log`) for the two I traced:
  - **11-14 23:11:30** (tombstone_16, game pid 21242, up 2676 s). 22:27:02 catcher start; 22:27:07 / :11 / :20
    `libil2cpp.so not loaded in the attached process (pid 21242)`; 22:28:47 and 22:31:41 `timeout was reached`; then
    `SUPERVISOR catcher silent 2xx s -> restarting it` + `catcher exited (rc=137)` about every 4.5 minutes (22:40, 22:48,
    22:53, 22:57, 23:02, 23:07); last `catcher start` 23:07:39; the game died 23:11:30.
  - **11-14 04:39:14** (tombstone_15, up 2972 s). 03:51-04:07 `timeout was reached` every ~90 s; 04:13-04:38 the same
    supervisor restarts (rc=137) every ~4.5 minutes; `catcher start` 04:38:46; the game died 28 s later.
- In both, the catcher never attached to that game process: 45 minutes of "catcher on, nothing caught", ended by the crash.

So the trigger is a client on the phone that connects to the gadget and is cut off mid-handshake: the attach that times
out, and above all the supervisor's `kill -9` of a catcher stuck in its attach (`end()` in `run_catch.sh`, rc=137). This is
the mechanism suspected since 10-29 (`docs/memory/pogo-crash-kinds-2026-10-29.md`, kind 1), now with two traced cases.

## Asked of AutoCatcher
1. **First attach only once the game can take it.** `PoGo started 8s ago -- waiting 4s before attaching` attaches at 12 s
   and gets `libil2cpp.so not loaded` three times; after that every attach to that process times out. Wait until
   `libil2cpp.so` is in `/proc/<pid>/maps` (read through `su`, like the LISTEN probe) before the first connect.
2. **Never cut an attach off mid-handshake.** Give the catcher its own attach timeout that ends the Frida session
   cleanly, and make the supervisor wait for that instead of `kill -9` after 3 s.
3. **Back off on a game process that refuses.** After 3 failed attaches to the same pid, stop connecting to that pid, say
   so in the app's status line ("cannot attach to this game start"), and try again only when the pid changes. Never
   restart the game (rule 3).
4. **Dates in `catch_loop.log`.** Its lines carry a time only, so a crash cannot be matched to a day without the file order.
5. **Minor.** While the game restarts, Termux python calls `su` about once a second (11-15 00:10-00:13: Magisk
   `stat failed: ENOENT` traces and toast-quota spam). One root shell, or a slower poll.

## Not asked (recorded)
- 11-15 00:10:47: `gdbus` SIGSEGV SEGV_ACCERR 32 ms after ZygiskFrida logged `Remapped` for `libgadget.so`, process up 5 s
  (tombstone_17, no abort message). Once in 32 records; looks like a race in ZygiskFrida's remap, not ours.
- A `SIGNALED` / status 9 exit followed by a new game process is Pokemod's own restart (`HALService`: "Attempting to kill
  game and injector blocking"), not a crash. `tools/cull_now.sh` now labels it so.

## 2026-11-19: two more of the same, and the game was not even on screen
Benny asked "ok" to "find what keeps connecting to the gadget and crashing the game (read-only)". Still read-only: nothing on
the phone was changed or restarted.
- **02:52:32** (tombstone_31, game pid 6692) and **10:54:24** (tombstone_00, pid 13283): thread `gdbus`, SIGSEGV fault 0x78,
  the same libsoup abort `soup-server-connection.c:716: could not get remote address: Transport endpoint is not connected`.
  No cull ran between 01:02 and 12:15.
- `catch_loop.log`: 02:32:57, 02:37:38, 02:42:18, 02:46:59, 02:51:39 `SUPERVISOR catcher silent 24x s -> restarting it`, each
  followed ~34 s later by `catcher exited (rc=137)` (SIGTERM did not end it in 3 s); last `catcher start` 02:52:17, the game
  died 15 s later. 10:51:43 `silent 256s`, 10:52:51 rc=137, 10:52:55 start, the game died 89 s later.
- **The game was in the background both times.** `dumpsys usagestats` has no `com.nianticlabs.pokemongo` ACTIVITY_RESUMED
  after 01:40:48 (Benny closed it at 01:40:49; it was started again in the background). The night: screen off. The morning:
  WhatsApp, Instagram, LinkedIn; the screen went off at 10:54:22, 2 s before the crash. Android's cached-app freezer works
  on the game there: exit-info 02:16:48 `FREEZER BINDER ASYNC FULL` (pid 16327).
- My reading (NOT proven): in the background the game is frozen, so the gadget answers nothing; the catcher's call hangs,
  its log goes silent, the supervisor kills it (-9) and starts another, whose connect also waits unanswered. When Android
  thaws the game, the gadget accepts a connection whose client is already gone, `getpeername` fails, and libsoup aborts the
  game. The same "connect-and-hang-up" crash as the old port probe (#60), made by the catcher itself.

### Asked (new, first)
6. **Run the catcher only while the game is on screen**: `dumpsys activity activities | grep -m1 topResumedActivity` names
   `com.nianticlabs.pokemongo` (the cull attaches only then since #158). When the game leaves the screen, end the catcher
   with SIGTERM while it still answers, and count the silence that follows as idle, not a hang. Then the catcher never sits
   in a call to a frozen game, and the supervisor's -9 (ask 2) has nothing left to cut off.
