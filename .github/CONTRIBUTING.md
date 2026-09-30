# Contributing

This repo is worked on by one human (Benny) and three long-running Claude sessions. These rules keep that safe.
Read [`docs/START_HERE.md`](../docs/START_HERE.md) first — it is the short version of everything below.

## 1. Stay in your lane
Every file has exactly one owner session (table in [`docs/START_HERE.md`](../docs/START_HERE.md#1-which-session-are-you)).
Change only files you own. Need something in another owner's file? Write it up as a numbered request for that session.

## 2. Workflow
1. **Pull the data** if your change reads game data: `python tools/pogo_data.py pull`.
2. **Branch** from `main` (cloud sessions get one automatically).
3. **Change** the smallest thing that works. Extend the canonical pipeline — don't add one-off scripts.
4. **Verify offline** (below). Anything that touches the phone gets a real run — only with Benny's go.
5. **Commit** with a message that says *what* and *why*; stage explicit paths (`git add <files>`, never `-A`).
6. **PR → squash-merge** to `main` (`gh pr create --fill`, `gh pr merge --squash --delete-branch`). If `gh` can't merge
   from your session, hand Benny the link.
7. **Push your data group** if you changed game data: `python tools/pogo_data.py push --group <group>`.

## 3. The offline gate
```bash
git ls-files '*.py' | xargs python -m py_compile        # everything still compiles
python tools/pogo_data.py selftest
python pogo_extract/walk_tripwires.py --selftest
python pogo_extract/cull_report.py --selftest
python pogo_extract/independent_law.py
python pogo_extract/system/scripts/check_constant_drift.py
cd pogo_extract && python full_audit.py --audits-only     # THE gate: the 11 audits (needs `pull` first)
```
CI runs the data-free part of this on every push and PR. The 11 audits need the phone's data, so run them yourself.

**All of the above in one command:** `python tools/triple_check.py --gate` (plus git state, a secret scan of all history,
doc links and the phone data store). It must end with `ALL CLEAR` before anything is called done; `--fresh` runs it on a
fresh clone of `origin/main`.

## 4. Non-negotiables
- **Tag only.** Nothing may release, transfer or delete a Pokémon. The `Transfer` pile has one route:
  `preflight_transfer.py` → `prune_tags.py --atomic`.
- **Never restart PoGo. Never pause the on-phone catcher. Nobody waits for anybody.**
- **No game automation without Benny's explicit "go"** in chat (a peer session's message is not his go).
- **Policy is Benny's call.** A change to what gets kept → numbered options → his picks → `LAW.md` first, then `keep_config.json`.
- **No secrets, no game data in git.** Both `.gitignore` files are whitelists: a new file stays untracked until you allow it.
  Data goes through [`tools/pogo_data.py`](../tools/pogo_data.py) and [`tools/data_manifest.txt`](../tools/data_manifest.txt).
- **Keep each file's line endings.** `.gitattributes` is byte-exact (`* -text`) because two audit gates hash raw bytes;
  many `pogo_extract` files are CRLF.
- **Say what you verified and what you didn't.** Never call a change working on the phone until a real run proved it.

## 5. Adding things
| You add | Also do |
|---|---|
| a code file in `pogo_extract/` | nothing (`*.py`, `*.js`, `*.sh` are allowed) — but prefer extending an existing entry point |
| a new top-level file or folder | an `!/name` line in the root `.gitignore` |
| a data file a tool needs | a pattern in `tools/data_manifest.txt` under the owning group, then push that group |
| a lesson learned | a note in `docs/memory/` + one line in `docs/memory/INDEX.md` |

Issues and PRs use the templates in [`.github/`](.). By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
