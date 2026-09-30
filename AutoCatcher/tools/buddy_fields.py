"""Read-only: every field of the live BuddyObservedData (zeros included) and its nested messages, to find the
"Walk together x.xx / 2.00 km" daily-heart record."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
function raw(o, depth) {
  var jc; try { jc = jsClass(o); } catch (e) { return '<unreadable>'; }
  var res = {_class: jc.name};
  fieldsOf(jc.k).forEach(function (fd) {
    try {
      var p = o.add(fd.off);
      if (fd.te === 0x12 || fd.te === 0x15) {
        if (fd.te === 0x15 && IL.isValueType(IL.classFromType(fd.t))) { res[fd.name] = '<struct ' + fd.tn + '>'; return; }
        var q = p.readPointer(); if (q.isNull()) { res[fd.name] = null; return; }
        var qn = jsClass(q).name;
        if (qn.indexOf('MapField') === 0 || qn.indexOf('Dictionary') === 0) {   /* MapField wraps a Dictionary: count its entries */
          var sub = {}; fieldsOf(jsClass(q).k).forEach(function (g) { try { var r = q.add(g.off).readPointer(); if (!r.isNull()) { var rn = jsClass(r).name; if (/Dictionary/.test(rn)) { fieldsOf(jsClass(r).k).forEach(function (h) { if (/count/i.test(h.name)) sub.count = r.add(h.off).readS32(); }); } } } catch (e) {} });
          res[fd.name] = {map: qn, tn: fd.tn, count: sub.count}; return;
        }
        res[fd.name] = depth < 2 ? raw(q, depth + 1) : '<' + qn + '>';
      } else if (fd.te === 0x0e) { res[fd.name] = str(p.readPointer()); }
      else if (fd.te === 0x11) { res[fd.name] = p.readS32(); }
      else { var v = prim(p, fd.te); res[fd.name] = v === undefined ? '<' + fd.tn + '>' : v; }
    } catch (e) { res[fd.name] = '<err>'; }
  });
  return res;
}
rpc.exports = {
  go: function () {
    var kl = findClass('holo-protos.dll', 'BuddyObservedData'); if (!kl) return 'no class';
    return instances(kl, 8).map(function (o) { return raw(o, 0); });
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
r = sc.exports_sync.go(); sc.unload(); sess.detach()
print(json.dumps(r[-1] if isinstance(r, list) and r else r, indent=1)[:5000])
