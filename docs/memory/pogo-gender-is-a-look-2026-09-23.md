---
name: pogo-gender-is-a-look-2026-09-23
description: For the 102 species whose males and females look different, each gender is its own plain ladder / variant (gender_variants.json); the evolution TARGET decides the gender key.
metadata:
  type: project
---

User 2026-09-23, on a female (dark) Hippowdon 67% in the pile: "why is dark hippo tagged? i have 4 dark ones ... fix all
these issues, this cant be the only pokemon". Male and female Hippowdon are different colours; the engine had pooled
them into one plain ladder (cap 3), so the 67% female lost to two 82% females and a 91% male.

**Rule now:** `pogo_extract/gender_variants.json` = the 102 species with visible gender differences (Bulbapedia's
list, fetched 2026-09-23; GO renders all of them, Eevee since 0.163). `evolvable_forms.gender_key(pid, gender)` returns
1/2 for those and for the gender-LOCKED evolvers (GENDER_TERMINALS), else 0. Every stage/variant key carries it:
keep_policy `_gterm` -> `_stage_key`, `_domgrp`, `_special_iv_grp`, `_all_by_key`; `_lawcheck`, `_evocheck`,
`audit_promises`, granular_tags Variant #N ordinals. LAW.md bucket 3b.

**Trap found by the promises audit the same hour:** the evolution target key must use the TARGET species' rule --
a Natu (one look) evolving into a Xatu (two looks) lands on the Xatu ladder of its gender; with the source's key
(0) the Xatu stage read as empty and two Natus were promised into full female ladders. `_tkey` now uses
`gender_key(sp_to_dex[t], r['gender'])`. Shinies / cards / costumes stay per species+form (not per gender) unless he
asks. Related: [[pogo-one-speciesid-many-plain-forms]], [[feedback-labels-true-for-the-mon-on-screen]].

**2 per gender (2026-09-25 15:49, "By gender, cap it to 2."):** keep_config caps.plain_line_gender = 2, applied through
`evolvable_forms.ladder_cap(cap, pid, gkey)` -- the ONE helper the engine (_stage_cap) and the audits that re-derive the
ladder (_lawcheck, _evocheck, audit_promises; registry entry in audit_invariants.AXES) all call. Dimorphic species only;
gender-LOCKED look-alikes (Ralts, Kirlia, Snorunt, Burmy, Salandit) keep the plain cap. Freed 41 on the first pass.
