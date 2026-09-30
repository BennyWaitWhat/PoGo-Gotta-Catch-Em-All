"""WHICH POKEMON ARE OFFERED FOR REMOTE TRADE -- one definition, used by the pusher and the report.

User 2026-09-19, in order: "Any shiny that I have more than 2 of, list the other lower iv ones for remote trade" ->
"make this a part of your cull every time to update it" -> "everyone, not just 3 shinies. keep the top 2 iv shinies"
-> "i save pokemon specifically just to have high quality trades" -> "a cap of 3 or 6 for each pokemon regardless if
shiny or not" -> "fix everything now that you're seeing whats wrong".

THE RULE
  * Group by COSMETIC VARIANT -- species, form, costume, art background, Dynamax/Gigantamax and shiny -- not by
    species alone. A group holding 2 or fewer offers nothing, so a costume you own twice is never touched. (Grouping
    by species+form offered 64 Pikachu, including copies that were the BEST of their own costume.)
  * Keep the best 2 by IV of each variant; every other copy is a candidate.
  * A candidate is offered only when being a SPARE COPY is the only thing keeping it: reasons exactly {shiny} for a
    shiny, exactly {variant_floor} for a non-shiny. That is what his rules hold as trade stock -- never a PvP asset,
    a legacy mover, a background, an XXL, an Adventure-Effect form, a trophy or anything else with a job.
  * Never a mon the in-game labels call irreplaceable: Variant #1, Shiny - Only One, Last Copy.
  * Never a mon in the release pile, already traded or lucky (one trade per Pokemon), a shadow (cannot be traded), a
    species the game master marks untradable, or one caught in the last 30 days (remote trades have a catch lockout).
  * Finally, at most SPECIES_CAP offers per species, best IV first.

Read-only: the bag DB, policy_reasons.json, the release pile, the client game master, form_enum.json.
"""
import collections, json, os, re, sqlite3, time

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP_BEST = 2          # the best 2 of each variant are never offered
SPECIES_CAP = 3        # ... and at most this many offers per species (user 2026-09-19: "make it 3")
LOCKOUT_DAYS = 30      # remote-trade catch lockout
NEVER_TAGS = ('Variant #1', 'Shiny - Only One')   # 'Last Copy' chip retired 2026-09-23; a last copy carries
#                                                   dex_only_copy, so SOLE_REASON already refuses to offer it
SOLE_REASON = ({'shiny'}, {'variant_floor'}, {'rarity'})   # a spare copy and nothing more -- 'rarity' is the
#                  legendary/mythical/UB/paradox cap, added 2026-09-19 ("in the remote trade stuff can you list
#                  legendaries and stuff"): a spare legendary inside its cap is stock like any other spare copy.
_norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())
_TRADABLE = None


def _tradable_tables():
    global _TRADABLE
    if _TRADABLE is None:
        by_form, by_dex = {}, {}
        for t in json.load(open(os.path.join(HERE, 'gamemaster_pokeminers.json'), encoding='utf-8')):
            s = (t.get('data') or {}).get('pokemonSettings')
            m = re.match(r'V(\d{4})_POKEMON_', t.get('templateId', ''))
            if not s or not m:
                continue
            if s.get('form'):
                by_form[_norm(s['form'])] = s.get('isTradable', True)
            else:
                by_dex.setdefault(int(m.group(1)), s.get('isTradable', True))
        _TRADABLE = (by_form, by_dex)
    return _TRADABLE


def variant_key(r):
    """The cosmetic variant, the same axes the keep rule caps -- plus shiny, which is its own collectible."""
    return (r['pokemon_id'], r['fresh_form'] or r['form'] or 0, r['fresh_costume'] or 0,
            r['fresh_natural_art_bg'] or 0,
            r['fresh_bread_mode'] or 0,   # every Max mode is its own bundle (evolvable_forms.BREAD_MODES)
            bool(r['fresh_shiny']))


def compute(rows=None, now=None):
    """-> (uids, stats). `rows` = in-bag dict rows; read from pokemon.db when omitted."""
    if rows is None:
        c = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'pokemon.db').replace(chr(92), '/'), uri=True)
        c.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in c.execute('SELECT * FROM pokemon WHERE in_bag=1 AND COALESCE(is_component,0)=0')]   # (2026-09-26) fused components hold no ladder slot
        finally:
            c.close()
    now = now or time.time()
    enum = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'form_enum.json'), encoding='utf-8')).items()}
    by_form, by_dex = _tradable_tables()
    try:
        pol = {u: set(v) for u, v in json.load(open(os.path.join(HERE, 'system', 'analysis', 'policy_reasons.json'),
                                                    encoding='utf-8')).items() if isinstance(v, list)}
        pile = set(open(os.path.join(HERE, 'system', 'analysis', 'tagsets', '6_Transfer.txt')).read().split())
    except Exception:
        return [], collections.Counter({'no keep reasons -- nothing offered': 1})

    def tradable(r):
        f = r['fresh_form'] or r['form'] or 0
        v = by_form.get(_norm(enum.get(f, ''))) if f else None
        return by_dex.get(r['pokemon_id'], True) if v is None else v

    def days(r):
        try:
            return (now - int(r['creation_time_ms']) / 1000) / 86400
        except Exception:
            return 999.0

    g = collections.defaultdict(list)
    for r in rows:
        g[variant_key(r)].append(r)
    picks, stats = [], collections.Counter()
    for lst in g.values():
        if len(lst) <= KEEP_BEST:
            stats['variant groups of 2 or fewer (untouched)'] += 1
            continue
        stats['variant groups over 2'] += 1
        for r in sorted(lst, key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))[KEEP_BEST:]:
            stats['spare copies'] += 1
            if r['uid_hex'] in pile:
                stats['in the release pile'] += 1
            elif r['is_traded'] or r['is_traded_flag_v2'] or r['is_lucky']:
                stats['already traded or lucky'] += 1
            elif r['fresh_alignment'] == 1:
                stats['shadow'] += 1
            elif not tradable(r):
                stats['untradable species'] += 1
            elif any(t in str(r['auth_tag_names'] or '') for t in NEVER_TAGS):
                stats['tagged #1 / only one / last copy'] += 1
            elif pol.get(r['uid_hex']) not in SOLE_REASON:
                stats['kept for a reason of its own'] += 1
            elif days(r) <= LOCKOUT_DAYS:
                stats['caught in the last 30 days'] += 1
            else:
                picks.append(r)
    per = collections.defaultdict(list)
    for r in picks:
        per[r['pokemon_id']].append(r)
    capped = []
    for v in per.values():
        v.sort(key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0)))
        stats['over the per-species cap'] += max(0, len(v) - SPECIES_CAP)
        capped += v[:SPECIES_CAP]
    stats['offered'] = len(capped)
    stats['species'] = len(per)
    return sorted(r['uid_hex'] for r in capped), stats


if __name__ == '__main__':
    uids, st = compute()
    print('Remote Trade offers: %d (cap %d per species, best 2 of each variant kept)' % (len(uids), SPECIES_CAP))
    for k, v in sorted(st.items()):
        print('   %-42s %d' % (k, v))
