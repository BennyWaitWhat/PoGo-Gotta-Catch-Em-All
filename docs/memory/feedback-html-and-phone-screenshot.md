---
name: feedback-html-and-phone-screenshot
description: Deliver every report/guide as a self-contained offline .html, never .md; and "screenshot" means the PHONE via adb screencap.
metadata:
  type: feedback
---

# Deliverables = HTML; "screenshot" = the phone

Two corrections the user made forcefully (2026-05), both worth never repeating:

## Always deliver as HTML, not Markdown
- Default EVERY report/guide/summary to a **self-contained, offline-capable single `.html` file** (inline CSS/JS, no external deps — they use it in the field on a phone with bad signal).
- Good patterns that landed well: sticky jump-nav, color-coded confidence tags, tap-to-navigate GPS pills (`https://www.google.com/maps/search/?api=1&query=LAT,LONG`), localStorage checkboxes, light/dark toggle.
- Only produce `.md` if explicitly asked. Do not hand over `.md` as the primary deliverable.

## "Take a screenshot" means the PHONE (PoGo app), not the desktop
- When the user says "screenshot rn" / "take a screenshot," they mean their **Pixel 9 Pro screen / the Pokémon GO app**, captured over ADB — NOT desktop computer-use screen capture.
- Command: `adb -s 100.98.158.56:5555 shell screencap -p /sdcard/_sc.png` then `adb -s 100.98.158.56:5555 pull /sdcard/_sc.png <local.png>`, then Read the PNG. Clean up the device temp file after.
- Don't waste a turn requesting desktop browser access for screenshots.

## Bonus: in-app stamp sheet is ground truth
- The PoGo in-app "Stamps" page shows the actual GO Stamp Rally points per ward (e.g., Minato = Tokyo Tower, SL広場 C11 292号, 鞆絵小学校校舎跡碑, 江戸見坂, 芝公園) — data that public trackers list as "in-app only / not published." Screenshot it rather than guessing centroids.
