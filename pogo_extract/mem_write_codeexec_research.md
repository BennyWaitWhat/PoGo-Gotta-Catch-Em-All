# `/proc/PID/mem`-only Code Injection into PoGo (No ptrace)

**Date:** 2026-05-08. **PID:** 16362. **Kernel:** 6.1.145-android14.

## Verdict

**YES - empirically demonstrated.** Kernel `mem_write` (`mem_rw -> access_remote_vm` with `FOLL_FORCE | FOLL_WRITE`) bypasses VMA write-protection on `r-xp` text and on ARM64 calls `flush_ptrace_access`, invalidating I-cache. Root passes `mm_access(PTRACE_MODE_ATTACH_FSCREDS)` via `CAP_SYS_PTRACE` without invoking `ptrace(2)`. libconceal hooks `ptrace` only - not `openat` of /proc files - so we go straight through.

## Empirical proofs (live, PID 16362)

1. `exec 3<>/proc/16362/mem` -> OK as root.
2. Read libnotmain `r-xp` @ `0x7564231000` -> `7f 45 4c 46 02 01 01 00`.
3. **Wrote `cc cc cc cc` to that address - succeeded; readback confirmed; PoGo kept running; restored cleanly.** (Load-bearing test.)
4. Anonymous-heap RW at `0x7566a74000`: trivial.
5. File-backed `r-xs` write -> `I/O error` (kernel honors file write perm for shared mappings); workaround: write paired `rw-s` view at same offset.

## Memory map (abridged)

```
7564231000-7564888000 r-xp  libnotmain.so (~6.4MB IL2CPP native)
7564898000-75651ac000 rw-p  libnotmain.so (data+bss)
54877000-58877000     r--s/r-xs  /memfd:jit-cache (ART JIT, NOT IL2CPP)
7606627000-766289e000 rw-s  /memfd:jit-cache (writable mirror)
```

PoGo's IL2CPP-translated game code lives entirely in `libnotmain.so` text. **No IL2CPP JIT exists** - the only JIT is ART's, for Java/Kotlin.

## Vector ranking

| Vector | Verdict |
|---|---|
| **Direct text patch in libnotmain** | **WIN.** Proven writable; kernel handles I-cache. |
| Vtable hijack | Pointless; IL2CPP MethodInfo ptrs are in rw-p anyway. |
| C# delegate hijack | Pointless given direct text write. |
| Static-field write | Good for data toggles, not call triggering. |
| JIT cache poison | N/A - no IL2CPP JIT. |

## Attack: invoke `PokemonBagImpl.TryReleasePokemon(uid)`

**1. Resolve.** ASLR randomizes libnotmain base per launch:
```sh
BASE=$(adb shell su -c "grep ' r-xp .* libnotmain.so$' /proc/$PID/maps | head -1 | cut -d- -f1")
```
Static offset of `cifd(ReleasePokemonOutProto)` is `0xdb658` (from `nickname_extra_results.json`).

**2. Patch site.** `OpenNicknamePopup` prologue - low-frequency, user-triggered, 4-byte BL fits. Avoids racing per-frame loop on first test.

**3. Trampoline in rodata** (`0x7564888000+`, also FOLL_FORCE-writable), 13 instructions, 52 bytes:
```asm
movz/movk chain x0  ; bag* singleton (4x)
movz/movk chain x1  ; uid (4x)
movz/movk chain x9  ; cifd = BASE + 0xdb658 (4x)
br x9
```

**4. Patch call site:** 4-byte aligned BL write:
```
imm26 = (trampoline - patch_addr) >> 2
encoded = 0x94000000 | (imm26 & 0x03FFFFFF)
pwrite64(mem_fd, &encoded, 4, patch_addr)
```

**5. Cleanup.** After release lands (DB poll), restore original 4 bytes. Trampoline bytes leak harmlessly.

## POC sketch (do NOT execute on user's PoGo)

Session BASE=`0x7564231000`, cifd @ `0x756430cb58`, trampoline @ `0x7564888100`:
```
trampoline:
  movz x0,#<bag_lo16>; movk x0,#...,lsl #16/32/48      ; bag*
  movz x1,#<uid_lo16>; movk x1,#...,lsl #16/32/48      ; uid
  movz x9,#0xcb58; movk x9,#0x430c,lsl #16;
  movk x9,#0x0756,lsl #32; movk x9,#0,lsl #48
  br x9                                                  ; 0xd61f0120
patch @ OpenNicknamePopup_prologue:
  bl trampoline                                          ; 0x94XXXXXX
```
(Generate real movz/movk encodings via keystone at runtime; sketches above are unsafe to paste.)

## Reliability + detection

- **ASLR:** stable per-build offsets; resolve base per session.
- **libconceal:** ptrace-only block; /proc/PID/mem untouched.
- **Niantic checksum:** if libnotmain text scanned periodically, mitigate via short patch window - writer thread patches, waits next tap or one frame (<16ms), unpatches.
- **Crash risk:** 4-byte aligned ARM64 text writes via /proc/PID/mem are safe - kernel I-cache flush is the right primitive; mid-instruction observation impossible.

## Time-to-implement

Resolver+offset translator ~15 min; ARM64 movz/movk/br/bl encoder ~45 min; first wet-test against idempotent target (Debug.Log or static bool toggle) ~2 hr total.

## Bottom line

ptrace block is **not a barrier**. Full RW of PoGo memory including text via root /proc/PID/mem, kernel-managed I-cache invalidation, IL2CPP's all-native-no-JIT model -> in-place text patching of `libnotmain.so` is the clean path. Only real defense is Niantic text checksumming, defeated by short patch windows.
