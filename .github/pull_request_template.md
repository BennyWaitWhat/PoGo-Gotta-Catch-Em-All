## What and why
<!-- One or two sentences. Link the issue if there is one. -->

## Owner check
- [ ] Every file in this PR belongs to my session ([`docs/START_HERE.md`](../docs/START_HERE.md) §1)

## Verified
- [ ] CI is green (compile, self-tests, safety guards, secret scan)
- [ ] `pogo_extract` change: `pogo_data.py pull` → `full_audit.py --audits-only` → all 11 audits PASS
- [ ] Phone-side change: a real run on the phone, with Benny's go — or say plainly that it is untested

## Safety
- [ ] Never releases, never restarts PoGo, never pauses the catcher
- [ ] No secrets, no game data (data goes through `tools/pogo_data.py`)
- [ ] Changes what gets kept? → Benny picked it from numbered options, and `LAW.md` was updated first
