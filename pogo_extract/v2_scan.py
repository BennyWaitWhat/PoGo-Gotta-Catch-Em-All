"""
Comprehensive offset scan v2 - exhaustive byte-level statistics.

For every offset 0-508 not in known set, compute stats at multiple interpretations:
  - 1 byte (count of value=1, of nonzero)
  - 4-byte i32
  - 4-byte f32
  - 8-byte i64
  - 8-byte f64

Output CSV + a summary report.
"""
import json, struct, math
from collections import Counter
from datetime import datetime, timezone

POGO_LAUNCH_MS = 1467590400000
NOW_MS = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

# Already mapped (4-byte aligned positions known to hold field data)
ALREADY_MAPPED = {32, 40, 44, 48, 52, 56, 60, 92, 104, 108, 112, 116, 120, 124, 128,
                  136, 144, 160, 168, 172, 196, 200, 225, 248, 264, 272, 276, 296,
                  336, 340, 344, 348, 352, 440, 480, 496}
# String-ptr 8-byte offsets known
KNOWN_STR_PTR = {64, 184, 256, 304, 360, 384}

print("Loading pokemon_v3.json...")
data = json.load(open('pokemon_v3.json'))
print(f"  {len(data)} pokemon")

all_bytes = []
all_uids = []
for p in data:
    raw = p.get('raw_proto', '')
    if len(raw) >= 1024:
        all_bytes.append(bytes.fromhex(raw))
        try:
            uid = struct.unpack_from('<Q', all_bytes[-1], 32)[0]
            all_uids.append(uid)
        except:
            all_uids.append(0)

N = len(all_bytes)
print(f"  {N} have 512+ byte protos\n")

# Build per-offset results dict
results = []  # list of dicts

for off in range(0, 509):
    rec = {'off': off}

    # 1-byte view
    bvals = [bs[off] for bs in all_bytes if off < len(bs)]
    bnz = sum(1 for v in bvals if v != 0)
    bones = sum(1 for v in bvals if v == 1)
    btwos = sum(1 for v in bvals if v == 2)
    rec['b_nz'] = bnz
    rec['b_eq1'] = bones
    rec['b_eq2'] = btwos
    rec['b_distinct'] = len(set(bvals))
    rec['b_top'] = Counter(bvals).most_common(5)

    # 4-byte i32
    if off + 4 <= 512:
        ivals = [struct.unpack_from('<i', bs, off)[0] for bs in all_bytes if off + 4 <= len(bs)]
        i_nz = sum(1 for v in ivals if v != 0)
        i_distinct = len(set(ivals))
        i_min = min(ivals) if ivals else 0
        i_max = max(ivals) if ivals else 0
        rec['i_nz'] = i_nz
        rec['i_distinct'] = i_distinct
        rec['i_min'] = i_min
        rec['i_max'] = i_max
        rec['i_top'] = Counter(v for v in ivals if v != 0).most_common(5)
        rec['i_vals'] = ivals  # for cross-correlation later

        # 4-byte f32
        fvals = [struct.unpack_from('<f', bs, off)[0] for bs in all_bytes if off + 4 <= len(bs)]
        f_pos_finite = sum(1 for v in fvals if v == v and 0.0001 < v < 1e6 and not math.isinf(v))
        f_neg_finite = sum(1 for v in fvals if v == v and -1e6 < v < -0.0001 and not math.isinf(v))
        f_in_001_5 = sum(1 for v in fvals if v == v and 0.0001 < v < 5)  # CPMs / friendship norm
        f_in_5_100 = sum(1 for v in fvals if v == v and 5 <= v < 100)   # km / friendship score
        f_in_100_5000 = sum(1 for v in fvals if v == v and 100 <= v < 5000)
        rec['f_pos'] = f_pos_finite
        rec['f_neg'] = f_neg_finite
        rec['f_001_5'] = f_in_001_5
        rec['f_5_100'] = f_in_5_100
        rec['f_100_5000'] = f_in_100_5000
        rec['f_vals'] = fvals
    else:
        rec.update({'i_nz': 0, 'i_distinct': 0, 'i_min': 0, 'i_max': 0, 'i_top': [], 'i_vals': [],
                    'f_pos': 0, 'f_neg': 0, 'f_001_5': 0, 'f_5_100': 0, 'f_100_5000': 0, 'f_vals': []})

    # 8-byte i64 (timestamp candidate)
    if off + 8 <= 512:
        qvals = [struct.unpack_from('<q', bs, off)[0] for bs in all_bytes if off + 8 <= len(bs)]
        q_ts_count = sum(1 for v in qvals if POGO_LAUNCH_MS < v < NOW_MS + 86400000)
        q_nz = sum(1 for v in qvals if v != 0)
        q_distinct = len(set(qvals))
        rec['q_nz'] = q_nz
        rec['q_distinct'] = q_distinct
        rec['q_ts_count'] = q_ts_count
        rec['q_top'] = Counter(v for v in qvals if v != 0).most_common(5)
        rec['q_vals'] = qvals
    else:
        rec.update({'q_nz': 0, 'q_distinct': 0, 'q_ts_count': 0, 'q_top': [], 'q_vals': []})

    results.append(rec)

# Save the raw results to a pickle for downstream use
import pickle
pickle.dump({'results': results, 'uids': all_uids, 'N': N}, open('v2_scan_results.pkl', 'wb'))

# ============================
# Print summary tables
# ============================

# 1) Offsets with notable boolean signal (rare 1-byte=1)
print("=" * 110)
print("BOOLEAN-LIKE OFFSETS (1-byte values, where eq1 count is 5..1500 and dominant byte=0 or 1):")
print("=" * 110)
print(f"{'Off':>4} {'eq1':>5} {'eq2':>5} {'NZ':>5} {'Dist':>5} {'AlreadyMapped':>13}  TopBytes")
for r in results:
    off = r['off']
    if 5 <= r['b_eq1'] <= 1500 and r['b_distinct'] <= 6 and r['b_eq1'] >= r['b_eq2']:
        m = '*' if off in ALREADY_MAPPED else ''
        in_strptr = any(off >= sp and off < sp + 8 for sp in KNOWN_STR_PTR)
        m += ' (str)' if in_strptr else ''
        print(f"{off:>4} {r['b_eq1']:>5} {r['b_eq2']:>5} {r['b_nz']:>5} {r['b_distinct']:>5} {m:>13}  {r['b_top']}")

# 2) Offsets with notable i32 signal (nz between 5 and 4000, distinct > 5)
print()
print("=" * 110)
print("I32 OFFSETS (nz=5..5000, distinct>=5; potential counters/IDs):")
print("=" * 110)
print(f"{'Off':>4} {'NZ':>5} {'Dist':>5} {'Min':>11} {'Max':>11} {'Marked':>8}  TopVals")
for r in results:
    off = r['off']
    if r['i_nz'] >= 5 and r['i_distinct'] >= 5 and r['i_nz'] <= 5000:
        # exclude if value range looks like garbage 32-bit pointer (huge min/max)
        if r['i_min'] < -1e9 or r['i_max'] > 1e9:
            continue
        m = '*' if off in ALREADY_MAPPED else ''
        in_strptr = any(off >= sp and off < sp + 8 for sp in KNOWN_STR_PTR)
        m += '(str)' if in_strptr else ''
        # also not aligned to 4? note it
        if off % 4 != 0: m += '!unalign'
        top3 = r['i_top'][:3]
        print(f"{off:>4} {r['i_nz']:>5} {r['i_distinct']:>5} {r['i_min']:>11} {r['i_max']:>11} {m:>8}  {top3}")

# 3) Float candidates (positive finite count interesting)
print()
print("=" * 110)
print("F32 OFFSETS (where many values are positive finite reals):")
print("=" * 110)
print(f"{'Off':>4} {'fPos':>5} {'in0-5':>6} {'in5-100':>7} {'in100-5k':>8} {'iNZ':>5} {'Marked':>8}  Sample floats")
for r in results:
    off = r['off']
    if r['f_pos'] >= 30 and (r['f_001_5'] >= 30 or r['f_5_100'] >= 30 or r['f_100_5000'] >= 30):
        m = '*' if off in ALREADY_MAPPED else ''
        in_strptr = any(off >= sp and off < sp + 8 for sp in KNOWN_STR_PTR)
        m += '(str)' if in_strptr else ''
        if off % 4 != 0: m += '!unalign'
        # Get a few example floats
        samples = [round(v, 4) for v in r['f_vals'][:200] if v == v and 0.0001 < v < 1e6][:5]
        print(f"{off:>4} {r['f_pos']:>5} {r['f_001_5']:>6} {r['f_5_100']:>7} {r['f_100_5000']:>8} {r['i_nz']:>5} {m:>8}  {samples}")

# 4) Timestamp candidates
print()
print("=" * 110)
print("TIMESTAMP CANDIDATES (i64 in valid PoGo range, count>=10):")
print("=" * 110)
print(f"{'Off':>4} {'TSct':>5} {'NZ':>5} {'Dist':>5} {'Marked':>8}  Sample TS")
for r in results:
    off = r['off']
    if r['q_ts_count'] >= 10:
        m = '*' if off in ALREADY_MAPPED else ''
        in_strptr = any(off >= sp and off < sp + 8 for sp in KNOWN_STR_PTR)
        m += '(str)' if in_strptr else ''
        # one example TS
        ts_sample = next((v for v in r['q_vals'] if POGO_LAUNCH_MS < v < NOW_MS + 86400000), 0)
        try:
            dt = datetime.fromtimestamp(ts_sample/1000, tz=timezone.utc).isoformat() if ts_sample else '-'
        except:
            dt = '?'
        print(f"{off:>4} {r['q_ts_count']:>5} {r['q_nz']:>5} {r['q_distinct']:>5} {m:>8}  {ts_sample} ({dt})")

print()
print("Done. Saved v2_scan_results.pkl for downstream cross-correlation.")
