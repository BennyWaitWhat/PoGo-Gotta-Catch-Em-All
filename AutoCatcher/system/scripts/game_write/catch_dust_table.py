"""STARDUST ONLY table for catch_loop_fast.py: the base catch stardust of every species, kept current by itself.

Benny 2026-11-18: "i also want a catch mode that only catches high stardust pokemon (+ shinies)"; "make sure you're
inclusive of EVERY higher than avg stardust pokemon for that mode"; "make sure that table is always updated".

WHAT IT IS: catch_dust.json (next to this file; the copy in git is the seed) lists every species with the stardust one
catch of it pays before any bonus: 100 + pokemonSettings.encounter.bonusStardustCaptureReward from the client game
master, the HIGHEST of a species' forms (the map says the species, not the form: a species that can pay is never left
alone). "base" = a normal catch = the most common value (100 today): a species above it pays more than a normal catch.
The catcher reads only this small file, never the 20 MB game master. Rows: [dex, name, stardust].

NOBODY REGENERATES IT BY HAND:
  --update       asks both upstreams the cull trusts (PokeMiners latest/ and alexelgt: a few bytes each), downloads the
                 ~20 MB game master only when a batch is newer than the table's (into its own temp file, deleted after),
                 rebuilds and replaces the table atomically. Garbage is refused (GUARDS below) and the old table stays.
                 Without a network it falls back to the installed game master (pogo_extract/, read only) when that one
                 is newer. The cull HOLDS a batch for Benny's word; this table does not wait for that and never touches
                 the cull's file.
  --auto LOG     what the catcher starts as a CHILD PROCESS at an attach and every 6 hours (never in its own process: a
                 slow network must not hold up a throw): --update, then the last day's catches in LOG held against the
                 table. Prints one json line; the catcher logs from it. CATCH_DUST_NO_NET=1 asks no upstream (tests).
  --for-deploy [files]   deploy.sh runs this before it pushes, with the phone's copies piped in: --update, then it prints
                 what the phone needs -- the table when the phone's is missing, different, or older (never an older
                 batch over a newer one: the phone also updates itself), and this file when the phone's differs (never
                 over a newer REV).
One update at a time: a lock file next to the table (a run that died leaves it; after 30 minutes it is taken over).
The table's text is the same for the same batch (no time stamp inside), so md5-verified deploys and the seed in git stay
stable. When the last check ran is in catch_dust.state.json next to it (state, not in git).

GUARDS (a candidate that trips one is never installed): the file does not parse; under 900 species with
pokemonSettings; the stardust field is gone; fewer species than the table has; more than 15% of the species change level.

  --gamemaster F [--batch MS]   rebuild from a game master on disk (the cull's .meta stamp next to it names the batch)
  --check [--gamemaster F]      the table's own consistency: header counts = body (CI has no game master); with a game
                                master, also that every template with a bonus is in the table at its own value or more
  --verify-catches FILE...      real catches (catcher log lines, or spawn-ledger records) against the table: a species
                                the server pays 2x more for than the table says, measured against the normal catches of
                                the same minute and Star Piece state
  --selftest
Standard library only: it also runs in Termux on the phone."""
import collections
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(HERE, "catch_dust.json")
STATE = os.path.join(HERE, "catch_dust.state.json")
REL = "system/scripts/game_write/catch_dust.json"            # the table under AutoCatcher/ and under the phone's ~/pogo
BREL = "system/scripts/game_write/catch_dust_table.py"       # this file, the same way (the phone runs it: --auto)
REV = 2                      # this file's revision: deploy.sh never puts a lower one over the phone's. +1 with every change
PHONE_HOME = "/data/data/com.termux/files/home/pogo"         # deploy.sh's H
INSTALLED_GM = os.path.normpath(os.path.join(HERE, os.pardir, os.pardir, os.pardir, os.pardir, "pogo_extract",
                                             "gamemaster_pokeminers.json"))
NORMAL = 100                 # a catch with no species bonus (the game master carries only the bonus on top of it)
FIELD = "bonusStardustCaptureReward"
TEMPLATE = re.compile(r"V(\d{4})_POKEMON_(.+)")
MIN_SPECIES, MAX_CHANGED = 900, 0.15
ABOUT = ("Base catch stardust of every species: 100 + pokemonSettings.encounter.bonusStardustCaptureReward, the highest of "
         "a species' forms. base = a normal catch (the most common value); the catcher's STARDUST ONLY switch "
         "(/data/local/tmp/pogo_dust.on) catches only species above it. Written by catch_dust_table.py --update, which runs "
         "by itself: never edited by hand. Rows: [dex, name, stardust].")
# The two upstreams, their markers and the "newer batch wins, never a downgrade" rule are pogo_extract/gm_guard.py's
# (SOURCES, parse_ts, parse_ax_ts) and refresh_gamemaster.py's -- copied, not imported: this file also runs on the phone,
# where pogo_extract does not exist. Both markers are on one millisecond clock.
PM = "https://raw.githubusercontent.com/PokeMiners/game_masters/master/latest/"
AX = "https://raw.githubusercontent.com/alexelgt/game_masters/master/"


def parse_ts(text):
    """PokeMiners' 13-byte latest/timestamp.txt -> milliseconds. ValueError on anything that is not a 2001-2096 time."""
    if isinstance(text, bytes):
        text = text.decode("ascii", "strict")
    v = int(text.strip())
    if not 10 ** 12 < v < 4 * 10 ** 12:
        raise ValueError("timestamp %r is not milliseconds since the epoch" % text.strip()[:20])
    return v


def parse_ax_ts(text):
    """alexelgt's timestamp.json ({"batchId": "<ms>", ...}) -> the batchId, checked like parse_ts."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "strict")
    return parse_ts(str(json.loads(text)["batchId"]))


SOURCES = collections.OrderedDict([("pokeminers", (PM + "timestamp.txt", PM + "latest.json", parse_ts)),
                                   ("alexelgt", (AX + "timestamp.json", AX + "GAME_MASTER.json", parse_ax_ts))])


def http_get(url, timeout=30, into=None, max_bytes=120 * 1024 * 1024):
    """GET -> bytes, or streamed into the file `into` (-> its size). `timeout` bounds each socket wait AND the whole
    transfer (max(20 s, 1.35 x timeout): urlopen's own timeout is per read). A body over max_bytes is refused."""
    end = time.time() + max(20.0, 1.35 * timeout)
    req = urllib.request.Request(url, headers={"User-Agent": "pogo-dust-table/1", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        parts, n = [], 0
        read = getattr(r, "read1", r.read)
        fh = open(into, "wb") if into else None
        try:
            while True:
                if time.time() > end:
                    raise OSError("download took longer than its %.0f s budget (%d bytes so far)" % (max(20.0, 1.35 * timeout), n))
                b = read(1 << 16)
                if not b:
                    return n if into else b"".join(parts)
                n += len(b)
                if n > max_bytes:
                    raise OSError("download larger than %d MB: not a game master" % (max_bytes // (1024 * 1024)))
                if fh:
                    fh.write(b)
                else:
                    parts.append(b)
        finally:
            if fh:
                fh.close()


def pretty(name):
    """MR_MIME -> Mr Mime (the app shows these names: no comma, no line break)."""
    return " ".join(w.capitalize() for w in re.sub(r"[^A-Za-z0-9]+", " ", str(name)).split()) or "?"


def species_dust(entries):
    """A game master (a list of {templateId, data}) -> ({dex: stardust}, {dex: name}, facts). A species = the HIGHEST of
    its forms. facts: templates = pokemonSettings templates read, field = how many of them carry the bonus field,
    forms = {dex: {template suffix: stardust}} for the inclusion check."""
    dust, ids, short, forms, n_field = {}, {}, {}, {}, 0
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or not isinstance(e.get("data"), dict):
            continue
        m = TEMPLATE.match(str(e.get("templateId", "")))
        st = e["data"].get("pokemonSettings")
        if not m or not isinstance(st, dict) or int(m.group(1)) < 1:
            continue
        dex = int(m.group(1))
        enc = st.get("encounter") if isinstance(st.get("encounter"), dict) else {}
        n_field += FIELD in enc
        try:
            bonus = max(0, int(enc.get(FIELD) or 0))
        except (TypeError, ValueError):
            bonus = 0
        forms.setdefault(dex, {})[m.group(2)] = NORMAL + bonus
        dust[dex] = max(dust.get(dex, 0), NORMAL + bonus)
        pid = st.get("pokemonId")
        if isinstance(pid, str) and re.search(r"[A-Za-z]", pid):
            ids.setdefault(dex, pid)
        if dex not in short or len(m.group(2)) < len(short[dex]):   # the form-less template is the shortest
            short[dex] = m.group(2)
    names = {d: pretty(ids.get(d) or short[d]) for d in dust}
    return dust, names, {"templates": sum(len(f) for f in forms.values()), "field": n_field, "forms": forms}


def base_of(dust):
    """A normal catch: the most common stardust value (a tie: the lower one)."""
    lv = collections.Counter(dust.values())
    return min(lv, key=lambda v: (-lv[v], v))


def table_text(dust, names, batch):
    """The table file's text: the same bytes for the same game master batch (no time inside)."""
    lv = collections.Counter(dust.values())
    head = [("about", ABOUT), ("batch", int(batch)), ("base", base_of(dust)), ("species", len(dust)),
            ("levels", collections.OrderedDict((str(k), lv[k]) for k in sorted(lv)))]
    rows = [json.dumps([d, names.get(d) or "#%d" % d, dust[d]]) for d in sorted(dust)]
    return "\n".join(["{"] + ["%s: %s," % (json.dumps(k), json.dumps(v)) for k, v in head] + ['"dust": [']
                     + [r + ("," if i < len(rows) - 1 else "") for i, r in enumerate(rows)] + ["]", "}"]) + "\n"


def parse_table(text):
    """Table text -> {"dust": {dex: stardust}, "names": {dex: name}, "base", "batch", "doc"}. ValueError when it is not one."""
    try:
        doc = json.loads(text)
        rows = doc["dust"]
        dust = {int(r[0]): int(r[2]) for r in rows}
        names = {int(r[0]): str(r[1]) for r in rows}
        if not dust or min(dust) < 1 or min(dust.values()) < 1:
            raise ValueError("no species, or a number under 1")
        return {"dust": dust, "names": names, "base": int(doc.get("base") or base_of(dust)), "batch": int(doc.get("batch") or 0),
                "doc": doc}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OverflowError) as e:
        raise ValueError("not a stardust table: %s" % (str(e)[:80] or type(e).__name__))


def read_table(path):
    try:
        with open(path, "rb") as fh:
            return parse_table(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError("%s: %s" % (os.path.basename(path), str(e)[:80] or type(e).__name__))


def check(text):
    """The table's own consistency (CI: there is no game master to hold it against) -> a list of problems, [] = fine."""
    try:
        t = parse_table(text)
    except ValueError as e:
        return [str(e)]
    doc, dust, names, bad = t["doc"], t["dust"], t["names"], []
    rows = doc["dust"]
    if [r[0] for r in rows] != sorted(dust) or len(rows) != len(dust):
        bad.append("rows are not one per species in dex order")
    if doc.get("species") != len(dust):
        bad.append("header species=%r, body has %d" % (doc.get("species"), len(dust)))
    lv = collections.Counter(dust.values())
    if doc.get("levels") != {str(k): lv[k] for k in lv}:
        bad.append("header levels do not match the body's counts %s" % {k: lv[k] for k in sorted(lv)})
    if doc.get("base") != base_of(dust):
        bad.append("header base=%r, the body's most common value is %d" % (doc.get("base"), base_of(dust)))
    if not isinstance(doc.get("batch"), int) or doc["batch"] < 0:
        bad.append("header batch=%r is not a batch time" % (doc.get("batch"),))
    if min(dust.values()) < NORMAL:
        bad.append("a species under %d stardust" % NORMAL)
    if len(dust) < MIN_SPECIES:
        bad.append("only %d species (under %d)" % (len(dust), MIN_SPECIES))
    if not any(v > base_of(dust) for v in dust.values()):
        bad.append("no species pays more than a normal catch")
    odd = [d for d, n in names.items() if not re.fullmatch(r"[A-Za-z0-9#][A-Za-z0-9 #]*", n)]
    if odd:
        bad.append("names the app cannot show (a comma, a line break, empty): dex %s" % odd[:5])
    if not bad and text != table_text(dust, names, doc["batch"]):
        bad.append("the file is not what this builder writes for its own rows (edited by hand?)")
    return bad


def inclusion_misses(entries, table):
    """Every game master template with a stardust bonus must be in the table at its own value or more (Benny: "inclusive
    of EVERY higher than avg stardust pokemon") -> [(templateId tail, its stardust, the table's)] for each that is not."""
    _d, _n, facts = species_dust(entries)
    return [("%04d %s" % (dex, form), v, table["dust"].get(dex)) for dex, fm in sorted(facts["forms"].items())
            for form, v in sorted(fm.items()) if v > NORMAL and not table["dust"].get(dex, 0) >= v]


def refuse(dust, facts, old):
    """Why this candidate must not replace the table ('' = it may). old = the table's {dex: stardust}, or None."""
    if len(dust) < MIN_SPECIES:
        return "only %d species with pokemonSettings (under %d)" % (len(dust), MIN_SPECIES)
    if not facts.get("field") or not any(v > NORMAL for v in dust.values()):
        return "the game master no longer carries encounter.%s" % FIELD
    if old:
        if len(dust) < len(old):
            return "the species count shrank: %d -> %d" % (len(old), len(dust))
        moved = sum(1 for d, v in old.items() if d in dust and dust[d] != v)
        if moved > MAX_CHANGED * len(old):
            return "%d of %d species changed level (over %d%%)" % (moved, len(old), round(MAX_CHANGED * 100))
    return ""


def diff_line(old, new):
    """What a new table changed, in a line: species added, raised, lowered (names, old -> new)."""
    od, nd, nm = (old or {}).get("dust") or {}, new["dust"], new["names"]
    if not od:
        return "%d species, %d pay more than a normal catch (%d)" % (len(nd), sum(v > new["base"] for v in nd.values()), new["base"])
    add = [d for d in nd if d not in od]
    up = [d for d in nd if d in od and nd[d] > od[d]]
    down = [d for d in nd if d in od and nd[d] < od[d]]
    gone = [d for d in od if d not in nd]

    def some(ds, arrow=True):
        return ", ".join(("%s %d -> %d" % (nm.get(d, "#%d" % d), od[d], nd[d])) if arrow else "%s %d" % (nm.get(d, "#%d" % d), nd[d])
                         for d in sorted(ds)[:6]) + (" ..." if len(ds) > 6 else "")
    parts = [("%d species added: %s" % (len(add), some(add, False))) if add else "",
             ("%d raised: %s" % (len(up), some(up))) if up else "", ("%d lowered: %s" % (len(down), some(down))) if down else "",
             ("%d gone" % len(gone)) if gone else ""]
    return "; ".join(p for p in parts if p) or "no species changed level"


def utc(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000.0)) + " UTC" if ms else "unknown batch"


def write_atomic(path, data):
    tmp = "%s.tmp%d" % (path, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            s = json.load(fh)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def installed_batch(gm_path):
    """The batch of the cull's installed game master, from the stamp next to it -- only when the stamp describes this very
    file (sha256). Read only. -> (batch ms, '') or (0, why)."""
    try:
        with open(gm_path + ".meta", encoding="utf-8") as fh:
            meta = json.load(fh)
        h = hashlib.sha256()
        with open(gm_path, "rb") as fh:
            for blk in iter(lambda: fh.read(1 << 20), b""):
                h.update(blk)
        if meta.get("sha256") != h.hexdigest():
            return 0, "its stamp describes another file"
        return parse_ts(str(meta["batch_ts"])), ""
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return 0, str(e)[:80] or type(e).__name__


def install(entries, batch, table, old, force=False):
    """Judge a parsed game master and, when it passes, write the table (only when its text changes). -> (why refused or '',
    the new table dict or None)."""
    dust, names, facts = species_dust(entries)
    why = refuse(dust, facts, None if force else (old or {}).get("dust"))
    if why:
        return why, None
    text = table_text(dust, names, batch)
    try:
        with open(table, "rb") as fh:
            same = fh.read() == text.encode("ascii")
    except OSError:
        same = False
    if not same:
        write_atomic(table, text.encode("ascii"))
    return "", parse_table(text)


def _lock(path, stale=1800):
    """One update at a time: two at once would download the same 20 MB into one temp file. An exclusive lock file; one
    older than `stale` seconds belongs to a run that died and is taken over. -> True when this run holds it. A folder
    that takes no lock file never blocks an update (replacing the table is atomic anyway)."""
    for _try in (1, 2, 3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - os.stat(path).st_mtime < stale:
                    return False
                os.remove(path)
            except OSError:
                pass   # it went away under us (that run just ended), or cannot be removed: try again, then give up
            continue
        except OSError:
            return True
        try:
            os.write(fd, ("%d %d\n" % (os.getpid(), time.time())).encode("ascii"))
        finally:
            os.close(fd)
        return True
    return False


def update(table=TABLE, state=STATE, fetch=http_get, now=None, installed=INSTALLED_GM, net=True, force=False, marker_s=10):
    """Bring the table to upstream's newest batch, one run at a time. -> (ok, line). ok = an upstream answered and the
    table now holds a batch at least as new as the newest one asked (already, or rebuilt here); anything else keeps the
    table and says why."""
    lock = table + ".lock"
    if not _lock(lock):
        return False, "another update of this table is running -- left to it"
    try:
        return _update(table, state, fetch, now, installed, net, force, marker_s)
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def _update(table, state, fetch, now, installed, net, force, marker_s):
    now = time.time() if now is None else now
    try:
        old = read_table(table)
    except ValueError:
        old = None
    have = old["batch"] if old else 0
    st, ups, errs = read_state(state), collections.OrderedDict(), []
    if net:
        for name, (ts_url, _j, parse) in SOURCES.items():
            try:
                ups[name] = parse(fetch(ts_url + "?cb=%d" % now, marker_s))
            except Exception as e:   # noqa: BLE001  (no network, a 404, a marker that is not one: all "did not answer")
                errs.append("%s: %s" % (name, str(e)[:70] or type(e).__name__))

    def done(ok, line, **more):
        try:
            cur = read_table(table)["batch"]
        except ValueError:
            cur = 0
        st.update(checked_ts=int(now), ok=bool(ok), note=line, batch=cur, upstream=dict(ups), **more)
        if ok:
            st["ok_ts"] = int(now)
            st.pop("refused", None)
        try:
            write_atomic(state, (json.dumps(st, indent=1) + "\n").encode("utf-8"))
        except OSError:
            pass
        return bool(ok), line

    if not ups:   # nobody answered: the installed game master (the cull's, read only) when it is newer than the table
        said = ("upstream not asked" if not net else "no upstream answered (%s)" % "; ".join(errs))
        ib, _why = installed_batch(installed) if installed else (0, "")
        if ib and (not old or ib > have):
            try:
                with open(installed, encoding="utf-8") as fh:
                    why, new = install(json.load(fh), ib, table, old, force)
            except (OSError, ValueError) as e:
                why, new = "the installed game master does not parse (%s)" % (str(e)[:60] or type(e).__name__), None
            if new:
                return done(False, "%s; rebuilt from the installed game master, batch %d (%s): %s" % (said, ib, utc(ib), diff_line(old, new)),
                            source="installed")
            return done(False, "%s; the installed game master (batch %d) was REFUSED: %s -- the table is kept" % (said, ib, why))
        return done(False, "%s -- the table is kept (%s)" % (said, "batch %d" % have if old else "there is none yet"))
    src = max(ups, key=lambda k: ups[k])
    up = ups[src]
    if old and up == have:
        return done(True, "batch %d (%s) is upstream's newest (%s): nothing to download" % (have, utc(have), src))
    if old and up < have:   # a stale edge, a rollback, or the upstream that has our batch did not answer: never a downgrade
        return done(False, "upstream's newest batch (%s, %d) is OLDER than the table's (%d)%s -- the table is kept"
                    % (src, up, have, ": " + "; ".join(errs) if errs else ""))
    ref = st.get("refused") if isinstance(st.get("refused"), dict) else {}
    if ref.get("batch") == up and not force:   # judged before and refused: not downloaded again until a newer one is out
        return done(False, "batch %d (%s) was refused before: %s -- the table is kept (batch %d)" % (up, src, ref.get("why"), have),
                    refused=ref)
    _ts_url, json_url, parse = SOURCES[src]
    tmp = table + ".download"
    try:
        fetch(json_url + "?cb=%d" % now, 180, into=tmp)
        if parse(fetch(SOURCES[src][0] + "?cb=%d" % (now + 1), 10)) != up:
            raise ValueError("upstream published while it was downloading (tried again next time)")
        with open(tmp, encoding="utf-8") as fh:
            entries = json.load(fh)
    except Exception as e:   # noqa: BLE001  (network, disk, a file that does not parse: the table stays)
        return done(False, "batch %d (%s) could not be read: %s -- the table is kept (%s)"
                    % (up, src, str(e)[:90] or type(e).__name__, "batch %d" % have if old else "there is none yet"))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    why, new = install(entries, up, table, old, force)
    if not new:
        return done(False, "batch %d (%s) REFUSED: %s -- the table is kept (%s)" % (up, src, why, "batch %d" % have if old else "there is none yet"),
                    refused={"batch": up, "why": why})
    return done(True, "batch %d (%s) via %s: %s" % (up, utc(up), src, diff_line(old, new)), source=src)


END = b"END-OF-DUST-TABLE"   # deploy.sh echoes it after the phone's table: it proves adb and su answered


def ship(local, phone):
    """deploy.sh's question: does the phone need this table? local / phone = the two files' bytes (phone None or b'' =
    not there). -> (yes, why). Never an older batch over a newer one: the phone also updates itself."""
    if not phone:
        return True, "the phone has no table"
    if phone == local:
        return False, "the phone's table is the same"
    try:
        pb = parse_table(phone.decode("utf-8"))["batch"]
    except (ValueError, UnicodeDecodeError):
        return True, "the phone's table does not read"
    lb = parse_table(local.decode("utf-8"))["batch"]
    if pb > lb:
        return False, "the phone's table is NEWER (batch %d > %d): not replaced" % (pb, lb)
    return True, "the phone's table differs (its batch %d, this one %d)" % (pb, lb)


def _bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


SEP = b"==DUST-TABLE-FOLLOWS=="   # deploy.sh echoes it between what it read of the phone's builder and the phone's table


def _md5(data):
    return hashlib.md5(data).hexdigest()


def for_deploy(files, phone, say, table=None, state=None, installed=None, me=None):
    """deploy.sh's hook. --update first (CATCH_DUST_NO_UPDATE=1 skips it, CATCH_DUST_NO_NET=1 asks no upstream), then what
    the phone needs, one path per line (deploy.sh adds them to its push list):
      this file (BREL)  when the phone's copy is missing or different -- the phone runs it (--auto) -- but never over a
                        copy with a higher REV (a deploy from an old checkout must not take the phone back);
      the table (REL)   when the phone's is missing, different or older -- never an older batch over a newer one.
    phone = what deploy.sh read off the phone: the md5 of its builder and that file's REV line (nothing = no builder
    there), the SEP line, the table's bytes, the END marker. The marker proves adb and su answered, so nothing before it
    means "not there"; no marker means the phone did not answer, and nothing is added. A deploy never dies on this."""
    table, state, me = table or TABLE, state or STATE, me or os.path.abspath(__file__)
    if os.environ.get("CATCH_DUST_NO_UPDATE") != "1":
        before = _bytes(table)
        try:
            say("DUST TABLE: " + update(table=table, state=state, installed=INSTALLED_GM if installed is None else installed,
                                        net=os.environ.get("CATCH_DUST_NO_NET") != "1", marker_s=4)[1])
        except Exception as e:   # noqa: BLE001
            say("DUST TABLE: update failed (%s) -- the table is kept" % (str(e)[:80] or type(e).__name__))
        if _bytes(table) != before:
            say("DUST TABLE: %s changed on this PC (a newer game master batch) -- commit it with your change" % REL)
    named = {os.path.normpath(f).replace(os.sep, "/") for f in files}
    out = (phone or b"").replace(b"\r\n", b"\n")
    if not out.endswith(END + b"\n"):
        if not {REL, BREL} <= named:
            say("DUST TABLE: the phone did not answer -- not pushed")
        return ""
    out, want = out[:-len(END) - 1], []
    head, sep, body = out.partition(SEP + b"\n")
    if not sep:        # an older deploy.sh piped the table alone: nothing is known about the phone's builder
        head, body = None, out
    if head is not None and BREL not in named:
        hl = head.decode("ascii", "replace").split("\n")
        pmd5 = next((x.strip() for x in hl if re.fullmatch(r"[0-9a-f]{32}", x.strip())), "")
        prev = next((int(m.group(1)) for m in (re.match(r"REV = (\d+)", x) for x in hl) if m), 0)
        mine = _bytes(me)
        if mine is None:
            say("DUST TABLE: %s is not on this PC -- not pushed" % BREL)
        elif pmd5 == _md5(mine):
            pass
        elif prev > REV:
            say("DUST TABLE: the phone's catch_dust_table.py is NEWER (rev %d > %d): not replaced" % (prev, REV))
        else:
            want.append(BREL)
            say("DUST TABLE: the phone's catch_dust_table.py is %s -- pushing it" % ("different (its rev %d, this one %d)" % (prev, REV) if pmd5 else "missing"))
    if REL not in named:
        local = _bytes(table)
        try:
            parse_table((local or b"").decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            say("DUST TABLE: this PC's table does not read (%s) -- not pushed" % (str(e)[:80] or type(e).__name__))
        else:
            yes, why = ship(local, body)
            say("DUST TABLE: %s -- %s" % (why, "pushing it" if yes else "not pushed"))
            if yes:
                want.append(REL)
    return "\n".join(want)


# ---- real catches against the table (Benny's rule: read the game's own records, never an estimate)
LOG_CATCH = re.compile(r"^(\d\d):(\d\d):(\d\d) CATCH (\S+) #(\d+) .*?dust=(\d+)")
LUMPS = (1800, 9000)   # the first catch of a day / of a 7-day streak pays this once on top (x1.5 with a Star Piece)
OVER = 2.0             # paying this many times the table's level is not weather (1.25x): the smallest real step, 100 -> 300, is 2.6x


def catch_records(lines):
    """Catcher log lines and/or spawn-ledger lines -> [(minute key, second, dex, award)]. A log has no dates: a clock that
    jumps back more than an hour starts a new day."""
    out, day, prev = [], 0, -1
    for ln in lines:
        m = LOG_CATCH.match(ln)
        if m or re.match(r"^\d\d:\d\d:\d\d ", ln):
            t = int(ln[0:2]) * 3600 + int(ln[3:5]) * 60 + int(ln[6:8])
            if t < prev - 3600:
                day += 1
            prev = t
            if m and int(m.group(6)) > 0:
                out.append((("log", day, t // 60), day * 86400 + t, int(m.group(5)), int(m.group(6))))
        elif ln.startswith("{"):
            try:
                r = json.loads(ln)
                if r.get("r") == "caught" and int(r.get("d") or 0) > 0 and r.get("id") is not None:
                    ms = int(r.get("tC") or r.get("t1") or 0)
                    out.append((("led", 0, ms // 60000), ms // 1000, int(r["id"]), int(r["d"])))
            except (ValueError, TypeError, AttributeError):
                continue
    return out


def verify_catches(records, table):
    """Every catch against the normal catches of its own minute and Star Piece state, then judged per SPECIES.
    A catch pays a flat 25 on top of (stardust x event x weather), x1.5 with a Star Piece, so against a normal catch of
    the same minute a species reads a little under the table's ratio, and weather adds at most 1.25x.
      above    a species most of whose catches (3 or more) paid 2x MORE than the table says: a table miss
      few      a species with 1-2 catches, all of them 2x more and not explained below: cannot be told yet
      isolated single catches 2x over while their species' others are not: 'swap' = a catch within 8 s paid too little
               by the same step (two throws in the air: the catcher matches results in send order and its log swapped
               their awards), 'lump' = the once-a-day / once-a-week first-catch bonus, 'other'
      under    a species most of whose catches paid half the table or less: a lower-paying form (the table holds the
               highest form on purpose)"""
    dust, base = table["dust"], table["base"]
    by_min = collections.defaultdict(list)
    for key, sec, dex, award in records:
        by_min[key].append((sec, dex, award))
    res = {"catches": len(records), "checked": 0, "noref": 0, "mixed": 0, "unknown": collections.Counter(),
           "level": collections.defaultdict(list), "above": {}, "few": {}, "under": {}, "swap": [], "lump": [], "other": []}
    rows = []
    for key, rs in by_min.items():
        refs = {}
        for sp in (False, True):   # the catcher's own Star Piece test on a normal catch: a bare award is a multiple of 25
            vals = sorted(a for _s, d, a in rs if dust.get(d) == base and bool(a % 25) == sp)
            if vals:
                refs[sp] = vals[(len(vals) - 1) // 2]   # the lower median: a mis-tabled species among them cannot lift it
        for sec, dex, award in rs:
            if not refs:
                res["noref"] += 1
                continue
            lvl = dust.get(dex)
            if lvl == base:
                ref = refs.get(bool(award % 25)) or min(refs.values())
            elif len(refs) == 1:
                ref = next(iter(refs.values()))
            else:   # a Star Piece started or ran out inside this minute: which state this catch had is not known
                res["mixed"] += 1
                continue
            if lvl is None:
                res["unknown"][dex] += 1
                lvl = base
            res["level"][lvl].append(award / float(ref))
            rows.append({"src": key[0], "sec": sec, "dex": dex, "a": award, "ref": ref, "lvl": lvl,
                         "x": (award / float(ref)) / (lvl / float(base))})
    res["checked"] = len(rows)
    by_sp = collections.defaultdict(list)
    for r in rows:
        by_sp[r["dex"]].append(r)
    res["species"] = len(by_sp)
    for dex, rs in by_sp.items():
        over = sum(r["x"] >= OVER for r in rs)
        low = sum(r["x"] <= 1 / OVER for r in rs)
        if len(rs) >= 3 and 2 * over > len(rs):
            res["above"][dex] = (over, len(rs), sorted(rs, key=lambda r: r["x"])[len(rs) // 2])
        elif len(rs) >= 3 and 2 * low > len(rs):
            res["under"][dex] = (low, len(rs))
    rows.sort(key=lambda r: (r["src"], r["sec"]))
    lows = [r for r in rows if r["x"] <= 1 / OVER]
    used, few = set(), collections.defaultdict(list)
    for r in rows:
        if r["x"] < OVER or r["dex"] in res["above"]:
            continue
        want = None
        for u in lows:   # its partner: too little by the same step, within 8 s
            if id(u) in used or u["src"] != r["src"] or abs(u["sec"] - r["sec"]) > 8:
                continue
            if 0.55 * r["ref"] * u["lvl"] / base <= r["a"] <= 1.35 * r["ref"] * u["lvl"] / base:
                want = u
                break
        expect = r["ref"] * r["lvl"] / float(base)
        if want is not None:
            used.add(id(want))
            res["swap"].append(r)
        elif any(abs(r["a"] - expect - x * k) <= 0.26 * expect + 3 for x in LUMPS for k in (1.0, 1.5)):
            res["lump"].append(r)
        elif len(by_sp[r["dex"]]) <= 2:
            few[r["dex"]].append(r)
        else:
            res["other"].append(r)
    for dex, rs in few.items():   # every one of its 1-2 catches paid more, unexplained: not enough to tell
        if len(rs) == len(by_sp[dex]):
            res["few"][dex] = rs
        else:
            res["other"] += rs
    return res


def catch_lines(paths, max_bytes=12 * 1024 * 1024):
    """The timed CATCH lines of catcher logs, oldest file first; of each file at most its last max_bytes (a day of the
    catcher's log is 3 to 6 MB). Read line by line: a 20 MB log never sits in memory."""
    out = []
    for path in paths:
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - max_bytes))
                if size > max_bytes:
                    fh.readline()   # the cut lands inside a line
                for raw in fh:
                    if b" CATCH " in raw:
                        ln = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if LOG_CATCH.match(ln):
                            out.append(ln)
        except OSError:
            continue
    return out


def last_day(lines):
    """The lines of the 24 hours before the last one. A catcher log carries clock times only (HH:MM:SS): going back from
    the end, a clock that jumps UP by more than an hour is midnight; past it, the day ends at the last line's own time."""
    end = prev = None
    past = False
    for i in range(len(lines) - 1, -1, -1):
        ln = lines[i]
        if not re.match(r"^\d\d:\d\d:\d\d ", ln):
            continue
        t = int(ln[0:2]) * 3600 + int(ln[3:5]) * 60 + int(ln[6:8])
        if end is None:
            end = prev = t
            continue
        if t > prev + 3600:
            if past:               # a second midnight: more than a day back
                return lines[i + 1:]
            past = True
        if past and t <= end:
            return lines[i + 1:]
        prev = t
    return lines


def auto(log, table=TABLE, state=STATE, **kw):
    """The catcher's child process: --update, then the last day's catches in the catcher's log (LOG.1, then LOG) held
    against the table as it is now. -> what the catcher logs from: {"ok", "line", "batch", and when the catches could be
    read: "catches", "checked", "species", "above": [{dex, name, table, over, n, a, ref}]}; else "verify_error". Whatever
    either step runs into is said in that answer, never raised: the catcher logs one line from it."""
    try:
        ok, line = update(table=table, state=state, **kw)
    except Exception as e:   # noqa: BLE001
        ok, line = False, "update failed (%s) -- the table is kept" % (str(e)[:80] or type(e).__name__)
    res = {"ok": bool(ok), "line": line, "batch": 0}
    try:
        tab = read_table(table)
        res["batch"] = tab["batch"]
        v = verify_catches(catch_records(last_day(catch_lines([log + ".1", log]))), tab)
        res.update(catches=v["catches"], checked=v["checked"], species=v["species"],
                   above=[{"dex": d, "name": tab["names"].get(d, "?"), "table": tab["dust"].get(d), "over": over, "n": n, "a": mid["a"], "ref": mid["ref"]}
                          for d, (over, n, mid) in sorted(v["above"].items(), key=lambda kv: -kv[1][1])])
    except Exception as e:   # noqa: BLE001  (no table, a log that cannot be opened, a record of an unexpected shape)
        res["verify_error"] = str(e)[:120] or type(e).__name__
    return res


def verify_report(res, table):
    names, dust, base = table["names"], table["dust"], table["base"]

    def nm(d):
        return "#%d %s" % (d, names.get(d, "?"))
    out = ["%d catches read; %d held against the normal catches of their own minute (%d had no normal catch in their minute, %d "
           "were in a minute where the Star Piece changed); %d species" % (res["catches"], res["checked"], res["noref"], res["mixed"], res["species"])]
    for lvl in sorted(res["level"]):
        v = sorted(res["level"][lvl])
        out.append("  table %5d: %6d catches, real pay %5.2fx a normal catch (median; the table says %.1fx)" % (lvl, len(v), v[len(v) // 2], lvl / float(base)))
    iso = len(res["swap"]) + len(res["lump"]) + len(res["other"])
    out.append("  single catches that paid 2x more than their species' level while its other catches did not: %d" % iso)
    out.append("    %d have a catch within 8 s that paid too LITTLE by the same step: two throws in the air, the log swapped their awards" % len(res["swap"]))
    out.append("    %d carried the first-catch-of-the-day / 7-day-streak bonus (+1,800 / +9,000, once)" % len(res["lump"]))
    out.append("    %d other%s" % (len(res["other"]), "".join(" | %s %d against a normal %d" % (nm(r["dex"]), r["a"], r["ref"]) for r in res["other"][:12])))
    for d, (over, n, mid) in sorted(res["above"].items(), key=lambda kv: -kv[1][1]):
        out.append("  ABOVE THE TABLE %s: table %s, but %d of its %d catches paid 2x more (typically %d against a normal %d)"
                   % (nm(d), dust.get(d, "unknown"), over, n, mid["a"], mid["ref"]))
    for d, rs in sorted(res["few"].items()):
        out.append("  TOO FEW TO TELL %s: table %s, %d catch(es), all paid more (%s)"
                   % (nm(d), dust.get(d, "unknown"), len(rs), ", ".join("%d against a normal %d" % (r["a"], r["ref"]) for r in rs)))
    if res["under"]:
        out.append("  pay LESS than the table (a lower form; the table holds the highest on purpose): "
                   + ", ".join("%s %d of %d" % (nm(d), lo, n) for d, (lo, n) in sorted(res["under"].items(), key=lambda kv: -kv[1][1])))
    if res["unknown"]:
        out.append("  species not in the table (always caught): %s" % ", ".join("#%d x%d" % kv for kv in sorted(res["unknown"].items())))
    out.append("RESULT: %s%s" % ("%d species pay more than the table says" % len(res["above"]) if res["above"] else "no species pays more than the table says",
                                 "; %d species with too few catches to tell" % len(res["few"]) if res["few"] else ""))
    return out


def _fake_gm(n=1000, bump=None, drop_field=False):
    """A game master of n species for the tests: every 3rd one +200, every 10th +400, dex 90 +900, 531 +2000; dex 52 has
    two forms (a plain one and one that pays)."""
    out = [{"templateId": "SPAWN_V0001_POKEMON_BULBASAUR", "data": {"genderSettings": {}}},
           {"templateId": "V0001_MOVE_X", "data": {"moveSettings": {}}}, {"templateId": "BROKEN"}, "junk"]
    for d in range(1, n + 1):
        b = 2000 if d == 531 else 900 if d == 90 else 400 if d % 10 == 0 else 200 if d % 3 == 0 else 0
        b = (bump or {}).get(d, b)
        enc = {"baseCaptureRate": 0.2}
        if b and not drop_field:
            enc[FIELD] = b
        out.append({"templateId": "V%04d_POKEMON_MON_%d" % (d, d), "data": {"pokemonSettings": {"pokemonId": "MON_%d" % d, "encounter": enc}}})
        if d == 52:
            out.append({"templateId": "V0052_POKEMON_MON_52_ALOLA", "data": {"pokemonSettings": {"pokemonId": 52, "form": "X",
                                                                                     "encounter": {} if drop_field else {FIELD: 650}}}})
            out.append({"templateId": "V0052_POKEMON_MON_52_NORMAL", "data": {"pokemonSettings": {"pokemonId": "MON_52"}}})
    return out


def _selftest():
    import shutil
    import tempfile
    failed = 0

    def check_(name, got, want):
        nonlocal failed
        ok = got == want
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name.ljust(58), repr(got)[:150], "" if ok else "  want %r" % (want,))

    gm = _fake_gm()
    dust, names, facts = species_dust(gm)
    check_("species: one row per dex, other templates ignored", (len(dust), facts["templates"], min(dust), max(dust)), (1000, 1002, 1, 1000))
    check_("no bonus = 100; +200 = 300; +2000 = 2100", (dust[1], dust[3], dust[10], dust[90], dust[531]), (100, 300, 500, 1000, 2100))
    check_("forms differ: the highest one wins (100 / 750 / 100)", (dust[52], sorted(facts["forms"][52].values())), (750, [100, 100, 750]))
    check_("names: from pokemonId, shown plainly", (names[52], pretty("MR_MIME"), pretty("NIDORAN_FEMALE"), pretty("HO_OH")),
           ("Mon 52", "Mr Mime", "Nidoran Female", "Ho Oh"))
    check_("base = the most common value", (base_of(dust), base_of({1: 300, 2: 300, 3: 100, 4: 100})), (100, 100))
    text = table_text(dust, names, 1794878074575)
    tab = parse_table(text)
    check_("the table reads back as it was built", (tab["dust"] == dust, tab["names"] == names, tab["base"], tab["batch"]), (True, True, 100, 1794878074575))
    check_("same batch = the same bytes (no time inside)", text == table_text(dict(reversed(list(dust.items()))), names, 1794878074575), True)
    check_("consistency: a built table is fine", check(text), [])
    check_("consistency: a header count that is off", len(check(text.replace('"species": 1000', '"species": 999'))), 1)
    check_("consistency: a level moved by hand", bool(check(text.replace('[3, "Mon 3", 300]', '[3, "Mon 3", 500]'))), True)
    check_("consistency: a name with a comma", bool(check(text.replace('"Mon 3"', '"Mon, 3"'))), True)
    check_("consistency: not JSON", check(text[:200])[0][:22], "not a stardust table: ")
    # (a) INCLUSION: every template with a bonus is in the table at its own value or more
    check_("inclusion: every template with a bonus is in, at >= its value", inclusion_misses(gm, tab), [])
    low = parse_table(table_text({**dust, 52: 100, 531: 300}, names, 1))
    check_("inclusion: a table that lost two is caught", [m[0][:4] for m in inclusion_misses(gm, low)], ["0052", "0531"])
    gone = dict(dust)
    del gone[90]
    check_("inclusion: a species missing from the table is caught", [m[0][:4] for m in inclusion_misses(gm, parse_table(table_text(gone, names, 1)))], ["0090"])
    # GUARDS
    check_("guard: fine", refuse(dust, facts, dust), "")
    check_("guard: under 900 species", refuse(*species_dust(_fake_gm(800))[::2], None)[:16], "only 800 species")
    check_("guard: the field is gone", refuse(*species_dust(_fake_gm(drop_field=True))[::2], dust)[:28], "the game master no longer ca")
    check_("guard: the species count shrank", refuse(*species_dust(_fake_gm(950))[::2], dust), "the species count shrank: 1000 -> 950")
    d16, _n, f16 = species_dust(_fake_gm(bump={d: 400 for d in range(1, 400, 2)}))
    check_("guard: over 15% changed level", refuse(d16, f16, dust), "200 of 1000 species changed level (over 15%)")
    d2, _n, f2 = species_dust(_fake_gm(1003, bump={7: 200, 8: 600}))
    check_("guard: a few changes and new species pass", refuse(d2, f2, dust), "")
    # --update against a fake upstream
    tmp = tempfile.mkdtemp()
    try:
        tb, stt = os.path.join(tmp, "catch_dust.json"), os.path.join(tmp, "catch_dust.state.json")
        T0 = 1794000000000
        web = {"pm_ts": T0, "ax_ts": T0 + 5000, "ax_gm": gm, "pm_gm": gm, "calls": [], "bump_ts": False}

        def fetch(url, timeout=30, into=None):
            web["calls"].append(url.split("?")[0].rsplit("/", 1)[1] + ("" if into is None else " ->file"))
            if "timestamp.txt" in url:
                if web["pm_ts"] is None:
                    raise OSError("no network")
                return str(web["pm_ts"]).encode()
            if "timestamp.json" in url:
                if web["ax_ts"] is None:
                    raise OSError("no network")
                ts = web["ax_ts"] + (1 if web["bump_ts"] and any("->file" in c for c in web["calls"]) else 0)
                return json.dumps({"batchId": str(ts), "uploadTime": "1"}).encode()
            body = web["ax_gm" if "GAME_MASTER" in url else "pm_gm"]
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            with open(into, "wb") as fh:
                fh.write(data)
            return len(data)

        ok, line = update(tb, stt, fetch, now=1795000000, installed=None)
        check_("update: no table yet -> built from the NEWER upstream", (ok, read_table(tb)["batch"], "via alexelgt" in line), (True, T0 + 5000, True))
        check_("update: one download, the other upstream's file never fetched", web["calls"],
               ["timestamp.txt", "timestamp.json", "GAME_MASTER.json ->file", "timestamp.json"])
        check_("update: nothing left behind", sorted(os.listdir(tmp)), ["catch_dust.json", "catch_dust.state.json"])
        check_("update: the state records the check", (read_state(stt)["ok"], read_state(stt)["ok_ts"], read_state(stt)["source"]), (True, 1795000000, "alexelgt"))
        b0, m0 = open(tb, "rb").read(), os.stat(tb).st_mtime_ns
        web["calls"] = []
        ok, line = update(tb, stt, fetch, now=1795000600, installed=None)
        check_("update: same batch -> two markers, no download", (ok, web["calls"], "nothing to download" in line),
               (True, ["timestamp.txt", "timestamp.json"], True))
        check_("update: the file is not rewritten", (open(tb, "rb").read() == b0, os.stat(tb).st_mtime_ns == m0, read_state(stt)["ok_ts"]), (True, True, 1795000600))
        web["ax_ts"] = None
        ok, line = update(tb, stt, fetch, now=1795000700, installed=None)
        check_("update: only the OLDER upstream answers -> kept, not a success", (ok, "OLDER" in line, read_state(stt)["ok_ts"]), (False, True, 1795000600))
        web.update(ax_ts=T0 + 9000, ax_gm=_fake_gm(1001, bump={7: 200}), calls=[])
        ok, line = update(tb, stt, fetch, now=1795000800, installed=None)
        check_("update: a newer batch -> rebuilt, what changed is said", (ok, line.split(" via ", 1)[-1]),
               (True, "alexelgt: 1 species added: Mon 1001 100; 1 raised: Mon 7 100 -> 300"))
        good = open(tb, "rb").read()
        web.update(ax_ts=T0 + 12000, ax_gm=_fake_gm(drop_field=True), calls=[])
        ok, line = update(tb, stt, fetch, now=1795000900, installed=None)
        check_("update: a batch without the field is REFUSED, the table stays", (ok, "REFUSED" in line, open(tb, "rb").read() == good), (False, True, True))
        web["calls"] = []
        ok, line = update(tb, stt, fetch, now=1795001000, installed=None)
        check_("update: a refused batch is not downloaded again", (ok, web["calls"], "refused before" in line), (False, ["timestamp.txt", "timestamp.json"], True))
        web.update(ax_ts=T0 + 13000, ax_gm=b'[{"templateId": "V0001_POKEMON_X", "data": {"pokemonSet', calls=[])
        ok, line = update(tb, stt, fetch, now=1795001100, installed=None)
        check_("update: a cut-off download is kept out, and not remembered as refused (tried again)",
               (ok, "could not be read" in line, open(tb, "rb").read() == good, (read_state(stt).get("refused") or {}).get("batch")),
               (False, True, True, T0 + 12000))
        web.update(ax_ts=T0 + 14000, ax_gm=_fake_gm(1001, bump={7: 200, 9: 400}), bump_ts=True, calls=[])
        ok, line = update(tb, stt, fetch, now=1795001200, installed=None)
        check_("update: upstream published during the download -> kept", (ok, "while it was downloading" in line, open(tb, "rb").read() == good), (False, True, True))
        web["bump_ts"] = False
        ok, line = update(tb, stt, fetch, now=1795001300, installed=None)
        check_("update: ...and taken on the next run", (ok, read_table(tb)["batch"], read_table(tb)["dust"][9]), (True, T0 + 14000, 500))
        check_("update: no temp file in any of those runs", sorted(os.listdir(tmp)), ["catch_dust.json", "catch_dust.state.json"])
        # no network: the installed game master (the cull's, read only) when it is newer
        inst = os.path.join(tmp, "gm.json")
        json.dump(_fake_gm(1002, bump={7: 200, 9: 400, 11: 600}), open(inst, "w"))
        sha = hashlib.sha256(open(inst, "rb").read()).hexdigest()
        json.dump({"batch_ts": T0 + 20000, "sha256": sha, "source": "alexelgt"}, open(inst + ".meta", "w"))
        gm_before = open(inst, "rb").read()
        web.update(pm_ts=None, ax_ts=None)
        ok, line = update(tb, stt, fetch, now=1795001400, installed=inst)
        check_("offline: rebuilt from the installed game master, not a success", (ok, read_table(tb)["batch"], read_table(tb)["dust"][11],
                                                                                read_state(stt)["ok_ts"]), (False, T0 + 20000, 700, 1795001300))
        check_("offline: the cull's file and stamp are untouched", (open(inst, "rb").read() == gm_before, sorted(os.listdir(tmp))),
               (True, ["catch_dust.json", "catch_dust.state.json", "gm.json", "gm.json.meta"]))
        json.dump({"batch_ts": T0 + 30000, "sha256": "0" * 64}, open(inst + ".meta", "w"))
        ok, line = update(tb, stt, fetch, now=1795001500, installed=inst)
        check_("offline: a stamp that describes another file is not trusted", (ok, read_table(tb)["batch"], "the table is kept" in line), (False, T0 + 20000, True))
        ok, line = update(tb, stt, fetch, now=1795001600, installed=inst, net=False)
        check_("net off (tests, CI): nobody is asked", (ok, line[:18]), (False, "upstream not asked"))
        # deploy.sh's question
        loc = open(tb, "rb").read()
        older = table_text(dust, names, T0).encode()
        newer = table_text(dust, names, T0 + 99000).encode()
        check_("ship: same bytes -> no; none / unreadable / older / differs -> yes; a NEWER one on the phone -> no",
               [ship(loc, loc)[0], ship(loc, b"")[0], ship(loc, None)[0], ship(loc, b"{nope")[0], ship(loc, older)[0], ship(loc, newer)[0]],
               [False, True, True, True, True, False])
        # one update at a time
        lockf, st0, tb0 = tb + ".lock", _bytes(stt), _bytes(tb)
        open(lockf, "w").close()
        got = update(tb, stt, fetch, now=1795001700, installed="", net=False)
        check_("lock: an update is running -> this one leaves it alone (table and state untouched, the lock stays the other's)",
               (got, _bytes(stt) == st0, _bytes(tb) == tb0, os.path.exists(lockf)), ((False, "another update of this table is running -- left to it"), True, True, True))
        os.utime(lockf, (time.time() - 7200, time.time() - 7200))
        ok, line = update(tb, stt, fetch, now=1795001800, installed="", net=False)
        check_("lock: one left by a run that died (2 h old) is taken over; every run removes its own",
               (ok, line[:18], os.path.exists(lockf), _bytes(stt) != st0), (False, "upstream not asked", False, True))
        # the last day of a catcher log
        day = ["09:00:00 CATCH Wild #1 x dust=125", "11:00:00 CATCH Wild #2 x dust=125", "Traceback (most recent call last):", "23:00:00 CATCH Wild #3 x dust=125",
               "01:00:00 CATCH Wild #4 x dust=125", "10:00:00 CATCH Wild #5 x dust=125"]
        check_("last day: 25 h before the last line is out, 23 h before is in (the clock jumps back at midnight)", last_day(day), day[1:])
        two = ["12:00:00 a", "23:30:00 b", "00:30:00 c", "23:45:00 d", "00:10:00 e"]
        check_("last day: a second midnight ends it; one day's lines, no lines and untimed lines are kept as they are",
               (last_day(two), last_day(day[:2]), last_day([]), last_day(["x", "y"])), (two[2:], day[:2], [], ["x", "y"]))
        lg = os.path.join(tmp, "catch_loop.log")
        with open(lg, "wb") as fh:
            fh.write(b"08:00:00 run 10s | caught=1\n08:00:01 CATCH Wild #16 x dust=125 candy=3 wx=0\nCATCH Wild #16 untimed dust=125\n\xff\xfe junk\n08:00:02 FLED Wild #16 x\n"
                     b"08:00:03 CATCH Incense #21 ball=1 dust=525 candy=3\n")
        check_("catch lines: the timed CATCH lines of the logs that exist, oldest file first; a cut first line is dropped",
               (catch_lines([lg + ".1", lg]), catch_lines([lg], max_bytes=60), catch_lines([lg + ".none"])),
               (["08:00:01 CATCH Wild #16 x dust=125 candy=3 wx=0", "08:00:03 CATCH Incense #21 ball=1 dust=525 candy=3"],
                ["08:00:03 CATCH Incense #21 ball=1 dust=525 candy=3"], []))
        # the catcher's child process: the update, then the last day's catches against the table
        tb2, st2 = os.path.join(tmp, "auto.json"), os.path.join(tmp, "auto.state.json")
        open(tb2, "w", encoding="ascii", newline="\n").write(table_text({**dust, 16: 100, 21: 100, 774: 1000}, names, T0 + 5))
        with open(lg + ".1", "w", encoding="utf-8", newline="\n") as fh:   # two days ago: must not count
            fh.write("".join("07:%02d:01 CATCH Wild #16 x dust=125\n07:%02d:02 CATCH Wild #774 x dust=4025\n" % (i, i) for i in range(5)))
            fh.write("".join("21:%02d:01 CATCH Wild #16 x dust=125\n" % i for i in range(3)))
        with open(lg, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join("06:%02d:01 CATCH Wild #16 x dust=125\n" % i for i in range(3)))   # yesterday 06:00: more than a day before the end
            fh.write("".join("20:%02d:01 CATCH Wild #16 x dust=125\n20:%02d:02 CATCH Wild #21 x dust=525\n20:%02d:03 CATCH Wild #774 x dust=1025\n" % (i, i, i) for i in range(4)))
            fh.write("00:10:00 run 5s\n" + "".join("07:%02d:01 CATCH Wild #16 x dust=125\n" % i for i in range(2)))
        res = auto(lg, table=tb2, state=st2, fetch=fetch, now=1795001900, installed="", net=False)
        check_("auto: the update's own line, the table's batch, and yesterday evening's + this morning's catches (not the older ones)",
               (res["ok"], res["line"][:18], res["batch"], res["catches"], res["checked"], res["species"]), (False, "upstream not asked", T0 + 5, 14, 14, 3))
        check_("auto: a species whose catches paid more than the table says is named with its numbers",
               res["above"], [{"dex": 21, "name": names.get(21, "?"), "table": 100, "over": 4, "n": 4, "a": 525, "ref": 125}])
        def boom(*_a, **_k):
            raise RuntimeError("boom")
        keep = (globals()["update"], globals()["verify_catches"])
        try:
            globals()["update"] = boom
            r1 = auto(lg, table=tb2, state=st2)
            globals().update(update=keep[0], verify_catches=boom)
            r2 = auto(lg, table=tb2, state=st2, fetch=fetch, now=1795001950, installed="", net=False)
        finally:
            globals().update(update=keep[0], verify_catches=keep[1])
        check_("auto: an update that raises, or a check of the catches that raises, is said in the answer -- the other part still runs",
               ((r1["ok"], r1["line"], r1["catches"]), (r2["line"][:18], r2["batch"], r2.get("verify_error"), "catches" in r2)),
               ((False, "update failed (boom) -- the table is kept", 14), ("upstream not asked", T0 + 5, "boom", False)))
        check_("auto: its answer is one json line; a table that is not there is said, not raised",
               (json.loads(json.dumps(res)) == res, sorted(auto(lg, table=tb2 + ".none", state=st2, fetch=fetch, now=1795002000, installed="", net=False))),
               (True, ["batch", "line", "ok", "verify_error"]))
        said = []
        env0 = {k: os.environ.get(k) for k in ("CATCH_DUST_NO_UPDATE", "CATCH_DUST_NO_NET")}
        os.environ.update(CATCH_DUST_NO_UPDATE="1")
        fd = lambda files, phone: for_deploy(files, phone, said.append, table=tb, state=stt)
        mark = END + b"\n"
        check_("for-deploy: the phone's copy is the same -> nothing added; missing / older -> the table's path; NEWER -> nothing",
               [fd(["a.py"], loc + mark), fd(["a.py"], mark), fd([], older + mark), fd(["a.py"], newer + mark)], ["", REL, REL, ""])
        check_("for-deploy: no marker = the phone did not answer -> nothing added (the deploy's own pushes will say why)",
               [fd(["a.py"], b""), fd(["a.py"], loc), fd(["a.py"], None), said[-1]], ["", "", "", "DUST TABLE: the phone did not answer -- not pushed"])
        check_("for-deploy: adb's CR LF line ends are read as LF", [fd([], loc.replace(b"\n", b"\r\n") + END + b"\r\n"), fd([], END + b"\r\n")], ["", REL])
        check_("for-deploy: the table already in the push list -> not added twice", [fd(["./" + REL], mark), fd([REL.replace("/", os.sep)], mark)], ["", ""])
        n_said = len(said)
        stt_before = _bytes(stt)
        check_("for-deploy: CATCH_DUST_NO_UPDATE=1 -> no update, the state file untouched, one line said",
               (fd([], mark), _bytes(stt) == stt_before, len(said) - n_said, said[-1]), (REL, True, 1, "DUST TABLE: the phone has no table -- pushing it"))
        os.environ.update(CATCH_DUST_NO_UPDATE="0", CATCH_DUST_NO_NET="1")
        n_said = len(said)
        got = for_deploy([], mark, said.append, table=tb, state=stt, installed="")
        check_("for-deploy: the update runs first (no network here: the table is kept), then the question",
               (got, [x.rsplit(" -- ", 1)[0] for x in said[n_said:]], _bytes(tb) == loc), (REL, ["DUST TABLE: upstream not asked", "DUST TABLE: the phone has no table"], True))
        os.environ.update(CATCH_DUST_NO_UPDATE="1")
        # this file rides along too: the phone runs it (--auto)
        mef = os.path.join(tmp, "builder.py")
        open(mef, "wb").write(b"REV = 2\nprint(1)\n")
        mm = _md5(b"REV = 2\nprint(1)\n").encode("ascii")
        fb = lambda files, head, body=loc: for_deploy(files, head + SEP + b"\n" + body + mark, said.append, table=tb, state=stt, me=mef)
        check_("for-deploy: the phone's builder is the same -> not added; missing or different -> added; a higher REV there -> never replaced",
               [fb([], mm + b"\nREV = 2\n"), fb([], b""), fb([], b"0" * 32 + b"\nREV = 1\n"), fb([], b"0" * 32 + b"\n"),
                fb([], b"0" * 32 + ("\nREV = %d\n" % (REV + 1)).encode("ascii")), said[-2]],
               ["", BREL, BREL, BREL, "", "DUST TABLE: the phone's catch_dust_table.py is NEWER (rev %d > %d): not replaced" % (REV + 1, REV)])
        check_("for-deploy: builder and table both missing -> both, the builder first; one named by hand -> only the other",
               [fb([], b"", b""), fb([BREL], b"", b""), fb([REL], b"", b""), fb([REL, "./" + BREL], b"", b"")], [BREL + "\n" + REL, REL, BREL, ""])
        check_("for-deploy: adb's CR LF line ends in the builder's part are read as LF", fb([], mm + b"\r\nREV = 2\r\n"), "")
        os.remove(tb)
        check_("for-deploy: no table on this PC -> nothing added, said", (fd([], mark), said[-1].split(" (")[0]), ("", "DUST TABLE: this PC's table does not read"))
        for k, v in env0.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # real catches against the table
    vt = parse_table(table_text({**dust, 16: 100, 19: 100, 21: 100, 774: 1000, 29: 300}, names, 1))
    L = ["20:00:01 CATCH Wild #16 ball=1 p=0.5 att=1 berry=0 0.6s dust=125 candy=3", "20:00:02 CATCH Wild #19 ball=1 p=0.5 att=1 berry=0 0.6s dust=150 candy=3",
         "20:00:03 CATCH Wild #774 ball=1 p=0.2 att=1 berry=0 0.6s dust=1025 candy=3", "20:00:04 CATCH Wild #29 ball=1 p=0.2 att=1 berry=0 0.6s dust=400 candy=3",
         "20:00:05 CATCH Wild #21 ball=1 p=0.2 att=1 berry=0 0.6s dust=325 candy=3", "20:00:06 CATCH Wild #16 ball=1 p=0.5 att=1 berry=0 0.6s dust=125 candy=3",
         "20:00:07 run 5s | caught=6", "20:01:01 CATCH Wild #16 ball=1 p=0.5 att=1 berry=0 0.6s dust=187 candy=3",
         "20:01:02 CATCH Wild #19 ball=1 p=0.5 att=1 berry=0 0.6s dust=187 candy=3", "20:01:03 CATCH Wild #774 ball=1 p=0.2 att=1 berry=0 0.6s dust=1537 candy=3",
         "20:01:04 CATCH Wild #21 ball=1 p=0.2 att=1 berry=0 0.6s dust=487 candy=3",
         "00:00:05 CATCH Wild #16 ball=1 p=0.5 att=1 berry=0 0.6s dust=1925 candy=3", "00:00:06 CATCH Wild #19 ball=1 p=0.5 att=1 berry=0 0.6s dust=125 candy=3",
         "00:00:07 CATCH Wild #19 ball=1 p=0.5 att=1 berry=0 0.6s dust=125 candy=3", "00:03:07 CATCH Wild #774 ball=1 p=0.5 att=1 berry=0 0.6s dust=1025 candy=3",
         '{"k":"spawn","e":"a","id":16,"r":"caught","d":225,"tC":1795000000000}', '{"k":"spawn","e":"b","id":21,"r":"caught","d":625,"tC":1795000001000}',
         '{"k":"spawn","e":"c","id":21,"r":"fled","d":null,"tC":1795000002000}', '{"k":"pos","t":1,"lat":1.0,"lng":2.0}']
    recs = catch_records(L)
    res = verify_catches(recs, vt)
    check_("catches: log lines and ledger records read, others ignored", (len(recs), recs[0], recs[-1][2:]), (16, (("log", 0, 1200), 72001, 16, 125), (21, 625)))
    check_("catches: a new day when the clock jumps back", sorted({k[1] for k, _s, _d, _a in recs if k[0] == "log"}), [0, 1])
    check_("catches: weather (150), a 1000 one and a 300 one are as the table says; a table-100 species paying 325 / 487 / 625 is ABOVE",
           {d: v[:2] for d, v in res["above"].items()}, {21: (3, 3)})
    check_("catches: the first catch of the day (+1,800) is not a species' pay", [(r["dex"], r["a"]) for r in res["lump"]], [(16, 1925)])
    check_("catches: no normal catch in its minute -> not judged", (res["noref"], res["checked"], res["species"]), (1, 15, 5))
    ev = ["21:%02d:01 CATCH Wild #16 x dust=225" % i for i in range(5)] + ["21:%02d:02 CATCH Wild #21 x dust=2025" % i for i in range(5)]
    rv = verify_catches(catch_records(ev), vt)
    check_("catches: a 1,000 species tabled at 100 at a 2x event (+1,800 every time) is ABOVE, not a daily bonus",
           ({d: v[:2] for d, v in rv["above"].items()}, len(rv["lump"])), ({21: (5, 5)}, 0))
    check_("catches: the report names the miss", [ln for ln in verify_report(res, vt) if "ABOVE" in ln or ln.startswith("RESULT")],
           ["  ABOVE THE TABLE #21 Mon 21: table 100, but 3 of its 3 catches paid 2x more (typically 487 against a normal 187)",
            "RESULT: 1 species pay more than the table says"])
    mix = catch_records(["10:00:01 CATCH Wild #16 x dust=125", "10:00:02 CATCH Wild #16 x dust=187", "10:00:03 CATCH Wild #774 x dust=1537"])
    check_("catches: the Star Piece changed inside the minute -> the 1000 one is not judged", (verify_catches(mix, vt)["mixed"], verify_catches(mix, vt)["checked"]), (1, 2))
    # two throws in the air: the log gave a 1000 one's award to a normal one and the normal award to the 1000 one
    sw = ["23:55:%02d CATCH Wild #16 x dust=150" % i for i in range(50, 56)] + ["23:55:56 CATCH Wild #506 x dust=1275", "23:56:02 CATCH Wild #774 x dust=150",
          "23:56:03 CATCH Wild #16 x dust=150"] + ["23:57:%02d CATCH Wild #506 x dust=150" % i for i in range(3)]
    rs = verify_catches(catch_records(sw), vt)
    check_("catches: an award swapped between two throws is not a species' pay",
           ([(r["dex"], r["a"]) for r in rs["swap"]], rs["above"], rs["few"], len(rs["other"]), len(rs["lump"])), ([(506, 1275)], {}, {}, 0, 0))
    one = verify_catches(catch_records(["09:00:01 CATCH Wild #16 x dust=125", "09:00:02 CATCH Wild #19 x dust=525"]), vt)
    check_("catches: one catch of a species, paid more, nothing explains it -> too few to tell (said, not judged)",
           (sorted(one["few"]), one["above"], [ln for ln in verify_report(one, vt) if ln.startswith("RESULT")]),
           ([19], {}, ["RESULT: no species pays more than the table says; 1 species with too few catches to tell"]))
    lowf = verify_catches(catch_records(["08:%02d:01 CATCH Wild #16 x dust=125" % i for i in range(4)] + ["08:%02d:02 CATCH Wild #774 x dust=125" % i for i in range(4)]), vt)
    check_("catches: a species that pays LESS than the table (a lower form) is said, never a miss", (lowf["under"], lowf["above"]), ({774: (4, 4)}, {}))
    return failed


def main(argv):
    def err(s):
        print(s, file=sys.stderr, flush=True)

    if "--selftest" in argv:
        return 1 if _selftest() else 0
    opt = {a: (argv[i + 1] if i + 1 < len(argv) else None) for i, a in enumerate(argv) if a in ("--gamemaster", "--batch", "--table")}
    table = opt.get("--table") or TABLE
    if "--for-deploy" in argv:
        rel = for_deploy(argv[argv.index("--for-deploy") + 1:], sys.stdin.buffer.read(), err)
        if rel:
            sys.stdout.buffer.write((rel + "\n").encode("ascii"))   # bytes: a Windows "\r\n" would end up in bash's file name
        return 0
    if "--auto" in argv:
        i = argv.index("--auto")
        if i + 1 >= len(argv):
            return 2
        print(json.dumps(auto(argv[i + 1], table=table, state=os.path.splitext(table)[0] + ".state.json",
                              net=os.environ.get("CATCH_DUST_NO_NET") != "1")), flush=True)
        return 0
    if "--update" in argv:
        ok, line = update(table=table, state=os.path.splitext(table)[0] + ".state.json", force="--force" in argv)
        if "--quiet" not in argv:
            print("DUST TABLE: " + line)
        return 0 if ok else 1
    if "--verify-catches" in argv:
        tab = read_table(table)
        lines = []
        for p in argv[argv.index("--verify-catches") + 1:]:
            with open(p, encoding="utf-8", errors="replace") as fh:
                lines += fh.read().splitlines()
        res = verify_catches(catch_records(lines), tab)
        print("\n".join(verify_report(res, tab)))
        return 1 if res["above"] else 0
    if "--check" in argv:
        try:
            with open(table, "rb") as fh:
                text = fh.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print("FAIL %s: %s" % (table, e))
            return 1
        bad = check(text)
        if not bad and opt.get("--gamemaster"):
            with open(opt["--gamemaster"], encoding="utf-8") as fh:
                gm = json.load(fh)
            miss = inclusion_misses(gm, parse_table(text))
            bad += ["template %s pays %s, the table has %s" % m for m in miss]
            n = sum(1 for f in species_dust(gm)[2]["forms"].values() for v in f.values() if v > NORMAL)
            print("inclusion: %d templates with a stardust bonus, %d not covered by the table" % (n, len(miss)))
        for b in bad:
            print("FAIL " + b)
        if not bad:
            t = parse_table(text)
            print("ok   %s: batch %d (%s), %d species, base %d, %d above it; levels %s"
                  % (os.path.basename(table), t["batch"], utc(t["batch"]), len(t["dust"]), t["base"],
                     sum(v > t["base"] for v in t["dust"].values()), json.dumps(t["doc"]["levels"])))
        return 1 if bad else 0
    if opt.get("--gamemaster"):
        gm_path = opt["--gamemaster"]
        batch = int(opt["--batch"]) if opt.get("--batch") else installed_batch(gm_path)[0]
        try:
            old = read_table(table)
        except ValueError:
            old = None
        with open(gm_path, encoding="utf-8") as fh:
            why, new = install(json.load(fh), batch, table, old, "--force" in argv)
        print("DUST TABLE: " + ("REFUSED: %s -- the table is kept" % why if not new else "batch %d (%s) from %s: %s"
                                % (batch, utc(batch), os.path.basename(gm_path), diff_line(old, new))))
        return 0 if new else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
