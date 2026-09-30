---
name: feedback-dont-change-system-settings-without-asking
description: "Don't auto-whitelist apps for battery, change UI/system settings, or touch permissions without explicit user approval."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5e83127-eb4b-45c2-bb2c-3416996bd829
---

The user pushed back hard ("wait why the fuck are you whitelisting campfire. leave it alone") when I added an app to the battery exemption whitelist as part of a "performance boost", and also rejected lowering the animation scale. Battery whitelisting, animation scales, refresh rate, font size, app permissions, and other system-wide UI behavior are USER-PREFERENCE territory — the user decides, not me.

For "performance boost" tasks, what IS fair game without asking: clear caches, kill background processes, adjust standby buckets / OOM scores for apps the user explicitly named, trim swap pressure. What requires asking first: battery whitelist additions, animation scales, system-wide UI settings, app permission changes — anything that affects persistent user-facing behavior.

**Why:** These settings change how the user's own device behaves day to day. Silently altering them is overreach; the user wants agency over their phone.

**How to apply:** Before applying any change that affects persistent user-facing behavior, ask. Scope autonomous "optimization" to reversible, non-preference actions on explicitly-named targets. Note: run as shell (uid 2000), `pm clear --cache-only <pkg>` never returns — PackageManagerService silently ignores callers without INTERNAL_DELETE_CACHE_FILES and never calls the observer (seen on A16 2026-09-01; the same code path is in the A17 CP3A services.jar). Use root `rm -rf /data/data/<pkg>/cache/* /data/data/<pkg>/code_cache/*` for cache clearing instead. Relates to [[user-phone-setup]].
