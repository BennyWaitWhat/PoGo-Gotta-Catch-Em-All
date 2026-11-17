"""The cull's two walk guards, with no phone, no data and no frida (CI runs this):
1. the pre-attach gate's parser (pogo_il2cpp._on_screen): the game must be the app on screen, with the screen on;
2. the purge's count proof (pogo_pipeline.counts_agree) and the line that names the egg records (_egg_line)."""
import os, struct, sys, types
sys.modules.setdefault('frida', types.ModuleType('frida'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pogo_il2cpp as pg
import pogo_pipeline as pp

G = '    topResumedActivity=ActivityRecord{8980209 u0 com.nianticlabs.pokemongo/com.nianticproject.holoholo.libholoholo.unity.UnityMainActivity t107}\n'
T = '    topResumedActivity=ActivityRecord{115176435 u0 com.google.android.apps.chromecast.app/.remotecontrol.atv.AtvRemoteControlActivity t61}\n'
assert pg._on_screen(G + '  mWakefulness=Awake\n') == (True, 'PoGo is on screen')
assert pg._on_screen(T + '  mWakefulness=Awake\n') == (False, 'com.google.android.apps.chromecast.app is on screen, PoGo is behind it')
assert pg._on_screen(G + '  mWakefulness=Asleep\n') == (False, 'the screen is off')
assert pg._on_screen(G.replace('topResumedActivity=', 'ResumedActivity: ') + '  mWakefulness=Awake\n')[0] is True
assert pg._on_screen('')[0] is False and pg._on_screen(None)[0] is False
# the wait: it attaches nothing and stops when the game stays behind another app; it returns when the game comes back
import time
_real_sleep, _real_read, _said = time.sleep, pg._adb_on_screen, []
time.sleep = lambda s: None
try:
    pg._adb_on_screen = lambda dev: (False, 'com.x is on screen, PoGo is behind it')
    try:
        pg.wait_on_screen('dev', wait_s=0)
        raise SystemExit('the gate let an attach through with another app on screen')
    except pg.NotReadyToAttach as e:
        assert str(e).startswith('STOPPED: PoGo is not on screen (com.x is on screen, PoGo is behind it)'), e
    _answers = [(False, 'com.x is on screen, PoGo is behind it'), (False, 'the screen is off'), (True, 'PoGo is on screen')]
    pg._adb_on_screen = lambda dev: _answers.pop(0)
    pg.wait_on_screen('dev', wait_s=60)
    assert not _answers, 'it kept reading after the game was back'
    pg._adb_on_screen = lambda dev: (True, 'PoGo is on screen')
    pg.wait_on_screen('dev')
finally:
    time.sleep, pg._adb_on_screen = _real_sleep, _real_read
print('on-screen gate OK')

ca = pp.counts_agree
assert ca(5747, 12, 5747, 12, 5759), 'the normal walk'
assert ca(5747, 12, 5747, 13, 5760), '11-16 18:52..21:06: one egg record more than the game counts, Pokemon equal'
assert not ca(5717, 12, 5716, 12, 5728), '11-16 18:11: a Pokemon short -- still refused'
assert not ca(5747, 12, 5746, 13, 5759), 'a Pokemon read as an egg -- refused by the Pokemon count'
assert not ca(5747, 12, 5747, 11, 5758), 'fewer egg records than the game counts -- refused'
assert not ca(5747, 12, 5747, 13, 5761), 'a record that is neither a Pokemon nor an egg -- refused'
assert not ca(None, 12, 5747, 12, 5759) and not ca(5747, None, 5747, 12, 5759) and not ca(5747, 12, 5747, 12, None), 'unread = unproven'
b = bytearray(0x200)
struct.pack_into('<Q', b, 32, 0x1122334455667788); b[80] = 1
struct.pack_into('<d', b, 88, 10.0); struct.pack_into('<d', b, 96, 15104.6)
struct.pack_into('<q', b, 160, 1794880789252); struct.pack_into('<i', b, 340, 3); struct.pack_into('<i', b, 400, 1)
rec = {'uid': str(0x1122334455667788), 'protoBytes': bytes(b).hex()}
assert pp._rec_is_egg(rec)
s = pp._egg_line(rec)
assert s.startswith('667788 made ') and '10 km egg (started at 15104.6 km), type 3, slot 1' in s and 'NOT' not in s and 'incubator' not in s, s
struct.pack_into('<Q', b, 152, 0x7000000000)
s2 = pp._egg_line({'uid': '5', 'protoBytes': bytes(b).hex()})
assert s2.endswith(", in an incubator, its id_ is NOT the node's uid"), s2
assert 'unreadable' in pp._egg_line({'uid': '5', 'protoBytes': 'zz'})
print('purge proof OK:', s)
