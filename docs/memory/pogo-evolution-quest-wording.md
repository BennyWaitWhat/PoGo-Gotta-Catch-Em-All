---
name: pogo-evolution-quest-wording
description: "Evolution-quest text in labels and reports is the GAME'S OWN i18n text (official_names_en.json 'quests'), not our paraphrase -- how a template maps to its string, the singular-hearts trap, the cache gotcha, the one refresh command (2026-09-30)."
metadata:
  type: project
---

Benny said yes (2026-09-30) to the game's own words for evolution quests. `evolvable_forms._quest_text` now renders the game's
i18n text; `gate_text` (the `need` in `shiny_gated.json`, the `[needs: ...]` in "Which way to evolve", the ladder report, Bag
Pulse's blocked-evolution table) carries it.

**Mapping (proved on all 37 `evolutionQuestTemplate` entries, 2026-09-30):** `display.description == display.title` = an i18n key,
spelled in either case (3 of the keys are upper-case in the game master); lowercased it is a key of `i18n_english.json`, and the
text holds `{0}` for the goal's number (`goals[0].target`). The type words in every text equal the template's conditions. 28
templates are named by an `evolutionBranch.questDisplay` (only field: `questRequirementTemplateId`); 9 (Community Day / buddy-event
variants) are named by no branch today but are worded too.

**What changed:** 6 meanings -- Sirfetch'd 'land throw 10 times' lost "Excellent"; Bisharp 'win 15 raids with Dark/Steel-type' is
"Defeat 15 Dark- or Steel-type Raid Bosses"; Kubfu x2 say "in raids or Max Battles"; Overqwil and Runerigus are "Win 10 raids",
not "complete raid battle 10 times". 8 ungrammatical ('earn hearts with 20 times', 'feed 25 times', 'use incense 1 times'). 23
wording only ('as your buddy' -> 'with your buddy', 'Pokémon', 'Psychic- or Ghost-type'). 67 advice lines, 25 of 36 shiny_gated
needs and 7 report lines changed text; pile, reasons and tag membership did not move.

**Traps:**
- Florges and Sylveon name the SINGULAR hearts key for goals of 20 / 70 / 7: 'Earn a heart with your buddy' is false for them. Rule:
  a text must state the number -- the plural sibling with the template's own target (goal 1 takes the singular sibling). The
  pairing lives in `evolvable_forms.quest_keys`; the refresh stores both numbers of every pair.
- `evolvable_forms.json` holds RENDERED text: cache version 11 + `qsig` (a hash of the quests section), so a refreshed reference
  rebuilds it although the game master did not change. Bump `v` whenever the rendered text changes.
- The engine file reads `official_names_en.json`, but the engine stamp (`keep_policy._engine_sha`) does not cover it: fine, it is
  text only, never a pile input. `BAG_ART=0` does not switch it off; a missing file falls back to the generated wording.
- The generated fallback (`_quest_goal`) equals the game's text for 36 of 37 (Annihilape: type order) and NAMES a condition it does not
  model ("(also: ...)") rather than dropping it. A multi-goal template is worded goal by goal.
- `gate_text` is keyed by the TARGET: the bare 'urshifu' shows one of the two Kubfu quests (no Kubfu in the bag; 'urshifu_rapid_strike'
  / '_single_strike' are right).
- The next cull re-announces the changed "Which way to evolve" lines once (the standing-lines dedupe is exact-string).
- NOT done (found on the way): `gate_text(target, src)` for a REGIONAL source names the Kanto branch's item (`_items` is keyed by
  pokemonId, not form): Galarian Slowpoke -> Galarian Slowking reads 'a Kings Rock + ...', the game asks for the quest only.
  `evolve_targets` avoids it (src None for regional keys); `refresh_evolve_shiny` does not (no such shiny in the pile today). The item
  and lure NAMES are hand-typed too: 7 of 16 differ from the game's (King's Rock, Lure Module x4, Upgrade, Gimmighoul Coins).
  `step_item` feeds `keep_policy._afford`, so re-keying by form is an engine change for Benny's review.

**Refresh (monthly, with the game master):** `python bag_art.py --refresh-names --i18n FILE [--gm FILE]` rebuilds names AND quests,
all or nothing; it refuses fewer than 20 quest templates, fewer than 12 texts, or fewer than 90% of the committed texts. Golden
checks: `bag_art.py --selftest`. Related: [[pogo-bag-pulse-sprites]], [[feedback-labels-true-for-the-mon-on-screen]].
