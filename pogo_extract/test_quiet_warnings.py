"""The four warning lines of the 2026-11-18 culls (Benny 17:44: "DUDE, whats with these warnings?!?!?! fix them"), with no
phone, no data and no frida (CI runs this):
1. retire's census check tells his release from a tag that lost a member (retire_tags.released_members + the delete loop);
2. a DeleteTag that threw says what it threw, and the game's known first-call hiccup gets one more try (the delete loop);
3. that hiccup on a tag write is said at INFO, in words neither of the cull's scans picks up (tag_ops._try_line);
4. one empty adb read is asked again before the freeze probe calls the game unreadable (pogo_il2cpp.game_world_frozen).
5. (the same evening, his "go.") a tag write and a tag delete run on the game's main thread: inside a frame of the
   game, one job per frame; with no frame hook or no frame in time they run on Frida's thread as before, and say so.
And the other side of each: what is NOT routine still comes out as a warning line."""
import contextlib, io, logging, os, shutil, subprocess, sys, tempfile, time, types
sys.modules.setdefault('frida', types.ModuleType('frida'))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, 'system', 'scripts')]
import pogo_il2cpp as pg
import full_audit as fa
import tag_ops
import retire_tags as rt
import safe_nuke_tags as snt

HICCUP = '"Field currentActivity or type signature  not found" thrown in ?.? +0xd98d9fc < ?.? +0x4f7ef94 < (3 more)'
# full_audit's retire relay echoes a RETIRE line that holds one of these, and everything after a COLLATERAL line
RELAY = ('refused', 'regained', 'still holds', 'not cleared')
assert repr(RELAY) in open(os.path.join(HERE, 'full_audit.py'), encoding='utf-8').read(), \
    "full_audit's retire relay words changed: update RELAY here and re-read retire_tags' calm lines against them"
relayed = lambda text: [l for l in text.splitlines() if 'COLLATERAL' in l or any(k in l for k in RELAY)]
warned = fa.job_warnings

# ---------------------------------------------------------------------------------------------- 1. who left a tag, and why
B = {'Transfer': {'tagId': '1', 'memberCount': 7, 'memberUids': list('abcdefg')},
     'Favorite': {'tagId': '2', 'memberCount': 2, 'memberUids': ['x', 'y']}}
A = dict(B, Transfer={'tagId': '1', 'memberCount': 4, 'memberUids': list('abcd')})
asked = []
gone_all = lambda uids: asked.append(list(uids)) or set(uids)
assert rt.released_members(B, A, gone_all) == {'Transfer': set('efg')} and asked == [['e', 'f', 'g']], 'his release, asked once'
assert rt.released_members(B, A, lambda u: {'e', 'f'}) == {}, 'one of them is still in the bag: not a release'
assert rt.released_members(B, B, lambda u: 1 / 0) == {}, 'nothing dropped: the bag is never read'
assert rt.released_members(B, dict(B, Favorite={'tagId': '2', 'memberCount': 3, 'memberUids': ['x', 'y', 'z']}), lambda u: 1 / 0) == {}
for bad in ({'tagId': '1', 'memberCount': 4},                                        # no member list on one side
            {'tagId': '1', 'memberCount': 4, 'memberUids': None},                    # the list could not be read
            {'tagId': '1', 'memberCount': 4, 'memberUids': ['a', 'b', 'c', '']},     # one member could not be read
            {'tagId': '1', 'memberCount': 4, 'memberUids': ['a', 'b', 'c']},         # the count is not the list
            {'tagId': '1', 'memberCount': 4, 'memberUids': ['a', 'b', 'c', 'NEW']},  # somebody joined as well
            {'tagId': '1', 'memberCount': 4, 'memberUids': ['a', 'a', 'b', 'c']}):   # a doubled entry
    assert rt.released_members(B, dict(B, Transfer=bad), lambda u: 1 / 0) == {}, bad
both = rt.released_members(B, dict(A, Favorite={'tagId': '2', 'memberCount': 1, 'memberUids': ['x']}), lambda u: set('efg'))
assert both == {'Transfer': set('efg')}, 'a tag whose lost member is still in the bag is never explained away: %r' % both

# ------------------------------------------------------------------------------- 2. the delete loop, against a fake game
THREW = {'hiccup': {'ok': False, 'err': 'DeleteTag threw an exception', 'excClass': 'Exception', 'excText': HICCUP},
         'other': {'ok': False, 'err': 'DeleteTag threw an exception', 'excClass': 'InvalidOperationException',
                   'excText': '"Too many requests"'},
         'blind': {'ok': False, 'err': 'DeleteTag threw an exception', 'excClass': '', 'excText': ''}}


class Game:
    """Tags {name: [uids]}, a bag, and a del_tag that follows a plan: 'ok', a THREW key, or '<key>+gone' (threw, deleted
    anyway). after(game, call number) runs right after each call: what happens on the phone during the settle wait."""
    def __init__(self, tags, bag, plan, after=None, uids=True):
        self.tags, self.bag, self.plan, self.after = {n: list(u) for n, u in tags.items()}, set(bag), list(plan), after
        self.ids = {n: str(100 + i) for i, n in enumerate(tags)}
        self.calls, self.uids, self.exports_sync, self.bag_reads = [], uids, self, 0

    def enum_tags_full(self, svc, with_uids=False):
        out = []
        for n, u in self.tags.items():
            t = {'name': n, 'tagId': self.ids[n], 'memberCount': len(u)}
            if with_uids:
                t['memberUids'] = list(u) if self.uids else None
            out.append(t)
        return out

    def del_tag(self, svc, tid):
        name = [n for n, i in self.ids.items() if i == tid][0]
        step = self.plan.pop(0)
        self.calls.append((name, step))
        step, _, where = step.partition('@')        # '@main' / '@miss': where the call ran (section 5)
        if step == 'ok' or step.endswith('+gone'):
            del self.tags[name]
        if self.after:
            self.after(self, len(self.calls))
        r = {'ok': True} if step == 'ok' else dict(THREW[step.split('+')[0]])
        if where == 'main':
            r.update(thread='main', frameWaitMs=12)
        elif where == 'miss':
            r.update(thread='frida', mainMiss=NO_FRAME)
        return r


def retire(game, retired=('Best GL', 'Best UL'), bag_read=None):
    """retire_tags.run_on_session on the fake game -> (what it printed, the script source it loaded)."""
    seen, keep = {}, (pg.pick_singleton, pg.get_script_with_helpers, pg.find_protos_for_uids, time.sleep, snt.clear_db_mirror)

    def find(sess, bag, uids, **k):
        game.bag_reads += 1
        return {u: '0x1' for u in uids if u in game.bag}
    pg.pick_singleton = lambda sess, ns, cls, fresh=False: cls
    pg.get_script_with_helpers = lambda sess, js='': seen.update(js=js) or game
    pg.find_protos_for_uids = bag_read or find
    time.sleep = lambda s: None
    snt.clear_db_mirror = lambda db, tag: 0
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            assert rt.run_on_session(None, 1, rt.args([]), list(retired), []) == 0
    finally:
        pg.pick_singleton, pg.get_script_with_helpers, pg.find_protos_for_uids, time.sleep, snt.clear_db_mirror = keep
    return out.getvalue(), seen.get('js', '')


NO_FRAME = 'no frame in 3000 ms -- is the game paused, loading or behind another app?'
TAGS = {'Transfer': list('abcdefg'), 'Favorite': ['x', 'y'], 'Best GL': [], 'Best UL': []}
BAG = set('abcdefgxyz')


def release3(g, n):                     # he releases the three new pile Pokemon while the first delete settles
    if n == 1:
        g.tags['Transfer'] = list('abcd')
        g.bag -= set('efg')


# A. the 17:16 cull: 'Best GL' deleted, 'Transfer 7 -> 4' was his release. No alarm, and the next shell is deleted too.
g = Game(TAGS, BAG, ['ok', 'ok'], release3)
out, js = retire(g)
assert g.calls == [('Best GL', 'ok'), ('Best UL', 'ok')] and 'Best GL' not in g.tags and 'Best UL' not in g.tags, out
assert 'COLLATERAL' not in out and 'Transfer             3 member(s) fewer' in out, out
assert 'retired shells: deleted 2 (Best GL, Best UL); 0 left' in out and g.bag_reads == 1, out
assert warned(out) == [] and relayed(out) == [], (warned(out), relayed(out))
assert 'function _excText(exc)' in js and 'function delTag' in js, 'the delete script carries the exception reader'

# B. a Pokemon that left a tag and is STILL in the bag: the alarm, the stop, exactly as before
def strip_fav(g, n):
    g.tags['Favorite'] = ['x']
g = Game(TAGS, BAG, ['ok', 'ok'], strip_fav)
out, _ = retire(g)
assert len(g.calls) == 1 and "*** COLLATERAL CHANGE DETECTED after deleting 'Best GL' -- stopping ***" in out, out
assert 'COLLATERAL: tag "Favorite"' in out and 'memberCount changed 2 -> 1' in out and warned(out) and relayed(out), out
assert 'retired shells: deleted 1 (Best GL); 1 left for later runs: Best UL' in out, out

# C. both at once: the release is said plainly, the stripped tag still stops the run, and only that tag is named
def both_at_once(g, n):
    release3(g, n); strip_fav(g, n)
g = Game(TAGS, BAG, ['ok', 'ok'], both_at_once)
out, _ = retire(g)
assert len(g.calls) == 1 and 'COLLATERAL: tag "Favorite"' in out and 'COLLATERAL: tag "Transfer"' not in out, out
assert 'Transfer             3 member(s) fewer' in out, out

# D. a release still on its way: the second look, 2 s later, sees them gone
late = {'n': 0}
def slow_bag(sess, bag, uids, **k):
    late['n'] += 1
    return {u: '0x1' for u in uids} if late['n'] == 1 else {}
g = Game(TAGS, BAG, ['ok', 'ok'], release3)
out, _ = retire(g, bag_read=slow_bag)
assert late['n'] == 2 and 'COLLATERAL' not in out and len(g.calls) == 2, out

# E. what cannot be read stays an alarm: no member lists, a bag read that stops, a member that joined
out, _ = retire(Game(TAGS, BAG, ['ok', 'ok'], release3, uids=False))
assert 'COLLATERAL: tag "Transfer"' in out and 'memberCount changed 7 -> 4' in out, out
def no_bag(sess, bag, uids, **k):
    raise RuntimeError('filtered bag walk INCOMPLETE after 5 tries')
out, _ = retire(Game(TAGS, BAG, ['ok', 'ok'], release3), bag_read=no_bag)
assert 'COLLATERAL: tag "Transfer"' in out and 'is not known: the bag read stopped with RuntimeError' in out, out
def joined(g, n):
    g.tags['Favorite'] = ['x', 'y', 'z']
out, _ = retire(Game(TAGS, BAG, ['ok', 'ok'], joined))
assert 'COLLATERAL: tag "Favorite"' in out and 'memberCount changed 2 -> 3' in out, out

# F. the game's first-call hiccup: ONE more try, then the shell is deleted; nothing reads as a warning
g = Game(TAGS, BAG, ['hiccup', 'ok', 'ok'])
out, _ = retire(g)
assert g.calls == [('Best GL', 'hiccup'), ('Best GL', 'ok'), ('Best UL', 'ok')], g.calls
assert "Best GL              deleted on the second try (the first hit the game's known first-call hiccup), every other tag intact" in out, out
assert 'retired shells: deleted 2' in out and warned(out) == [] and relayed(out) == [], out

# G. the hiccup on both tries: the shell stays, said calmly with the game's own words, the run ends, the next cull tries again
g = Game(TAGS, BAG, ['hiccup', 'hiccup', 'ok'])
out, _ = retire(g)
assert g.calls == [('Best GL', 'hiccup'), ('Best GL', 'hiccup')], g.calls
assert "Best GL              still there: the game's known first-call hiccup on both tries (Exception -- " + HICCUP in out, out
assert 'retired shells: deleted 0 (-); 2 left for later runs: Best GL, Best UL' in out, out
assert warned(out) == [] and relayed(out) == [] and 'rate limit' not in out, (warned(out), relayed(out))

# H. any OTHER exception: no second try, its own text in the line, and it reads as a warning in both scans
g = Game(TAGS, BAG, ['other', 'ok'])
out, _ = retire(g)
assert g.calls == [('Best GL', 'other')], g.calls
line = 'Best GL              DeleteTag refused: the game threw InvalidOperationException -- "Too many requests" -- stopping this run'
assert line in out and warned(out) == [line] and relayed(out) == ['  ' + line], out
out, _ = retire(Game(TAGS, BAG, ['blind']))       # an exception nothing could be read from: still loud
assert 'DeleteTag refused: the game threw an exception nothing could be read from -- stopping' in out and warned(out), out

# I. the call threw and the tag is gone all the same: counted as deleted, checked like any delete
g = Game(TAGS, BAG, ['other+gone', 'ok'])
out, _ = retire(g)
assert len(g.calls) == 2 and 'Best GL              deleted (the game answered the call with InvalidOperationException; the tag is gone all the same)' in out, out
assert 'retired shells: deleted 2' in out and warned(out) == [], out

# J. the lines that were always there
g = Game(dict(TAGS, **{'Best GL': ['q']}), BAG, ['ok'])
out, _ = retire(g)
assert 'Best GL              still holds 1 member(s)' in out and g.calls == [('Best UL', 'ok')], out
out, _ = retire(Game({'Transfer': ['a']}, {'a'}, []))
assert 'retired shells on the device: 0 -- all clear' in out, out

# K. (section 5) the delete on the game's main thread: said per tag; a miss is a '!' line; the hiccup ON it is news
g = Game(TAGS, BAG, ['ok@main', 'ok@main'])
out, js = retire(g)
assert out.count('deleted, every other tag intact [main thread]') == 2 and warned(out) == [] and relayed(out) == [], out
assert 'function _onMain(run)' in js and not js.startswith('var _MT_OFF'), 'the delete script carries the frame runner'
g = Game(TAGS, BAG, ['ok@miss', 'ok@miss'])
out, _ = retire(g)
miss = "! the delete of Best GL did NOT get the game's main thread (%s) -- it went from Frida's thread, the way every delete went before 2026-11-18" % NO_FRAME
assert out.count('did NOT get') == 1 and miss in out and warned(out) == [miss] and 'retired shells: deleted 2' in out, out
g = Game(TAGS, BAG, ['hiccup@main', 'hiccup@main', 'ok'])
out, _ = retire(g)
line = 'Best GL              DeleteTag refused: the game threw Exception -- %s [on the main thread] -- stopping this run' % HICCUP
assert len(g.calls) == 2 and line in out and warned(out) == [line] and relayed(out), out
off = tempfile.NamedTemporaryFile(delete=False)
off.close()
keep_off, tag_ops.MAIN_THREAD_OFF = tag_ops.MAIN_THREAD_OFF, off.name
try:                                                 # the kill switch file: no frame hook in the delete script ...
    assert tag_ops.main_thread_writes() is False
    out, js = retire(Game(TAGS, BAG, ['ok', 'ok']))
    assert js.startswith('var _MT_OFF = true;\n') and 'retired shells: deleted 2' in out, js[:60]

    class Sess:                                      # ... and none in the writers' script
        def create_script(self, src):
            self.src, self.exports_sync = src, self
            return self
        on = load = init_status = lambda self, *a: None
    keep_info, tag_ops.log.info = tag_ops.log.info, lambda *a: None
    try:
        assert tag_ops._load_bulk_tag_script(Sess()).src.startswith('var _MT_OFF = true;\n/*')
        os.remove(off.name)
        assert tag_ops.main_thread_writes() is True and tag_ops._load_bulk_tag_script(Sess()).src.startswith('/*')
    finally:
        tag_ops.log.info = keep_info
finally:
    tag_ops.MAIN_THREAD_OFF = keep_off
    if os.path.exists(off.name):
        os.remove(off.name)

# ------------------------------------------------------------------------------------ 3. the hiccup on a tag write
# (the batch writer itself is not driven here: audit_invariants counts every file that calls it as one that can add tags)
R = {'ok': False, 'built': 23, 'err': 'the write exc', 'excClass': 'System.Exception', 'excText': HICCUP}
WRITER = 'apply_changes'
routine, line = tag_ops._try_line(WRITER, 1, 1, 0, R, 23)
assert routine and line == 'first-call hiccup: tag write batch 1/1, try 1 of 3 (System.Exception -- %s)' % HICCUP, line
# full_audit echoes every sync line that holds the writer's name, and reads 'INFO <writer>:' as "the write was answered"
assert WRITER not in line and warned('17:16:58 INFO ' + line) == [], line
NRE = dict(R, excClass='System.NullReferenceException', excText='no message thrown in ?.? +0x4d96de4')
routine, line = tag_ops._try_line(WRITER, 2, 3, 1, NRE, 150)
assert not routine and line == (WRITER + ': batch 2/3 retry 1: built=23 requested=150 err=the write exc '
                                'System.NullReferenceException -- no message thrown in ?.? +0x4d96de4'), line
assert warned('17:16:58 WARNING ' + line), 'any other exception is still a warning line'
assert tag_ops._try_line('apply_members', 1, 1, 0, {'ok': True, 'built': 2}, 3) == (
    False, 'apply_members: batch 1/1 retry 0: built=2 requested=3 err=None '), 'a short batch keeps the old line'
assert not tag_ops.first_call_hiccup(None) and not tag_ops.first_call_hiccup('Field currentActivity')
# (section 5) the hiccup is routine only OFF the main thread: on it, the thread never was the cause, and that is news
assert tag_ops._try_line(WRITER, 1, 1, 0, dict(R, thread='frida'), 23)[0] is True
routine, line = tag_ops._try_line(WRITER, 1, 1, 0, dict(R, thread='main'), 23)
assert not routine and line.endswith(HICCUP + ' [ON THE MAIN THREAD: the thread is not what causes this]') and warned('17:16:58 WARNING ' + line), line
# where the calls of one write ran: an INFO line the scans pass, and a WARNING for a write that missed the main thread
tag_ops.LAST_THREAD.update(main=0, frida=0, wait_ms=[], miss=[])
for r in ({'ok': True, 'thread': 'main', 'frameWaitMs': 9}, {'ok': True, 'thread': 'main', 'frameWaitMs': 14}, {'ok': True}, 'boom'):
    tag_ops._thread_note(r)
assert tag_ops._thread_lines() == [('info', "tag write: 2 call(s) ran on the game's main thread (a frame came after 9 / 14 ms)")]
assert WRITER not in tag_ops._thread_lines()[0][1] and warned('18:40:01 INFO ' + tag_ops._thread_lines()[0][1]) == []
tag_ops._thread_note({'ok': True, 'thread': 'frida', 'mainMiss': NO_FRAME})
tag_ops._thread_note({'ok': True, 'thread': 'frida', 'mainMiss': NO_FRAME})
lv, line = tag_ops._thread_lines()[1]
assert lv == 'warning' and line == ("tag write: 2 call(s) did NOT get the game's main thread (%s) -- sent from Frida's thread, "
                                    "the way every write went before 2026-11-18" % NO_FRAME), line
assert WRITER not in line and warned('18:40:01 WARNING ' + line), line
tag_ops.LAST_THREAD.update(main=0, frida=0, wait_ms=[], miss=[])
tag_ops._thread_note({'ok': True, 'thread': 'frida'})          # the kill switch: Frida's thread, nothing to say
assert tag_ops._thread_lines() == []


class Levels(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self); self.seen = []

    def emit(self, rec):
        self.seen.append((rec.levelname, rec.getMessage()))


h = Levels()
tag_ops.log.addHandler(h)
tag_ops.log.propagate = False                       # the lines are judged here, not printed into CI's log
try:
    tag_ops._try_log(WRITER, 1, 1, 0, R, 23)
    tag_ops._try_log(WRITER, 1, 1, 1, NRE, 23)
finally:
    tag_ops.log.removeHandler(h)
    tag_ops.log.propagate = True
assert [l for l, _ in h.seen] == ['INFO', 'WARNING'] and h.seen[0][1].startswith('first-call hiccup: tag write batch 1/1'), h.seen
assert h.seen[1][1].startswith(WRITER + ': batch 1/1 retry 1: built=23 requested=23'), h.seen

# ------------------------------------------------------------------------------------------ 4. the freeze probe's read
keep = (pg._resolve_device, pg._adb_pidof, pg._adb_unitymain_wchan, time.sleep)
pg._resolve_device, pg._adb_pidof, time.sleep = (lambda: 'dev'), (lambda d=None: 16800), (lambda s: None)
try:
    def reads(seq):
        seq = list(seq)
        pg._adb_unitymain_wchan = lambda d, p: seq.pop(0)
        return seq
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        left = reads(['', 'futex_wait_queue'])               # the 17:40 cull: one empty read, the game is fine
        assert pg.rescue_frozen_world(None, 'liveness scan for the live graph') is False
        assert left == [] and pg._FREEZE_PROBE['unreadable'] is None and out.getvalue() == '', out.getvalue()
        left = reads(['', '', ''])                           # empty three times: said, as before
        assert pg.rescue_frozen_world(None, 'liveness scan for the live graph') is False and left == []
    said = out.getvalue()
    assert said.startswith('!! freeze probe after liveness scan for the live graph could not read the game (UnityMain\'s wait '
                           'channel read back empty on 3 read(s)') and warned(said), said
    left = reads(['sigsuspend', '', 'sigsuspend', 'sigsuspend'])
    assert pg.game_world_frozen(gap_s=0) is True and left == [], 'a frozen game is still seen through one empty read'
    left = reads(['sigsuspend', 'futex_wait_queue'])
    assert pg.game_world_frozen(gap_s=0) is False and pg._FREEZE_PROBE['unreadable'] is None
    # a read that used up the time budget (the phone is not answering) is not asked again
    clock = iter([0.0, 10.0])
    real = time.time
    time.time = lambda: next(clock)
    try:
        left = reads(['', 'never read'])
        assert pg._wchan_asked_again('dev', 1) == ('', 1) and left == ['never read']
    finally:
        time.time = real
finally:
    pg._resolve_device, pg._adb_pidof, pg._adb_unitymain_wchan, time.sleep = keep

# ---------------------------------------------------------------- the script the phone runs: its syntax, and the new reads
block = rt.exc_text_js()
assert block.startswith('var _GHAPI = null;') and block.rstrip().endswith('}'), 'the cut of the writer script moved'
assert all(('function %s(' % f) in block for f in ('_GH', '_ghFields', '_ghStr', '_excText', '_onMain', '_mtFrame', '_mtHook')) \
    and 'rpc.exports' not in block
assert rt.exc_text_js(os.path.join(HERE, 'no_such_file.js')) == '' and rt.exc_text_js(__file__) == ''
node = shutil.which('node')
if not node:
    assert not os.environ.get('CI'), 'CI must run the script checks: node is missing'
    print('test_quiet_warnings OK (node not found: the delete script was not parsed or run)')
    raise SystemExit(0)
HARNESS = r"""
const fs = require('fs');
const JS = fs.readFileSync(process.argv[2], 'utf8'), BLOCK = fs.readFileSync(process.argv[3], 'utf8');
const mem = new Map();
class P {
  constructor(a) { this.a = BigInt(a); }
  isNull() { return this.a === 0n; }
  add(n) { return new P(this.a + BigInt(n)); }
  toString() { return '0x' + this.a.toString(16); }
  _g(k) { const v = mem.get(this.a); if (!v || v.k !== k) throw new Error('access violation accessing ' + this); return v.v; }
  readPointer() { return new P(this._g('p')); }
  readS32() { return this._g('i'); }
  readU32() { return this._g('i'); }
  readU16() { return this._g('h'); }
  readU64() { const v = this._g('q'); return {toString: () => String(v)}; }
  readCString() { return this._g('s'); }
  writePointer(p) { mem.set(this.a, {k: 'p', v: p.a}); }
  writeS32(n) { mem.set(this.a, {k: 'i', v: n}); }
  writeU64(n) { mem.set(this.a, {k: 'q', v: n}); }
}
const put = (a, k, v) => mem.set(BigInt(a), {k, v});
let top = 0x100000n;
const Memory = {alloc: () => { top += 0x100n; return new P(top); }};
const Process = {pointerSize: 8, findModuleByName: () => ({base: new P(0x7000000000n), size: 0x1000, enumerateExports: () => []})};
const ptr = (x) => (x instanceof P ? x : new P(x));
const uint64 = (s) => BigInt(s);
const NAMES = ['get_NumberOfTags', 'GetCachedTagToPokemonBindingForIndex', 'DeleteTag'];
NAMES.forEach((n, i) => put(0x9000 + i * 0x10 + 0x8, 's', n));
const IL2 = {
  cGM: (cl, it) => { const k = Number(it.readPointer().a); if (k >= NAMES.length) return new P(0); it.writePointer(new P(k + 1)); return new P(0x9000 + k * 0x10); },
  mGN: (m) => m.add(0x8),
};
const TAGS = [];                                  // binding pointers by index
let deleted = [], throwNext = false;
function rI(method, inst, args, exc) {
  const name = method.add(0x8).readCString();
  if (name === 'get_NumberOfTags') { put(0x8000 + 0x10, 'i', TAGS.length); return new P(0x8000); }
  if (name === 'GetCachedTagToPokemonBindingForIndex') return new P(TAGS[args.readPointer().readS32()]);
  deleted.push(args.readPointer().readU64().toString());
  if (throwNext) exc.writePointer(new P(0xE000));
  return new P(0);
}
function tag(i, name, id, uids, opt) {            // lay one tag out the way the game does
  const bp = 0x20000 + i * 0x1000, tp = bp + 0x100, ns = bp + 0x200, l = bp + 0x300, it = bp + 0x400;
  opt = opt || {};
  put(bp + 0x10, 'p', BigInt(tp)); put(tp + 0x40, 'p', BigInt(ns)); put(tp + 0x38, 'q', id);
  put(ns + 0x10, 'i', name.length); [...name].forEach((c, k) => put(ns + 0x14 + k * 2, 'h', c.charCodeAt(0)));
  put(bp + 0x18, 'p', uids === null ? 0n : BigInt(l));
  if (uids !== null) {
    put(l + 0x18, 'i', opt.count !== undefined ? opt.count : uids.length);
    if (!opt.noItems) put(l + 0x10, 'p', BigInt(it));
    uids.forEach((u, j) => {
      const el = bp + 0x800 + j * 0x40;
      put(it + 0x20 + j * 8, 'p', u === null ? 0n : BigInt(el));
      if (u !== null && u !== '?') put(el + 0x20, 'q', u);
    });
  }
  TAGS[i] = bp;
}
tag(0, 'Transfer', 11, [101, null, 103, '?']);    // a null member pointer and a member whose uid cannot be read
tag(1, 'Best UL', 12, null);                      // no list at all: an empty tag
tag(2, 'Huge', 13, [], {count: 25000});           // a count nobody believes
tag(3, 'Broken', 14, [7], {noItems: true});       // the list's items cannot be read
const run = (withText) => {
  const rpc = {exports: {}};
  const args = ['rpc', 'Memory', 'Process', 'ptr', 'uint64', '_ensureInit', 'cFN', 'IL2', 'rI', '_excName'];
  const vals = [rpc, Memory, Process, ptr, uint64, () => {}, () => new P(0x500), IL2, rI, () => ' (InvalidOperationException)'];
  new Function(...args, (withText ? 'function _excText(e) { return \'"boom" thrown in X.Y +0x10\'; }\n' : '') + JS)(...vals);
  return rpc.exports;
};
const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.error(what + '\nGOT : ' + JSON.stringify(a) + '\nWANT: ' + JSON.stringify(b)); process.exit(1); } };
const x = run(true);
eq(x.enumTagsFull('0x1'), [{name: 'Transfer', tagId: '11', memberCount: 4}, {name: 'Best UL', tagId: '12', memberCount: 0},
                           {name: 'Huge', tagId: '13', memberCount: 25000}, {name: 'Broken', tagId: '14', memberCount: 1}], 'the census without uids is the old one');
eq(x.enumTagsFull('0x1', true), [{name: 'Transfer', tagId: '11', memberCount: 4, memberUids: ['101', '', '103', '']},
                                 {name: 'Best UL', tagId: '12', memberCount: 0, memberUids: []},
                                 {name: 'Huge', tagId: '13', memberCount: 25000, memberUids: null},
                                 {name: 'Broken', tagId: '14', memberCount: 1, memberUids: null}], 'the census with uids');
eq(x.delTag('0x1', '12'), {ok: true}, 'a delete that did not throw');
eq(deleted, ['12'], 'the id that was sent');
throwNext = true;
eq(x.delTag('0x1', '12'), {ok: false, err: 'DeleteTag threw an exception', excClass: 'InvalidOperationException', excText: '"boom" thrown in X.Y +0x10'}, 'what it threw');
eq(run(false).delTag('0x1', '12'), {ok: false, err: 'DeleteTag threw an exception', excClass: 'InvalidOperationException', excText: ''}, 'without the reader: the class alone');
// the cut of the writer script stands on its own: it loads, and a null exception reads as nothing
const t = new Function('Process', 'NativeFunction', 'Memory', 'ptr', BLOCK + '\nreturn _excText;')(Process, function () {}, Memory, ptr);
eq(t(new P(0)), '', 'the reader on a null exception');
// ---- 5. THE GAME'S MAIN THREAD: the frame runner on a fake game ------------------------------------------------------
const FULL = fs.readFileSync(process.argv[4], 'utf8');
const ok = (c, what) => { if (!c) { console.error('FAIL: ' + what); process.exit(1); } };
function world(opt) {                             // a fake game: the il2cpp lookups the runner makes (plus the two the writer's init() gets to), and its frames
  opt = opt || {};
  const strs = new Map(), hooks = [];
  let at = 0x40000000n;
  const impl = {
    il2cpp_domain_get: () => new P(0x10),
    il2cpp_domain_get_assemblies: (dom, sp) => { put(sp.a, 'i', 3); for (let i = 0; i < 3; i++) put(0x5000 + i * 8, 'p', BigInt(0x6000 + i)); return new P(0x5000); },
    il2cpp_assembly_get_image: (asm) => new P(asm.a + 0x1000n),
    il2cpp_thread_attach: () => { w.attached.push(!!w.inFrame); return new P(0x11); },   // the writer's init(): on which thread?
    il2cpp_image_get_name: () => ({readCString: () => 'not-the-game.dll'}),
    il2cpp_class_from_name: (img, ns, nm) => (!opt.noClass && img.a === 0x7001n && strs.get(ns.a) === 'Niantic.Zeppelin.Scheduler' && strs.get(nm.a) === 'Scheduler') ? new P(0x8000) : new P(0),
    il2cpp_class_get_method_from_name: (k, name, argc) => { if (opt.noMethod || k.a !== 0x8000n || strs.get(name.a) !== 'LateUpdate' || argc !== 0) return new P(0); put(0x9000, 'p', 0xC0DEn); return new P(0x9000); },
  };
  const w = {
    hooks, lib: true, attached: [],
    Process: {pointerSize: 8, findModuleByName: () => (w.lib ? {base: new P(0x7000000000n), size: 0x1000, enumerateExports: () => Object.keys(impl).map((n) => ({name: n, address: n}))} : null)},
    Memory: {alloc: () => { at += 0x100n; return new P(at); }, allocUtf8String: (t) => { at += 0x100n; strs.set(at, t); return new P(at); }},
    NativeFunction: function (addr) { return impl[addr]; },
    Interceptor: {attach: (code, fn) => { if (opt.noAttach) throw new Error('unable to intercept function'); hooks.push({code: code.toString(), fn}); }},
    frame: () => { w.inFrame = true; try { hooks.forEach((h) => h.fn()); } finally { w.inFrame = false; } },
  };
  return w;
}
const loadBlock = (w, pre) => new Function('Process', 'Memory', 'ptr', 'NativeFunction', 'Interceptor', 'setTimeout',
  (pre || '') + BLOCK + '\nreturn {_onMain: _onMain, _MT: _MT, wait: function (n) { _MT_WAIT_MS = n; }};')(w.Process, w.Memory, ptr, w.NativeFunction, w.Interceptor, setTimeout);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  // a frame comes: the job runs INSIDE the frame, once, and the result says so
  let w = world(), a = loadBlock(w), runs = 0;
  const job = () => { runs++; return {ok: true, inFrame: !!w.inFrame}; };
  let p = a._onMain(job);
  ok(p instanceof Promise && w.hooks.length === 1 && w.hooks[0].code === '0xc0de', 'the hook goes on Scheduler.LateUpdate: ' + a._MT.why);
  await sleep(5);
  ok(runs === 0, 'nothing runs before a frame');
  w.frame();
  let r = await p;
  ok(runs === 1 && r.ok && r.inFrame === true && r.thread === 'main' && typeof r.frameWaitMs === 'number' && r.mainMiss === undefined, 'ran in the frame: ' + JSON.stringify(r));
  w.frame(); w.frame();
  ok(runs === 1, 'a later frame runs nothing');
  // two jobs: one per frame, in order, and the hook went in once
  const order = [];
  const p1 = a._onMain(() => { order.push(1); return {ok: true}; }), p2 = a._onMain(() => { order.push(2); return {ok: true}; });
  w.frame();
  ok(order.join() === '1', 'one job per frame');
  w.frame();
  await p1; await p2;
  ok(order.join() === '1,2' && w.hooks.length === 1, 'in order, one hook');
  // a frame inside a running job (never nested)
  let nested = 0;
  p = a._onMain(() => { nested++; w.hooks[0].fn(); return {ok: true}; });
  const q = a._onMain(() => { nested += 10; return {ok: true}; });
  w.frame();
  ok(nested === 1, 'a job never starts inside another');
  w.frame(); await p; await q;
  ok(nested === 11, 'the second job ran on the next frame');
  // a job that throws on the main thread comes back as a value
  p = a._onMain(() => { throw new Error('boom'); });
  w.frame();
  r = await p;
  ok(r.ok === false && /threw on the main thread: Error: boom/.test(r.err) && r.thread === 'main', 'a throw is a value: ' + JSON.stringify(r));
  // NO frame in time: the job runs on Frida's thread, says why, and a late frame never runs it again
  a.wait(25); runs = 0;
  p = a._onMain(job);
  r = await p;
  ok(runs === 1 && r.ok && r.inFrame === false && r.thread === 'frida' && /^no frame in 25 ms/.test(r.mainMiss), 'the old way, with the reason: ' + JSON.stringify(r));
  w.frame(); w.frame();
  ok(runs === 1, 'a late frame does not run it a second time');
  p = a._onMain(() => { throw new Error('late boom'); });
  r = await p;
  ok(r.ok === false && /the write threw: Error: late boom/.test(r.err) && r.thread === 'frida', 'a throw on the old way still answers: ' + JSON.stringify(r));
  // the game is still not drawing: the next write does not wait a second time ...
  r = a._onMain(job);
  ok(!(r instanceof Promise) && runs === 2 && r.thread === 'frida' && /^still no frame since a write waited 25 ms/.test(r.mainMiss), 'one wait per stall: ' + JSON.stringify(r));
  w.frame();                                      // ... and once a frame has been seen, writes go to the main thread again
  p = a._onMain(job);
  ok(p instanceof Promise, 'frames are back: the write waits for one');
  w.frame();
  r = await p;
  ok(r.thread === 'main' && r.inFrame === true && runs === 3, 'frames are used again when they come back');
  // no class, no method, a hook that cannot be put in: the old way at once (no Promise), with the reason, and no retry
  for (const [opt, why] of [[{noClass: true}, /^no Niantic\.Zeppelin\.Scheduler\.Scheduler class/], [{noMethod: true}, /^no Scheduler\.LateUpdate/], [{noAttach: true}, /^the frame hook could not be put in: Error: unable to intercept/]]) {
    w = world(opt); a = loadBlock(w); runs = 0;
    r = a._onMain(job);
    ok(!(r instanceof Promise) && runs === 1 && r.thread === 'frida' && why.test(r.mainMiss) && w.hooks.length === 0, 'no hook: ' + JSON.stringify(r));
    r = a._onMain(job);
    ok(runs === 2 && why.test(r.mainMiss) && a._MT.state === -1, 'the lookup is not made twice');
  }
  // the kill switch: no hook is even tried, and there is nothing to explain
  w = world(); a = loadBlock(w, 'var _MT_OFF = true;\n'); runs = 0;
  r = a._onMain(job);
  ok(runs === 1 && r.thread === 'frida' && r.mainMiss === undefined && w.hooks.length === 0 && a._MT.state === 0, 'switched off: ' + JSON.stringify(r));
  // THE WRITER'S OWN EXPORT goes through the runner. Its init() runs FIRST, on the thread that called (init attaches
  // that thread to the game's runtime): this fake game has no game image, so nothing is queued and no hook goes in.
  const writer = (w, post) => {
    const rpc = {exports: {}};
    new Function('rpc', 'Process', 'Memory', 'ptr', 'NativeFunction', 'Interceptor', 'setTimeout', 'send', 'recv', FULL + (post || ''))(rpc, w.Process, w.Memory, ptr, w.NativeFunction, w.Interceptor, setTimeout, () => {}, () => {});
    return rpc.exports;
  };
  w = world();
  r = writer(w).bulkApplyChanges('0x1', [{proto: '0x2', add: ['0x3']}]);
  ok(!(r instanceof Promise) && /^missing image/.test(r.err) && r.thread === undefined && w.hooks.length === 0 && w.attached.join() === 'false',
     'init first, on the thread that called: ' + JSON.stringify(r) + ', attached inside a frame: ' + w.attached);
  // ... and with init() done, the body runs in the frame (no tag classes in this fake game: the body throws there)
  w = world();
  const xw = writer(w, '\nstate.ready = true;');
  p = xw.bulkApplyChanges('0x1', [{proto: '0x2', add: ['0x3']}]);
  ok(p instanceof Promise && w.hooks.length === 1, 'the write waits for a frame');
  w.frame();
  r = await p;
  ok(r.ok === false && /^the write threw on the main thread: TypeError/.test(r.err) && r.thread === 'main', 'the body ran in the frame: ' + JSON.stringify(r));
  try { r = xw.bulkApplyChanges('0x1', [], true); } catch (e) { r = {threw: String(e)}; }
  ok(!(r instanceof Promise) && /^TypeError/.test(r.threw || '') && r.thread === undefined, 'direct = the body itself, on the thread that called: ' + JSON.stringify(r));
  // THE DELETE goes through the same runner when it is in front of the script, and stays as it was without it
  w = world(); deleted = []; throwNext = false;
  const rpcD = {exports: {}};
  new Function('rpc', 'Memory', 'Process', 'ptr', 'uint64', '_ensureInit', 'cFN', 'IL2', 'rI', '_excName', 'NativeFunction', 'Interceptor', 'setTimeout', BLOCK + '\n' + JS)(
    rpcD, {alloc: Memory.alloc, allocUtf8String: w.Memory.allocUtf8String}, w.Process, ptr, uint64, () => { w.attached.push(!!w.inFrame); }, () => new P(0x500), IL2, rI, () => ' (X)', w.NativeFunction, w.Interceptor, setTimeout);
  p = rpcD.exports.delTag('0x1', '12');
  ok(p instanceof Promise && deleted.length === 0 && w.attached.join() === 'false', 'the delete waits for a frame; its init ran first, on the thread that called: ' + w.attached);
  w.frame();
  r = await p;
  ok(r.ok === true && r.thread === 'main' && deleted.join() === '12', 'the delete ran in the frame: ' + JSON.stringify(r));
  eq(run(false).delTag('0x1', '12'), {ok: true}, 'without the runner the delete is the old call');
  console.log('delete script OK');
})().catch((e) => { console.error('FAIL: ' + (e && e.stack || e)); process.exit(1); });
"""
tmp = tempfile.mkdtemp(prefix='quiet_warnings_')
try:
    with open(tag_ops.BULK_TAG_JS, encoding='utf-8') as f:
        full = f.read()
    files = {'all.js': pg.JS_PREAMBLE + '\n' + block + '\n' + snt.JS, 'snt.js': snt.JS, 'block.js': block, 'harness.js': HARNESS,
             'full.js': full}
    for name, text in files.items():
        with open(os.path.join(tmp, name), 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
    p = subprocess.run([node, '--check', os.path.join(tmp, 'all.js')], capture_output=True, text=True)
    assert p.returncode == 0, 'the delete script does not parse:\n' + p.stderr
    p = subprocess.run([node, '--check', os.path.join(tmp, 'full.js')], capture_output=True, text=True)
    assert p.returncode == 0, 'the writer script does not parse:\n' + p.stderr
    p = subprocess.run([node, os.path.join(tmp, 'harness.js'), os.path.join(tmp, 'snt.js'), os.path.join(tmp, 'block.js'),
                        os.path.join(tmp, 'full.js')],
                       capture_output=True, text=True)
    assert p.returncode == 0 and 'delete script OK' in p.stdout, p.stdout + p.stderr
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print('test_quiet_warnings OK')
