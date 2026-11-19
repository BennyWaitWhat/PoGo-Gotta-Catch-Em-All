# Request to the AutoCatcher session: Cull Now's two PC lines (2026-11-18)

From the Pokemon Inventory session. Benny, 2026-11-18: "the entire thing needs to run on the phone just like the gym mode."

Since PR "The cull runs on the phone", a Cull Now tap is answered by a listener **on the phone** (Termux,
`~/cull/tools/cull_phone.sh`, started by Termux:Boot `~/.termux/boot/40-pogo-cull`). The whole cull runs there; the PC can be
off. The file protocol is unchanged: the app writes `/data/local/tmp/pogo_cull.req`, the listener writes
`/data/local/tmp/pogo_cull_status.txt`. Nothing in the app has to change for it to work.

Two lines in `AutoCatcher/ondevice_toggle/apk/src/com/benny/autocatcher/MainActivity.java` now say something untrue:

1. The help text of Cull Now: "Asks the PC to run one cull. It only tags the Transfer pile; you release by hand. The PC must
   be on." Suggested: "Runs one cull on the phone. It only tags the Transfer pile; you release by hand."
2. `Logic.cull`, a tap nobody answered within 45 s: "the PC has not picked it up -- is it on and is the listener running?"
   Suggested: "the phone's cull listener did not pick it up -- ask Claude".

New status lines the app will show (all start with one of the words it already colours: ready / queued / running / done /
STOPPED): `ready HH:MM: tap Cull Now, then go back to Pokemon GO -- the phone runs one cull`;
`queued HH:MM: open Pokemon GO and stay in it -- the cull starts when the game is on screen (it waits until HH:MM)`;
`STOPPED HH:MM: battery N% and not charging -- the cull runs on the phone, charge it first, then tap again`;
`STOPPED HH:MM: a cull from the PC is attached right now -- tap again in a few minutes`.
