"""Read-only: current PlayerStats.KmWalked (live copies) + the method names/arg counts on PlayerStatsProto."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import pogo_il2cpp as pg
import dump_game_limits as dl
JS = dl.JS.split("rpc.exports = {")[0] + r"""
rpc.exports = {
  go: function () {
    var kl = findClass('holo-protos.dll', 'PlayerStatsProto');
    var getM = new NativeFunction(EX['il2cpp_class_get_methods'], 'pointer', ['pointer', 'pointer'], PROP);
    var mName = new NativeFunction(EX['il2cpp_method_get_name'], 'pointer', ['pointer'], PROP);
    var mArgs = new NativeFunction(EX['il2cpp_method_get_param_count'], 'uint32', ['pointer'], PROP);
    var it = Memory.alloc(PS); it.writePointer(NULL); var m, meth = [];
    while ((m = getM(kl, it)) && !m.isNull()) meth.push(cs(mName(m)) + '/' + mArgs(m));
    var kms = instances(kl, 64).map(function (o) { var r = readObj(o, 0); return r.KmWalked; });
    return {methods: meth, km: kms};
  }
};
"""
sess, pid = pg.get_session(); sc = sess.create_script(JS); sc.load()
r = sc.exports_sync.go(); sc.unload(); sess.detach()
print("methods:", r["methods"]); print("KmWalked live copies:", sorted(set(r["km"]), key=lambda x: float(x or 0))[-5:])
