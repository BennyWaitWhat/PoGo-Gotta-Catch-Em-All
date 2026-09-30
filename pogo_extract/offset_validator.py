"""Drift-check the known offsets against live samples.

Inputs:  list of {struct_name: hex_bytes} samples pulled via Frida.
Output:  per-sentinel pass/fail report. If any FAIL, refuse writes.

Usage as a module:
    from offset_validator import validate_samples, ValidationResult
    result = validate_samples(version, samples)
    if not result.passed:
        result.dump(); sys.exit(1)

Standalone usage (samples on stdin as JSON):
    python offset_validator.py 0.359.0 < samples.json
"""
from __future__ import annotations

import dataclasses as dc
import json
import struct
import sys
import time
from pathlib import Path

OFFSETS_PATH = Path(__file__).with_name("pogo_offsets.json")
LOG_PATH = Path(__file__).with_name("drift_log.jsonl")

_FMT = {
    "i32": ("<i", 4),
    "u32": ("<I", 4),
    "i64": ("<q", 8),
    "u64": ("<Q", 8),
    "f32": ("<f", 4),
    "byte": ("<B", 1),
}


def _read(raw: bytes, offset: int, ftype: str):
    fmt, size = _FMT[ftype]
    if offset + size > len(raw):
        return None
    return struct.unpack_from(fmt, raw, offset)[0]


@dc.dataclass
class SentinelResult:
    sentinel_id: str
    struct_name: str
    field: str
    rule: str
    sample_size: int
    pass_count: int
    fail_count: int
    fail_examples: list[tuple]   # up to 5 (value, sample_idx)
    status: str                  # PASS | FAIL | SKIP

    @property
    def pass_rate(self) -> float:
        return self.pass_count / self.sample_size if self.sample_size else 0.0


@dc.dataclass
class ValidationResult:
    version: str
    timestamp: int
    sentinels: list[SentinelResult]
    skipped_reasons: list[str]

    @property
    def passed(self) -> bool:
        return all(s.status != "FAIL" for s in self.sentinels)

    @property
    def any_skipped(self) -> bool:
        return any(s.status == "SKIP" for s in self.sentinels) or bool(self.skipped_reasons)

    def dump(self, stream=sys.stdout) -> None:
        stream.write(f"\n=== Offset drift check: PoGo {self.version} ===\n")
        for s in self.sentinels:
            tag = {"PASS": "OK  ", "FAIL": "FAIL", "SKIP": "skip"}[s.status]
            stream.write(
                f"  [{tag}] {s.sentinel_id:<32} "
                f"{s.pass_count}/{s.sample_size} pass ({s.pass_rate:.2%})\n"
            )
            if s.status == "FAIL" and s.fail_examples:
                for v, idx in s.fail_examples[:3]:
                    stream.write(f"        sample[{idx}] {s.field}={v!r}\n")
        for r in self.skipped_reasons:
            stream.write(f"  [skip] {r}\n")
        stream.write(f"  overall: {'PASS' if self.passed else 'FAIL'}\n")

    def to_jsonl(self) -> str:
        return json.dumps({
            "ts": self.timestamp,
            "version": self.version,
            "passed": self.passed,
            "sentinels": [dc.asdict(s) for s in self.sentinels],
            "skipped": self.skipped_reasons,
        })

    def log(self) -> None:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(self.to_jsonl() + "\n")


def _load_offsets() -> dict:
    with open(OFFSETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_field(version_block: dict, struct_name: str, field: str):
    """Return (offset, type) or None if the schema does not describe it."""
    s = version_block.get("structs", {}).get(struct_name)
    if not s:
        return None
    f = s.get("fields", {}).get(field)
    if not f:
        return None
    return f["offset"], f["type"]


def _check_one(raw_samples: list[bytes],
               sentinel: dict,
               version_block: dict) -> SentinelResult:
    struct_name = sentinel["struct"]
    field = sentinel["field"]
    rule = sentinel["rule"]
    resolved = _resolve_field(version_block, struct_name, field)
    if not resolved:
        return SentinelResult(
            sentinel_id=sentinel["id"], struct_name=struct_name, field=field,
            rule=rule, sample_size=0, pass_count=0, fail_count=0,
            fail_examples=[], status="SKIP",
        )
    offset, ftype = resolved

    exclude = sentinel.get("exclude_when_field_eq")
    exclude_offset, exclude_type, exclude_values = None, None, None
    if exclude:
        e = _resolve_field(version_block, struct_name, exclude["field"])
        if e:
            exclude_offset, exclude_type = e
            exclude_values = set(exclude["values"])

    pass_count = 0
    fail_count = 0
    fail_examples: list[tuple] = []
    used = 0
    for idx, raw in enumerate(raw_samples):
        if exclude_offset is not None:
            ev = _read(raw, exclude_offset, exclude_type)
            if ev in exclude_values:
                continue
        v = _read(raw, offset, ftype)
        if v is None:
            continue
        used += 1
        ok = _evaluate(rule, v, sentinel)
        if ok:
            pass_count += 1
        else:
            fail_count += 1
            if len(fail_examples) < 5:
                fail_examples.append((v, idx))

    min_n = sentinel.get("min_sample_size", 1)
    min_rate = sentinel.get("min_pass_rate", 0.99)

    if used < min_n:
        status = "SKIP"
    elif (pass_count / used) >= min_rate:
        status = "PASS"
    else:
        status = "FAIL"

    return SentinelResult(
        sentinel_id=sentinel["id"], struct_name=struct_name, field=field,
        rule=rule, sample_size=used, pass_count=pass_count,
        fail_count=fail_count, fail_examples=fail_examples, status=status,
    )


def _evaluate(rule: str, value, sentinel: dict) -> bool:
    if rule == "range":
        return sentinel["min"] <= value <= sentinel["max"]
    if rule == "enum":
        return value in sentinel["values"]
    if rule == "nonzero":
        return value != 0
    if rule == "exact":
        return value == sentinel["expected"]
    raise ValueError(f"unknown sentinel rule: {rule}")


def validate_samples(version: str,
                     samples_by_struct: dict[str, list[bytes]]) -> ValidationResult:
    """Run all sentinels for `version` against the provided samples.

    samples_by_struct: {struct_name: [raw_bytes, ...], ...}
    """
    offsets = _load_offsets()
    block = offsets.get("versions", {}).get(version)
    skipped: list[str] = []
    if not block:
        skipped.append(f"no offset block for version {version}")
        return ValidationResult(version=version, timestamp=int(time.time()),
                                sentinels=[], skipped_reasons=skipped)

    results = []
    for sentinel in block.get("sentinels", []):
        s_name = sentinel["struct"]
        raws = samples_by_struct.get(s_name)
        if not raws:
            results.append(SentinelResult(
                sentinel_id=sentinel["id"], struct_name=s_name,
                field=sentinel["field"], rule=sentinel["rule"],
                sample_size=0, pass_count=0, fail_count=0,
                fail_examples=[], status="SKIP",
            ))
            skipped.append(f"no samples for struct {s_name}")
            continue
        results.append(_check_one(raws, sentinel, block))

    return ValidationResult(version=version, timestamp=int(time.time()),
                            sentinels=results, skipped_reasons=skipped)


def mark_validated(version: str, package_offsets: dict | None = None) -> None:
    """Promote `version` to known_good in pogo_offsets.json.

    If package_offsets is None, copy the previous known_good version's struct
    block forward (drift check passed, so offsets still apply).
    """
    data = _load_offsets()
    versions = data.setdefault("versions", {})
    if version not in versions:
        if not package_offsets:
            # Find latest known_good and clone its structs.
            known = [k for k, v in versions.items() if v.get("status") == "known_good"]
            if not known:
                raise RuntimeError("no prior known_good version to clone from")
            base = versions[sorted(known)[-1]]
            package_offsets = {
                "structs": base["structs"],
                "sentinels": base["sentinels"],
            }
        versions[version] = {
            "first_seen": time.strftime("%Y-%m-%d"),
            "last_validated": time.strftime("%Y-%m-%d"),
            "status": "known_good",
            "notes": "Promoted after drift check passed.",
            **package_offsets,
        }
    else:
        versions[version]["last_validated"] = time.strftime("%Y-%m-%d")
        versions[version]["status"] = "known_good"
    data["last_validated_version"] = version
    tmp = OFFSETS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    Path(tmp).replace(OFFSETS_PATH)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: offset_validator.py <version> [samples.json]", file=sys.stderr)
        return 2
    version = sys.argv[1]
    src = open(sys.argv[2]) if len(sys.argv) > 2 else sys.stdin
    payload = json.load(src)
    # JSON in: {"PokemonProto": ["aabbcc...", ...], ...} hex strings.
    samples = {
        s: [bytes.fromhex(h) for h in arr]
        for s, arr in payload.items()
    }
    result = validate_samples(version, samples)
    result.dump()
    result.log()
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
