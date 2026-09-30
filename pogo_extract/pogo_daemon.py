"""Persistent Frida session daemon for PoGo.

One frida.Session attached to PoGo, two loaded scripts (pogo_il2cpp helpers +
bulk_tag.js), pre-resolved PokedexImpl / PokemonBagImpl / TaggingRpcService
instance addresses. Exposes an HTTP RPC API on localhost:8765 so multiple
short-lived Python clients can run sub-second queries without re-attaching.

Endpoints:
    GET  /health         -> {ok, pid, bag, svc, dex, uptime}
    GET  /bag/walk       -> {count, results: {uid_str: proto_ptr_str}}
    GET  /dex/hundos     -> {count, pids: [pid, ...]}
    GET  /tags/server    -> {tags: {name: count}}
    POST /tags/add       -> body {tag_name, uids[]}    -> bulk tag op
    POST /tags/remove    -> body {tag_name, uids[]}    -> bulk untag op
    GET  /shutdown       -> graceful exit

Auto-recover: if frida raises ProcessNotFoundError mid-request, re-attach +
re-resolve singletons before retrying once.

Logs to pogo_daemon.log.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import frida

import pogo_il2cpp as pg

HOST = '127.0.0.1'
PORT = 8765
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pogo_daemon.log')
BULK_TAG_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bulk_tag.js')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(LOG_PATH, mode='a', encoding='utf-8'),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger('pogo_daemon')


# ---------------------------------------------------------------------------
# Pokedex hundo reader (mirrors read_pokedex_hundos.py logic, no logging).
# ---------------------------------------------------------------------------
DEX_HUNDO_JS = r"""
rpc.exports = {
    readAllHundos: function(addr) {
        var inst = ptr(addr);
        var dictAll = inst.add(0x10).readPointer();
        var entries = dictAll.add(0x18).readPointer();
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);
        var hundos = [];
        for (var i = 0; i < maxLen; i++) {
            var ep = data.add(i * 24);
            var hashCode = ep.readS32();
            if (hashCode < 0) continue;
            var pid = ep.add(8).readS32();
            var protoPtr = ep.add(16).readPointer();
            if (protoPtr.isNull()) continue;
            var mapField = protoPtr.add(0x80).readPointer();
            if (mapField.isNull()) continue;
            var list = mapField.add(0x18).readPointer();
            if (list.isNull()) continue;
            var head = list.add(0x10).readPointer();
            var lcount = list.add(0x18).readS32();
            var node = head; var iters = 0; var got = false;
            while (node && !node.isNull() && iters < lcount + 50) {
                try {
                    var kvpVal = node.add(0x30).readPointer();
                    if (!kvpVal.isNull()) {
                        var catEnum = kvpVal.add(0x10).readS32();
                        var acq = kvpVal.add(0x15).readU8();
                        if (catEnum === 14 && acq) { hundos.push(pid); got = true; break; }
                    }
                    var next = node.add(0x18).readPointer();
                    if (next.isNull() || next.equals(head)) break;
                    node = next;
                } catch(e) { break; }
                iters++;
            }
        }
        return {pids: hundos};
    }
};
"""


class DaemonState:
    """Owns the live frida session + scripts + cached singleton addresses."""

    def __init__(self):
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.sess = None
        self.pid = None
        self.helpers = None       # script with pogo_il2cpp.JS_PREAMBLE rpc
        self.bulk = None          # script with bulk_tag.js rpc
        self.dex_reader = None    # script with DEX_HUNDO_JS rpc
        self.bag_addr = None
        self.svc_addr = None
        self.dex_addr = None
        self.attach()

    # ------------------------------------------------------------------
    # session lifecycle
    # ------------------------------------------------------------------
    def attach(self):
        """Attach to current PoGo PID and resolve singletons. Raises on failure."""
        log.info('attaching to PoGo...')
        self.sess, self.pid = pg.get_session()
        log.info('attached pid=%s', self.pid)

        bulk_src = open(BULK_TAG_JS_PATH, 'r', encoding='utf-8').read()
        self.bulk = self.sess.create_script(bulk_src)
        self.bulk.on('message', self._on_bulk_msg)
        self.bulk.load()
        st = self.bulk.exports_sync.init_status()
        if not st.get('ready'):
            raise RuntimeError(f'bulk_tag init failed: {st}')
        log.info('bulk_tag.js loaded + ready')

        self.helpers = pg.get_script_with_helpers(self.sess)
        log.info('pogo_il2cpp helpers loaded')

        self.dex_reader = self.sess.create_script(DEX_HUNDO_JS)
        self.dex_reader.load()

        self.bag_addr = self._resolve_bag()
        log.info('bag @ %s', self.bag_addr)
        self.svc_addr = self._resolve_svc()
        log.info('svc @ %s', self.svc_addr)
        self.dex_addr = self._resolve_dex()
        log.info('dex @ %s', self.dex_addr)

        idx = self.bulk.exports_sync.index_pokemon()
        log.info('bulk index_pokemon: %s', idx)

    def _liveness_candidates(self, ns, cls):
        """Like pg.find_singleton but returns the full hit list, no count assertion."""
        script = pg.get_script_with_helpers(self.sess)
        try:
            r = script.exports_sync.find_singleton(ns, cls)
            if 'err' in r:
                raise RuntimeError(f'find_singleton({ns}.{cls}): {r["err"]}')
            return r.get('hits', [])
        finally:
            script.unload()

    def _resolve_bag(self):
        cands = self._liveness_candidates('Niantic.Holoholo.Internal', 'PokemonBagImpl')
        if not cands:
            raise RuntimeError('no PokemonBagImpl instance')
        # Pick the one whose AllPokemon walk yields the most entries (real bag).
        best, best_n = None, -1
        for c in cands:
            try:
                r = self.helpers.exports_sync.bag_walk(c)
                n = len(r) if isinstance(r, dict) else 0
                log.info('  bag candidate %s -> %d entries', c, n)
                if n > best_n:
                    best, best_n = c, n
            except Exception as e:
                log.info('  bag candidate %s -> err %r', c, e)
        if best is None:
            raise RuntimeError(f'no working bag candidate among {cands}')
        return best

    def _resolve_svc(self):
        cands = self._liveness_candidates('Niantic.Holoholo.Tagging', 'TaggingRpcService')
        if not cands:
            raise RuntimeError('no TaggingRpcService instance')
        if len(cands) == 1:
            return cands[0]
        # Pick the candidate that returns >0 tags via NumberOfTags probe.
        if not hasattr(self, '_tag_enum_script') or self._tag_enum_script is None:
            self._tag_enum_script = self.sess.create_script(TAG_ENUM_JS)
            self._tag_enum_script.load()
        best, best_n = None, -1
        for c in cands:
            try:
                r = self._tag_enum_script.exports_sync.enum_all_tags(c)
                n = r.get('totalTags', 0) if r.get('ok') else 0
                log.info('  svc candidate %s -> totalTags=%d', c, n)
                if n > best_n:
                    best, best_n = c, n
            except Exception as e:
                log.info('  svc candidate %s -> err %r', c, e)
        return best if best else cands[0]

    def _resolve_dex(self):
        cands = self._liveness_candidates('Niantic.Holoholo.Internal', 'PokedexImpl')
        if not cands:
            raise RuntimeError('no PokedexImpl instance')
        if len(cands) == 1:
            return cands[0]
        # Pick the candidate whose readAllHundos returns >0 pids.
        best, best_n = None, -1
        for c in cands:
            try:
                r = self.dex_reader.exports_sync.read_all_hundos(c)
                n = len(r.get('pids', []))
                log.info('  dex candidate %s -> %d hundos', c, n)
                if n > best_n:
                    best, best_n = c, n
            except Exception as e:
                log.info('  dex candidate %s -> err %r', c, e)
        return best if best else cands[0]

    def detach_quiet(self):
        for s in (self.helpers, self.bulk, self.dex_reader):
            try:
                if s: s.unload()
            except Exception:
                pass
        try:
            if self.sess: self.sess.detach()
        except Exception:
            pass
        self.helpers = self.bulk = self.dex_reader = self.sess = None

    def reattach(self):
        log.warning('reattaching to PoGo after process change...')
        self.detach_quiet()
        self.attach()

    def _on_bulk_msg(self, message, data):
        if message.get('type') == 'error':
            log.error('bulk script error: %s', message.get('description'))
        else:
            p = message.get('payload')
            if isinstance(p, dict) and p.get('type') == 'status':
                log.debug('bulk status: %s', p.get('msg'))

    # ------------------------------------------------------------------
    # endpoint helpers (each runs under self.lock; auto-recover on PID change)
    # ------------------------------------------------------------------
    def _run(self, fn, retries=1):
        """Call fn() under the daemon lock. If frida says process is gone, reattach + retry."""
        with self.lock:
            for attempt in range(retries + 1):
                try:
                    return fn()
                except (frida.ProcessNotFoundError, frida.InvalidOperationError,
                        frida.InvalidArgumentError) as e:
                    if attempt >= retries:
                        raise
                    log.warning('frida error %r - reattaching', e)
                    self.reattach()

    def health(self):
        return self._run(lambda: {
            'ok': True,
            'pid': self.pid,
            'bag': self.bag_addr,
            'svc': self.svc_addr,
            'dex': self.dex_addr,
            'uptime': round(time.time() - self.start_time, 2),
        })

    def bag_walk(self):
        def go():
            res = self.helpers.exports_sync.bag_walk(self.bag_addr)
            return {'count': len(res), 'results': res}
        return self._run(go)

    def dex_hundos(self):
        def go():
            r = self.dex_reader.exports_sync.read_all_hundos(self.dex_addr)
            pids = r.get('pids', [])
            return {'count': len(pids), 'pids': pids}
        return self._run(go)

    def tags_server(self):
        """Enumerate all server-side tag bindings via TaggingRpcService."""
        def go():
            return self._enum_server_tags()
        return self._run(go)

    def _enum_server_tags(self):
        """Iterate idx in [0..NumberOfTags), call findTagIdByName-equivalent flow.

        bulk_tag.js exposes listAllTags(inst) which dumps per-binding offsets;
        we need a tighter {name: count} map, so we walk via the same RPC
        primitives. Implementation: call findTagIdByName for each known name
        is wrong; instead enumerate by binding index using the dedicated
        helper script (created lazily).
        """
        if not hasattr(self, '_tag_enum_script') or self._tag_enum_script is None:
            self._tag_enum_script = self.sess.create_script(TAG_ENUM_JS)
            self._tag_enum_script.load()
        r = self._tag_enum_script.exports_sync.enum_all_tags(self.svc_addr)
        if not r.get('ok'):
            return {'err': r.get('err', 'unknown'), 'tags': {}}
        out = {}
        for t in r['tags']:
            if 'err' in t: continue
            out[t['name']] = t['boundPokemonCount']
        return {'tags': out, 'total': r.get('totalTags')}

    def tags_op(self, tag_name, uids, op):
        """op = 'add' or 'remove'. uids = list of uid strings."""
        if op not in ('add', 'remove'):
            return {'err': f'bad op: {op}'}
        def go():
            # Lookup tagProto address by name.
            ftid = self.bulk.exports_sync.find_tag_id_by_name(self.svc_addr, tag_name)
            if not ftid.get('ok'):
                return {'err': f'tag {tag_name!r} not found: {ftid.get("err")}'}
            tag_proto = ftid['tagProtoAddr']
            tag_idx = ftid['idx']

            # Resolve uids -> proto pointers via bag walk filter.
            found = self.helpers.exports_sync.bag_find_for_uids(self.bag_addr, list(uids))
            ptrs = [found[u] for u in uids if u in found]
            missing = [u for u in uids if u not in found]

            if not ptrs:
                return {'err': 'no protos resolved', 'missing': missing}

            if op == 'add':
                res = self.bulk.exports_sync.bulk_tag_many(self.svc_addr, tag_proto, ptrs)
            else:
                # bulkUntagOne is per-pokemon; iterate.
                results = []
                for p in ptrs:
                    rr = self.bulk.exports_sync.bulk_untag_one(self.svc_addr, p, tag_proto)
                    results.append(rr.get('ok', False))
                res = {'ok': all(results), 'built': sum(results), 'requested': len(ptrs)}

            return {
                'ok': bool(res.get('ok')),
                'op': op,
                'tag': tag_name,
                'tag_idx': tag_idx,
                'resolved': len(ptrs),
                'requested': len(uids),
                'missing': missing,
                'result': res,
            }
        return self._run(go)


# Enum-all-tags helper. Kept here (not bulk_tag.js) because we only need it
# for the daemon's /tags/server endpoint and we want to control its JS image.
TAG_ENUM_JS = r"""
rpc.exports = {
    enumAllTags: function(serviceAddr) {
        var il2cpp = Process.findModuleByName('libil2cpp.so');
        var exp = {};
        il2cpp.enumerateExports().forEach(function(e){ if (e.name.indexOf('il2cpp_')===0) exp[e.name] = e.address; });
        var dG = new NativeFunction(exp.il2cpp_domain_get,'pointer',[]);
        var dGA = new NativeFunction(exp.il2cpp_domain_get_assemblies,'pointer',['pointer','pointer']);
        var aGI = new NativeFunction(exp.il2cpp_assembly_get_image,'pointer',['pointer']);
        var iGN = new NativeFunction(exp.il2cpp_image_get_name,'pointer',['pointer']);
        var cFN = new NativeFunction(exp.il2cpp_class_from_name,'pointer',['pointer','pointer','pointer']);
        var cGM = new NativeFunction(exp.il2cpp_class_get_methods,'pointer',['pointer','pointer']);
        var mGN = new NativeFunction(exp.il2cpp_method_get_name,'pointer',['pointer']);
        var rI  = new NativeFunction(exp.il2cpp_runtime_invoke,'pointer',['pointer','pointer','pointer','pointer']);
        var dom = dG();
        var sp = Memory.alloc(4); var asms = dGA(dom, sp); var na = sp.readS32();
        var gameImg = null;
        for (var a=0;a<na;a++){ var i = aGI(asms.add(a*Process.pointerSize).readPointer()); if (iGN(i).readCString()==='holo-game.dll'){ gameImg=i; break; } }
        var svcCls = cFN(gameImg, Memory.allocUtf8String('Niantic.Holoholo.Tagging'), Memory.allocUtf8String('TaggingRpcService'));
        var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
        var m, getCount=null, getBinding=null;
        while ((m = cGM(svcCls, iter)) && !m.isNull()) {
            var nm = mGN(m).readCString();
            if (nm === 'get_NumberOfTags') getCount = m;
            if (nm === 'GetCachedTagToPokemonBindingForIndex') getBinding = m;
        }
        var inst = ptr(serviceAddr);
        var exc = Memory.alloc(Process.pointerSize); exc.writePointer(ptr(0));
        var ret = rI(getCount, inst, ptr(0), exc);
        var totalTags = ret.add(0x10).readS32();
        var tags = [];
        for (var i = 0; i < totalTags; i++) {
            var idxBuf = Memory.alloc(4); idxBuf.writeS32(i);
            var args = Memory.alloc(Process.pointerSize); args.writePointer(idxBuf);
            var exc2 = Memory.alloc(Process.pointerSize); exc2.writePointer(ptr(0));
            var bp = rI(getBinding, inst, args, exc2);
            if (!exc2.readPointer().isNull() || bp.isNull()) { tags.push({idx:i, err:'no binding'}); continue; }
            var tagProto = bp.add(0x10).readPointer();
            var name = '';
            try {
                var nameStr = tagProto.add(0x40).readPointer();
                if (!nameStr.isNull()) {
                    var len = nameStr.add(0x10).readS32();
                    if (len > 0 && len < 100) {
                        var chars = [];
                        for (var ci = 0; ci < len; ci++) chars.push(String.fromCharCode(nameStr.add(0x14 + ci*2).readU16()));
                        name = chars.join('');
                    }
                }
            } catch(e) {}
            var count = -1;
            for (var off of [0x18, 0x20, 0x28]) {
                try {
                    var p2 = bp.add(off).readPointer();
                    if (p2.isNull()) continue;
                    var c = p2.add(0x18).readS32();
                    if (c >= 0 && c < 100000) { count = c; break; }
                } catch(e) {}
            }
            tags.push({idx:i, name:name, boundPokemonCount: count});
        }
        return {ok:true, totalTags: totalTags, tags: tags};
    }
};
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
STATE: DaemonState = None  # set in main()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info('%s - %s', self.address_string(), fmt % args)

    def _send(self, code, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get('Content-Length', '0') or '0')
        if n == 0: return {}
        raw = self.rfile.read(n)
        return json.loads(raw.decode('utf-8'))

    def do_GET(self):
        try:
            if self.path == '/health':
                self._send(200, STATE.health()); return
            if self.path == '/bag/walk':
                self._send(200, STATE.bag_walk()); return
            if self.path == '/dex/hundos':
                self._send(200, STATE.dex_hundos()); return
            if self.path == '/tags/server':
                self._send(200, STATE.tags_server()); return
            if self.path == '/shutdown':
                self._send(200, {'ok': True, 'msg': 'shutting down'})
                threading.Thread(target=lambda: (time.sleep(0.2), os._exit(0)), daemon=True).start()
                return
            self._send(404, {'err': 'unknown path', 'path': self.path})
        except Exception as e:
            log.exception('GET %s failed', self.path)
            self._send(500, {'err': str(e), 'type': type(e).__name__})

    def do_POST(self):
        try:
            body = self._read_json()
            if self.path == '/tags/add':
                self._send(200, STATE.tags_op(body['tag_name'], body['uids'], 'add')); return
            if self.path == '/tags/remove':
                self._send(200, STATE.tags_op(body['tag_name'], body['uids'], 'remove')); return
            self._send(404, {'err': 'unknown path', 'path': self.path})
        except Exception as e:
            log.exception('POST %s failed', self.path)
            self._send(500, {'err': str(e), 'type': type(e).__name__})


class ThreadedHTTPServer(HTTPServer):
    """Daemon mutex is held inside DaemonState; we still want each request on
    its own thread so /shutdown can run while a slow query is in flight."""
    daemon_threads = True


def main():
    global STATE
    STATE = DaemonState()
    srv = ThreadedHTTPServer((HOST, PORT), Handler)
    log.info('listening on http://%s:%d', HOST, PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info('keyboard interrupt - shutting down')
    finally:
        STATE.detach_quiet()


if __name__ == '__main__':
    main()
