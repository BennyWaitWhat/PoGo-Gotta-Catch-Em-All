---
name: phone-thermal-diagnosis-2026-09-29
description: "Read-only 'why is my phone hot' recipe + baseline: PoGo automation (Pokemod + GPS Joystick walk + Termux catcher) = 2-2.5 cores = ~3.4 W CPU rails, ~4.5 W total; skin 43-44 C = status 2; charging cut to 0 by chg_mdis=26; the thresholds and where each number is read."
metadata:
  node_type: memory
  type: reference
  originSessionId: 8d19b2ac-5ec2-4202-a142-d338f99d4ce6
  modified: 2026-09-29T05:57:45.688Z
---

**Recipe (2026-09-29, read-only, ~2 min):** pipe a script over `adb -s 100.98.158.56:5555 shell sh < collect.sh`
(copy kept as `Phone Maintenance/thermal_diag_collect.sh`; write it with the Write tool -- a bash heredoc with
that much quoting fails in the Bash tool). Then `awk` the `##### SECTION` markers into per-section files. The
useful reads, in order of payoff:
- `dumpsys thermalservice`: current temps + status per sensor, thresholds. VIRTUAL-SKIN is what Android throttles
  on (levels 39/43/45/46.5/52/65 C); VIRTUAL-SKIN-CHARGE-WIRED decides charging (34/38/41/45/47/55 C).
- `su -c cat /dev/thermal/tz-by-name/<name>/temp` for soc_therm, charging_therm, quiet_therm, rfpa_therm, BIG/MID/
  LITTLE/G3D (millidegrees). VIRTUAL-SKIN is HAL-only: read it from `logcat -s pixel-thermal`
  (`VIRTUAL-SKIN:43.6`), which also prints the ODPM power rails (S4M_VDD_CPUCL0 / S2M_VDD_CPUCL1 / S3M_VDD_CPUCL2
  / S2S_VDD_G3D in mW) and the cooling-device writes (`update cdev thermal-cpufreq-2 sysfs to 3`).
- cooling devices: `/sys/class/thermal/cooling_device*/{type,cur_state}`; `chg_mdis cur=26 max=26` = charging
  fully cut. Kernel `google_battery` line `CSI[speed=0 ... status=20]` = charge speed limited by system thermals.
- power: `/sys/class/power_supply/usb/{voltage_now,current_now}` = charger input (0.5 A x 9 V = 4.5 W steady game,
  1.0-1.3 A during a game reload); `battery/current_now` ~ 0 means not charging even though "AC powered".
- CPU: `dumpsys cpuinfo` (per-process %, last ~40 s), `top -H -b -n 2 -d 3`, and per-process jiffies since boot
  from `/proc/<pid>/stat` fields 14+15 sorted.
- location: `dumpsys location` -- listener list per provider, "gps_hardware ... mStarted", GNSS Manager Status
  Provider listeners; sensors: `dumpsys sensorservice` handle table (sampling_period per client) + "Connection
  Number" blocks (per package). Wakelocks: `dumpsys power`; kernel wakeup sources: `/sys/class/wakeup/*`.
- log buffers hold < 10 min at this phone's ~210 lines/s; grab death/crash evidence within minutes or it is gone
  (the old PoGo pid's end at 01:47:22 was unrecoverable 6 min later).

**Baseline found:** game in foreground under automation = 200-275% CPU (UnityMain ~90%, GfxDeviceW ~40%, 4
Job.Workers ~20% each), system_server 25-66%, GMS 20-25% (FlpThread fusing the joystick's mock fixes; 129,645
fused fixes in 11 h; "delivery blocked - too fast" 38/s), surfaceflinger+HWC ~25%, sensors HAL 10%, Oura 10-18%
([[oura-analytics-retry-storm]]). Load avg 7-9 on 8 cores. Memory 15.0/15.6 GB, zram 6.3/7.8 GB (zstd), PoGo RSS
3.2-3.4 GB. Display at 2.5% brightness and the modem (5G SA, data on WiFi) were NOT contributors. Game keeps a
bright wakelock and audio (MmapPlayback) the whole time; GPS Joystick holds `gpsjoystick:movement`.

**Pokemod owns the root logcat processes (proved 2026-09-29 by `/proc/<pid>/environ`: every one carries
`TMPDIR=/data/user/0/com.pokemod.app.public/cache`, i.e. spawned through Pokemod's `su` shell, pid under magiskd).**
The rolling writer `logcat -e '^(?!(SystemUpdate|SurfaceFlinger|Parcel))' -T1 -b all -v color,usec,uid -f
/data/local/tmp/logs/logcat -n10 -r9128` (10 x 9 MB) is Pokemod's support-log collector, restarted at every game
launch by its long-lived root `sh`; the `logcat -b crash -B` children are its crash watchers and get orphaned
(ppid 1) whenever an injector is killed on relaunch. Harmless, ~0 CPU; killing the writer is undone at the next
launch, so turn it off inside Pokemod if unwanted. Pokemod's TMPDIR in `environ` is the quick attribution test. Related: [[pokemod-launch-path]], [[feedback-never-kill-system-bound-hals]],
[[feedback-html-and-phone-screenshot]].
