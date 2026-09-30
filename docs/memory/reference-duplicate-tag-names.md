---
name: reference-duplicate-tag-names
description: "The game accepts two tags with one name. A verify-miss retry in create_tag made two 'Evolve for UL' (2026-09-30); every by-name lookup then picks one at random. Guards and the by-id cleanup."
metadata:
  type: reference
---

**What happened (cull 2026-09-30 13:49):** prune created the new 'Evolve for UL'. `tag_ops.create_tag` checked 3 s after
the AddTag, the client cache did not show it yet, and the retry sent a SECOND AddTag. The game accepted both: two tags,
one name. The 3 members landed on one copy; prune's verify read the other (server=0, "deferred (locked...)" was that
mis-read); the post-push reconcile saw DRIFT, and the pass ended SYNC FAILED rc 3 with retire / Remote Trade / order
skipped. The pile itself was pushed and verified.

**Why it is dangerous:** `findTagIdByName` returns the FIRST match, and `safe_nuke_tags.tag_census` / `retire_tags` key by
NAME -- a by-name delete could remove the copy that holds members, and `clear_db_mirror` would drop the name everywhere.

**Guards (2026-09-30):**
- `create_tag` polls a returned AddTag for `VERIFY_WINDOW_S` (30 s) before ever sending another; `DuplicateTagName` when
  `bulk_tag.js countTagsByName` sees 2+ copies (on create and on "already exists").
- `prune_tags` skips a duplicated tag (write_failed, rc 1) instead of writing into it; the pile still pushes.
- `safe_nuke_tags.py` refuses a by-name delete of a duplicated name. `--empty-duplicates NAME` deletes only the EMPTY
  extra copies, by tagId, one at a time, collateral-checked by tagId, DB mirror untouched; refuses when two copies hold
  members (merge by hand). `retire_tags` never acts on a duplicated name.

**Cleanup:** `python system/scripts/safe_nuke_tags.py --dry-run --empty-duplicates "Evolve for UL"`, then without
--dry-run -- a phone write: only on Benny's word.
Related: [[pogo-tag-vocabulary-2026-09-09]], [[reference-pogo-tag-order]], [[feedback-action-tag-names-on-top]].
