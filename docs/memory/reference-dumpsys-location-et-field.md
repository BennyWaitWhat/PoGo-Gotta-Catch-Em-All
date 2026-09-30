---
name: reference-dumpsys-location-et-field
description: "dumpsys location \"et=\" is the elapsedRealtime VALUE since boot, not age — don't misread as staleness"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 23479c7f-0c89-4422-8b89-8816a5d0591b
---

In `dumpsys location`, a `Location[... et=+1h20m ...]` line's `et=` is the fix's **elapsedRealtime timestamp value** (duration since boot), **NOT its age**. A *fresh* fix therefore shows `et ≈ current uptime`, and `et` grows ~1s/s as uptime grows — this is normal, not drift.

How to tell fresh vs stale: a stale/frozen fix shows an `et` that is much LESS than current uptime and stops increasing (e.g. a real GPS fix stuck at `et=+35s` = taken 35s after boot, never refreshed because the chip went idle). A fresh fix's `et` keeps pace with uptime.

2026-06-05: this exact field cost a long misdiagnosis on the PoGo spoof — `et=+1h20m` (growing) was read as "mock is 80 min stale" when it actually meant "mock is fresh, uptime is 1h20m." Verified by hooking GPS Joystick's injection: its own `elapsedRealtimeNanos` was `4898645059764` ≈ current uptime = fresh. The Chicago mock was never stale. See [[project-pogo-spoof-stack]].

To confirm freshness without misreading et: compare two reads seconds apart (coords moving + et tracking uptime = live), or instrument the injector and print `elapsedRealtimeNanos` vs `SystemClock.elapsedRealtimeNanos()`.
