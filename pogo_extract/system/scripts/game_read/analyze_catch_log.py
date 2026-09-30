"""Mine the long-running catch_log.txt for the ANSWER without a new test:
Every time ULTRA was CONSUMED (count dropped), what catch event fired right before it?
 - 'manual ball=ULTRA' near an Ultra drop  => button-catch goes through CatchPokemonProto (client ball) => EASY fix.
 - 'vgp3/go-plus' near an Ultra drop (no manual) => Sfida path (server ball)                         => HARD fix.
Also reports Great drops (manual Great throws are the user's normal play) for contrast. READ-ONLY."""
import os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
LOG = os.path.join(ROOT, "system", "analysis", "pokemod", "catch_log.txt")

inv_re = re.compile(r"^(\d\d:\d\d:\d\d) INV \{(.+)\}")
catch_re = re.compile(r"^(\d\d:\d\d:\d\d) CATCH (.+)")


def parse_inv(s):
    out = {}
    for m in re.finditer(r"'(\w+)':\s*(-?\d+)", s):
        out[m.group(1)] = int(m.group(2))
    return out


def main():
    if not os.path.exists(LOG):
        print("no catch_log.txt"); return
    lines = open(LOG, encoding="utf-8", errors="replace").read().splitlines()
    last = None
    pending = []          # catch events since last INV
    ultra_drops = []      # (ts, delta, events)
    poke_drops = 0
    great_drops = 0
    n_vgp3 = 0
    n_manual = {}
    total_lines = len(lines)
    for ln in lines:
        cm = catch_re.match(ln)
        if cm:
            ev = cm.group(2)
            pending.append((cm.group(1), ev))
            if ev.startswith("vgp3"):
                n_vgp3 += 1
            elif ev.startswith("manual"):
                b = ev.split("ball=")[-1] if "ball=" in ev else "?"
                n_manual[b] = n_manual.get(b, 0) + 1
            continue
        im = inv_re.match(ln)
        if im:
            cur = parse_inv(im.group(2))
            if last is not None:
                for k in ("POKE", "GREAT", "ULTRA"):
                    if k in cur and k in last:
                        d = cur[k] - last[k]
                        if -50 < d < 0:  # a real consumption (ignore big reconnect/refill jumps)
                            if k == "ULTRA":
                                ultra_drops.append((im.group(1), d, list(pending)))
                            elif k == "POKE":
                                poke_drops += -d
                            elif k == "GREAT":
                                great_drops += -d
            last = cur
            pending = []
    print(f"log lines: {total_lines}")
    print(f"catch events: vgp3={n_vgp3}, manual={n_manual}")
    print(f"consumed totals (from small INV drops): POKE={poke_drops}, GREAT={great_drops}, ULTRA={sum(-d for _,d,_ in ultra_drops)}")
    print(f"\n=== ULTRA-consumption events ({len(ultra_drops)}) — what fired right before each ===")
    if not ultra_drops:
        print("  NONE. Ultra never dropped in the whole log => no real-WAINA button/Ultra catch was ever captured here.")
    for ts, d, evs in ultra_drops[:60]:
        ev_str = "; ".join(f"{t} {e}" for t, e in evs) if evs else "(no catch event logged in this interval)"
        print(f"  {ts}  ULTRA {d}:  {ev_str}")


if __name__ == "__main__":
    main()
