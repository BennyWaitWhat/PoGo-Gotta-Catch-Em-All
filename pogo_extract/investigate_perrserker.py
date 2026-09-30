"""Investigate Perrserker UL ranking discrepancy.

Mine: UL867 (96.40%)
Pokemod: UL635 (96.40%)
Same percentage, very different rank.
"""
import math, json
from collections import Counter

CPM = [
    0.094, 0.135137432, 0.16639787, 0.192650919, 0.21573247, 0.236572661,
    0.25572005, 0.273530381, 0.29024988, 0.306057377, 0.3210876, 0.335445036,
    0.34921268, 0.362457751, 0.37523559, 0.387592406, 0.39956728, 0.411193551,
    0.42250001, 0.432926419, 0.44310755, 0.4530599578, 0.46279839, 0.472336083,
    0.48168495, 0.4908558, 0.49985844, 0.508701765, 0.51739395, 0.525942511,
    0.53435433, 0.542635767, 0.55079269, 0.558830576, 0.56675452, 0.574569153,
    0.58227891, 0.589887907, 0.59740001, 0.604818814, 0.61215729, 0.619399365,
    0.62656713, 0.633644533, 0.64065295, 0.647576426, 0.65443563, 0.661214806,
    0.667934, 0.674577537, 0.68116492, 0.687680648, 0.69414365, 0.700538673,
    0.7068842, 0.713164996, 0.71939909, 0.725571552, 0.7317, 0.734741009,
    0.73776948, 0.740785574, 0.74378943, 0.746781211, 0.74976104, 0.752729087,
    0.7556855, 0.758630378, 0.76156384, 0.764486065, 0.76739717, 0.770297266,
    0.7731865, 0.776064962, 0.77893275, 0.781790055, 0.78463697, 0.787473578,
    0.79030001, 0.792803968, 0.79530001, 0.797800015, 0.8003, 0.802799995,
    0.8053, 0.807800014, 0.81029999, 0.812799985, 0.81529999, 0.81779999,
    0.82029998, 0.82279998, 0.82529997, 0.82779996, 0.83029996, 0.83279996,
    0.83529995, 0.83779995, 0.84029995, 0.84279995, 0.84529994
]

# Perrserker base stats
BA, BD, BS = 195, 162, 172
CAP = 2500
TARGET_IV = (14, 15, 15)

def compute_cp(ia, idf, ista, cpm):
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta_raw = (BS + ista) * cpm
    return max(10, int(atk * math.sqrt(defe) * math.sqrt(sta_raw) / 10))

def stat_product(ia, idf, ista, cpm):
    atk = (BA + ia) * cpm
    defe = (BD + idf) * cpm
    sta = math.floor((BS + ista) * cpm)
    return atk * defe * sta

def find_max_level_idx(ia, idf, ista, cap):
    for i in range(len(CPM) - 1, -1, -1):
        if compute_cp(ia, idf, ista, CPM[i]) <= cap:
            return i
    return -1

# Compute SP for all 4096 IV combos
results = []
for a in range(16):
    for de in range(16):
        for s in range(16):
            idx = find_max_level_idx(a, de, s, CAP)
            if idx < 0:
                sp = 0
                lvl = 0
                cp = 0
            else:
                sp = stat_product(a, de, s, CPM[idx])
                lvl = idx * 0.5 + 1.0
                cp = compute_cp(a, de, s, CPM[idx])
            results.append({
                'iv': (a, de, s),
                'sp': sp,
                'level': lvl,
                'cp': cp,
            })

# Sort by SP descending (Python's sort is stable, ties keep insertion order = a*256+d*16+s)
sorted_results = sorted(results, key=lambda r: -r['sp'])
max_sp = sorted_results[0]['sp']

# Find target
target_record = None
for i, r in enumerate(sorted_results):
    if r['iv'] == TARGET_IV:
        target_record = (i + 1, r)
        break

target_rank, target_data = target_record
target_sp = target_data['sp']
target_pct = target_sp / max_sp * 100

with open('perrserker_investigation.txt', 'w') as out:
    def w(s=''):
        print(s)
        out.write(s + '\n')

    w("=" * 80)
    w("PERRSERKER UL RANKING INVESTIGATION")
    w("=" * 80)
    w(f"Base stats: atk={BA}, def={BD}, hp={BS}")
    w(f"Target IVs: {TARGET_IV} (atk/def/sta)")
    w(f"CP cap: {CAP}")
    w()
    w(f"Max SP: {max_sp:.4f}")
    w(f"Target SP: {target_sp:.4f}")
    w(f"Target %: {target_pct:.4f}%")
    w(f"Target rank (Python stable sort): {target_rank}")
    w(f"  Pokemod rank: 635")
    w(f"  My code rank: 867")
    w()

    # How many ties at this exact SP?
    ties_exact = [r for r in results if r['sp'] == target_sp]
    w(f"Records with EXACT same SP as target: {len(ties_exact)}")
    if len(ties_exact) <= 20:
        for r in ties_exact:
            w(f"  iv={r['iv']} sp={r['sp']:.4f} L{r['level']} CP{r['cp']}")
    w()

    # Group by percentage rounded to 2 decimals
    pct_values = Counter()
    for r in results:
        if max_sp:
            pct = round(r['sp'] / max_sp * 100, 2)
            pct_values[pct] += 1
    same_pct = pct_values.get(96.40, 0)
    w(f"Records that round to 96.40% (2-decimal display): {same_pct}")
    w()

    # Show window around target rank
    w("Records ranked 600-900 (around the discrepancy zone):")
    w(f"{'rank':>5} {'iv':>12} {'sp':>14} {'pct':>8} {'level':>5} {'cp':>5}")
    for i in range(599, min(900, len(sorted_results))):
        r = sorted_results[i]
        pct = r['sp'] / max_sp * 100
        marker = ' <-- TARGET' if r['iv'] == TARGET_IV else ''
        if 625 <= i+1 <= 645 or 860 <= i+1 <= 880 or r['iv'] == TARGET_IV:
            w(f"{i+1:>5} {str(r['iv']):>12} {r['sp']:>14.4f} {pct:>7.4f}% L{r['level']:>3.1f} {r['cp']:>5}{marker}")
    w()

    # Key question: how does Pokemod tiebreak?
    # Pokemod likely uses a specific tiebreak order. Let's investigate ties around rank 635-867.
    w("Look at records with VERY close SP (within 0.001) around the target:")
    nearby = sorted([(i+1, r) for i, r in enumerate(sorted_results)
                     if abs(r['sp'] - target_sp) < 0.001],
                    key=lambda x: x[0])
    w(f"  Found {len(nearby)} records within 0.001 SP of target")
    if len(nearby) <= 50:
        for rank, r in nearby:
            pct = r['sp'] / max_sp * 100
            marker = ' <-- TARGET' if r['iv'] == TARGET_IV else ''
            w(f"  rank={rank} iv={r['iv']} sp={r['sp']:.6f} pct={pct:.4f}% L{r['level']} CP{r['cp']}{marker}")
    w()

    # Now: between rank 635 and 867, what's the SP range?
    w("Block from rank 635 to 870 - SP and level distribution:")
    sp_at_635 = sorted_results[634]['sp']
    sp_at_867 = sorted_results[866]['sp']
    w(f"  SP at rank 635: {sp_at_635:.6f}")
    w(f"  SP at rank 867: {sp_at_867:.6f}")
    w(f"  diff: {sp_at_635 - sp_at_867:.6f} ({(sp_at_635-sp_at_867)/max_sp*100:.6f}%)")
    w()

    # See exactly how many records between 635 and 867 share SP with target
    # Crucially: is there a big block of identical SP from rank 635 to ~867?
    in_block = [(i+1, sorted_results[i]) for i in range(634, 867)]
    sp_set = set(r['sp'] for _, r in in_block)
    w(f"  Distinct SP values in rank 635..867: {len(sp_set)}")
    sp_target_count_in_block = sum(1 for _, r in in_block if r['sp'] == target_sp)
    w(f"  Records in rank 635..867 with EXACT target SP: {sp_target_count_in_block}")
    w()

    # Hypothesis test: maybe Pokemod sorts ties by some other tiebreak (e.g., level desc, then CP desc, then IV order)
    # Try alternative sorts to see which produces rank 635
    w("=" * 80)
    w("ALTERNATIVE TIEBREAK HYPOTHESES")
    w("=" * 80)

    def find_target_rank(sort_key, desc='?'):
        sr = sorted(results, key=sort_key)
        for i, r in enumerate(sr):
            if r['iv'] == TARGET_IV:
                return i + 1, desc
        return None, desc

    # Hypothesis 1: SP desc, then level asc (lower-level wins ties = harder to find)
    r1, d1 = find_target_rank(lambda r: (-r['sp'], r['level']), 'SP desc, then level asc')
    w(f"  SP desc, then level asc: rank {r1}")

    # Hypothesis 2: SP desc, then level desc
    r2, d2 = find_target_rank(lambda r: (-r['sp'], -r['level']), 'SP desc, then level desc')
    w(f"  SP desc, then level desc: rank {r2}")

    # Hypothesis 3: SP desc, then CP desc
    r3, _ = find_target_rank(lambda r: (-r['sp'], -r['cp']), 'SP desc, then CP desc')
    w(f"  SP desc, then CP desc: rank {r3}")

    # Hypothesis 4: SP desc, then CP asc
    r4, _ = find_target_rank(lambda r: (-r['sp'], r['cp']), 'SP desc, then CP asc')
    w(f"  SP desc, then CP asc: rank {r4}")

    # Hypothesis 5: SP desc, then atk IV desc
    r5, _ = find_target_rank(lambda r: (-r['sp'], -r['iv'][0]), 'SP desc, then atk IV desc')
    w(f"  SP desc, then atk IV desc: rank {r5}")

    # Hypothesis 6: SP desc, then atk IV asc
    r6, _ = find_target_rank(lambda r: (-r['sp'], r['iv'][0]), 'SP desc, then atk IV asc')
    w(f"  SP desc, then atk IV asc: rank {r6}")

    # Hypothesis 7: round SP differently
    # Pokemod might round SP to integer or to a specific precision before sorting
    for digits in [0, 1, 2, 3, 4]:
        sr = sorted(results, key=lambda r: -round(r['sp'], digits))
        for i, rr in enumerate(sr):
            if rr['iv'] == TARGET_IV:
                w(f"  round SP to {digits} digits, then sort desc: rank {i+1}")
                break

    # Hypothesis 8: maybe Pokemod uses CP*something*level
    # Or uses a different tiebreak on the *original* unfloored SP
    w()
    w("Hypothesis: Pokemod might use unfloored stat product")

    def stat_product_unfloored(ia, idf, ista, cpm):
        atk = (BA + ia) * cpm
        defe = (BD + idf) * cpm
        sta = (BS + ista) * cpm  # not floored
        return atk * defe * sta

    results_uf = []
    for a in range(16):
        for de in range(16):
            for s in range(16):
                idx = find_max_level_idx(a, de, s, CAP)
                if idx < 0:
                    sp = 0
                else:
                    sp = stat_product_unfloored(a, de, s, CPM[idx])
                results_uf.append({'iv': (a, de, s), 'sp': sp})
    sr_uf = sorted(results_uf, key=lambda r: -r['sp'])
    for i, r in enumerate(sr_uf):
        if r['iv'] == TARGET_IV:
            w(f"  unfloored stat product, sort desc: rank {i+1}")
            max_sp_uf = sr_uf[0]['sp']
            w(f"    pct: {r['sp']/max_sp_uf*100:.4f}%")
            break

    # Hypothesis 9: Pokemod's PvPoke approach - what if there's a half-step CP cap rounding diff?
    # PvPoke uses level * 2 increments. Let me also compute under floor but sort by exact SP.
    # The 96.40% display means it's truncated to 2 decimals. Many distinct SPs round to 96.40%.
    # If Pokemod's "rank" is actually the rank when grouping ties, maybe it counts blocks differently.

    # Hypothesis 10: rank with BLOCK-WISE counting ("dense rank")
    # = count of distinct SPs strictly greater than target_sp + 1
    distinct_sps = sorted(set(r['sp'] for r in results), reverse=True)
    dense_rank = next((i+1 for i, s in enumerate(distinct_sps) if s == target_sp), None)
    w(f"  Dense rank (count of distinct SPs >= target): {dense_rank}")

    # Hypothesis 11: average rank for ties
    # = position of first tied + (count-1)/2 or similar
    first_tie = next(i+1 for i, r in enumerate(sorted_results) if r['sp'] == target_sp)
    last_tie = max(i+1 for i, r in enumerate(sorted_results) if r['sp'] == target_sp)
    avg_tie = (first_tie + last_tie) / 2
    w(f"  Average rank (first/last/avg of ties): first={first_tie}, last={last_tie}, avg={avg_tie}")

    # CRITICAL: in PvPoke source code, the rank is the LAST occurrence of the SP value (i.e., 1-indexed
    # with all tied entries collapsed to the same rank = the final position). Or the first?
    # Actually PvPoke counts using simple sort and 1-indexed array position - so ties get sequential ranks.
    # Pokemod might be doing something else. Let me check what value 635 corresponds to.

    w()
    w("=" * 80)
    w("WHAT IS RANK 635?")
    w("=" * 80)
    r635 = sorted_results[634]
    pct635 = r635['sp'] / max_sp * 100
    w(f"  iv={r635['iv']} sp={r635['sp']:.6f} pct={pct635:.4f}% L{r635['level']} CP{r635['cp']}")

    # And if I sort by stable order with insertion key = a*256+d*16+s, where does 14/15/15 land?
    # 14*256+15*16+15 = 3584+240+15 = 3839
    # That's deep in the list. Among ties with same SP, it would be late.

    # Alternative: maybe Pokemod sorts ties by IV combo in REVERSE (15/15/15 first, lower last)
    # Let me try that.
    r_pkmd, _ = find_target_rank(lambda r: (-r['sp'], -(r['iv'][0]*256+r['iv'][1]*16+r['iv'][2])),
                                   'SP desc, then IV-encoded desc (15/15/15 first within ties)')
    w(f"  SP desc, then IV-encoded desc: rank {r_pkmd}")

    r_pkmd2, _ = find_target_rank(lambda r: (-r['sp'], r['iv'][0]*256+r['iv'][1]*16+r['iv'][2]),
                                   'SP desc, then IV-encoded asc (0/0/0 first within ties)')
    w(f"  SP desc, then IV-encoded asc: rank {r_pkmd2}")

    w()
    w("=" * 80)
    w("EXAMINE TIES AT TARGET SP")
    w("=" * 80)
    target_ties = [r for r in results if abs(r['sp'] - target_sp) < 1e-9]
    w(f"  Records with same SP: {len(target_ties)}")
    for tr in target_ties:
        encoded = tr['iv'][0]*256 + tr['iv'][1]*16 + tr['iv'][2]
        w(f"    iv={tr['iv']} encoded={encoded}")

    w()
    w("=" * 80)
    w("OFF-BY-EXACT-232 ANALYSIS")
    w("=" * 80)
    diff = 867 - 635
    w(f"Diff = 867 - 635 = {diff}")
    w(f"Records between rank 635 and 867 (exclusive): {867-635-1}")
    # Count distinct SPs in that range
    block_sps = set()
    for i in range(634, 867):
        block_sps.add(round(sorted_results[i]['sp'], 6))
    w(f"Distinct rounded SPs in rank 635..866: {len(block_sps)}")
    # Distribution of "%"
    pcts_block = Counter()
    for i in range(634, 867):
        pcts_block[round(sorted_results[i]['sp']/max_sp*100, 2)] += 1
    w(f"  pct distribution in block: {dict(pcts_block)}")

    w()
    w("=" * 80)
    w("SUMMARY")
    w("=" * 80)
print(f"Wrote: perrserker_investigation.txt")
