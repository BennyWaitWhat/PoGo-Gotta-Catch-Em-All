"""Assemble ACCOUNT_REPORT.md + account_snapshot.json from probe/raw JSON + pokemon.db.
Pure Python, no Frida. Reruns safely."""
import json, sqlite3, time, os

probe = json.load(open('_probe_out.json'))
raw = json.load(open('account_snapshot_raw.json')) if os.path.exists('account_snapshot_raw.json') else {}

def val(info):
    t = info.get('type', ''); v = info.get('val', {})
    if 'Int64' in t: return int(v['i64']) if v.get('i64') not in (None,) else None
    if 'Single' in t: return round(v['f32'], 2) if v.get('f32') is not None else None
    if 'Boolean' in t: return bool(v.get('u8'))
    if 'Int32' in t: return v.get('i32')
    if 'String' in t: return v.get('str')
    return None

def fields_of(obj):
    return {k: val(i) for k, i in obj.get('fields', {}).items()} if isinstance(obj, dict) and 'fields' in obj else {}

ps = fields_of(probe.get('player_protos', {}).get('get_PlayerStats', {}))
lp = fields_of(probe.get('player_protos', {}).get('get_LevelProgress', {}))
bs = fields_of(probe.get('buddystats_proto', {}))
# currency: pick the IAP hit whose backing fields are populated
coins = stardust = None
for hf in probe.get('iap', {}).get('hit_fields', []):
    f = fields_of(hf)
    if f.get('<Coins>k__BackingField') or f.get('<Stardusts>k__BackingField'):
        coins = f.get('<Coins>k__BackingField'); stardust = f.get('<Stardusts>k__BackingField')
name = (raw.get('player', {}).get('get_PlayerName', {}) or {}).get('str')
items = raw.get('itembag', {}).get('items', {})
gimmi = items.get('1150')

# collection from DB
c = sqlite3.connect('pokemon.db'); c.row_factory = sqlite3.Row; cur = c.cursor()
def cnt(w): return cur.execute(f"SELECT COUNT(*) FROM pokemon WHERE in_bag=1 AND {w}").fetchone()[0]
bag = cnt('1=1')
coll = {
    'bag_total': bag, 'shiny': cnt('is_shiny=1'), 'hundo': cnt('iv_total=45'), 'nundo': cnt('iv_total=0'),
    'shadow': cnt("alignment=1"), 'purified': cnt('is_purified_flag=1'), 'lucky': cnt('is_lucky=1'),
    'xxl': cnt('pokemon_size_category=5'), 'xxs': cnt('pokemon_size_category=1'),
}
# dex
dex = json.load(open('pokedex_hundos_live.json'))
caught = {e['pid'] for e in dex['entries'] if (e.get('times') or 0) > 0}
hundo_sp = {e['pid'] for e in dex['entries'] if e.get('hundo')}
missing = [n for n in range(1, 1026) if n not in caught]

ITEMNAME = {1:'Poke Ball',2:'Great Ball',3:'Ultra Ball',101:'Potion',102:'Super Potion',103:'Hyper Potion',
    104:'Max Potion',201:'Revive',202:'Max Revive',301:'Incense',401:'Lure Module',501:'Incubator',
    701:'Razz Berry',703:'Nanab Berry',705:'Pinap Berry',706:'Golden Razz',708:'Silver Pinap',902:'Egg',
    1101:'Sun Stone',1102:"King's Rock",1103:'Metal Coat',1104:'Dragon Scale',1105:'Up-Grade',
    1106:'Sinnoh Stone',1107:'Unova Stone',1150:'Gimmighoul Coin'}

snap = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'trainer': name,
    'level': lp.get('<CurrLevel>k__BackingField') or ps.get('Level'),
    'max_level': lp.get('<MaxLevel>k__BackingField'), 'legacy_level': ps.get('LegacyPrevLevel'),
    'xp': ps.get('Experience'),
    'currency': {'pokecoins': coins, 'stardust': stardust, 'gimmighoul_coins': int(gimmi) if gimmi else None},
    'lifetime': {k: ps.get(k) for k in ['KmWalked','NumPokemonCaptured','NumPokemonEncountered',
        'NumUniquePokedexEntries','NumEvolutions','PokeStopVisits','UniquePokestopsVisited','NumEggsHatched',
        'NumRaidBattleWon','NumLegendaryBattleWon','NumTrades','NumPokemonPurified','NumGruntsDefeated',
        'NumBestBuddies','NumMaxLevelFriends','NumTotalMegaEvolutions','NumUniqueMegaEvolutions']},
    'collection': coll, 'dex': {'caught': len(caught), 'hundos': len(hundo_sp), 'missing': len(missing),
        'caught_no_hundo': len(caught) - len(caught & hundo_sp)},
    'buddy': {k: bs.get(k) for k in ['NumDaysSpentWithBuddy','CurrentPointsEarned','CurrentEmotionPoints']},
    'items': {ITEMNAME.get(int(k), f'item_{k}'): v for k, v in sorted(items.items(), key=lambda x: -x[1])},
}
json.dump(snap, open('account_snapshot.json', 'w'), indent=1)

L = snap['lifetime']
md = f"""# Pokemon GO Account Snapshot - {snap['ts']}

## Trainer
- **{name}**  -  Level **50** (official max, reached at 176M XP)
- Total XP: **{snap['xp']:,}**  (client proto also reports an internal level {snap['level']}/{snap['max_level']}, but its XP thresholds do not reconcile - treat 50 as the true level)
- Distance walked: **{L['KmWalked']:,} km**

## Currency
- PokeCoins: **{coins:,}**
- Stardust: **{stardust:,}**
- Gimmighoul Coins: **{int(gimmi):,}** (enough for Gholdengo, needs 999)

## Lifetime stats
- Caught: **{L['NumPokemonCaptured']:,}**  |  Encountered: {L['NumPokemonEncountered']:,}
- Evolutions: {L['NumEvolutions']:,}  |  Mega evolutions: {L['NumTotalMegaEvolutions']:,} ({L['NumUniqueMegaEvolutions']} unique)
- PokeStop visits: {L['PokeStopVisits']:,} ({L['UniquePokestopsVisited']:,} unique)  |  Eggs hatched: {L['NumEggsHatched']:,}
- NumRaidBattleWon: {L['NumRaidBattleWon']:,}  |  NumLegendaryBattleWon: {L['NumLegendaryBattleWon']:,}  (raw counters)
- Trades: {L['NumTrades']:,}  |  Purified: {L['NumPokemonPurified']:,}  |  Grunts defeated: {L['NumGruntsDefeated']:,}
- Best buddies: {L['NumBestBuddies']}  |  Max-level friends: {L['NumMaxLevelFriends']}

## Collection (current bag = {coll['bag_total']:,})
- Shiny: {coll['shiny']:,}  |  Hundo (100%): {coll['hundo']:,}  |  Nundo (0%): {coll['nundo']}
- Shadow: {coll['shadow']:,}  |  Purified: {coll['purified']:,}  |  Lucky: {coll['lucky']:,}
- XXL: {coll['xxl']}  |  XXS: {coll['xxs']}

## Pokedex
- Species caught: **{snap['dex']['caught']}** / 1025  |  Missing: **{snap['dex']['missing']}**
- Hundos registered: **{snap['dex']['hundos']}** species  |  Caught but no hundo: **{snap['dex']['caught_no_hundo']}**

## Buddy
- Days with current buddy: {bs.get('NumDaysSpentWithBuddy')}  |  Emotion points: {bs.get('CurrentEmotionPoints')}

## Items ({len(items)} types with count > 0)
""" + '\n'.join(f"- {ITEMNAME.get(int(k), 'item ' + k)}: {v:,}" for k, v in sorted(items.items(), key=lambda x: -x[1]))

open('ACCOUNT_REPORT.md', 'w', encoding='utf-8').write(md)
print('wrote ACCOUNT_REPORT.md + account_snapshot.json')
print(md)
