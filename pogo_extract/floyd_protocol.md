# Floyd (rebranded Frida) protocol — findings

## TL;DR

- **Pokemod's `pokemod-injector` is `frida-inject` 17.8.2 with all `frida` -> `floyd`
  identifier renames.** It is NOT a server. It runs once: ptrace-attach, load agent,
  run a single .js, exit. There is no persistent socket to connect to.
- **The `/floyd-zymbiote-<32hex>` abstract Unix socket is transient**: it appears
  only during a `Floyd.RoboLauncher` zygote-fork injection, which Pokemod uses
  for spawn-time injection — irrelevant to attaching an already-running PoGo.
- **Building a "Floyd client" is therefore moot for our 858-transfer task.**
  There is no Floyd daemon listening; the renames are purely defensive
  (libconceal pattern-matches on `frida` strings).
- **Vanilla `frida-server 17.9.5` works**, given (a) SELinux Permissive and
  (b) attaching during PoGo's first ptrace-window. Demonstrated end-to-end:
  attached to com.nianticlabs.pokemongo PID 27885, loaded JS, got back
  `{pid: 27885, modules_total: 354, libnotmain_base: 0x755b238000}`.
- libil2cpp is absent — PoGo is native (BoringSSL/C++), not IL2CPP/Unity.
  Hooks must target `libnotmain.so` (iPogo's lib) and `libgame*.so` symbols
  via Module exports / signature scans, not IL2CPP class metadata.

## Renamed identifier table

Five-char `frida` -> `floyd` substitution covers everything wire-side. All
strings keep length, so binary-patching the Python `_frida.pyd` is sufficient
to produce a Floyd-protocol client. Found via `strings pokemod-injector.bin`:

| Vanilla Frida              | Pokemod Floyd               |
| -------------------------- | --------------------------- |
| `frida:rpc`                | `floyd:rpc`                 |
| `re.frida.HostSession17`   | `re.floyd.HostSession17`    |
| `re.frida.AgentSession17`  | `re.floyd.AgentSession17`   |
| `re.frida.AgentSessionProvider17` | `re.floyd.AgentSessionProvider17` |
| `re.frida.AgentController17` | `re.floyd.AgentController17` |
| `re.frida.AgentMessageSink17` | `re.floyd.AgentMessageSink17` |
| `re.frida.BusSession17`    | `re.floyd.BusSession17`     |
| `re.frida.PortalSession17` | `re.floyd.PortalSession17`  |
| `re.frida.ServiceSession17` | `re.floyd.ServiceSession17` |
| `re.frida.AuthenticationService17` | `re.floyd.AuthenticationService17` |
| `re.frida.GadgetSession17` | (not found in injector)     |
| `re.frida.Channel17`       | (not found in injector)     |
| `re.frida.TransportBroker17` | (not found in injector)   |
| `re.frida.Helper`          | `re.floyd.Helper`           |
| `re.frida.Error.*`         | `re.floyd.Error.*` (full set) |
| `/re/frida/HostSession`    | `/re/floyd/HostSession`     |
| `/re/frida/AgentSession`   | `/re/floyd/AgentSession`    |
| `/re/frida/AgentMessageSink` | `/re/floyd/AgentMessageSink` |
| `/re/frida/AuthenticationService` | `/re/floyd/AuthenticationService` |
| `/re/frida/AgentController` | `/re/floyd/AgentController` |
| `/re/frida/PortalSession`  | `/re/floyd/PortalSession`   |
| `/re/frida/Helper`         | `/re/floyd/Helper`          |
| `frida-server`             | `floyd-server`              |
| `frida-helper-{32,64}`     | `floyd-helper-{32,64}`      |
| `frida-agent-{32,64}.so`   | `floyd-agent-{32,64}.so`    |
| `libfrida-agent-raw.so`    | `libfloyd-agent-raw.so`     |
| `frida-android-helper`     | `floyd-android-helper`      |
| `/frida-zymbiote-<hex>`    | `/floyd-zymbiote-<hex>`     |

Three string ranges + 209 occurrences in `_frida.pyd` are all that's needed.
`floyd_client.py patch` performs this in-place, producing `_floyd.pyd`.

## Why the Floyd-client path is dead-end (for our use case)

1. **No daemon.** `pokemod-injector` is `frida-inject` (one-shot), not
   `frida-server`. It accepts `--pid N --script S.js` and exits. Verified:
   running it produces `[INJ] pid=N: inject() entrypoint=floyd_agent_main`
   then `Unexpectedly timed out while waiting for stop` (or completes the
   script and exits). It never opens a listening socket.
2. **`/floyd-zymbiote-` is transient.** That socket only exists for ~ms during
   `Floyd.RoboLauncher.handle_zymbiote_connections` — the zygote-fork
   spawn-injection path (`Floyd.RoboLauncher.prepare_zymbiote_injection`,
   `make_zymbiote_payload`, `inject_zymbiote`). It is NOT a control plane;
   it's how the freshly-forked zymbiote child reports back to the launcher.
3. **No `--listen` flag in pokemod-injector.** `Pokemod Injector version
   17.8.2-97ca929 --help` returns "Unknown option --help" (help suppressed),
   and no `listen-on`/`bind` flag appears in stripped strings. Available
   flags are limited to `--pid`, `--script`, `--enable-development`,
   `--script-runtime qjs|v8`, `--parameters` — exactly the frida-inject set.
4. **Pokemod's IPC is internal.** The Pokemod Android app spawns
   `pokemod-injector` as a child process and must use stdin/stdout or unix-pipe
   IPC — not the DBus/Floyd RPC surface. The renamed `re.floyd.HostSession17`
   strings are present because the same Vala code is compiled in, but the
   `frida-inject` codepath doesn't expose them.

## What works: vanilla frida-server 17.9.5

Already deployed at `/data/local/tmp/frida-server`. Constraints:
- Must run with **SELinux permissive** (`setenforce 0`); enforcing causes
  attach to time out at "waiting for stop" because the helper can't ptrace.
- Must launch via `nohup ... < /dev/null > log 2>&1 &` — a bare `&` from `su -c`
  inherits a controlling tty and dies on shell-detach.
- **Attach window:** PoGo's anti-debug (libconceal embedded in libnotmain.so)
  starts blocking ptrace some seconds into the run. Reliable approach is:
  force-stop, monkey-launch, sleep 5-6s, attach, do all work in one session.
  Subsequent attaches to the same PID time out.
- After each frida session, frida-server's process cache may go stale; if a
  PID isn't visible in `enumerate_processes()`, restart frida-server.

End-to-end POC (executed):
```
$ python floyd_client.py connect 27885 poc_il2cpp.js
[+] using device: Device(id="socket@127.0.0.1:31337", ...)
[+] attached to PID 27885
MSG: {'type': 'send', 'payload': {'pid': 27885, 'modules_total': 354,
       'il2cpp_base': None, 'il2cpp_size': None,
       'libnotmain_base': '0x755b238000', 'libunity_base': None}}
```

## Inject chain for 858-transfer plan

Given the constraint that PoGo's anti-ptrace lets us attach exactly once per
launch, the bulk-transfer/nickname workflow must be a single long-running
script:

1. `am force-stop com.nianticlabs.pokemongo`
2. `setenforce 0` (Magisk; reverts after reboot)
3. start `frida-server -l 127.0.0.1:31337` if not already running
4. `monkey -p com.nianticlabs.pokemongo` to launch fresh
5. sleep 5-6s for PoGo init to settle
6. `frida -H 127.0.0.1:31337 -p $(pidof) -l bulk_ops.js`, where `bulk_ops.js`:
   - resolves `IPokemonBag_ReleasePokemon` and `NicknamePokemon` via signature
     scan against `libnotmain.so` (offsets in
     `proto_offsets_discovered_v2.md`)
   - reads work queue from `cull_plan.csv` over `recv()` channel
   - executes 858 transfers + tag applications inline
   - sends `done` on completion
7. detach session; PoGo continues normally

Do NOT detach and reattach — the second attach will time out.

## Files added by this investigation

- `floyd_client.py` — patcher + connect helper (uses vanilla frida-server)
- `_floyd.pyd` — Floyd-renamed copy of `_frida.pyd` (kept for reference; not
  needed for the bulk-transfer workflow)
- `poc_il2cpp.js` — minimal probe script
- `floyd_protocol.md` — this document

## Open questions / next steps

- If Pokemod's anti-detect at the agent level proves valuable (e.g. it patches
  PoGo's anti-cheat surface in ways vanilla frida-agent doesn't), the path
  forward would be: extract `main_agent` (currently base64-encoded under
  `/data/user/0/com.pokemod.app.public/files/agents/`), reverse it, and load
  it as a frida-agent via `Process.dlopen`. Out of scope here.
- libconceal location/identification: it lives inside `libnotmain.so` (we have
  `libconceal_strings.txt`). A targeted patch of its anti-ptrace check (look
  for a `prctl(PR_SET_DUMPABLE, 0)` or `/proc/self/status` `TracerPid` read)
  would let us reattach freely. Out of scope here.
