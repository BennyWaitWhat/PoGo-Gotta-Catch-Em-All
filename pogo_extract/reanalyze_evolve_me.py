"""Re-analyze Evolve Me list with: highest IV per pattern, tie-break Spewpa>Scatterbug.
Also check Maushold gap, account for Lycanroc Dusk now obtained."""
import sqlite3, json
fe = {int(k):v for k,v in json.load(open('form_enum.json')).items()}

def pat(n): return n.replace('Vivillon','').replace('Scatterbug','').replace('Spewpa','')
VIV = {fid: fe[fid] for fid in range(2594, 2614) if fid in fe}
SC = {fid: fe[fid] for fid in range(2745, 2765) if fid in fe}
SP = {fid: fe[fid] for fid in range(2765, 2785) if fid in fe}
ALL_PATS = set(pat(v) for v in VIV.values())

c = sqlite3.connect('pokemon.db').cursor()
have_viv_pats = set(pat(VIV.get(r[0],'')) for r in c.execute("SELECT form FROM pokemon WHERE species_name='Vivillon' AND in_bag=1"))
missing = sorted(ALL_PATS - have_viv_pats)
print(f"Missing Vivillon patterns: {missing}\n")

print('=== Per missing pattern: best evolve candidate ===')
print('  Rule: highest IV; tie-break -> Spewpa wins (closer to Vivillon)')
candidates = []
for pp in missing:
    sc_form = next((f for f,n in SC.items() if pat(n)==pp), None)
    sp_form = next((f for f,n in SP.items() if pat(n)==pp), None)
    sc_best = c.execute("""SELECT uid_hex, uid, iv_total, cp FROM pokemon
        WHERE species_name='Scatterbug' AND form=? AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 1""", (sc_form,)).fetchone() if sc_form else None
    sp_best = c.execute("""SELECT uid_hex, uid, iv_total, cp FROM pokemon
        WHERE species_name='Spewpa' AND form=? AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 1""", (sp_form,)).fetchone() if sp_form else None

    pick = None
    if sc_best and sp_best:
        if sp_best[2] >= sc_best[2]:  # Spewpa wins on tie
            pick = ('Spewpa', sp_form, sp_best)
        else:
            pick = ('Scatterbug', sc_form, sc_best)
    elif sc_best:
        pick = ('Scatterbug', sc_form, sc_best)
    elif sp_best:
        pick = ('Spewpa', sp_form, sp_best)

    if pick:
        sp_n = sp_best[2] if sp_best else None
        sc_n = sc_best[2] if sc_best else None
        candidates.append((pp, pick))
        print(f"  {pp:13s}  SC iv={sc_n}  SP iv={sp_n}  -> {pick[0]:11s} uid={pick[2][0]} iv={pick[2][2]}")
    else:
        print(f"  {pp:13s}  NONE - need to catch")

# Tandemaus
print('\n=== Maushold gap ===')
have_maus = set(r[0] for r in c.execute("SELECT form FROM pokemon WHERE species_name='Maushold' AND in_bag=1"))
print(f"Have: {sorted(have_maus)} ({[fe.get(f) for f in have_maus]})")
if 2983 not in have_maus:
    r = c.execute("""SELECT uid_hex, uid, iv_total FROM pokemon
        WHERE species_name='Tandemaus' AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 1""").fetchone()
    if r:
        print(f"  Best Tandemaus: uid={r[0]} iv={r[2]}  (1% FamilyOfThree chance per evolve)")
        candidates.append(('maus_FoT', ('Tandemaus', 0, r)))

# Lycanroc - check Dusk
print('\n=== Lycanroc gap ===')
have_lyc = set(r[0] for r in c.execute("SELECT form FROM pokemon WHERE species_name='Lycanroc' AND in_bag=1"))
print(f"Have: {sorted(have_lyc)} ({[fe.get(f) for f in have_lyc]})")
if 2686 not in have_lyc:
    print('  MISSING Dusk - tag Own Tempo Rockruff')
else:
    print('  All 3 Lycanroc forms present')

# Save plan
plan = []
for pp, (label, form, row) in candidates:
    plan.append({'pattern': pp, 'species': label, 'form': form, 'uid_hex': row[0], 'uid': row[1], 'iv': row[2]})
with open('evolve_me_plan_v2.json','w') as f:
    json.dump(plan, f, indent=2)
print(f"\n=== Plan saved: {len(plan)} candidates ===")

# Compare to current Evolve Me tag
print('\n=== Current Evolve Me (in_bag=1) ===')
current = list(c.execute("""SELECT uid_hex, species_name, form, iv_total FROM pokemon
    WHERE in_bag=1 AND auth_tag_names LIKE '%Evolve Me%'"""))
print(f"Currently {len(current)} tagged + in bag")
new_uids = set(p['uid_hex'] for p in plan)
cur_uids = set(r[0] for r in current)
to_remove = cur_uids - new_uids
to_add = new_uids - cur_uids
to_keep = cur_uids & new_uids
print(f"  KEEP unchanged: {len(to_keep)}")
print(f"  ADD (new better picks): {len(to_add)}")
for uid in to_add:
    pp = next(p for p in plan if p['uid_hex']==uid)
    print(f"    + {pp['pattern']:13s}  {pp['species']:11s}  uid={uid}  iv={pp['iv']}")
print(f"  REMOVE (old picks no longer best): {len(to_remove)}")
for uid in to_remove:
    r = next(rr for rr in current if rr[0]==uid)
    nm = fe.get(r[2],str(r[2])).replace(r[1],'')
    print(f"    - {r[1]:11s}  {nm:13s}  uid={uid}  iv={r[3]}")

with open('evolve_me_diff.json','w') as f:
    json.dump({'add': sorted(to_add), 'remove': sorted(to_remove), 'keep': sorted(to_keep)}, f, indent=2)
