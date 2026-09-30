"""Smoke test for pogo_il2cpp module."""
import time
import pogo_il2cpp as pg

_T0 = time.time()
def _tick(label): print(f"[t+{time.time()-_T0:6.2f}s] {label}")

_tick("start")
sess, pid = pg.get_session()
_tick(f"get_session -> pid={pid}")

targets = [
    ('Niantic.Holoholo.Internal', 'PokedexImpl'),
    ('Niantic.Holoholo.Internal', 'PokemonBagImpl'),
    ('Niantic.Holoholo.Tagging',  'TaggingRpcService'),
]
addrs = {}
for ns, cls in targets:
    _p = time.time()
    addr = pg.find_singleton(sess, ns, cls)
    dur = time.time() - _p
    addrs[cls] = addr
    print(f"  {cls:<22} addr={addr} ({dur*1000:.0f}ms)")
    assert dur < 1.0, f"{cls} took {dur:.2f}s, expected <1s"

_tick("all 3 singletons found")

_p = time.time()
all_protos = pg.walk_bag_protos(sess, addrs['PokemonBagImpl'])
dur = time.time() - _p
print(f"\nwalk_bag_protos: {len(all_protos)} entries ({dur*1000:.0f}ms)")
first5 = list(all_protos.items())[:5]
for uid, proto in first5:
    print(f"  uid={uid:>20}  proto={proto}")

_tick("done")
sess.detach()
