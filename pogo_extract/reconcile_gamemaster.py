"""MAKE THE GAME AUTHORITATIVE OVER pvpoke (user 2026-09-20: "Dig into the game further and double check
every thing" / "leverage it if it means improvement").

pvpoke's gamemaster is a community file about the PvP metagame; `gamemaster_pokeminers.json` is the client's
OWN game master. Where they disagree, the game is right, and this project ranks, caps and culls on pvpoke's
copy. Measured on the live bag, pvpoke was wrong in two ways that reach a keep decision:

  BASE STATS   1 of 1,191 stat lines disagreed -- dugtrio def 136 (pvpoke) vs 134 (the game) -- and 14 in-bag
               rows rank on it. A wrong base stat is a wrong stat product is a wrong league rank.
  EVOLUTIONS   pvpoke's `family.evolutions` MISSES edges the game has: corsola_galarian has no family at all
               (the game evolves it to Cursola), zygarde has none (-> zygarde_complete), poltchageist's edge is
               recorded BACKWARDS on sinistcha. rank_cache._reachable() trims stages the game forbids, so
               pvpoke claiming too much is already handled -- but it can only ever REMOVE, so an edge pvpoke
               LACKS is invisible: that mon is ranked as if it were a final stage and its real later stage is
               never scored. That is the under-protection direction, the one that releases a keeper.

ADDITIVE ONLY on edges. Nothing is ever deleted: `_reachable()` is the remover and it reads the game directly,
so removing here would only risk dropping a stage on a mapping miss. Base stats ARE overwritten, but only when
the pvpoke id matched a game template by NAME (never by a dex-only guess), and every change is printed.

  python reconcile_gamemaster.py [--dry-run]
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())


def game_tables():
    """norm(form|pokemonId) -> {'stats': (a,d,s), 'evo': [(form_key, species_key), ...]}

    A VARIANT template must never fill in the BASE species key. Letting CORSOLA_GALARIAN's branch answer for
    'CORSOLA' handed a Kantonian Corsola a Cursola stage, and FARFETCHD_GALARIAN handed a Kantonian
    Farfetch'd a Sirfetch'd -- five wrong edges on the first draft of this file. The base key is filled only
    by a template with no form at all, or by <SPECIES>_NORMAL, which IS the base form."""
    out, owners, by_id = {}, {}, {}
    for t in json.load(open(os.path.join(HERE, 'gamemaster_pokeminers.json'), encoding='utf-8')):
        s = (t.get('data') or {}).get('pokemonSettings')
        if not s or not re.match(r'V\d{4}_POKEMON_', t.get('templateId', '')):
            continue
        st = s.get('stats') or {}
        rec = {'stats': (st.get('baseAttack'), st.get('baseDefense'), st.get('baseStamina')),
               'evo': [(norm(b.get('form') or ''), norm(b.get('evolution')))
                       for b in (s.get('evolutionBranch') or []) if b.get('evolution')]}
        is_normal = bool(s.get('form')) and norm(s['form']) == norm(s['pokemonId']) + 'NORMAL'
        keys = [(norm(s['form']), True)] if s.get('form') else []
        if s.get('form'):
            owners.setdefault(norm(s['form']), set()).add(norm(s['pokemonId']))
            by_id.setdefault(norm(s['pokemonId']), dict(rec, strong=False))
        if not s.get('form') or is_normal:
            keys.append((norm(s['pokemonId']), is_normal))
        for k, strong in keys:
            if k not in out:
                out[k] = dict(rec); out[k]['strong'] = strong
            else:
                # <SPECIES>_NORMAL OUTRANKS THE FORMLESS TEMPLATE (2026-09-20). The game ships both for many
                # species and they are NOT always equal: V0051_POKEMON_DUGTRIO says baseDefense 134 while
                # V0051_POKEMON_DUGTRIO_NORMAL says 136, and every Kantonian Dugtrio in the bag is form 61 =
                # DugtrioNormal, whose stored CP only reconstructs at 136. Taking whichever template the file
                # listed first "corrected" pvpoke to the stale number and audit_invariants BLOCKed it -- which
                # is the check doing its job. The form the game actually assigns is the authority.
                if strong and not out[k].get('strong'):
                    out[k] = dict(rec); out[k]['strong'] = True
                elif not out[k]['evo'] and rec['evo']:
                    out[k]['evo'] = rec['evo']
    # A FORM NAME SHARED BY TWO SPECIES answers for neither (2026-09-26): NIDORAN_NORMAL is the form of BOTH Nidorans, and
    # the first template won -- Nidoran M was handed Nidoran F's branch (an edge nidoran_male -> nidorina). Drop the
    # shared key; each species then answers by its own pokemonId (NIDORANMALE / NIDORANFEMALE).
    for k, ids in owners.items():
        if len(ids) > 1:
            out.pop(k, None)
            for i in ids:
                out.setdefault(i, by_id[i])
    return out


def bag_bridge():
    """norm(live Form enum name) -> the pvpoke speciesId this project ranks that form as.

    Name matching alone cannot connect pvpoke's 'zygarde' to the game's ZYGARDE_FIFTY_PERCENT, or
    'poltchageist' to POLTCHAGEIST_COUNTERFEIT -- and those are exactly the two rows whose real evolution
    pvpoke is missing. The bag knows the answer: to_pvpoke_id() is the mapping the ranker itself uses, and the
    Form enum names the same form the game does. Covers every form actually held, which is the set that can
    cost a keeper."""
    import sqlite3
    sys.path.insert(0, os.path.join(HERE, 'system', 'scripts'))
    import rank_cache as rc
    enum = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'form_enum.json'), encoding='utf-8')).items()}
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'pokemon.db').replace(chr(92), '/'), uri=True)
    try:
        pairs = con.execute('SELECT DISTINCT species_name, form FROM pokemon WHERE in_bag=1').fetchall()
    finally:
        con.close()
    out = {}
    for sp, form in pairs:
        sid = rc.to_pvpoke_id(sp, form, 0)
        k = norm(enum.get(int(form or 0), ''))
        if sid and k:
            out.setdefault(k, sid)
    return out


def pv_key(sid):
    """The game keys a pvpoke speciesId could be spelled as, best first."""
    return [norm(sid),
            norm(sid.replace('_alolan', '_alola').replace('_paldean', '_paldea')),
            norm(sid + '_normal'),
            norm(sid.replace('_alolan', '_alola') + '_normal')]


def main():
    G = game_tables()
    BRIDGE = bag_bridge()
    path = os.path.join(HERE, 'pvpoke_gamemaster.json')
    gm = json.load(open(path, encoding='utf-8'))
    by_sid = {p['speciesId']: p for p in gm['pokemon']}

    # game key -> pvpoke speciesId, preferring the shortest id (plain 'corsola' over a costume spelling)
    k2sid = dict(BRIDGE)
    for p in gm['pokemon']:
        if '_shadow' in p['speciesId']:
            continue
        for k in pv_key(p['speciesId']):
            if k in G and (k not in k2sid or len(p['speciesId']) < len(k2sid[k])):
                k2sid[k] = p['speciesId']
    sid2keys = {}
    for k, v in BRIDGE.items():
        sid2keys.setdefault(v, []).append(k)

    stat_fix, edge_add, unmapped, reversed_fix = [], [], [], []
    for p in gm['pokemon']:
        sid = p['speciesId']
        if '_shadow' in sid:
            continue
        g = next((G[k] for k in pv_key(sid) if k in G), None)
        # ...and the form(s) the BAG says this id is, which is how zygarde finds ZYGARDE_FIFTY_PERCENT
        gevo = list(g['evo']) if g else []
        for k in sid2keys.get(sid, []):
            for e in (G.get(k) or {}).get('evo', []):
                if e not in gevo:
                    gevo.append(e)
        if not g and not gevo:
            continue
        g = g or {'stats': (None, None, None)}
        # ---- base stats: the game is the authority
        b = p.get('baseStats') or {}
        cur = (b.get('atk'), b.get('def'), b.get('hp'))
        if None not in g['stats'] and None not in cur and g['stats'] != cur:
            stat_fix.append((sid, cur, g['stats']))
            b['atk'], b['def'], b['hp'] = g['stats']
        # ---- evolution edges: ADD what the game has and pvpoke lacks
        want = []
        for fk, spk in gevo:
            # the form key names the exact target (OINKOLOGNE_FEMALE); the species key is the fallback for a
            # target pvpoke models as one entry (DUDUNSPARCE_TWO/THREE are both pvpoke's 'dudunsparce')
            t = (k2sid.get(fk) or k2sid.get(re.sub('NORMAL$', '', fk)) or k2sid.get(spk)
                 or k2sid.get(re.sub('NORMAL$', '', spk)))
            if t is None:
                unmapped.append((sid, fk or spk))
            elif t != sid and t not in want:
                want.append(t)
        if not want:
            continue
        fam = p.get('family') or {}
        have = list(fam.get('evolutions') or [])
        new = [t for t in want if t not in have]
        if new:
            # A REVERSED EDGE IS NOT AN EDGE. pvpoke files poltchageist's evolution on sinistcha, pointing back
            # at poltchageist; adding the real direction on top of that makes a 2-cycle that recursed the ranker
            # to death. Only ever drop the reverse when the GAME has no such branch -- then it is not pvpoke
            # modelling something we missed, it is pvpoke being backwards.
            for t in new:
                tp = by_sid.get(t) or {}
                tfam = tp.get('family') or {}
                if sid in (tfam.get('evolutions') or []):
                    gt = next((G[k] for k in pv_key(t) if k in G), None)
                    gtk = [a or b for a, b in ((gt or {}).get('evo') or [])]
                    if not any(k2sid.get(k) == sid or k2sid.get(re.sub('NORMAL$', '', k)) == sid for k in gtk):
                        tfam['evolutions'] = [e for e in tfam['evolutions'] if e != sid]
                        reversed_fix.append((t, sid))
            edge_add.append((sid, have, new))
            fam['evolutions'] = have + new
            fam.setdefault('id', 'FAMILY_%s' % norm(sid))
            p['family'] = fam

    print('BASE STATS corrected from the game: %d' % len(stat_fix))
    for sid, a, b in sorted(stat_fix):
        print('   %-28s pvpoke %-18s -> GAME %s' % (sid, a, b))
    print('REVERSED edges dropped (the game declares the opposite direction): %d' % len(reversed_fix))
    for t, sid in sorted(reversed_fix):
        print('   %-28s no longer claims %r as an evolution' % (t, sid))
    print('EVOLUTION EDGES added (additive only, never removed): %d' % len(edge_add))
    for sid, have, new in sorted(edge_add):
        print('   %-28s %s + %s' % (sid, have or '[]', new))
    if unmapped:
        seen = sorted({'%s -> %s' % (s, k) for s, k in unmapped})
        print('game targets with NO pvpoke entry (left alone, cannot be ranked): %d  e.g. %s'
              % (len(seen), '; '.join(seen[:6])))
    if '--dry-run' in sys.argv:
        print('--dry-run: pvpoke_gamemaster.json NOT written.')
        return 0
    if not stat_fix and not edge_add and not reversed_fix:
        print('nothing to reconcile -- pvpoke already agrees with the game.')
        return 0
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(gm, f, ensure_ascii=False)
    os.replace(tmp, path)
    print('pvpoke_gamemaster.json rewritten (%d stat fix, %d edge add) -- re-run the ranker.'
          % (len(stat_fix), len(edge_add)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
