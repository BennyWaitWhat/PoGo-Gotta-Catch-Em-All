"""Find Vivillon patterns the user is missing + best Scatterbug/Spewpa to evolve.
Also check Maushold FamilyOfThree/Four and Lycanroc Dusk gaps."""
import sqlite3, json
fe = json.load(open('form_enum.json'))
fe = {int(k): v for k, v in fe.items()}

VIVILLON_FORMS = {fid: fe[fid] for fid in range(2594, 2614) if fid in fe}
SCATTERBUG_FORMS = {fid: fe[fid] for fid in range(2745, 2765) if fid in fe}
SPEWPA_FORMS = {fid: fe[fid] for fid in range(2765, 2785) if fid in fe}
def pat(fname): return fname.replace('Vivillon','').replace('Scatterbug','').replace('Spewpa','')
PATTERNS = {pat(v) for v in VIVILLON_FORMS.values()}

c = sqlite3.connect('pokemon.db').cursor()
have_viv_pats = set()
for r in c.execute("SELECT form FROM pokemon WHERE species_name='Vivillon' AND in_bag=1"):
    have_viv_pats.add(pat(VIVILLON_FORMS.get(r[0],'')))

missing_pats = sorted(PATTERNS - have_viv_pats)
print(f'Vivillon patterns: {len(PATTERNS)} total, have {len(have_viv_pats)}, missing {len(missing_pats)}\n')
print(f"Have: {sorted(have_viv_pats)}")
print(f"\nMissing: {missing_pats}\n")

# For each missing pattern, find best Scatterbug then best Spewpa
print('=== Best evolve candidate per missing pattern ===')
candidates = []
for pp in missing_pats:
    sc_form = next((f for f,n in SCATTERBUG_FORMS.items() if pat(n)==pp), None)
    sp_form = next((f for f,n in SPEWPA_FORMS.items() if pat(n)==pp), None)
    best = None
    for label, form, species in (('Scatterbug',sc_form,'Scatterbug'), ('Spewpa',sp_form,'Spewpa')):
        if form is None: continue
        rows = c.execute("""SELECT uid_hex, iv_total, cp, fresh_shiny FROM pokemon
            WHERE species_name=? AND form=? AND in_bag=1
            ORDER BY iv_total DESC, cp DESC LIMIT 1""", (species, form)).fetchall()
        if rows:
            best = (label, form, *rows[0])
            break
    if best:
        candidates.append((pp, best))
        print(f"  {pp:13s}  {best[0]:11s} form={best[1]} uid={best[2]} iv={best[3]} cp={best[4]} shiny={best[5]}")
    else:
        print(f"  {pp:13s}  NONE - need to catch a {pp} pattern")

# Maushold check
print('\n=== Maushold gap ===')
have_maus = set(r[0] for r in c.execute("SELECT form FROM pokemon WHERE species_name='Maushold' AND in_bag=1"))
print(f"Have Maushold forms: {sorted(have_maus)} ({[fe.get(f) for f in have_maus]})")
missing_maus = {2983:'MausholdFamilyOfThree', 2984:'MausholdFamilyOfFour'}
miss = [k for k in missing_maus if k not in have_maus]
for fid in miss:
    print(f"  MISSING: {missing_maus[fid]} (form {fid})")
    rows = c.execute("""SELECT uid_hex, iv_total, cp, fresh_shiny FROM pokemon
        WHERE species_name='Tandemaus' AND in_bag=1
        ORDER BY iv_total DESC, cp DESC LIMIT 3""").fetchall()
    print(f"  Top Tandemaus to evolve (Family-of-Three is ~99%, Four is ~1%):")
    for r in rows: print(f"    uid={r[0]} iv={r[1]} cp={r[2]} shiny={r[3]}")

# Lycanroc check
print('\n=== Lycanroc gap ===')
have_lyc = set(r[0] for r in c.execute("SELECT form FROM pokemon WHERE species_name='Lycanroc' AND in_bag=1"))
print(f"Have Lycanroc forms: {sorted(have_lyc)} ({[fe.get(f) for f in have_lyc]})")
lyc_forms = {2684:'LycanrocMidday', 2685:'LycanrocMidnight', 2686:'LycanrocDusk'}
miss_lyc = [k for k in lyc_forms if k not in have_lyc]
for fid in miss_lyc:
    nm = lyc_forms[fid]
    print(f"  MISSING: {nm} (form {fid})")
    if 'Dusk' in nm:
        rows = c.execute("""SELECT uid_hex, iv_total, cp FROM pokemon
            WHERE species_name='Rockruff' AND form=2737 AND in_bag=1
            ORDER BY iv_total DESC, cp DESC LIMIT 3""").fetchall()
        print(f"  Best Own Tempo Rockruff (form 2737 = Dusk):")
        for r in rows: print(f"    uid={r[0]} iv={r[1]} cp={r[2]}")
    else:
        rows = c.execute("""SELECT uid_hex, iv_total, cp FROM pokemon
            WHERE species_name='Rockruff' AND form=2831 AND in_bag=1
            ORDER BY iv_total DESC, cp DESC LIMIT 3""").fetchall()
        print(f"  Best Normal Rockruff (form 2831, evolves day=Midday / night=Midnight):")
        for r in rows: print(f"    uid={r[0]} iv={r[1]} cp={r[2]}")

# Save uid list to evolve
out = [c[1][2] for c in candidates]  # Scatterbug/Spewpa uids
print(f"\nVivillon evolve candidates ready to tag: {len(out)}")
with open('evolve_me_uids.json','w') as f:
    json.dump({'vivillon_evolve_uids': out, 'patterns': [c[0] for c in candidates]}, f, indent=2)
