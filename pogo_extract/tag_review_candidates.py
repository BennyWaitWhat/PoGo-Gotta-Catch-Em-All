"""Tag candidates from review_candidates_final.json as REVIEW on the server."""
import json, os, time, sys, subprocess
import pogo_il2cpp as pg

sys.stdout.reconfigure(line_buffering=True)

CANDIDATES_PATH = 'review_candidates_final.json'
RESULT_PATH = 'tag_review_result.json'
TAG_NAME = 'REVIEW'
TAG_COLOR = 7
BATCH_SIZE = 30
BATCH_PACE_S = 0.4


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _to_unsigned_u64_str(v):
    if isinstance(v, str):
        if v.lower().startswith('0x'):
            return str(int(v, 16))
        # decimal: handle signed
        n = int(v)
    elif isinstance(v, int):
        n = v
    else:
        raise TypeError(f"can't convert {type(v).__name__} to UID")
    if n < 0:
        n += 1 << 64
    return str(n)


def _extract_uid(item):
    if isinstance(item, (str, int)):
        return _to_unsigned_u64_str(item)
    if isinstance(item, dict):
        # prefer hex if present (always unsigned), otherwise signed int
        if 'uid_hex' in item:
            return _to_unsigned_u64_str('0x' + item['uid_hex'])
        for k in ('uid', 'uid_int_signed', 'uid_unsigned', 'uid_str'):
            if k in item:
                return _to_unsigned_u64_str(item[k])
        raise KeyError(f"no uid key in {list(item.keys())}")
    raise TypeError(f"can't extract uid from {type(item).__name__}")


def wait_for_candidates():
    log(f"waiting for {CANDIDATES_PATH}...")
    last_log = 0
    while not os.path.exists(CANDIDATES_PATH):
        time.sleep(2)
        last_log += 2
        if last_log >= 30:
            log(f"  still waiting...")
            last_log = 0
    with open(CANDIDATES_PATH, 'r') as f:
        data = json.load(f)
    if isinstance(data, dict):
        items = (data.get('candidates') or data.get('uids') or data.get('review')
                 or data.get('review_candidates'))
        if items is None:
            for k, v in data.items():
                if isinstance(v, list) and v:
                    items = v
                    break
        if items is None:
            raise RuntimeError(f"can't find UID list in {CANDIDATES_PATH}: keys={list(data.keys())}")
    else:
        items = data
    uid_strs = [_extract_uid(it) for it in items]
    # dedup but preserve order
    seen, uniq = set(), []
    for u in uid_strs:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    log(f"loaded {len(uniq)} unique candidate UIDs (raw items: {len(items)})")
    return uniq


def find_or_create_review_tag(bulk, svc):
    log(f"looking for existing '{TAG_NAME}' tag...")
    r = bulk.exports_sync.find_tag_id_by_name(svc, TAG_NAME)
    if r.get('ok'):
        log(f"  found existing: idx={r.get('idx')} tagProto={r.get('tagProtoAddr')}")
        return r
    log(f"  not found; creating '{TAG_NAME}' (color={TAG_COLOR})...")
    add = bulk.exports_sync.add_tag_on_instance(svc, TAG_NAME, TAG_COLOR)
    log(f"  AddTag result: {add}")
    if not add.get('ok'):
        raise RuntimeError(f"AddTag failed: {add}")
    log(f"  waiting 5s for server round-trip...")
    time.sleep(5)
    r2 = bulk.exports_sync.find_tag_id_by_name(svc, TAG_NAME)
    if not r2.get('ok'):
        raise RuntimeError(f"created '{TAG_NAME}' but can't find it after: {r2}")
    log(f"  created: idx={r2.get('idx')} tagProto={r2.get('tagProtoAddr')}")
    return r2


def server_count_for_tag(bulk, svc, tag_idx):
    chk = bulk.exports_sync.get_pokemon_for_tag(svc, tag_idx)
    if not isinstance(chk, dict):
        return None
    dump = chk.get('dump', {})
    for k, v in dump.items():
        if isinstance(v, dict) and 'count' in v and isinstance(v['count'], int):
            return v['count']
    return None


def run():
    uids = wait_for_candidates()

    log("connecting to PoGo via Frida...")
    sess, pid = pg.get_session()
    log(f"  attached PID {pid}")

    log("resolving singletons (PokemonBagImpl + TaggingRpcService)...")
    bag = pg.find_singleton(sess, 'Niantic.Holoholo.Internal', 'PokemonBagImpl')
    log(f"  bag @ {bag}")
    svc = pg.find_singleton(sess, 'Niantic.Holoholo.Tagging', 'TaggingRpcService')
    log(f"  svc @ {svc}")

    log("walking bag for candidate proto pointers...")
    proto_map = pg.find_protos_for_uids(sess, bag, uids)
    log(f"  found {len(proto_map)}/{len(uids)} protos in bag")
    missing = [u for u in uids if u not in proto_map]
    if missing:
        log(f"  missing UIDs ({len(missing)}): {missing[:10]}{'...' if len(missing)>10 else ''}")

    log("loading bulk_tag.js...")
    bulk = sess.create_script(open('bulk_tag.js', 'r', encoding='utf-8').read())

    def on(msg, data):
        p = msg.get('payload', {}) if isinstance(msg, dict) else {}
        if isinstance(p, dict):
            t = p.get('type', '')
            if t in ('status', 'ready'):
                log(f"  [js] {p.get('msg', '')}")
            elif msg.get('type') == 'error':
                log(f"  [frida-err] {msg.get('description', '')}")
    bulk.on('message', on)
    bulk.load()
    st = bulk.exports_sync.init_status()
    if not st.get('ready'):
        raise RuntimeError(f"init failed: {st}")

    tag_info = find_or_create_review_tag(bulk, svc)
    tag_proto = tag_info['tagProtoAddr']
    tag_idx = tag_info['idx']

    ptrs = [proto_map[u] for u in uids if u in proto_map]
    log(f"\n=== tagging {len(ptrs)} pokemon as '{TAG_NAME}' in batches of {BATCH_SIZE} ===")

    count_tagged = 0
    count_failed = 0
    batches = [ptrs[i:i+BATCH_SIZE] for i in range(0, len(ptrs), BATCH_SIZE)]
    for bi, batch in enumerate(batches):
        log(f"  batch {bi+1}/{len(batches)}: {len(batch)} pokemon")
        try:
            res = bulk.exports_sync.bulk_tag_many(svc, tag_proto, batch)
            if res.get('ok'):
                built = res.get('built', 0)
                count_tagged += built
                if built < len(batch):
                    count_failed += len(batch) - built
                    log(f"    ok: built={built}/{len(batch)}")
                else:
                    log(f"    ok: built={built}")
            else:
                count_failed += len(batch)
                log(f"    FAIL: {res}")
        except Exception as e:
            count_failed += len(batch)
            log(f"    EXC: {e}")
        time.sleep(BATCH_PACE_S)

    log(f"\n=== tagging done: tagged={count_tagged} failed={count_failed} ===")
    log("waiting 4s for server to settle...")
    time.sleep(4)

    log("verifying server REVIEW count...")
    server_count = server_count_for_tag(bulk, svc, tag_idx)
    log(f"  server REVIEW count: {server_count}")
    log(f"  candidate count:     {len(uids)}")
    if server_count is not None and server_count == len(uids):
        log(f"  MATCH")
    else:
        log(f"  MISMATCH (delta={None if server_count is None else server_count - len(uids)})")

    result = {
        'tag_name': TAG_NAME,
        'count_tagged': count_tagged,
        'count_failed': count_failed,
        'server_count_after': server_count,
        'candidate_count': len(uids),
        'protos_found_in_bag': len(proto_map),
    }
    with open(RESULT_PATH, 'w') as f:
        json.dump(result, f, indent=2)
    log(f"saved {RESULT_PATH}: {result}")

    try:
        sess.detach()
    except Exception:
        pass
    return result


def main():
    max_attempts = 3  # 1 initial + 2 retries
    last_err = None
    for attempt in range(1, max_attempts + 1):
        log(f"=== attempt {attempt}/{max_attempts} ===")
        try:
            run()
            return
        except (RuntimeError, Exception) as e:
            last_err = e
            msg = str(e)
            log(f"  attempt {attempt} failed: {msg}")
            # Frida-only restart class: process not found, detached prematurely, attach fails, etc.
            if attempt < max_attempts:
                log(f"  sleeping 5s before retry...")
                time.sleep(5)
            else:
                raise


if __name__ == '__main__':
    main()
