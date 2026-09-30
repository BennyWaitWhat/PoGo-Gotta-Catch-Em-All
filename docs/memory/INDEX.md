> Exported from Benny's PC memory (the notes predate the cloud move on 2026-09-29). Where a note describes the Windows PC
> (Git Bash, PowerShell, `C:\...` paths, local adb) the cloud equivalent is in `docs/START_HERE.md` and `docs/cloud_setup.md`.
> A `[[name]]` link with no matching file points at a note that was left out (not PoGo). New lessons: add a note here + a line below.

# Memory export (Pokemon GO knowledge for cloud sessions)

Snapshot of Benny's auto-memory notes that matter for the PoGo repo, copied verbatim (frontmatter included) on 2026-09-29.
Notes describe the LOCAL setup: Windows PC, rooted Pixel 9 Pro, adb over Tailscale, Frida. A cloud clone cannot reach the phone, so treat phone/cull/gym/catcher notes as background and rules, not as things to run.
Paths such as `pogo_extract/...`, `AutoCatcher/...` are relative to the git root (`Phone Maintenance/`).
Notes reference each other as [[note-name]] = the file `note-name.md` in this folder.

## Phone / root / device
- [Re-root the Pixel after an OTA](pixel-reroot-after-ota.md) -- OTA boots stock init_boot = root gone, nothing lost; patch init_boot on-device, fastboot flash. A17 verdict.
- [User phone setup](user-phone-setup.md) -- Pixel 9 Pro, OS/build, Magisk, Vector/LSPosed modules, boot scripts, root hiding.
- [Phone root-app sources](phone-root-app-sources.md) -- repo map + update gotchas for sideloaded root apps/modules; `adb install -r` keeps LSPosed scope.
- [APK install verification](apk-install-verification.md) -- verify version/size/SHA256 and show the user before install.
- [Wireless ADB via Tailscale](wireless-adb-via-tailscale.md) -- use the stable Tailscale IP, not the LAN IP; a Bravia TV shares the adb server; cloud sessions: ADB_TARGET=127.0.0.1:5555 (Tailscale in the VM), never a bare adb.
- [NEVER kill system-bound HALs](feedback-never-kill-system-bound-hals.md) -- `ctl.stop` on GNSS/modem HALs = crash loop into safe mode.
- [dumpsys location et= field](reference-dumpsys-location-et-field.md) -- `et=` is elapsedRealtime since boot, NOT age.
- [Phone thermal diagnosis 2026-09-29](phone-thermal-diagnosis-2026-09-29.md) -- read-only hot-phone recipe; PoGo automation = 2.5 cores = ~4.5 W; skin 43 C = status 2 cuts charging (chg_mdis 26); thresholds + where to read.

## How I should work
- [Report >2x = watch, review, understand, improve](feedback-report-twice-watch-improve.md) -- 3rd report of anything: tool-printed counter, all occurrences, trigger from data, fix shipped.
- [Read screen TEXT, not just its name](feedback-read-screen-text-not-just-name.md) -- every warning/lockout: capture its text + a screencap.
- [Agents on Opus 5.5](feedback-agents-opus-5-5.md) -- pin `model: 'claude-opus-5-5'` on every workflow agent.
- [Number findings, then ask](feedback-number-findings-then-ask.md) -- removals/phone/policy: numbered list, wait for picks; tooling defects: fix, then report.
- [Always re-check upstream](feedback-always-recheck-upstream.md) -- re-query releases live before any "up to date" claim; read release bodies; check log timestamps.
- [Game pace: decide IN the runner](feedback-game-pace-decide-in-runner.md) -- steer via gym_state/runner_inbox (`AutoCatcher/tools/gym_send.sh`), never a restart per decision; restart only via `gym_restart.sh`.
- [Session conduct: one known-good tool](feedback-pogo-session-conduct.md) -- extend the canonical pipeline; no agent fan-outs or one-off scripts.
- [Do it yourself; workflows too slow](feedback-do-it-yourself-workflows-too-slow.md) -- PoGo changes inline, verify with the offline audits, then cull.
- [Workflow hunters never edit live files](feedback-workflow-hunters-never-edit-live.md) -- say read-only in plain words; 09-29 hunters patched 29 files; finished by 2 reviewers; open: catcher picker, shiny ce labels, server replies.
- [Tell me what to expect](feedback-tell-me-what-to-expect.md) -- announce phone phases, ask for `go`; serial phone steps run myself.
- [Never probe scripts with --help](feedback-never-probe-scripts-with-help.md) -- most ignore argv and RUN; `full_audit.py --help` ran a cull 09-29 (now rc 2); never pipe phone scripts into head.
- [Don't change system settings without asking](feedback-dont-change-system-settings-without-asking.md) -- no battery/UI/permission changes without approval.
- [ALWAYS read in-game records](feedback-read-in-game-records.md) -- report the game's own fields (KmWalked, incubators, buddy stats), never my arithmetic.
- [Verify before irreversible / don't confabulate](feedback-verify-before-irreversible.md) -- read the authoritative source; don't rationalize a shaky premise.
- [Total diligence, no spot-checks](feedback-total-diligence-no-spotcheck.md) -- scan EVERY form from the live enum.
- [HTML deliverables + "screenshot"=phone](feedback-html-and-phone-screenshot.md) -- reports as self-contained .html; "screenshot" = phone ADB screencap.
- [Git Bash on Windows gotchas](feedback-git-bash-windows.md) -- prefer PowerShell; MSYS mangles Unix paths; no `zip`.
- [Check for live sessions before release advice](feedback-check-live-sessions-before-release-advice.md) -- read other recent transcripts first (4 keepers were lost once).
- [One phone pass, not three](feedback-one-phone-pass-not-three.md) -- back-to-back passes froze PoGo; one pass per go.
- [Never pause the catcher; walks don't](feedback-no-catcher-pause-outside-cull.md) -- CATCHER_PAUSE_ENABLED=False since 09-24; read-only walks are WANTED for research ("read from the phone"); agents never attach Frida.
- [NEVER restart PoGo from a cull](feedback-no-app-restart-while-playing.md) -- "never restart the game. ever."; restart_pogo() raises.
- [Evolve into an open slot beats releasing](feedback-evolve-into-open-slot-beats-release.md) -- candy/item short = HOLD, never release.
- [Action tag names, on top](feedback-action-tag-names-on-top.md) -- tags say WHAT TO DO, <= 18 chars, first in order; no Evolve tag on mid-stage targets.
- [Labels must be true for the mon on screen](feedback-labels-true-for-the-mon-on-screen.md) -- literally true of THAT mon now.
- [Never re-propose the plain shiny cap](feedback-never-repropose-plain-shiny-cap.md) -- 4 plain shinies; the lever is the IV floor; refused cap cuts listed.
- [Bag Pulse cull-by-cull + PvP standing](pogo-bag-pulse-cull-by-cull.md) -- last 30 passes with IV/PvP series and cumulative wins; `ladder_report.pvp_metrics` + `--backfill-pvp` (2026-09-29).
- [Cull report sections](feedback-cull-report-sections.md) -- every cull: What improved + Why each pile mon + Which way to evolve.
- [Say "Just caught" in pile explanations](feedback-just-caught-in-pile-explanations.md) -- name the just-caught copy that outdated each pile mon.
- [Trade picks are GOOD ones](feedback-trade-picks-are-good-ones.md) -- Trade = top 10 of the remainder, never the worst copies.

## PoGo — safety rules for the irreversible pile
- [BAN LOCKOUT 2026-09-26 04:55](pogo-ban-lockout-2026-09-26.md) -- main locked out mid-automation; NO game automation without his explicit go; >= strike 2.
- [TAG ONLY — never release](feedback-tag-only-never-release-no-xxs.md) -- I tag Transfer; HE releases in game. XXS is dead.
- [Pre-flight Transfer on EVERY axis](feedback-transfer-preflight-every-axis.md) -- check the pile against every keep axis; RECRAWL first; no gym excuse.
- [Pile gate: preflight stamp](pogo-pile-gate-2026-09.md) -- only route to Transfer: preflight_transfer -> prune_tags --atomic.
- [Second account walk 2026-09-26](pogo-second-account-walk-2026-09-26.md) -- florandez set + Alt Bag Pulse BvcioQeAeZcposXoFHFE8Q; released_pids.json. MAIN is active again since 2026-09-27 (see accounts note).
- [Accounts + line pools 2026-09-26](pogo-accounts-and-line-pools-2026-09-26.md) -- oyebenny (trainer BennyValentinC, ACTIVE 09-27) / florandez sets; switch_account.py; guard TRAINERS alias; florandez 2 plain per line.
- [Data completeness before destructive actions](pogo-data-completeness-before-destructive-actions.md) -- never cull on incomplete data; NULL = PROTECTED.
- [PvP "fits the league"](pogo-pvp-fit-label-not-keep.md) -- rank<=5 keep is CP-blind; Best GL/UL = best copy that can still enter.
- [Keep PvP by RANK, never IV magnitude](feedback-pvp-rank-not-iv-threshold.md) -- rank<=5 + CP-viability alone; no spares; Best/shadow floor #55 on both accounts since 2026-09-29 02:3x.
- [Bag count ONLY from a live walk this turn](feedback-bag-count-only-from-live-walk.md) -- the game counts Pokémon + incubating eggs; bag_count.json.
- [Source of truth = DB rules](pogo-source-of-truth-db-rules.md) -- query the DB by rule; tags and cached protos drift.
- [Capped vs keep-all bug class](pogo-capped-vs-keepall-bug-class.md) -- #1 defect; when a cap changes, fix EVERY consumer.
- [Forensic cull audit 2026-09](pogo-forensic-cull-audit-2026-09.md) -- form->speciesId mapping bug (165 rows); one provable wrong release.

## PoGo — collection model & tags
- [LAW.md + collection vision](feedback-pogo-collection-vision-2026-09-13.md) -- edit LAW.md first; cap values in keep_config.json; shinies comb up by IV.
- [Decisions 2026-09-17](feedback-pogo-collection-vision-2026-09-17-decisions.md) -- favorites kept, mega level irrelevant, nicknames cleared.
- [Ultracode audit 2026-06-09](pogo-ultracode-audit-2026-06-09.md) -- fresh_* columns ONLY; collapse goes UP; shinies never collapse-victims.
- [PoGo tag system 2026](pogo-tag-system-2026.md) -- registry, only-tag-what-is-not-native, collapse history.
- [Tag vocabulary 2026-09-09](pogo-tag-vocabulary-2026-09-09.md) -- managed tags; colors 0-8; EMPTY-SET contract; DeleteTag drains 3/cycle.
- [Granular keep tags 2026-09](pogo-granular-tags-2026-09.md) -- every keeper covered by a tag or chip; `full_audit.py` = one-command cycle.
- [One speciesId, many plain forms](pogo-one-speciesid-many-plain-forms.md) -- a stage is (speciesId, FORM); Shellos/Floette traps.
- [Gender is a look (2026-09-23)](pogo-gender-is-a-look-2026-09-23.md) -- plain ladder PER GENDER for 102 species; the target decides the key.
- [Rank tags are per STAGE](pogo-rank-tags-per-stage-2026-09.md) -- `GL/UL Rank N` = own stage; `Evo GL/UL Rank N` = a later stage.
- [Tag ORDER on the phone](reference-pogo-tag-order.md) -- SortIndex@0x4c; order_tags.py ORDER; add new managed tags to ORDER.
- [Tag inheritance + Evolve Shiny](reference-pogo-tag-inheritance.md) -- tags inherit through evolution; Evolve Shiny via build_tagsets.
- [Comb-up bar ignored displacement](pogo-combup-bar-ignored-displacement-2026-09-13.md) -- labels must use the keep rule's occupancy model.
- [Pattern-pooled lines](pogo-pattern-pooled-lines-2026-09.md) -- one plain_line pool per PATTERN; no comb-up.
- [Special backgrounds are capped](pogo-special-backgrounds-capped.md) -- top-3 per (species, form, card); costume copies take those slots first.
- [Fusion components hold no ladder slot](pogo-fusion-components-no-ladder-slot.md) -- fused Reshiram/Zekrom kept as 'fused'.
- [PoGo collector keep-rules 2026](pogo-collector-keep-rules-2026.md) -- AE roster, Gigantamax count, Mighty flag, remote-trade lockout.
- [Adventure-Effect live registry](pogo-adventure-effect-live-registry.md) -- AE per mon; registry read every recrawl; audit_tag_truth.py.
- [PoGo location cards + S2 decode](reference-pogo-location-cards-and-s2.md) -- cards capped top-6; captured_s2_cell via s2sphere.
- [Viability-blind best-stage bug](pogo-viability-blind-best-stage-bug.md) -- rank_cache ignored cap-reachability; fixed at source.
- [PvP rank has NO headroom concept](reference-pvp-rank-no-headroom-research.md) -- viability_margin is -101 since 2026-09-28: a stage 'reaches' UL at 2,400+ / GL at 1,400+ (user's cut-off).
- [Pokemod overlay rank mechanics](reference-pokemod-overlay-rank-mechanics.md) -- per-stage rank at a level-50 ceiling; state the ceiling.
- [Showcase points formula + XXL rule](reference-pogo-showcase-score-formula.md) -- 800·c + 150·u + 50·IV% + 178; XXL ≥1000 pts, top 2; coefficients read live.
- [XXL trim is a one-off](pogo-xxl-trim-one-off.md) -- only when he says: `full_audit.py --xxl-trim` = best 1/species + best 5/type at 1,050+; everyday stays top 2; 5 showcase entries at once.
- [Keep research 2026-09-29](pogo-keep-research-2026-09-29.md) -- bag refills (~64/day, caps allow ~12,300); applied unpaid-hold commit, walk-tied candy, shadow legendaries 3, middle 1; open: LAW caps 783, trade spares 469, merge 235.
- [Pokedex is lifetime, not bag](pogo-pokedex-lifetime-not-bag.md) -- read PokedexImpl; never infer from the DB.

## PoGo — tooling & internals
- [Autocull daemon OFF 2026-09-22](autocull-disabled-2026-09-22.md) -- culls only with me; daemon + dashboard stopped.
- [pogo_extract project](project-pogo-extract.md) -- Frida/IL2CPP bag -> pokemon.db, the cull, server tags.
- [keep_config + dashboard/Studio](project-keep-config-dashboard.md) -- caps in keep_config.json; dashboard on 8765; ADDITIVE-ONLY.
- [Dashboard hardening 2026-06-10](pogo-dashboard-hardening-2026-06-10.md) -- dry-run Sync wasn't dry; restart long-lived processes after edits.
- [Workflow review 2026-09-29](pogo-workflow-review-2026-09-29.md) -- full_audit runs the pages + stops its dashboard; empty shells get 24 h grace (order churn); open proposals (evolve-tag fold, Best label/rule, floor).
- [Cull pass anatomy + speed cuts](pogo-cull-pass-anatomy-2026-09-12.md) -- 75s -> 43s; cached singletons, stamp reuse.
- [PoGo IL2CPP internals](pogo-il2cpp-internals.md) -- Form enum, evolution keeps the proto ptr, bag-walk, MapField, level math.
- [Live cosmetic reads + form/costume offsets](reference-live-cosmetic-reads.md) -- DB display_* unreliable; read PokemonDisplayProto live.
- [Pokemod obfuscation maps + oracle](pogo-game-0427-oracle-obfmap.md) -- game 0.429.1 / Pokemod 13.3.3; per-class resolver.
- [GC world freeze = "you froze the game"](pogo-gc-world-freeze-2026-09-09.md) -- stop_gc_world + a managed call deadlocks PoGo.
- [PoGo clone crash classes](pogo-clone-crash-classes.md) -- never Dismiss() stale clone screens; null-derefs abort under Frida.
- [Pokemod launch path](pokemod-launch-path.md) -- HALService + `pokemod-injector` holds the session; vpgp_agent in `:pgp`.
- [Pokemod vPGP = two agents](pokemod-vpgp-tweaks-module.md) -- the virtual Go Plus needs the game-side VPGPTweaks module.
- [Pokemod labels + sync-lag lesson](project-pokemod-labels-and-sync-lag.md) -- cache lag skips the mirror -> run a second pass.
- [Buddy system](reference-pogo-buddy-system.md) -- Best=300 hearts; daily caps; gym battles count only with the buddy in the party; BuddyRpcService.
- [Native gym flow](reference-pogo-native-gym-flow.md) -- runtime_invoke only; LateUpdate tick; LaunchData.PlayerTeam; Golden Razz feeder (706 allowed only here).
- [PoGo Frida stability](pogo-frida-stability.md) -- PID drift fix, liveness API for singletons, kill stuck python on DB lock.
- [Stale service graph 2026-09-29](pogo-stale-service-graph-2026-09-29.md) -- game rebuilt its services in-process; live_graph() for EVERY class; walk_tripwires STOP (rc 8) on catcher-log proof, age alone only WARNs.
- [Frida 17 Java bridge](reference-frida17-java-bridge.md) -- bundle frida-java-bridge via frida-compile.
- [On-phone autonomous catcher](pogo-on-phone-catcher.md) -- `AutoCatcher/`; `propagate`; liveness only before hooks; pause handshake; crash-loop breaker; no 706/708.
- [Field Research reward catcher](pogo-field-research-reward-catcher.md) -- clears "Today" rewards (open Today once); v3: lost-throw re-throw by box proof, cap 6; `tools/reward_sim.py`.
- [Map tappables / event apples](reference-pogo-map-tappables-apples.md) -- TAPPABLE_TYPE_MAPLE at Mossy-lured stops → apples 1151/1152/1155 or a hidden Pokémon; tap = gesture handler `void ?(Object, EventArgs)`, NOT Tapped(); `tools/apple_collector.py`.
- [PoGo repo + session ownership 2026-09-29](pogo-repo-and-session-ownership-2026-09-29.md) -- one private repo (root Phone Maintenance/), one owner per folder/file, `pogo_desktop_busy` marker for desktop attaches, no root CLAUDE.md.
- [Rate-limit detection](reference-pogo-limit-detection.md) -- "can't spin" = server OutOfRange (res2) at stops in range; account flags clean (GetPlayer warn/ban 0); catcher LIMIT line + spin back-off.
- [GPS Joystick control](reference-gps-joystick-control.md) -- Pro Intents API (SPEED/WALK/...); timing fix 250/248; never stop it with PoGo open.
- [Walk-credit speed curve](reference-pogo-walk-credit-speed-curve.md) -- KmWalked full to ~10.5 km/h, 0% from 11.9; updates every ~123 s.
- [PoGo spoof stack](project-pogo-spoof-stack.md) -- joystick mock -> Pokemod bridge -> PoGo; the GPS chip is the real leak.
- [PoGo server authority](pogo-server-authority.md) -- the server is authoritative; client writes can't forge rewards.
- [Fresh-catch tag-write lag](reference-fresh-catch-tag-write-lag.md) -- tags on minutes-old catches can silently no-op.
- [Hatched-mon isEgg_ artifact](reference-hatched-mon-isegg-artifact.md) -- isEgg_ stays 1 for 1-2 days; an egg is a SHAPE.

## PoGo — game data & reference
- [PoGo game state 2026](pogo-game-state-2026.md) -- Scopely-owned, levels, friends, trades. NEVER hardcode storage capacity.
- [PoGo mechanics reference](pogo-mechanics-reference.md) -- CP/CPM, IV floors, multipliers, size enum, Mega ladder, proto fields.
- [The GAME outranks pvpoke](pogo-game-authoritative-over-pvpoke.md) -- reconcile_gamemaster.py copies client truth; the client vetoes stale flags.
- [Form enum arbitrates CP ties](pogo-form-enum-arbitrates-cp-ties.md) -- the live form NAME decides tied ids.
- [Game master monthly refresh](project-gamemaster-monthly-refresh.md) -- refresh_gamemaster.py exits 2 on a rank<=5 crossing; since 2026-09-29 it also refreshes pvpoke's meta rankings (the top-200 dust-advice gate) on the same 30-day clock.
- [Client limits dump 2026-09-24](reference-pogo-client-limits.md) -- every client threshold in game_limits.json/.html; the egg speed cap is server-only.
- [PokeGenie backup](project-pokegenie-backup.md) -- regenerate PokeGenie's collection from pokemon.db.
- [PokeGenie art internals](reference-pokegenie-art-internals.md) -- `app_imageDir/i_<id>.jpg`; patch ScanHistory too.
