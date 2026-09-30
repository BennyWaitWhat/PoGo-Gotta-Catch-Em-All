#!/usr/bin/env python
"""Static reader for global-metadata.dat (IL2CPP metadata v31) — NO DEVICE NEEDED.

Recovers AUTHORITATIVE type names, field names + declaration order, and enum
members+values from PoGo's global-metadata.dat. Field byte-OFFSETS are NOT stored
in metadata (they live in libil2cpp.so); but field identity/order is ground truth,
and PoGo protos (Google.Protobuf C# classes) lay out in declaration order after the
0x10 arm64 object header, so index->offset is largely mechanical.

Usage:
  python meta_dump.py QuestProto
  python meta_dump.py --ns Holoholo.Rpc QuestProto
  python meta_dump.py --enum QuestRewardProto.RewardOneofCase
  python meta_dump.py --grep Quest        # list type FQNs whose name contains 'Quest'

Verified working 2026-05-29 against pogo_extract/global-metadata.dat (v31, 0xFAB11BAF).
"""
import struct, sys, os

PATH = os.environ.get(
    "POGO_METADATA",
    r"C:\Users\Blanco\Desktop\Claude Operations\Phone Maintenance\pogo_extract\global-metadata.dat",
)
d = open(PATH, "rb").read()
u32 = lambda o: struct.unpack_from('<I', d, o)[0]
i32 = lambda o: struct.unpack_from('<i', d, o)[0]
u16 = lambda o: struct.unpack_from('<H', d, o)[0]
assert u32(0) == 0xFAB11BAF, "bad magic (not il2cpp metadata)"
assert u32(4) == 31, f"expected metadata v31, got v{u32(4)} (header offsets below are v31-specific)"

# Header = sanity(u32) + version(u32) then (offset,size) u32 pairs in this order (v31):
H = ['stringLiteral','stringLiteralData','string','events','properties','methods',
     'parameterDefaultValues','fieldDefaultValues','fieldAndParameterDefaultValueData',
     'fieldMarshaledSizes','parameters','fields','genericParameters',
     'genericParameterConstraints','genericContainers','nestedTypes','interfaces',
     'vtableMethods','interfaceOffsets','typeDefinitions','images','assemblies',
     'fieldRefs','referencedAssemblies','attributeData','attributeDataRange',
     'unresolvedIndirectCallParameterTypes','unresolvedIndirectCallParameterRanges',
     'windowsRuntimeTypeNames','windowsRuntimeStrings','exportedTypeDefinitions']
o = 8; hdr = {}
for nm in H:
    hdr[nm] = (u32(o), u32(o + 4)); o += 8

soff, ssz = hdr['string']; sb = d[soff:soff + ssz]
cstr = lambda i: sb[i:sb.find(b'\x00', i)].decode('utf-8', 'ignore')

TD, TDSZ = hdr['typeDefinitions'][0], 0x58   # Il2CppTypeDefinition size for THIS build (probed)
FLD, FLDSZ = hdr['fields'][0], 0x0C          # {nameIndex i32, typeIndex i32, token u32}
NEST = hdr['nestedTypes'][0]                 # array of i32 type indices
FDV = hdr['fieldDefaultValues'][0]; FDVN = hdr['fieldDefaultValues'][1] // 12
DATA = hdr['fieldAndParameterDefaultValueData'][0]
fdv = {}
for i in range(FDVN):
    b = FDV + i * 12; fdv[i32(b)] = i32(b + 8)

# Il2CppTypeDefinition field offsets (v31): name@0 ns@4 fieldStart@0x20
#   field_count@0x44 (u16); nestedTypesStart@0x30; nested_type_count@0x48 (u16)
def types():
    n = hdr['typeDefinitions'][1] // TDSZ
    for i in range(n):
        yield i, TD + i * TDSZ

def find(name, ns=None):
    for _, b in types():
        if cstr(i32(b)) == name and (ns is None or cstr(i32(b + 4)) == ns):
            return b
    return None

def fields(b):
    fs = i32(b + 0x20); fc = u16(b + 0x44)
    return [cstr(i32(FLD + fi * FLDSZ)) for fi in range(fs, fs + fc)]

def enum_members(b):
    fs = i32(b + 0x20); fc = u16(b + 0x44); out = []
    for fi in range(fs, fs + fc):
        nm = cstr(i32(FLD + fi * FLDSZ))
        if nm == 'value__':
            continue
        di = fdv.get(fi)
        val = struct.unpack_from('<i', d, DATA + di)[0] if di not in (None, -1) else None
        out.append((nm, val))
    return out

def main():
    args = sys.argv[1:]
    ns = None
    if '--ns' in args:
        i = args.index('--ns'); ns = args[i + 1]; del args[i:i + 2]
    if not args:
        print(__doc__); return
    if args[0] == '--grep':
        needle = args[1]
        seen = set()
        for _, b in types():
            nm = cstr(i32(b))
            if needle.lower() in nm.lower():
                fq = f"{cstr(i32(b + 4))}.{nm}"
                if fq not in seen:
                    seen.add(fq); print(fq)
        return
    if args[0] == '--enum':
        outer, inner = args[1].split('.')
        ob = find(outer, ns)
        if not ob:
            print("outer type not found"); return
        ns0 = i32(ob + 0x30); nc = u16(ob + 0x48); tgt = None
        for k in range(ns0, ns0 + nc):
            nb = TD + i32(NEST + k * 4) * TDSZ
            if cstr(i32(nb)) == inner:
                tgt = nb
        if not tgt:
            print(f"nested enum {inner} not found in {outer}"); return
        for nm, v in enum_members(tgt):
            print(f"{v}: {nm}")
        return
    b = find(args[0], ns)
    if not b:
        print("type not found (try --grep)"); return
    print(f"{cstr(i32(b + 4))}.{args[0]}  (field_count={u16(b + 0x44)})")
    for j, f in enumerate(fields(b)):
        print(f"  [{j}] {f}")

if __name__ == '__main__':
    main()
