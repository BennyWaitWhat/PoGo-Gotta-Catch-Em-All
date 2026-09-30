"""Frida session preamble: version check + drift check before any DB writes.

Call run_preflight() from any extraction script BEFORE you open a sqlite
connection or send writes. Returns a ValidationResult; the caller decides
whether to bail.

Wire-up in an existing extract script:

    from frida_session_guard import run_preflight, PreflightError
    try:
        result = run_preflight(session, sample_count=64)
    except PreflightError as e:
        print(f"preflight failed: {e}"); sys.exit(2)
    # result.passed == True from here on
"""
from __future__ import annotations

import json
import sys
import time

from offset_validator import ValidationResult, validate_samples, mark_validated
from version_detector import (
    adb_dumpsys_versionname, load_offsets, load_state, reconcile, mark_run,
)


_SAMPLER_JS = r"""
// Walk PokemonBagImpl.pokemonById_ (LinkedHashMap) and emit raw bytes for
// PokemonProto + PokemonDisplayProto. The caller passes the offsets in case
// the LinkedHashMap layout itself drifts.
rpc.exports = {
    sample: function(bagInstAddr, takeCount, protoSize, displayPtrOffset, displaySize) {
        var bag = ptr(bagInstAddr);
        var dict = bag.add(0x10).readPointer();
        if (dict.isNull()) return {err: "bag.dict null"};
        var entries = dict.add(0x18).readPointer();
        if (entries.isNull()) return {err: "dict.entries null"};
        var maxLen = entries.add(0x18).readS32();
        var data = entries.add(0x20);
        var entrySize = 24;
        var protoHex = [], displayHex = [];
        for (var i = 0; i < maxLen && protoHex.length < takeCount; i++) {
            var ep = data.add(i * entrySize);
            if (ep.readS32() < 0) continue;
            var valPtr = ep.add(16).readPointer();
            if (valPtr.isNull()) continue;
            try {
                protoHex.push(hexdump(valPtr, {length: protoSize, header: false, ansi: false})
                              .split('\n').map(function(l){return l.split('  ')[1].replace(/ /g,'');}).join(''));
                var dp = valPtr.add(displayPtrOffset).readPointer();
                if (!dp.isNull()) {
                    displayHex.push(hexdump(dp, {length: displaySize, header: false, ansi: false})
                                    .split('\n').map(function(l){return l.split('  ')[1].replace(/ /g,'');}).join(''));
                }
            } catch (e) {}
        }
        return {proto: protoHex, display: displayHex};
    }
};
"""


class PreflightError(RuntimeError):
    pass


def run_preflight(frida_session,
                  bag_resolver,
                  *,
                  sample_count: int = 64,
                  display_ptr_offset: int = 0x158,
                  auto_promote: bool = False) -> ValidationResult:
    """Version-check, sample-pull, drift-validate. Returns a ValidationResult.

    `frida_session` is an attached frida.core.Session.
    `bag_resolver(session) -> int` resolves a PokemonBagImpl* (you already have
        the lookup logic in extract_owners_bagwalk.py and read_pokedex.py).

    `display_ptr_offset` is the byte offset on PokemonProto where the
        PokemonDisplayProto pointer lives; default 0x158 matches v1 layout.
    """
    version = adb_dumpsys_versionname()
    offsets = load_offsets()
    state = load_state()
    info = reconcile(version, offsets, state)

    print(f"PoGo {version} (was {info['last_seen']}); status={info['status']}, "
          f"action={info['action_required']}")

    if info["action_required"] == "none":
        mark_run(version)
        return ValidationResult(version=version, timestamp=int(time.time()),
                                sentinels=[], skipped_reasons=["no-op same version"])

    if info["action_required"] == "full_validation":
        raise PreflightError(
            f"PoGo {version} is unknown. Re-run offset discovery (analyze_offsets.py + "
            f"offset_validate.py), then call offset_validator.mark_validated({version!r})."
        )

    # action == drift_check: pull samples and verify each sentinel still holds.
    proto_block = offsets["versions"][version]["structs"]["PokemonProto"]
    display_block = offsets["versions"][version]["structs"]["PokemonDisplayProto"]

    bag_addr = bag_resolver(frida_session)
    script = frida_session.create_script(_SAMPLER_JS)
    script.load()
    out = script.exports_sync.sample(
        str(bag_addr), sample_count,
        proto_block["size_bytes"], display_ptr_offset, display_block["size_bytes"],
    )
    if "err" in out:
        raise PreflightError(f"sampler: {out['err']}")

    samples = {
        "PokemonProto": [bytes.fromhex(h) for h in out.get("proto", [])],
        "PokemonDisplayProto": [bytes.fromhex(h) for h in out.get("display", [])],
    }
    result = validate_samples(version, samples)
    result.dump()
    result.log()

    if not result.passed:
        raise PreflightError(
            "drift detected: refusing to write. See drift_log.jsonl for details."
        )

    if auto_promote and not info["known"]:
        mark_validated(version)
    mark_run(version)
    return result


def main() -> int:
    # Convenience: dry-run without a Frida session, just compares versions.
    try:
        v = adb_dumpsys_versionname()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    offsets = load_offsets()
    state = load_state()
    info = reconcile(v, offsets, state)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
