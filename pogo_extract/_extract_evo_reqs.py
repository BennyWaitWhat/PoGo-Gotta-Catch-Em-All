"""Read EVOLUTION REQUIREMENTS for the 3 target species from the LIVE game master.
Path: GameMasterData singleton -> Get_PokemonSettings(HoloPokemonId) -> PokemonSettingsProto
      -> evolutionBranch_ (+144 RepeatedField<EvolutionBranchProto>).
READ ONLY."""
import frida, sys, time, json
sys.path.insert(0, '.')
import pogo_il2cpp as pg
sys.stdout.reconfigure(line_buffering=True)

# pid -> (name, target_pid, target_name)
TARGETS = {
    824: ('Dottler', 826, 'Orbeetle'),
    625: ('Bisharp', 983, 'Kingambit'),
    999: ('Gimmighoul', 1000, 'Gholdengo'),
}

EVO_JS = r"""
function imgByName(name) {
    _ensureInit();
    var sp = Memory.alloc(4);
    var asms = IL2.dGA(IL2.dG(), sp);
    var na = sp.readS32();
    for (var a = 0; a < na; a++) {
        var img = IL2.aGI(asms.add(a * Process.pointerSize).readPointer());
        if (IL2.iGN(img).readCString() === name) return img;
    }
    return null;
}
function gmCls(ns, name) {
    var i = imgByName('holo-game.dll');
    return IL2.cFN(i, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
}
function readStr(p) {
    if (p.isNull()) return '';
    var len = p.add(0x10).readS32();
    if (len <= 0 || len > 400) return '';
    var s = '';
    for (var i = 0; i < len; i++) s += String.fromCharCode(p.add(0x14 + i*2).readU16());
    return s;
}
// RepeatedField<T>: items pointer @ +0x10 (managed array), count @ +0x18. Array data @ +0x20.
function repeatedCount(rf) { if (rf.isNull()) return 0; return rf.add(0x18).readS32(); }
function repeatedItemPtr(rf, i) {
    var arr = rf.add(0x10).readPointer();
    return arr.add(0x20 + i * Process.pointerSize).readPointer();
}

// Find GameMasterData singleton via liveness (DI container singleton).
rpc.exports.findgm = function() {
    var k = gmCls('', 'GameMasterData');
    if (k.isNull()) return {err:'no GameMasterData class'};
    return liveness_find_instances(k);
};

// Probe: read get_StaticDataIsReady on a candidate
rpc.exports.gmready = function(addr) {
    var k = gmCls('', 'GameMasterData');
    var m = cMN(k, 'get_StaticDataIsReady', 0);
    try { var r = rI(m, ptr(addr), ptr(0), null); return {ok:true, ready: !!(r.toInt32() & 0xff)}; }
    catch(e) { return {ok:false, err:e.toString()}; }
};

// Call Get_PokemonSettings(HoloPokemonId) -> PokemonSettingsProto, then dump evolution branches.
rpc.exports.evoreqs = function(gmAddr, pid) {
    var gmk = gmCls('', 'GameMasterData');
    // pick the 1-arg Get_PokemonSettings overload
    var m = null;
    var iter = Memory.alloc(Process.pointerSize); iter.writePointer(ptr(0));
    var mm;
    var _mGpc = (function(){
        var il2cpp=Process.findModuleByName('libil2cpp.so');var e=null;
        il2cpp.enumerateExports().forEach(function(x){if(x.name==='il2cpp_method_get_param_count')e=x.address;});
        return e?new NativeFunction(e,'uint32',['pointer']):null;
    })();
    while ((mm = IL2.cGM(gmk, iter)) && !mm.isNull()) {
        if (IL2.mGN(mm).readCString() === 'Get_PokemonSettings') {
            var pc = _mGpc ? _mGpc(mm) : -1;
            if (pc === 1) { m = mm; break; }
        }
    }
    if (!m) return {err:'no 1-arg Get_PokemonSettings'};
    // HoloPokemonId is an int32 enum -> pass boxed as a value-type arg (pointer to int32).
    var idBuf = Memory.alloc(4); idBuf.writeS32(pid);
    var args = Memory.alloc(Process.pointerSize); args.writePointer(idBuf);
    var settings;
    try { settings = rI(m, ptr(gmAddr), args, null); }
    catch(e) { return {err:'invoke threw: '+e.toString()}; }
    if (settings.isNull()) return {ok:true, found:false, pid:pid};

    // PokemonSettingsProto offsets (verified from recon):
    //  uniqueId_ @16, familyId_ @120, candyToEvolve_ @124, kmBuddyDistance_ @128,
    //  evolution_ @80 (RepeatedField<HoloPokemonId>), evolutionBranch_ @144 (RepeatedField<EvolutionBranchProto>)
    var out = {ok:true, found:true, pid:pid};
    out.uniqueId = settings.add(120).readS32();   // familyId is also the family enum
    out.familyId = settings.add(120).readS32();
    out.candyToEvolve = settings.add(124).readS32();
    out.kmBuddyDistance = settings.add(128).readFloat();
    out.unique = settings.add(16).readS32();

    // simple evolution list
    var evoRf = settings.add(80).readPointer();
    var evos = [];
    var ec = repeatedCount(evoRf);
    var evoArr = evoRf.isNull() ? null : evoRf.add(0x10).readPointer();
    for (var i = 0; i < ec && i < 20; i++) {
        evos.push(evoArr.add(0x20 + i*4).readS32());
    }
    out.evolutionIds = evos;

    // evolution branches
    var brRf = settings.add(144).readPointer();
    var bc = repeatedCount(brRf);
    var branches = [];
    for (var b = 0; b < bc && b < 20; b++) {
        var br = repeatedItemPtr(brRf, b);
        if (br.isNull()) continue;
        // EvolutionBranchProto offsets (verified):
        //  Evolution@16, EvolutionItemRequirement@20, CandyCost@24, KmBuddyDistanceRequirement@28,
        //  Form@32, GenderRequirement@36, LureItemRequirement@40, MustBeBuddy@44,
        //  Priority@48, NoCandyCostViaTrade@52, TemporaryEvolution@56,
        //  QuestDisplay@72 (RepeatedField<EvolutionQuestInfoProto>),
        //  CandyCostPurified@84, EvolutionItemRequirementCost@92, EvolutionMoveRequirement@96
        var branch = {
            evolution:        br.add(16).readS32(),
            evolutionItemReq: br.add(20).readS32(),
            candyCost:        br.add(24).readS32(),
            kmBuddyDistanceReq: br.add(28).readFloat(),
            form:             br.add(32).readS32(),
            genderReq:        br.add(36).readS32(),
            lureItemReq:      br.add(40).readS32(),
            mustBeBuddy:      !!br.add(44).readU8(),
            priority:         br.add(48).readS32(),
            noCandyViaTrade:  !!br.add(52).readU8(),
            tempEvolution:    br.add(56).readS32(),
            candyCostPurified: br.add(84).readS32(),
            evoItemReqCost:   br.add(92).readS32(),
            evoMoveReq:       br.add(96).readS32(),
        };
        // QuestDisplay repeated field
        var qdRf = br.add(72).readPointer();
        var qdc = repeatedCount(qdRf);
        var quests = [];
        for (var q = 0; q < qdc && q < 10; q++) {
            var qd = repeatedItemPtr(qdRf, q);
            if (qd.isNull()) continue;
            // EvolutionQuestInfoProto: QuestRequirementTemplateId@16(string), Description@24(string), Target@32(int)
            quests.push({
                templateId: readStr(qd.add(16).readPointer()),
                description: readStr(qd.add(24).readPointer()),
                target: qd.add(32).readS32(),
            });
        }
        branch.quests = quests;
        branches.push(branch);
    }
    out.branches = branches;
    return out;
};
"""

def pick_gm(sc, hits):
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    for h in hits:
        try:
            r = sc.exports_sync.gmready(h)
            if r.get('ok') and r.get('ready'):
                return h
        except Exception:
            pass
    return hits[0]

def main():
    for attempt in range(10):
        try:
            sess, pid = pg.get_session()
            print(f"attached pid={pid}")
            sc = pg.get_script_with_helpers(sess, EVO_JS)
            sc.exports_sync.init()
            gm_r = sc.exports_sync.findgm()
            if 'err' in gm_r:
                print(f"findGM err: {gm_r['err']}")
                sess.detach(); return
            hits = gm_r.get('hits', [])
            print(f"GameMasterData instances: {len(hits)} -> {hits}")
            gm = pick_gm(sc, hits)
            print(f"using GM @ {gm}")
            out = {}
            for spid, (name, tpid, tname) in TARGETS.items():
                r = sc.exports_sync.evoreqs(gm, spid)
                out[str(spid)] = {'name': name, 'target_pid': tpid, 'target_name': tname, 'data': r}
                print(f"\n=== {name} (pid {spid}) -> {tname} (pid {tpid}) ===")
                if r.get('err'):
                    print(f"  ERR: {r['err']}")
                    continue
                if not r.get('found'):
                    print("  no PokemonSettings found")
                    continue
                print(f"  familyId={r['familyId']} candyToEvolve(default)={r['candyToEvolve']} kmBuddy={r['kmBuddyDistance']}")
                print(f"  evolutionIds={r['evolutionIds']}")
                for b in r['branches']:
                    print(f"  BRANCH -> evo={b['evolution']} candyCost={b['candyCost']} "
                          f"itemReq={b['evolutionItemReq']} itemReqCost={b['evoItemReqCost']} "
                          f"kmBuddy={b['kmBuddyDistanceReq']} mustBeBuddy={b['mustBeBuddy']} "
                          f"lureReq={b['lureItemReq']} moveReq={b['evoMoveReq']} "
                          f"tempEvo={b['tempEvolution']} noCandyViaTrade={b['noCandyViaTrade']}")
                    for q in b['quests']:
                        print(f"      QUEST templateId='{q['templateId']}' target={q['target']} desc='{q['description']}'")
            json.dump(out, open('_extract_evo_reqs_out.json','w'), indent=2)
            print("\nwrote _extract_evo_reqs_out.json")
            sess.detach()
            return
        except (frida.InvalidOperationError, frida.TransportError, frida.ProcessNotFoundError,
                frida.ServerNotRunningError, RuntimeError) as e:
            print(f"[retry {attempt+1}] {type(e).__name__}: {e}")
            time.sleep(4)

if __name__ == '__main__':
    main()
