"""Capture the asset URLs Pokemon GO actually requests, by hooking il2cpp_string_new in the live game.

User 2026-09-02: "My game's pokemon inventory obviously load their images... find what the game is using
and loading." The device caches downloaded assets under files/DiskCache with HASHED filenames and stores
no URL anywhere, so the only way to learn the URL template is to watch the game build it.

Every managed string the game creates passes through il2cpp_string_new / il2cpp_string_new_len. We hook
both, keep only strings that look like asset URLs, and print the distinct ones. Open the Pokemon inventory
(or scroll it) while this runs and the icon URLs appear.

READ-ONLY: hooks observe and return immediately, nothing is modified, no GC world is stopped, and the
script detaches cleanly. Attach only through pogo_il2cpp.get_session(), which refuses a cold-starting
process.

    python sniff_asset_urls.py [--seconds 60]
"""
import argparse, collections, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pogo_il2cpp as pg

JS = r"""
var seen = {};
function look(s) {
    if (!s) return;
    // asset-ish only: keep the noise down, we want URLs and asset paths
    if (s.length < 8) return;
    if (!/^https?:\/\//i.test(s) && !/(pokemon|icon|sprite|asset|addressable|\.png|\.jpg|\.webp)/i.test(s)) return;
    if (seen[s]) return;
    seen[s] = 1;
    send({url: s});
}
var m = Process.findModuleByName('libil2cpp.so');
var exp = {};
m.enumerateExports().forEach(function (e) { exp[e.name] = e.address; });

if (exp['il2cpp_string_new']) {
    Interceptor.attach(exp['il2cpp_string_new'], {
        onEnter: function (a) { try { look(a[0].readUtf8String()); } catch (e) {} }
    });
}
if (exp['il2cpp_string_new_len']) {
    Interceptor.attach(exp['il2cpp_string_new_len'], {
        onEnter: function (a) {
            try { look(a[0].readUtf8String(a[1].toInt32())); } catch (e) {}
        }
    });
}
send({ready: true, hooked: Object.keys(exp).filter(function (k) { return k.indexOf('string_new') >= 0; })});
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=60)
    a = ap.parse_args()

    sess, pid = pg.get_session()
    print('attached pid %d -- open/scroll the Pokemon inventory now' % pid)
    urls = collections.Counter()

    def on_message(msg, data):
        if msg.get('type') != 'send':
            return
        p = msg.get('payload') or {}
        if p.get('ready'):
            print('hooks installed: %s' % p.get('hooked'))
        elif p.get('url'):
            u = p['url']
            urls[u] += 1
            if len(urls) <= 400:
                print('  %s' % u[:200])

    script = sess.create_script(JS)
    script.on('message', on_message)
    script.load()
    try:
        time.sleep(a.seconds)
    finally:
        try:
            script.unload()
        except Exception:
            pass
        sess.detach()

    print('\n=== %d distinct asset-ish strings ===' % len(urls))
    hosts = collections.Counter()
    for u in urls:
        if u.lower().startswith('http'):
            hosts[u.split('/')[2] if len(u.split('/')) > 2 else u] += 1
    print('hosts:', dict(hosts.most_common(10)))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'asset_urls.txt')
    open(out, 'w', encoding='utf-8').write('\n'.join(sorted(urls)))
    print('wrote %s' % out)


if __name__ == '__main__':
    main()
