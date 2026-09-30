---
name: pogo-workflow-review-2026-09-29
description: 2026-09-29 cull-workflow review ("go and be awesome"): full_audit now regenerates the pages + stops its own dashboard; empty managed shells get a 24 h grace before retire (tag-order churn); open proposals list.
metadata:
  type: project
---

Shipped (tooling, no policy):
- `full_audit.finish_step(rc)`: on a clean pass runs gen_artifacts.py + gen_bag_pulse.py, then terminates the
  dashboard THIS run started (every exit path; `--keep-dashboard`, `--no-pages`). Only the Bag Pulse publish is left to me.
- `retire_tags.grace_filter`: an EMPTY managed shell is deleted only after 24 h empty (`--grace-hours`, stamps in
  system/analysis/empty_since.json). Cause: evolve tags flip 0<->1 members per cull; delete-at-once + re-create next pass
  reshuffled the tag order EVERY cull (27-33 SortIndex edits + DeleteTag + AddTag; post-tags 15 s -> 40-60 s, 09-27..29).

His picks (01:0x): 1 fold (+ keep the PvP markers), 2 'i dont understand' (NOT done -- explain again: Best label only at the own stage + later stage counts only if it beats what he owns), 3 floor 100, 4 RT skip, 5 report, 6 phone button 'not yet'. SHIPPED 1/3/4/5 the same night (gate green 01:38, pile 62 = 20 shadows + 18 Bests past #100 + fodder). Originally proposed: fold the 10 evolve tags into Evolve Once / Evolve Twice / Evolve Gated
(user: "I either evolve once or evolve twice"); Best GL/UL/ML only at the OWN stage as a label, and a later stage counts
only when it beats what he owns there (274 later-stage Bests, 200 do not beat; 7 kept only by those); floor 150->100
(33 GL + 35 UL Bests, 18 kept only by those); skip the Remote Trade re-verify when the offer set is unchanged; report
noise (standing "which way" lines, fodder block); a phone-side cull trigger.

Per-pass timing 09-28/29: walk 25-52 s, audits 6-17 s, sync 15-45 s, post-tags 37-60 s, total 80-145 s.
Related: [[feedback-action-tag-names-on-top]], [[pogo-bag-pulse-cull-by-cull]].

Lessons 01:3x: never chain a phone pass behind a PIPED gate (`... | tail -1 && full_audit.py` ran the cull on a red gate --
check $? of the gate itself); a gender-split promise (oinkologne/oinkologne_female) stays a split in the table -- the truth
audit skips the branch the game master shuts to that copy; a showcase pick never sits on a consumed copy (dex_only/trophy/
card/legendary/best shadow/legacy) -- producer + membership mirror; path_between matches ids exactly or at an '_' boundary
(pidgeotto != pidgeot). LAW.md is SHARED across accounts while caps differ (row 8 'top 1' is florandez's) -- open.
