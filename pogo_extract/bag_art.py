"""bag_art.py -- the IMPURE half of Bag Pulse's pictures (2026-09-30; decisions and numbers: docs/memory/pogo-bag-pulse-sprites.md).

Bag Pulse used to name the Transfer pile in text. Benny releases that pile BY HAND in the game, so seeing each mon's exact
look (form, costume, gender, shiny, background card) next to its name finds the right copy faster. This module turns pile
rows into embedded pictures; pogo_display.py (pure) decides WHICH picture and WHAT name. DISPLAY ONLY: it never changes what
is kept, tagged or released.

    prepare(rows, sprite_uids, card_uids)  -> Art: {icon file: data: URI}, per-uid Match, cards, stats. NEVER raises.
    pile_card_html(art, pile_rows, names)  -> the 'In the Transfer tag now' card (server-rendered, one tile per look)
    assemble(TEMPLATE, DATA, art, card)    -> the finished page (kill switch, closing-tag-safe DATA JSON)

THE CULL MUST NEVER FAIL BECAUSE OF ART. Every failure -- no network, a 404, a corrupt cache, an odd PNG, the wall budget --
falls back to today's text (or a letter placeholder in the tile). Bounds: 6 daemon fetch threads, 6 s per request, ONE 25 s
wall budget for all art work, 80 sprite + 12 card fetches per run, a circuit breaker after 3 network failures in a row, a
640 KB sprite budget per page. No Pillow / numpy in the cloud VM (cloud/setup.sh installs neither), so the image step is a
stdlib PNG codec (measured: 0 failures on 84 sprites + 256 card headers, ~0.1 s per sprite, 5-12 KB each).

CACHE: system/analysis/art_cache/{s72,c64}/ (processed thumbnails only) + misses.json. Rebuildable from a public source, so
it is NOT in the phone data store (tools/data_manifest.txt does not match it; docs/data.md says why). Directory names carry
the processing parameters: change a size and the old directory is simply ignored.
Env: BAG_ART=0 turns art AND official names off (today's page, byte for byte); BAG_ART_CACHE=<dir>; BAG_ART_OFFLINE=1.

    python bag_art.py --selftest                                   offline, no DB, no phone, no network
    python bag_art.py --text [FILE]                                a page's words, pictures stripped, then the names its script draws
                                                                   into the cull log (default: the active account's Bag Pulse)
    python bag_art.py --refresh-index --tree FILE | --clone DIR    rebuild pogo_icon_index.txt (a saved trees-API JSON or
                                                                   `git ls-tree` list, or a local clone; read-only git only)
    python bag_art.py --refresh-names --i18n FILE [--gm FILE] [--commit SHA]
                                                                   rebuild official_names_en.json from i18n_english.json: the game's
                                                                   species + form names AND the wording of its evolution quests
                                                                   (evolvable_forms._quest_text reads it). The client game master says
                                                                   which i18n texts the quests display (default
                                                                   gamemaster_pokeminers.json); one command for all the game's text
Any other argument prints this usage and exits 2: nothing runs on a guessed flag (docs/memory/feedback-never-probe-scripts-
with-help.md).
"""
import base64
import collections
import datetime
import html
import http.client
import json
import os
import queue
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib

sys.dont_write_bytecode = True
import pogo_display as pd
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, 'system', 'analysis', 'art_cache')
SPRITE_PX, CARD_PX = 72, 64                       # longest side of an embedded thumbnail (the page shows 48 / 24 / 32 px)
SPRITE_SUB, CARD_SUB = 's%d' % SPRITE_PX, 'c%d' % CARD_PX
SPRITE_MAX, CARD_MAX = 16 * 1024, 24 * 1024       # bytes of ONE cached thumbnail: a bigger file is corrupt or foreign
SPRITE_BUDGET, CARD_BUDGET = 640_000, 100_000     # raw thumbnail bytes one page embeds (~98 sprites at the 6.5 KB average)
BODY_MAX, CARD_BODY_MAX = 700_000, 1_500_000      # a source PNG bigger than this is not fetched (cards: 100-680 KB today)
MAX_SRC_PX = 4_000_000                            # decode refuses bigger images (the largest card is 1024 x 1024)
ALPHA_MIN = 8                                     # alpha at or above this counts as 'inside the sprite' for the crop
MAX_SPRITE_FETCH, MAX_CARD_FETCH = 80, 12
WORKERS, FETCH_TIMEOUT, WALL_S, BREAKER = 6, 6.0, 25.0, 3
STALE_DAYS = 60                                   # the icon index is called old after this many days since it was listed
MISS_DAYS = {'404': 7, 'oversize': 30, 'undecodable': 1}    # negative cache; a network failure is NEVER cached
PIXEL = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=='   # 1 px placeholder: keeps the box
SIG = b'\x89PNG\r\n\x1a\n'


# ============================================================================================================ PNG codec
class Unsupported(Exception):
    """A PNG this codec will not touch (16-bit, interlaced, truncated, corrupt ...): that mon falls back to text."""


def _chunks(b):
    """(type, data) for every chunk up to IEND, CRC-checked; anything short of a whole, valid stream raises Unsupported."""
    if b[:8] != SIG:
        raise Unsupported('not a PNG')
    i, n = 8, len(b)
    while i + 12 <= n:
        ln, t = struct.unpack('>I4s', b[i:i + 8])
        end = i + 8 + ln
        if end + 4 > n:
            raise Unsupported('truncated')
        d = b[i + 8:end]
        if zlib.crc32(t + d) & 0xffffffff != struct.unpack('>I', b[end:end + 4])[0]:
            raise Unsupported('bad crc')
        yield t, d
        if t == b'IEND':
            return
        i = end + 4
    raise Unsupported('no IEND')


def png_ok(b, max_side, max_bytes):
    """A cached / to-be-embedded thumbnail: whole stream, 8-bit RGB(A), small. No decode: the cache read must stay cheap."""
    try:
        if len(b) > max_bytes:
            return False
        w = h = 0
        idat = 0
        for t, d in _chunks(b):
            if t == b'IHDR':
                w, h, bd, ct = struct.unpack('>IIBB', d[:10])
                if bd != 8 or ct not in (2, 6):
                    return False
            elif t == b'IDAT':
                idat += 1
        return bool(w) and idat > 0 and max(w, h) <= max_side
    except (Unsupported, struct.error, ValueError):
        return False


def decode(b, max_px=MAX_SRC_PX):
    """-> (w, h, rgba bytearray). 8-bit non-interlaced gray / gray+a / rgb / rgba / palette only; the inflate is bounded
    by the size the header promises, so a decompression bomb cannot exhaust memory."""
    ihdr = plte = trns = None
    idat = []
    for t, d in _chunks(b):
        if t == b'IHDR' and len(d) == 13:
            ihdr = struct.unpack('>IIBBBBB', d)
        elif t == b'PLTE':
            plte = d
        elif t == b'tRNS':
            trns = d
        elif t == b'IDAT':
            idat.append(d)
    if not ihdr or not idat:
        raise Unsupported('no image data')
    w, h, bd, ct, cm, fm, il = ihdr
    if il:
        raise Unsupported('interlaced')
    if bd != 8 or cm or fm:
        raise Unsupported('bit depth %d' % bd)
    if w < 1 or h < 1 or w * h > max_px:
        raise Unsupported('size %dx%d' % (w, h))
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ct)
    if ch is None or (ct == 3 and not plte):
        raise Unsupported('color type %d' % ct)
    stride = w * ch
    need = (stride + 1) * h
    try:
        raw = zlib.decompressobj().decompress(b''.join(idat), need + 1)
    except zlib.error as e:
        raise Unsupported('zlib: %s' % e)
    if len(raw) < need:
        raise Unsupported('short data')
    if ct == 3:                                        # palette -> per-channel translate tables
        tr = [bytes(plte[3 * k + c] if 3 * k + c < len(plte) else 0 for k in range(256)) for c in range(3)]
        ta = bytes((trns[k] if trns and k < len(trns) else 255) for k in range(256))
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ft == 1:                                    # Sub
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif ft == 2:                                  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:                                  # Average
            for i in range(ch):
                line[i] = (line[i] + (prev[i] >> 1)) & 255
            for i in range(ch, stride):
                line[i] = (line[i] + ((line[i - ch] + prev[i]) >> 1)) & 255
        elif ft == 4:                                  # Paeth
            for i in range(ch):
                line[i] = (line[i] + prev[i]) & 255
            for i in range(ch, stride):
                a, b_, c = line[i - ch], prev[i], prev[i - ch]
                p = a + b_ - c
                pa, pb, pc = abs(p - a), abs(p - b_), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else (b_ if pb <= pc else c))) & 255
        elif ft != 0:
            raise Unsupported('filter %d' % ft)
        row = out[y * w * 4:(y + 1) * w * 4]
        if ct == 6:
            row[:] = line
        elif ct == 2:
            row[0::4], row[1::4], row[2::4], row[3::4] = line[0::3], line[1::3], line[2::3], b'\xff' * w
        elif ct == 0:
            row[0::4] = row[1::4] = row[2::4] = line
            row[3::4] = b'\xff' * w
        elif ct == 4:
            row[0::4] = row[1::4] = row[2::4] = line[0::2]
            row[3::4] = line[1::2]
        else:
            b_line = bytes(line)
            row[0::4], row[1::4], row[2::4], row[3::4] = (b_line.translate(tr[0]), b_line.translate(tr[1]),
                                                          b_line.translate(tr[2]), b_line.translate(ta))
        out[y * w * 4:(y + 1) * w * 4] = row
        prev = line
    return w, h, out


_ALPHA_TBL = bytes(1 if a >= ALPHA_MIN else 0 for a in range(256))


def bbox(w, h, px):
    """(x0, y0, x1, y1) of the pixels with alpha >= ALPHA_MIN; Unsupported when the image is empty."""
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        flags = bytes(px[y * w * 4 + 3:(y + 1) * w * 4:4]).translate(_ALPHA_TBL)
        a = flags.find(1)
        if a >= 0:
            y0, y1 = min(y0, y), y
            x0, x1 = min(x0, a), max(x1, flags.rfind(1))
    if x1 < 0:
        raise Unsupported('fully transparent')
    return x0, y0, x1 + 1, y1 + 1


def crop(w, h, px, box):
    x0, y0, x1, y1 = box
    nw, nh = x1 - x0, y1 - y0
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        s = ((y0 + y) * w + x0) * 4
        out[y * nw * 4:(y + 1) * nw * 4] = px[s:s + nw * 4]
    return nw, nh, out


def _spans(n, m):
    """For each of m output cells, the (source index, overlap length) pairs of an area-average from n source cells."""
    k = n / m
    out = []
    for i in range(m):
        a, b = i * k, (i + 1) * k
        out.append([(s, min(b, s + 1) - max(a, s)) for s in range(int(a), min(n, int(b) + 1)) if min(b, s + 1) - max(a, s) > 1e-9])
    return out


def downscale(w, h, px, max_side):
    """Area-average on PREMULTIPLIED colour, so a transparent edge never fringes dark. Never upscales."""
    if max(w, h) <= max_side:
        return w, h, px
    k = max_side / max(w, h)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    cols, rows_ = _spans(w, nw), _spans(h, nh)
    out = bytearray(nw * nh * 4)
    for j, ys in enumerate(rows_):
        for i, xs in enumerate(cols):
            r = g = b = a = ws = 0.0
            for yy, wy in ys:
                base = yy * w
                for xx, wx in xs:
                    wt = wx * wy
                    o = (base + xx) * 4
                    al = px[o + 3]
                    if al:
                        wa = wt * al
                        r += px[o] * wa
                        g += px[o + 1] * wa
                        b += px[o + 2] * wa
                        a += wa
                    ws += wt
            if a > 0:
                o = (j * nw + i) * 4
                out[o], out[o + 1], out[o + 2] = min(255, int(r / a + .5)), min(255, int(g / a + .5)), min(255, int(b / a + .5))
                out[o + 3] = min(255, int(a / ws + .5))
    return nw, nh, out


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)


def encode(w, h, px, rgb=False):
    """8-bit RGBA (or RGB when `rgb`) PNG; each row takes the adaptive filter with the smallest residual sum."""
    bpp = 3 if rgb else 4
    stride = w * bpp
    rows, prev = [], bytearray(stride)
    for y in range(h):
        src = px[y * w * 4:(y + 1) * w * 4]
        if rgb:
            cur = bytearray(stride)
            cur[0::3], cur[1::3], cur[2::3] = src[0::4], src[1::4], src[2::4]
        else:
            cur = bytearray(src)
        f1, f2, f4 = bytearray(stride), bytearray(stride), bytearray(stride)
        for i in range(stride):
            a = cur[i - bpp] if i >= bpp else 0
            c = prev[i - bpp] if i >= bpp else 0
            f1[i] = (cur[i] - a) & 255
            f2[i] = (cur[i] - prev[i]) & 255
            f4[i] = (cur[i] - _paeth(a, prev[i], c)) & 255
        best = min(((sum(v if v < 128 else 256 - v for v in ln), ft, ln) for ft, ln in ((0, cur), (1, f1), (2, f2), (4, f4))),
                   key=lambda t: t[0])
        rows.append(bytes((best[1],)) + bytes(best[2]))
        prev = cur

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (SIG + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2 if rgb else 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))


def thumb(data, side, crop_alpha=True, opaque_rgb=False):
    """Source PNG bytes -> thumbnail PNG bytes. Icons are cropped to their alpha box (the 256 x 256 files carry a wide
    margin; cropping makes the 'Images/Pokemon' and 'Images/Pokemon - 256x256' copies identical); cards keep their frame and
    are written as RGB when fully opaque."""
    w, h, px = decode(data)
    if crop_alpha:
        w, h, px = crop(w, h, px, bbox(w, h, px))
    w, h, px = downscale(w, h, px, side)
    return encode(w, h, px, rgb=bool(opaque_rgb and px[3::4].count(255) == w * h))


# ================================================================================================================ fetch
class NotFound(Exception):
    """HTTP 404 / 410: the file is not there (negative-cached, upstream gaps do get fixed)."""


class NetError(Exception):
    """Anything network-level: no route, a timeout, HTTP 403 / 407 / 429 / 5xx. Counted by the breaker, NEVER cached."""


class BadBody(Exception):
    """A 200 that is not the picture: 'oversize' is a property of the file (cached), 'not a PNG' looks like a proxy or
    captive-portal page and is treated as a network failure (a 30-day negative entry would poison the cache)."""

    def __init__(self, why):
        Exception.__init__(self, why)
        self.why = why


class Undecodable(Exception):
    """A complete download this codec cannot turn into a thumbnail."""


def http_get(url, timeout=FETCH_TIMEOUT, max_bytes=BODY_MAX):
    """One public GET (raw.githubusercontent.com single files only). urllib honours HTTPS_PROXY and the CA env."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'pogo-bag-art'}), timeout=timeout) as r:
            body = r.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise NotFound(url)
        raise NetError('HTTP %d' % e.code)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise NetError('%s: %s' % (type(e).__name__, str(e)[:100]))
    if len(body) > max_bytes:
        raise BadBody('oversize')
    if body[:8] != SIG:
        raise BadBody('not a PNG')
    return body


def _outcome(exc):
    if exc is None:
        return 'ok'
    if isinstance(exc, NotFound):
        return '404'
    if isinstance(exc, BadBody) and exc.why == 'oversize':
        return 'oversize'
    if isinstance(exc, Undecodable):
        return 'undecodable'
    return 'net'


def _pump(jobs, run, workers, clock, deadline):
    """Run `run(job)` for every job on `workers` daemon threads (0 = inline, for tests) until the wall budget or the
    circuit breaker stops it. -> ({job: (outcome, value)}, tripped); outcome 'ok' | '404' | 'oversize' | 'undecodable' | 'net' |
    'skip' (never started: 'budget' / 'offline'), and whether the breaker tripped. A hung socket cannot block the caller
    or the interpreter's exit."""
    out, streak = {}, 0
    if clock() >= deadline:
        return {j: ('skip', 'budget') for j in jobs}, False

    def settle(job, exc, val):
        nonlocal streak
        o = _outcome(exc)
        out[job] = (o, val if o == 'ok' else (getattr(exc, 'why', None) or str(exc)[:100]))
        streak = streak + 1 if o == 'net' else 0
        return streak >= BREAKER
    if workers <= 0:
        for job in jobs:
            if clock() >= deadline or streak >= BREAKER:
                break
            try:
                settle(job, None, run(job))
            except Exception as e:
                settle(job, e, None)
    else:
        q, res, stop = queue.Queue(), queue.Queue(), threading.Event()
        for j in jobs:
            q.put(j)

        def work():
            while not stop.is_set():
                try:
                    j = q.get_nowait()
                except queue.Empty:
                    return
                try:
                    res.put((j, None, run(j)))
                except Exception as e:
                    res.put((j, e, None))
        for _ in range(min(workers, len(jobs))):
            threading.Thread(target=work, daemon=True).start()
        while len(out) < len(jobs):
            left = deadline - clock()
            if left <= 0:
                break
            try:
                j, exc, val = res.get(timeout=min(left, 0.2))
            except queue.Empty:
                continue
            if settle(j, exc, val):
                break
        stop.set()
    for j in jobs:
        out.setdefault(j, ('skip', 'offline' if streak >= BREAKER else 'budget'))
    return out, streak >= BREAKER


# ================================================================================================================ cache
class Cache:
    """art_cache/{s72,c64}/<file> thumbnails + misses.json. Every method is safe on a missing, unwritable or corrupt
    directory: reads return None, writes return False. Writes are tmp + os.replace, so a reader never sees half a file."""

    def __init__(self, root, now=time.time):
        self.root, self.now, self.usable = root, now, False
        self._misses, self._dirty = None, False
        try:
            for sub in (SPRITE_SUB, CARD_SUB):
                os.makedirs(os.path.join(root, sub), exist_ok=True)
            self.usable = os.path.isdir(root) and os.access(root, os.W_OK)
        except OSError:
            self.usable = False

    def _path(self, kind, name):
        return os.path.join(self.root, SPRITE_SUB if kind == 's' else CARD_SUB, name if kind == 's' else name + '.png')

    def read(self, kind, name):
        p = self._path(kind, name)
        lim, side = (SPRITE_MAX, SPRITE_PX) if kind == 's' else (CARD_MAX, CARD_PX)
        try:
            with open(p, 'rb') as f:
                b = f.read(lim + 1)
        except OSError:
            return None
        if png_ok(b, side, lim):
            return b
        try:
            os.remove(p)                                  # garbage, truncated or oversize: gone, refetched when online
        except OSError:
            pass
        return None

    def write(self, kind, name, data):
        return self._atomic(self._path(kind, name), data)

    def _atomic(self, p, data):
        tmp = '%s.%d.tmp' % (p, os.getpid())
        try:
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, p)
            return True
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def _load_misses(self):
        if self._misses is None:
            try:
                d = json.load(open(os.path.join(self.root, 'misses.json'), encoding='utf-8'))
                self._misses = {k: v for k, v in d.items() if isinstance(v, dict) and isinstance(v.get('until'), (int, float))}
            except Exception:
                self._misses = {}                          # corrupt or absent: ignored, rewritten on the next save
        return self._misses

    def missed(self, key):
        e = self._load_misses().get(key)
        return bool(e) and e['until'] > self.now()

    def miss(self, key, why, days):
        self._load_misses()[key] = {'until': self.now() + days * 86400, 'why': why}
        self._dirty = True

    def save_misses(self):
        if self._dirty and self._misses is not None:
            m = {k: v for k, v in self._misses.items() if v['until'] > self.now()}
            self._atomic(os.path.join(self.root, 'misses.json'), json.dumps(m, sort_keys=True).encode('utf-8'))


# ============================================================================================================= prepare
class Art:
    """What prepare() produced. sprites: key -> data URI (key = icon file name, 'c:'+stem for a card)."""

    def __init__(self):
        self.sprites, self.match, self.cards = {}, {}, {}      # cards: uid -> (CardInfo, sprite key or None)
        self.stats = collections.OrderedDict(
            wanted=0, cached=0, fetched=0, missing=0, unavailable=0, capped=0, over_budget=0, embedded=0, bytes=0,
            cards_wanted=0, cards_fetched=0, cards_missing=0, cards_capped=0, cards_embedded=0, offline='', cache='', seconds=0.0, error='',
            index='', listed='')

    def sprite_key(self, uid):
        m = self.match.get(uid)
        return m.fn if m and m.fn in self.sprites else None

    def approx(self, uids):
        return sum(1 for u in uids if u in self.match and self.match[u].approx)

    def page_stats(self):
        """The stats the PAGE carries (DATA.art): everything but the local cache path -- an unusable cache dir is a path on
        the cloud VM that has no business in a published artifact."""
        d = {k: v for k, v in self.stats.items() if k != 'cache'}
        d['cache_ok'] = not self.stats['cache']
        if d.get('error'):          # an exception text can carry a local path (an unreadable index): keep only the file name
            d['error'] = re.sub(r"(?:[A-Za-z]:)?[\\/][^'\"\s]*[\\/]([^\\/'\"\s]+)", r'\1', str(d['error']))
        return d

    def line(self, pile_uids):
        """The art summary line gen_bag_pulse prints BEFORE its KPI line. full_audit.finish_step shows only the LAST stdout line, so a
        cull never shows this one: the page footnote is the in-cull signal that art degraded (review note, 2026-09-30)."""
        s = self.stats
        mine = {self.sprite_key(u) for u in pile_uids} - {None}
        age = index_age(s['listed'])
        flags = ''.join(t for t, on in ((' | OFFLINE (%s)' % s['offline'], s['offline']), (' | CACHE UNUSABLE (%s)' % s['cache'], s['cache']),
                                        (' | ERROR %s' % s['error'], s['error']),
                                        (' | ICON INDEX %d DAYS OLD (bag_art.py --refresh-index)' % (age or 0), age is not None and age > STALE_DAYS)) if on)
        return ('art: %d sprites (%d KB), %d of them for the %d pile mons, %d approximate, %d cards | cache %d hit / %d fetched / '
                '%d missing / %d unavailable%s | icon index %s%s | %.1f s' % (
                    s['embedded'], s['bytes'] // 1024, len(mine), len(pile_uids), self.approx(pile_uids), s['cards_embedded'],
                    s['cached'], s['fetched'], s['missing'], s['unavailable'], flags, s['index'] or '?',
                    (' (listed %s)' % s['listed']) if s['listed'] else '', s['seconds']))


def index_age(listed, today=None):
    """Days since the icon index was listed from upstream (its header date), None when unknown."""
    try:
        return ((today or datetime.date.today()) - datetime.date.fromisoformat(listed)).days
    except (TypeError, ValueError):
        return None


def enabled():
    return os.environ.get('BAG_ART', '1') != '0'


def prepare(rows, sprite_uids, card_uids=(), cache_dir=None, offline=None, fetch=None, index=None, names=None,
            clock=None, now=None, workers=WORKERS, wall_s=WALL_S):
    """Resolve, cache and thumbnail the pictures for `sprite_uids` (priority order: the current pile first) and the location
    cards of `card_uids`. NEVER raises: a failure in any stage leaves that stage's mons as text. `fetch(url) -> bytes` (raising
    NotFound / NetError / BadBody), `clock` (the wall budget) and `now` (negative-cache expiry) are injectable so the self-test
    needs no network and no waiting."""
    art, t0 = Art(), time.monotonic()
    try:
        _prepare(art, rows, sprite_uids, card_uids, cache_dir, offline, fetch, index, names, clock or time.monotonic,
                 now or time.time, workers, wall_s)
    except Exception as e:                                  # today's text page is the fallback for anything at all
        art.stats['error'] = '%s: %s' % (type(e).__name__, str(e)[:120])
    art.stats['seconds'] = round(time.monotonic() - t0, 1)
    return art


def _embed(b):
    return 'data:image/png;base64,' + base64.b64encode(b).decode('ascii')


def _prepare(art, rows, sprite_uids, card_uids, cache_dir, offline, fetch, index, names, clock, now, workers, wall_s):
    st = art.stats
    ix = index or pd.IconIndex.load()
    nm = names or pd.Names.load()
    st['index'], st['listed'] = ix.meta.get('committed', '') or '', ix.meta.get('listed', '') or ''
    if ix.error:
        st['error'] = 'icon index: %s' % ix.error
    if offline is None:
        offline = os.environ.get('BAG_ART_OFFLINE') == '1'
    if offline:
        st['offline'] = 'BAG_ART_OFFLINE'
    cache = Cache(cache_dir or os.environ.get('BAG_ART_CACHE') or CACHE_DIR, now)
    if not cache.usable:
        st['cache'] = cache.root
    deadline = clock() + wall_s
    by_uid = {r['uid_hex']: r for r in rows}
    tripped = False

    def fetch_many(kind, items, cap, side, is_card):
        """items: ordered unique names that are neither cached nor known missing. -> ({name: thumbnail bytes}, Counter of what
        happened): fetched / missing (negative-cached) / unavailable (offline, budget, network) / capped (over the run's cap)."""
        nonlocal tripped
        todo = items[:cap]
        tally = collections.Counter(capped=len(items) - len(todo))
        if not todo:
            return {}, tally
        if offline or tripped:
            tally['unavailable'] += len(todo)
            return {}, tally
        body_max = CARD_BODY_MAX if is_card else BODY_MAX

        def one(name):
            path = pd.card_path(name) if is_card else pd.sprite_path(name)
            if path is None:                                 # never reaches a URL or a cache path (the callers validate too)
                raise Undecodable('unsafe name %r' % name[:40])
            url = pd.raw_url(path)
            body = fetch(url) if fetch else http_get(url, max_bytes=body_max)
            if not isinstance(body, (bytes, bytearray)) or body[:8] != SIG:
                raise BadBody('not a PNG')
            if len(body) > body_max:
                raise BadBody('oversize')
            try:
                return thumb(bytes(body), side, crop_alpha=not is_card, opaque_rgb=is_card)
            except Exception as e:
                raise Undecodable('%s: %s' % (type(e).__name__, e))
        res, trip = _pump(todo, one, workers, clock, deadline)
        got = {}
        for name, (o, val) in res.items():
            key = ('c:' if is_card else 's:') + name
            if o == 'ok' and len(val) <= (CARD_MAX if is_card else SPRITE_MAX):
                got[name] = val
                cache.write(kind, name, val)
                tally['fetched'] += 1
            elif o in ('ok', 'undecodable'):                 # a thumbnail over the size limit is as good as undecodable
                cache.miss(key, 'undecodable: %s' % (val if o != 'ok' else 'thumbnail too big'), MISS_DAYS['undecodable'])
                tally['missing'] += 1
            elif o in MISS_DAYS:                             # 404 (a week: upstream gaps do get fixed) / oversize (a month)
                cache.miss(key, o, MISS_DAYS[o])
                tally['missing'] += 1
            else:                                            # 'net' / 'skip': nothing is remembered, the next run retries
                tally['unavailable'] += 1
        if trip:
            tripped = True
            st['offline'] = st['offline'] or 'network'
        return got, tally

    # ---- sprites: current pile first, then the in-bag mons of past passes
    wanted = []
    for u in sprite_uids:
        r = by_uid.get(u)
        if r is None:
            continue
        m = ix.resolve(r)
        art.match[u] = m
        if m.fn and pd.sprite_path(m.fn) and m.fn not in wanted:
            wanted.append(m.fn)
    st['wanted'] = len(wanted)
    have, need = {}, []
    for fn in wanted:
        b = cache.read('s', fn)
        if b:
            have[fn] = b
            st['cached'] += 1
        elif cache.missed('s:' + fn):
            st['missing'] += 1
        else:
            need.append(fn)
    got, tally = fetch_many('s', need, MAX_SPRITE_FETCH, SPRITE_PX, False)
    have.update(got)
    for k in ('fetched', 'missing', 'unavailable', 'capped'):
        st[k] += tally[k]
    for fn in wanted:                                       # embed in priority order until the page budget is spent
        b = have.get(fn)
        if not b:
            continue
        if st['bytes'] + len(b) > SPRITE_BUDGET:
            st['over_budget'] += 1
            continue
        art.sprites[fn] = _embed(b)
        st['bytes'] += len(b)
        st['embedded'] += 1

    # ---- location cards of the current pile (last: they never starve a sprite of the wall budget)
    try:
        cards, order = {}, []
        for u in card_uids:
            r = by_uid.get(u)
            cid = pd.card_id(r) if r is not None else 0
            if cid:
                info = nm.card_info(cid)
                stem = ix.card_stem(info.image_url) if info.image_url else None
                cards[u] = (info, stem)
                if stem and stem not in order:
                    order.append(stem)
        st['cards_wanted'] = len(order)
        chave, cneed = {}, []
        for stem in order:
            b = cache.read('c', stem)
            if b:
                chave[stem] = b
            elif not cache.missed('c:' + stem):
                cneed.append(stem)
        got, tally = fetch_many('c', cneed, MAX_CARD_FETCH, CARD_PX, True)
        chave.update(got)
        st['cards_fetched'], st['cards_missing'], st['cards_capped'] = tally['fetched'], tally['missing'], tally['capped']
        spent = 0
        for stem in order:
            b = chave.get(stem)
            if b and spent + len(b) <= CARD_BUDGET:
                art.sprites['c:' + stem] = _embed(b)
                spent += len(b)
                st['cards_embedded'] += 1
        for u, (info, stem) in cards.items():
            art.cards[u] = (info, ('c:' + stem) if stem and ('c:' + stem) in art.sprites else None)
    except Exception as e:
        st['error'] = st['error'] or 'cards: %s: %s' % (type(e).__name__, str(e)[:100])
    cache.save_misses()


# ================================================================================================================= HTML
E = lambda s: html.escape(str(s), quote=True)

ART_CSS = '''/* Bag Pulse pictures (2026-09-30, bag_art.py): the Transfer pile as tiles -- one tile per look (sprite + card), one row per copy */
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px;align-items:start;margin-top:10px}
.tile{background:var(--surface-2);border:1px solid var(--line);border-radius:12px;padding:8px 10px;min-width:0}
.tile .hd{display:flex;align-items:center;gap:8px}
.tile h3{font-size:13px;line-height:1.2;margin:0;font-weight:700;overflow-wrap:break-word;min-width:0}
.tile h3 em{font-style:normal;color:var(--mut);font-weight:600}
.spr{flex:none;width:48px;height:48px;object-fit:contain}
.spr.approx,.s24.approx{outline:1px dashed var(--mut);outline-offset:1px;border-radius:6px}
.spr.none{display:flex;align-items:center;justify-content:center;border-radius:50%;background:var(--line);color:var(--mut);font-weight:800}
.tile .apx{display:block;margin-top:2px;font-size:10px;font-weight:600;color:var(--mut)}
.tile ul{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:2px;font-size:12px;font-variant-numeric:tabular-nums}
.tile li{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 6px}
.tile li b{font-family:var(--font-num);font-weight:700}
.tile li span{color:var(--mut)}
.c{font-style:normal;font-size:10px;text-transform:uppercase;letter-spacing:.06em;border:1px solid var(--line);border-radius:999px;padding:0 6px;color:var(--mut)}
.c.sh{color:var(--shiny);border-color:var(--shiny)}.c.sd{color:var(--warn);border-color:var(--warn)}.c.lk{color:var(--hundo);border-color:var(--hundo)}.c.mx{color:var(--pvp);border-color:var(--pvp)}
.card-row{display:flex;align-items:center;gap:8px;margin-top:6px;padding-top:6px;border-top:1px solid var(--line);font-size:11px;color:var(--mut);line-height:1.25}
.card-row b{color:var(--ink);font-weight:700}
.cth{flex:none;width:32px;height:32px;border-radius:6px;object-fit:cover}
.s24{width:24px;height:24px;object-fit:contain;vertical-align:middle;margin-right:3px}
.pi{display:inline-block;white-space:nowrap;margin-bottom:2px}
@media (max-width:480px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.tile .hd{flex-direction:column;align-items:flex-start;gap:4px}}
'''

# Filled BEFORE any Chart.js-dependent code (assemble puts it first in the page script): a CDN failure aborts the script at
# Chart.defaults and would otherwise take the whole pile card with it. pileCell renders a pass-table cell from pile_items.
ART_JS = '''const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
for (const im of document.querySelectorAll('img[data-spr]')) { const u = D.spr && D.spr[im.dataset.spr]; if (u) im.src = u; }
const pileCell = p => !p.pile_items ? p.pile_list : p.pile_items.map(it => '<span class="pi">' +
  (it.k && D.spr[it.k] ? '<img class="s24' + (it.a ? ' approx' : '') + '" src="' + D.spr[it.k] + '" alt="' + esc(it.n || '') + '" width="24" height="24">' : '') +
  esc(it.t) + '</span>').join(', ') + (p.pile_more ? ' ...' : '');
'''


def _copy_row(r, names, gender_key, max_axis):
    iv = round((r['iv_total'] or 0) / 45 * 100)
    sign = ''
    if gender_key and gender_key(r['pokemon_id'], r['gender']):
        sign = {1: ' \u2642', 2: ' \u2640'}.get(r['gender'], '')            # a sex sign only where it is a LOOK (cull_report.desc's rule)
    chips = ''.join('<i class="c %s">%s</i>' % (css, E(t)) for t, css in pd.look_chips(r, names, max_axis))
    return '<li><b>%d%%</b><span>CP %s%s</span>%s</li>' % (iv, r['cp'] or 0, sign, chips)


def art_note(art, pile_rows, tiles=0, blank=0):
    """The footnote under the pile card: whose art it is, how old the icon index is, what is approximate, why a tile has no picture."""
    s = art.stats
    bits = ['The pictures are the game\'s own icons, mirrored by PokeMiners/pogo_assets (mirror state of %s%s).' % (
        E(s['index']) or 'an unknown date', (', listed %s' % E(s['listed'])) if s['listed'] else '')]
    age = index_age(s['listed'])
    if age is not None and age > STALE_DAYS:
        bits.append('The icon list is %d days old, so a brand-new form or costume may show an approximate picture.' % age)
    apx = art.approx(r['uid_hex'] for r in pile_rows)
    if apx:
        bits.append('Dashed = approximate: the mirror has no exact art for that look (%d of these %d).' % (apx, len(pile_rows)))
    if blank:
        why = [w for w, on in (('offline', s['offline']), ('not fetched: network or time budget', s['unavailable'] and not s['offline']),
                               ('not in the mirror', s['missing']), ('over the page budget', s['over_budget']),
                               ('over the fetch cap', s['capped']), ('cache folder unusable', s['cache']),
                               ('the art step hit an error', s['error'])) if on]
        bits.append('%d of the %d tiles show a letter instead of a picture (%s).' % (blank, tiles, E(', '.join(why) or 'no icon for that look')))
    return ' '.join(bits)


def pile_card_html(art, pile_rows, names, gender_key=None, max_axis=None, unknown=0):
    """The 'In the Transfer tag now (N)' card: one tile per look (label + icon + card), one row per copy. Tiles are sorted,
    so the page is deterministic. A row with no picture keeps its tile, its label and its numbers: the picture is the only
    thing art can add, never a reason to drop a mon from the list."""
    n = len(pile_rows) + unknown
    head = '<div class="card wide" id="pile_card"><div class="eyebrow">Transfer tag</div><h2>In the Transfer tag now (%d)</h2>' % n
    if not n:
        return head + '<p class="note">Nothing is tagged for Transfer right now.</p></div>'
    tiles = {}
    for r in pile_rows:
        m = art.match.get(r['uid_hex']) or pd.Match(None, ())
        lab = names.label(r)
        # `dropped` is part of the key: a shiny copy the mirror has no shiny art for wears the PLAIN file, and must not share a
        # tile (and its 'approximate' flag) with an exact plain copy of the same species
        tiles.setdefault((lab.lower(), lab, m.fn or '', tuple(m.dropped), pd.card_id(r)), []).append(r)
    out = []
    for (_l, lab, fn, _dropped, cid), copies in sorted(tiles.items()):
        copies.sort(key=lambda r: (-(r['iv_total'] or 0), -(r['cp'] or 0), r['uid_hex']))
        first = copies[0]['uid_hex']
        m = art.match.get(first) or pd.Match(None, ())
        key = art.sprite_key(first)
        if key:
            img = '<img class="spr%s" data-spr="%s" alt="%s" width="48" height="48" src="%s"%s>' % (
                ' approx' if m.approx else '', E(key), E(lab), PIXEL,
                (' title="approximate: no %s art in the asset mirror"' % E('/'.join(m.dropped))) if m.approx else '')
        else:
            img = '<span class="spr none" aria-hidden="true">%s</span>' % E(lab[:1].upper())
        apx = '<span class="apx">\u2248 art: no %s sprite</span>' % E('/'.join(m.dropped)) if key and m.approx else ''
        card = ''
        if cid:
            info, ckey = art.cards.get(first) or (names.card_info(cid), None)
            thumb_img = ('<img class="cth" data-spr="%s" alt="%s" width="32" height="32" src="%s">' % (
                E(ckey), E('%s: %s' % (info.kind, info.name)), PIXEL)) if ckey else ''
            card = '<div class="card-row">%s<span><b>%s</b><br>%s</span></div>' % (thumb_img, E(info.kind), E(info.name))
        out.append('<div class="tile"><div class="hd">%s<div><h3>%s%s</h3>%s</div></div>%s<ul>%s</ul></div>' % (
            img, E(lab), (' <em>&times;%d</em>' % len(copies)) if len(copies) > 1 else '', apx, card,
            ''.join(_copy_row(r, names, gender_key, max_axis) for r in copies)))
    extra = ('<p class="note">%d more in the tag were not in the last walk.</p>' % unknown) if unknown else ''
    return (head + '<p class="note">Release these by hand in the game; the tool only tags. A tile is one look (form, costume, shiny, '
            'background); each row is one copy: IV %, CP and whatever sets it apart.</p><div class="tiles">' + ''.join(out) + '</div>' + extra
            + '<p class="note">' + art_note(art, pile_rows, len(out), sum(1 for t in out if 'class="spr none"' in t)) + '</p></div>')


def assemble(template, data, art=None, card_html='', on=True):
    """The finished page. One regex pass, so nothing a replacement contains is ever rescanned. `on` False (BAG_ART=0, or
    the import failed) fills every hook with what the page held before this feature -- byte for byte. DATA is JSON with every
    '<' escaped, so no name or label can close the script element."""
    js = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    hooks = {'DATA': js, 'ART_CSS': ART_CSS if on else '', 'PILE_CARD': (card_html + '\n    ') if on and card_html else '',
             'ART_JS': ART_JS if on else '', 'PILE_CELL': 'pileCell(p)' if on else 'p.pile_list'}
    return re.sub(r'__(DATA|ART_CSS|PILE_CARD|ART_JS|PILE_CELL)__', lambda m: hooks[m.group(1)], template)


# ================================================================================================= maintenance commands
def _atomic_text(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def _listing(tree, clone, commit, committed):
    """-> (paths, commit, committed date) from a saved listing or a local clone. Read-only: `git ls-tree` / `rev-parse` /
    `log` on the object store, never checkout / pull / reset (the PokeMiners clones are shared)."""
    if tree:
        text = open(tree, encoding='utf-8').read()
        try:
            d = json.loads(text)
        except ValueError:
            d = None
        if isinstance(d, dict) and 'tree' in d:
            if d.get('truncated'):
                raise SystemExit('the saved trees-API listing is TRUNCATED -- refusing to build on it (docs/memory/reference-pokegenie-art-internals.md)')
            return [t['path'] for t in d['tree'] if t.get('type') == 'blob'], commit or ('tree-%s' % (d.get('sha') or 'unknown')[:12]), committed or 'unknown'
        return [l for l in text.splitlines() if l.strip()], commit or 'unknown', committed or 'unknown'
    import subprocess
    gd = os.path.join(clone, '.git') if os.path.isdir(os.path.join(clone, '.git')) else clone

    def git(*a):
        try:
            return subprocess.run(['git', '--git-dir=' + gd] + list(a), capture_output=True, timeout=120, check=True).stdout.decode('utf-8', 'replace').strip()
        except (OSError, subprocess.SubprocessError) as e:
            raise SystemExit('git %s failed in %s: %s' % (a[0], gd, e))
    paths = git('ls-tree', '-r', '--name-only', 'HEAD').splitlines()
    return paths, git('rev-parse', 'HEAD'), git('log', '-1', '--format=%cs', 'HEAD')


def refresh_index(tree=None, clone=None, commit=None, committed=None, out=None):
    out = out or pd.INDEX_PATH
    paths, commit, committed = _listing(tree, clone, commit, committed)
    icons, cards = pd.split_listing(paths)
    old_icons, old_cards, _m, _e = pd.read_index(out)
    # never shrink the seed: a partial listing (an API cut-off, a sparse or blobless-broken clone) would silently strip icons
    if len(icons) < 3000 or len(icons) < 0.9 * len(old_icons) or (old_cards and len(cards) < 0.9 * len(old_cards)):
        raise SystemExit('refusing to write: %d icons / %d cards is a shrink (committed: %d / %d; floor 3,000 icons)'
                         % (len(icons), len(cards), len(old_icons), len(old_cards)))
    _atomic_text(out, pd.format_index(icons, cards, commit, committed, datetime.date.today().isoformat()))
    print('wrote %s: %d icons (%+d), %d cards (%+d), commit %s (%s)' % (
        out, len(icons), len(icons) - len(old_icons), len(cards), len(cards) - len(old_cards), commit[:12], committed))
    return 0


# upstream typos in the i18n keys: key (normalised) -> the key it should have been. form_squakabilly_white is the only one
# found (2026-09-30); without it the generic form_white ('White Kyurem') is all a white Squawkabilly could match.
KEY_FIXES = {'squakabillywhite': 'squawkabillywhite'}


# THE GAME'S OWN WORDS FOR THE EVOLUTION QUESTS ride in the same file (2026-09-30, Benny: "yes" to the game's text). Every
# evolutionQuestTemplate of the client game master displays one i18n key (display.description == display.title); the i18n file
# says what that key reads ('Defeat {0} Dark- or Steel-type Raid Bosses'). evolvable_forms._quest_text renders it with the goal's
# own number and falls back to a generated wording for a template the file lacks, so a stale file costs wording, never a label.
QUEST_MIN_TEMPLATES, QUEST_MIN_STRINGS = 20, 12       # refuse-to-shrink floors (2026-09-30: 37 evolution quests display 21 texts)


def _quest_templates(gm_path):
    """{template id: ([display keys, lowercased], the target of its one goal or None)} for every evolutionQuestTemplate of the
    client game master. Read-only."""
    gm = json.load(open(gm_path, encoding='utf-8'))
    out = {}
    for t in gm:
        q = ((t.get('data') or {}).get('evolutionQuestTemplate')) if isinstance(t, dict) else None
        if not isinstance(q, dict):
            continue
        d = q.get('display') or {}
        goals = q.get('goals') or []
        out[str(t.get('templateId') or q.get('questTemplateId'))] = (
            list(dict.fromkeys(str(d[k]).lower() for k in ('description', 'title') if d.get(k))),
            ((goals[0].get('target') or 1) if len(goals) == 1 else None))
    return out


def _build_quests(kv, gm_path, old):
    """The 'quests' section: the game's text for every i18n key an evolution quest displays, plus the OTHER number of each
    singular / plural pair (the Florges quests name the SINGULAR hearts text for goals of 20 and 7 and need the plural one).
    Sorted, nothing dated: the same two input files give the same bytes. Refuses a shrink like refresh_index does: fewer than
    QUEST_MIN_TEMPLATES quests in the game master, fewer than QUEST_MIN_STRINGS texts, or fewer texts than 90% of the committed
    section means a wrong or partial input file, and it must not strip the wording. -> (quests, template count, templates whose
    text the i18n file lacks, templates that show a singular text for a goal above 1)."""
    import evolvable_forms as ef
    tpl = _quest_templates(gm_path)
    if len(tpl) < QUEST_MIN_TEMPLATES:
        raise SystemExit('refusing to write: %s lists %d evolution quests (floor %d) -- the wrong or a partial game master?'
                         % (gm_path, len(tpl), QUEST_MIN_TEMPLATES))
    out, lost, plural = {}, [], []
    for tid in sorted(tpl):
        keys, n = tpl[tid]
        hit = [k for k in keys if str(kv.get(k, '')).strip()]
        if not hit:
            lost.append(tid)
        for k in hit:
            for x in ef.quest_keys(k):
                if str(kv.get(x, '')).strip():
                    out[x] = kv[x]
        if hit and n not in (None, 1) and re.search(r'_(single|singular)$', hit[0]):
            plural.append(tid)
    if len(out) < QUEST_MIN_STRINGS or (old and len(out) < 0.9 * len(old)):
        raise SystemExit('refusing to write: %d quest texts is a shrink (committed: %d; floor %d) -- the wrong i18n file?'
                         % (len(out), len(old or ()), QUEST_MIN_STRINGS))
    return {k: out[k] for k in sorted(out)}, len(tpl), lost, plural


def refresh_names(i18n, commit=None, out=None, gm=None, built=None):
    """Rebuild official_names_en.json: species + form names and the evolution-quest wording, ALL or nothing -- every refusal
    happens before the one atomic write. `gm` = the client game master (default gamemaster_pokeminers.json); `built` = the date
    stamped into _src (default today: a test passes one so two runs are byte-identical)."""
    out = out or pd.NAMES_PATH
    gm = gm or pd.GM_PATH
    d = json.load(open(i18n, encoding='utf-8'))['data']
    kv = dict(zip(d[0::2], d[1::2]))
    species = {int(k[13:]): v for k, v in kv.items() if re.fullmatch(r'pokemon_name_\d{4}', k) and int(k[13:]) > 0 and str(v).strip()}
    forms = {}
    for k in sorted(kv):
        if k.startswith('form_') and not re.match(r'form_(change|warn)', k) and str(kv[k]).strip():
            n = pd.norm(k[5:])
            if n in forms and forms[n] != kv[k]:
                print('note: %s collides after normalising (%r vs %r); the first key wins' % (k, forms[n], kv[k]))
            forms.setdefault(n, kv[k])
    for bad, good in KEY_FIXES.items():
        if bad in forms:
            forms.setdefault(good, forms[bad])
    if len(species) < 900 or len(forms) < 200:
        raise SystemExit('refusing to write: %d species / %d forms looks like the wrong file' % (len(species), len(forms)))
    if not os.path.exists(gm):
        raise SystemExit('refusing to write: no client game master at %s -- the quest wording is built from its evolutionQuestTemplate '
                         'entries (python tools/pogo_data.py pull, or --gm FILE)' % gm)
    try:
        old = json.load(open(out, encoding='utf-8')).get('quests') or {}
    except (OSError, ValueError, AttributeError):
        old = {}
    quests, n_tpl, lost, plural = _build_quests(kv, gm, old)
    src = 'PokeMiners/pogo_assets Texts/Latest APK/JSON/i18n_english.json%s, built %s' % ((' @ ' + commit) if commit else '', built or datetime.date.today().isoformat())
    text = json.dumps({'_src': src, 'species': {str(k): species[k] for k in sorted(species)}, 'forms': {k: forms[k] for k in sorted(forms)},
                       'quests': quests}, ensure_ascii=False, indent=0) + '\n'
    _atomic_text(out, text)
    print('wrote %s: %d species, %d forms, %d quest texts for %d evolution quests (%d KB)' % (
        out, len(species), len(forms), len(quests), n_tpl, len(text.encode('utf-8')) // 1024))
    for tid in lost:
        print('note: %s displays a text this i18n file does not have; the generated wording covers it' % tid)
    if plural:
        print('note: %d quest(s) name a singular text for a goal above 1 -- the plural text is used with their own number: %s' % (len(plural), ', '.join(plural)))
    return 0


def cull_log_names(page):
    """The names the page script draws into the cull log's 'Tagged for Transfer' column (DATA.passes), newest pass first, each
    once with its count: 'Spritzee, Minior (Green Core) x12, Ekans'. --text strips scripts, so a wrong label there (2026-10-24:
    'Minior (Green Plumage)') never reached the read before publishing. '' when the page carries no pass data."""
    i = page.find('const D = ')
    try:
        data = json.JSONDecoder().raw_decode(page, i + len('const D = '))[0] if i >= 0 else {}
    except ValueError:
        data = {}
    ct = collections.Counter()
    for p in (data.get('passes') or []) if isinstance(data, dict) else []:
        for t in re.sub(r' \.\.\.$', '', str(p.get('pile_list') or '')).split(', '):
            t = re.sub(r' \d+%(?: \(released\))?$', '', t.strip())
            if t:
                ct[t] += 1
    return ', '.join(n if c == 1 else '%s x%d' % (n, c) for n, c in ct.items())


def usage():
    print(__doc__)
    return 2


def main(argv):
    a = list(argv)

    def opt(name):
        if name in a:
            i = a.index(name)
            v = a[i + 1] if i + 1 < len(a) else None
            del a[i:i + 2]
            return v
        return None
    if a == ['--selftest']:
        return _selftest()
    if a and a[0] == '--text' and len(a) <= 2:
        # the page's visible words (tags, scripts, styles and data-URI pictures stripped): what the cull reads before it
        # publishes Bag Pulse; no FILE = the active account's page (2026-09-30, fewer cull steps)
        import account_guard
        p = a[1] if len(a) == 2 else os.path.join(HERE, 'system', 'analysis', 'collection_stats.html'
                                                  if account_guard.active() in (None, 'oyebenny') else 'bag_pulse_alt.html')
        s = raw = open(p, encoding='utf-8').read()
        for pat in (r'<script[\s\S]*?</script>', r'<style[\s\S]*?</style>', r'<[^>]+>'):
            s = re.sub(pat, ' ', s)
        print(os.path.basename(p) + ': ' + ' '.join(html.unescape(s).split()))
        names = cull_log_names(raw)
        if names:
            print('cull log names (drawn by the page script, newest pass first): ' + names)
        return 0
    if a and a[0] == '--refresh-index':
        a.pop(0)
        tree, clone, commit, committed = opt('--tree'), opt('--clone'), opt('--commit'), opt('--committed')
        return refresh_index(tree, clone, commit, committed) if not a and bool(tree) != bool(clone) else usage()
    if a and a[0] == '--refresh-names':
        a.pop(0)
        if any(f in a and a.index(f) == len(a) - 1 for f in ('--i18n', '--commit', '--gm')):
            return usage()                                 # a flag with no value is a guess, never a default
        i18n, commit, gm = opt('--i18n'), opt('--commit'), opt('--gm')
        return refresh_names(i18n, commit, gm=gm) if not a and i18n else usage()
    return usage()


# ============================================================================================================= self-test
def _selftest():
    """Offline, no DB, no phone, no network (urlopen and socket.connect are booby-trapped): the codec, the cache, the fetch
    policy, the matcher's golden cases, the names, the cards, the HTML and the kill switch. Wired into tools/triple_check.py
    and CI. A golden case that fails after a refresh of pogo_icon_index.txt usually means upstream added art: update it."""
    import random
    import shutil
    import socket
    import tempfile
    t0, bad, n = time.monotonic(), [], [0]

    def ck(cond, msg):
        n[0] += 1
        if not cond:
            bad.append(msg)

    def boom(*a, **k):
        raise AssertionError('the self-test touched the network')
    urllib.request.urlopen, socket.socket.connect = boom, boom

    tmp = tempfile.mkdtemp(prefix='bag_art_selftest_')
    try:
        _selftest_body(ck, tmp, random, os)
    except Exception as e:                                   # a crash inside a check is a failed check, with its traceback
        import traceback
        bad.append('crashed: %s\n%s' % (e, traceback.format_exc()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if bad:
        print('bag_art selftest FAILED (%d of %d checks):' % (len(bad), n[0]))
        for b in bad:
            print('  -', b)
        return 1
    print('bag_art selftest: ok (%d checks, %.1f s)' % (n[0], time.monotonic() - t0))
    return 0


def real_icons_names(ix):
    return sorted(ix.icons.values())


def _row(uid, dex, name, iv=40, cp=500, **kw):
    r = {'uid_hex': uid, 'pokemon_id': dex, 'species_name': name, 'form': 0, 'fresh_form': 0, 'fresh_costume': 0, 'fresh_shiny': 0,
         'gender': 1, 'fresh_alignment': 0, 'fresh_bread_mode': 0, 'pokemon_size_category': 3, 'is_lucky': 0, 'iv_total': iv, 'cp': cp,
         'fresh_has_location_card': 0, 'fresh_loc_card_enum': 0}
    r.update(kw)
    return r


def _fake_png(w=128, h=128, hue=0, rgb_bg=None):
    """A coloured disc inside a transparent margin (rgb_bg: an opaque background instead: a 'card')."""
    px = bytearray(w * h * 4)
    cx, cy, rad = w / 2, h / 2, w * 0.34
    col = ((hue * 67) % 200 + 40, (hue * 131) % 200 + 40, (hue * 29) % 200 + 40)
    for y in range(h):
        for x in range(w):
            o = (y * w + x) * 4
            if rgb_bg:
                px[o:o + 4] = bytes(rgb_bg + (255,))
            if (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad:
                px[o:o + 4] = bytes(col + (255,))
    return encode(w, h, px)


def _png_bytes(w, h, ct, bd, raw, il=0, plte=None, trns=None):
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (SIG + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, bd, ct, 0, 0, il)) + (chunk(b'PLTE', plte) if plte else b'')
            + (chunk(b'tRNS', trns) if trns else b'') + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _selftest_body(ck, tmp, random, os):
    P = os.path.join
    real = pd.IconIndex.load()
    ck(real.error is None and len(real.icons) > 3000 and len(real.cards) > 100, 'committed icon index unreadable: %s (%d icons)' % (real.error, len(real.icons)))
    ck(all(pd._SPRITE_OK.match(v) for v in real.icons.values()), 'an indexed icon name would not pass sprite_path validation')
    # ---- matcher: golden cases on the REAL committed index and enums

    def rw(dex, name, form=0, cos=0, g=1, sh=0):
        return _row('g', dex, name, form=form, fresh_form=form, fresh_costume=cos, gender=g, fresh_shiny=sh)
    gold = [
        ('Lechonk female', rw(915, 'Lechonk', 3231, g=2), 'pm915.icon.png', ()),
        ('Sudowoodo female', rw(185, 'Sudowoodo', 1202, g=2), 'pm185.g2.icon.png', ()),
        ("Galarian Farfetch'd", rw(83, "Farfetch'd", 2338), 'pm83.fGALARIAN.icon.png', ()),
        ("Galarian Farfetch'd shiny", rw(83, "Farfetch'd", 2338, sh=1), 'pm83.fGALARIAN.s.icon.png', ()),
        ('Galarian Mr. Mime', rw(122, 'Mr. Mime', 2339), 'pm122.fGALARIAN.icon.png', ()),
        ('Flabebe Yellow shiny', rw(669, 'Flab\u00e9b\u00e9', 2615, sh=1), 'pm669.fYELLOW.s.icon.png', ()),
        ('Raichu costume _2', rw(26, 'Raichu', 0, cos=28), 'pm26.cCOSTUME_2.icon.png', ()),
        ('Scatterbug pattern (no upstream art: update when it ships)', rw(664, 'Scatterbug', 2762), 'pm664.icon.png', ('form',)),
        ('Pikachu Diwali 2024 female (no .g2: update when it ships)', rw(25, 'Pikachu', 2850, g=2), 'pm25.fDIWALI_2024.icon.png', ('gender',)),
        ('Pikachu Holiday 2016 shiny female', rw(25, 'Pikachu', 0, cos=1, g=2, sh=1), 'pm25.cHOLIDAY_2016.g2.s.icon.png', ()),
        ('dex 1012 (no name in the game i18n either)', rw(1012, 'Poltchageist'), 'pm1012.icon.png', ()),
    ]
    for label, row, fn, dropped in gold:
        m = real.resolve(row)
        ck(m.fn == fn and m.dropped == dropped, 'golden %s: got %s %s, want %s %s' % (label, m.fn, m.dropped, fn, dropped))
    ck(real.resolve(rw(99999, 'Nothing')).dropped == ('species',) and real.resolve(rw(99999, 'Nothing')).fn is None, 'unknown species must say species')
    ck(real.resolve(rw(25, 'Pikachu', 987654)).dropped == ('form',), 'a form id the enum never heard of must flag the sprite')
    bad_dex = [(d, fn) for (d, *_r), fn in real.icons.items() if not fn.startswith('pm%d.' % d)]
    ck(not bad_dex, 'an icon is indexed under the wrong dex: %s' % bad_dex[:3])
    dex_ok = all(real.resolve(rw(d, 'X', f, cos, g, s)).fn is None or real.resolve(rw(d, 'X', f, cos, g, s)).fn.startswith('pm%d.' % d)
                 for d in sorted(real.dexes)[::37] for f in (0, 2338, 2615) for cos in (0, 28) for g in (1, 2) for s in (0, 1))
    ck(dex_ok, 'resolve() returned a file of another species')

    # ---- codec
    src = _fake_png(128, 128, hue=3)
    w, h, px = decode(src)
    ck((w, h) == (128, 128) and len(px) == 128 * 128 * 4, 'decode size')
    ck(encode(w, h, px) == encode(*decode(encode(w, h, px))), 'encode -> decode -> encode is not stable')
    b = bbox(w, h, px)
    ck(0 < b[0] < 64 < b[2] < 128 and 0 < b[1] < 64 < b[3] < 128, 'alpha box should be the disc, got %s' % (b,))
    cw, ch_, _cp = crop(w, h, px, b)
    ck(cw == b[2] - b[0] and ch_ == b[3] - b[1], 'crop size')
    t = thumb(src, SPRITE_PX)
    tw, th, tpx = decode(t)
    ck(max(tw, th) == SPRITE_PX, 'a 128 px sprite is cropped and scaled to a 72 px longest side, got %dx%d' % (tw, th))
    ck(png_ok(t, SPRITE_PX, SPRITE_MAX), 'a fresh thumbnail must pass png_ok')
    red = bytearray(64 * 64 * 4)
    for y in range(64):
        for x in range(64):
            if (x - 32) ** 2 + (y - 32) ** 2 <= 30 * 30:
                red[(y * 64 + x) * 4:(y * 64 + x) * 4 + 4] = bytes((255, 0, 0, 255))
    dw, dh, dpx = downscale(64, 64, red, 20)
    edge = [dpx[i:i + 4] for i in range(0, len(dpx), 4) if 0 < dpx[i + 3] < 255]
    ck(edge and all(e[0] >= 250 and e[1] <= 5 and e[2] <= 5 for e in edge), 'premultiplied downscale left a dark fringe')
    ck(downscale(10, 10, bytearray(400), 72)[:2] == (10, 10), 'downscale must never upscale')
    rgb_raw = b''.join(b'\x00' + bytes([200, 100, 50] * 4) for _ in range(4))
    ck(decode(_png_bytes(4, 4, 2, 8, rgb_raw))[2][:4] == bytes([200, 100, 50, 255]), 'RGB decode')
    pal_raw = b''.join(b'\x00' + bytes([1, 0, 1, 0]) for _ in range(4))
    pw, ph, ppx = decode(_png_bytes(4, 4, 3, 8, pal_raw, plte=bytes([9, 9, 9, 10, 20, 30]), trns=bytes([0, 128])))
    ck(bytes(ppx[:8]) == bytes([10, 20, 30, 128, 9, 9, 9, 0]), 'palette decode with tRNS')
    ck(bytes(decode(_png_bytes(4, 4, 6, 8, b''.join(b'\x00' + bytes(16) for _ in range(4))))[2][:4]) == bytes(4), 'rgba decode')
    for label, blob in (('16-bit', _png_bytes(2, 2, 6, 16, bytes(2 * (1 + 16)))), ('interlaced', _png_bytes(2, 2, 6, 8, bytes(2 * 9), il=1)),
                        ('truncated', src[:len(src) // 2]), ('garbage', b'not a png at all'), ('empty', b''),
                        ('transparent', encode(4, 4, bytearray(64)))):
        try:
            thumb(blob, SPRITE_PX)
            ck(False, '%s PNG must raise Unsupported' % label)
        except Unsupported:
            ck(True, '')
        except Exception as e:
            ck(False, '%s PNG raised %s instead of Unsupported' % (label, type(e).__name__))
    try:
        decode(_png_bytes(60000, 60000, 6, 8, b'x'))
        ck(False, 'a 60000 x 60000 header must be refused before anything is inflated')
    except Unsupported:
        ck(True, '')
    flip = bytearray(t)
    flip[len(flip) // 2] ^= 0xff
    ck(not png_ok(bytes(flip), SPRITE_PX, SPRITE_MAX) and not png_ok(t[:-9], SPRITE_PX, SPRITE_MAX), 'a corrupt / truncated thumbnail passed png_ok')
    card_src = _fake_png(200, 160, hue=5, rgb_bg=(20, 40, 60))
    ct = thumb(card_src, CARD_PX, crop_alpha=False, opaque_rgb=True)
    ck(ct[25] == 2 and png_ok(ct, CARD_PX, CARD_MAX), 'an opaque card is written as RGB (color type 2)')

    # ---- a fixture world: fake species, an offline cache with valid thumbnails for some of them
    names_fx = pd.Names(species={900: 'Alpha', 901: 'Beta', 902: 'Gamma', 903: 'Delta', 904: 'Epsilon'}, forms={},
                        form_enum={0: 'Unset'}, costume_enum={0: 'Unset', 5: 'Holiday2016'}, card_enum={7: 'LcSpecialbackgroundTeamRed', 8: 'Lc2026ChicagoGofest001', 9: 'LcNewer2027001'},
                        gm=[{'templateId': 'A', 'data': {'locationCardSettings': {'locationCard': 'LC_SPECIALBACKGROUND_TEAMRED', 'imageUrl': 'sb_TeamRed', 'cardType': 'SPECIAL_BACKGROUND'}}},
                            {'templateId': 'B', 'data': {'locationCardSettings': {'locationCard': 'LC_2026_CHICAGO_GOFEST_001', 'imageUrl': 'LC_2026_CHICAGO'}}},
                            {'templateId': 'C', 'data': {'pokemonSettings': {}}}])
    fx = pd.IconIndex(['pm%d.icon.png' % d for d in (900, 901, 902, 903)], ['sb_TeamRed', 'lc_2026_Chicago'], {0: 'Unset'}, {0: 'Unset', 5: 'Holiday2016'})
    cache_dir = P(tmp, 'cache')
    seed = Cache(cache_dir)
    for i, d in enumerate((900, 901, 902)):
        seed.write('s', 'pm%d.icon.png' % d, thumb(_fake_png(96, 96, hue=i + 1), SPRITE_PX))
    seed.write('c', 'sb_TeamRed', ct)
    pc = lambda iv_total: '%d%%' % round(iv_total / 45 * 100)      # iv_total is the 0-45 sum; the page shows a percent
    rows = [_row('u0', 900, 'Alpha', iv=44, cp=900), _row('u1', 900, 'Alpha', iv=30, cp=100), _row('u2', 901, 'Beta', fresh_shiny=1),
            _row('u3', 902, 'Gamma', fresh_has_location_card=1, fresh_loc_card_enum=7), _row('u4', 903, 'Delta'), _row('u5', 999, 'Nowhere'),
            _row('u6', 904, 'Epsilon', fresh_has_location_card=1, fresh_loc_card_enum=9)]
    uids = [r['uid_hex'] for r in rows]
    art = prepare(rows, uids, uids, cache_dir=cache_dir, offline=True, index=fx, names=names_fx, workers=0)
    ck(set(art.sprites) == {'pm900.icon.png', 'pm901.icon.png', 'pm902.icon.png', 'c:sb_TeamRed'}, 'embedded keys: %s' % sorted(art.sprites))
    ck(all(v.startswith('data:image/png;base64,') and png_ok(base64.b64decode(v.split(',', 1)[1]), SPRITE_PX, CARD_MAX) for v in art.sprites.values()),
       'every embedded value must be a small valid PNG data URI')
    ck(art.stats['embedded'] == 3 and art.stats['cards_embedded'] == 1 and art.stats['offline'] and art.stats['unavailable'] == 1, 'stats %s' % dict(art.stats))
    ck(art.sprite_key('u4') is None and art.sprite_key('u5') is None and art.match['u5'].dropped == ('species',), 'a missing sprite / species must have no key')
    doc = pile_card_html(art, rows, names_fx, gender_key=lambda pid, g: 1 if pid == 900 else 0)
    ck(doc.count('class="tile"') == 6, 'tiles: one per look (Alpha x2 share one): %d' % doc.count('class="tile"'))
    ck(doc.count('data-spr="pm900.icon.png"') == 1 and 'alt="Alpha"' in doc and 'width="48" height="48"' in doc, 'a tile carries its sprite key and its name as alt, once')
    ck(all('data-spr="%s"' % k[:] in doc or k.startswith('c:') for k in art.sprites) and 'data-spr="c:sb_TeamRed"' in doc, 'every embedded picture is referenced by its tile / card')
    ck('spr none' in doc and doc.count('spr none') == 3 and 'CP 500' in doc and pc(40) in doc, 'a tile with no picture keeps label, IV and CP with a letter placeholder')
    ck('Special Background' in doc and 'Team Red' in doc and 'Location Background' in doc and 'Newer2027' not in doc and 'Newer 2027' in doc,
       'card text: kind and humanised name, also without a picture')
    ck('\u2642' in doc and doc.index(pc(44)) < doc.index(pc(30)), 'sex sign where the injected rule says so; copies sorted best IV first')
    ck('spr none' in pile_card_html(prepare(rows, uids, uids, cache_dir=P(tmp, 'empty'), offline=True, index=fx, names=names_fx, workers=0), rows, names_fx),
       'an empty cache offline is a text page')
    # an approximate copy never shares a tile (or its 'approximate' flag) with an exact one: the mirror has no shiny Alpha, so the
    # shiny copy wears the plain file -- same file, same label, but its own dashed tile
    ax = [_row('x0', 900, 'Alpha', iv=40), _row('x1', 900, 'Alpha', iv=44, fresh_shiny=1)]
    aa = prepare(ax, ['x0', 'x1'], (), cache_dir=cache_dir, offline=True, index=fx, names=names_fx, workers=0)
    ah = pile_card_html(aa, ax, names_fx)
    ck(aa.match['x1'].dropped == ('shiny',) and aa.match['x0'].dropped == () and ah.count('class="tile"') == 2
       and ah.count('class="spr approx"') == 1 and ah.count('approximate: no shiny art') == 1 and 'no shiny sprite' in ah,
       'an approximate copy must get its own tile: %d tiles' % ah.count('class="tile"'))
    # the page carries the art stats but never a local path; the log line and the note say how old the icon index is
    f0 = P(tmp, 'afile0')
    open(f0, 'w').write('x')
    bc_art = prepare(rows, uids, (), cache_dir=f0, offline=True, index=fx, names=names_fx, workers=0)
    ps = bc_art.page_stats()
    ck(f0 in bc_art.stats['cache'] and 'cache' not in ps and ps['cache_ok'] is False and f0 not in json.dumps(ps)
       and art.page_stats()['cache_ok'] is True, 'DATA.art must not carry the cache path: %s' % ps)
    ck(index_age('2026-01-01', datetime.date(2026, 3, 1)) == 59 and index_age('junk') is None and index_age('') is None and index_age(None) is None, 'index_age')
    old_art, new_art = Art(), Art()
    old_art.stats['index'], old_art.stats['listed'] = '2020-01-01', '2020-01-02'
    new_art.stats['index'], new_art.stats['listed'] = '2020-01-01', datetime.date.today().isoformat()
    ck('days old' in art_note(old_art, []) and 'DAYS OLD' in old_art.line([]) and 'listed 2020-01-02' in old_art.line([])
       and 'days old' not in art_note(new_art, []) and 'DAYS OLD' not in new_art.line([]), 'a stale icon index is said so, a fresh one is not')
    ic_, cd_ = pd.split_listing([pd.ICON_DIR + 'pm25 x.icon.png', pd.ICON_DIR + 'pm25.icon.png', pd.ICON_DIR + 'pm26.f..icon.png', pd.CARD_DIR + 'a b.png',
                                 pd.CARD_DIR + 'ok_1.png', pd.CARD_DIR + 'a.b.png'])
    ck(ic_ == ['pm25.icon.png'] and cd_ == ['ok_1'], 'a listing name that would fail validation never enters the index: %s %s' % (ic_, cd_))

    # ---- a broken cache never crashes; the bad entries are simply not embedded
    afile = P(tmp, 'afile')
    open(afile, 'w').write('x')
    for label, cd in (('path is a file', afile), ('below a file', P(afile, 'sub'))):
        a2 = prepare(rows, uids, uids, cache_dir=cd, offline=True, index=fx, names=names_fx, workers=0)
        ck(not a2.sprites and not a2.stats['error'], 'cache %s: %s %s' % (label, a2.sprites.keys(), a2.stats['error']))
    bd = P(tmp, 'broken')
    Cache(bd)
    open(P(bd, SPRITE_SUB, 'pm900.icon.png'), 'wb').write(b'garbage bytes')
    open(P(bd, SPRITE_SUB, 'pm901.icon.png'), 'wb').write(t[:len(t) // 2])
    open(P(bd, SPRITE_SUB, 'pm902.icon.png'), 'wb').write(b'\x00' * (SPRITE_MAX + 5))
    open(P(bd, 'misses.json'), 'w').write('{not json')
    a3 = prepare(rows, uids, uids, cache_dir=bd, offline=True, index=fx, names=names_fx, workers=0)
    ck(not a3.sprites and not a3.stats['error'], 'garbage / truncated / oversize cached files must not be embedded: %s %s' % (list(a3.sprites), a3.stats['error']))
    ck(all(not os.path.exists(P(bd, SPRITE_SUB, 'pm90%d.icon.png' % i)) for i in range(3)), 'a bad cached file is removed')
    ck(prepare(None, None, None, cache_dir=bd, offline=True, workers=0).stats['error'] != '', 'garbage arguments are reported, not raised')
    real_replace = os.replace

    def deny(*a, **k):
        raise OSError('no space left')
    os.replace = deny
    try:
        ck(Cache(P(tmp, 'ro')).write('s', 'pm1.icon.png', t) is False and not [f for f in os.listdir(P(tmp, 'ro', SPRITE_SUB)) if f.endswith('.tmp')],
           'a failed write must return False and leave no .tmp file')
    finally:
        os.replace = real_replace

    # ---- page size is bounded whatever the pile
    big_dir = P(tmp, 'big')
    bc = Cache(big_dir)
    nz = random.Random(4)
    noisy = bytearray(72 * 72 * 4)
    for i in range(0, len(noisy), 8):
        noisy[i:i + 4] = bytes(nz.randrange(256) for _ in range(4))
        noisy[i + 3] = 255
    fat = encode(72, 72, noisy)
    ck(8000 < len(fat) <= SPRITE_MAX, 'fixture sprite is %d bytes' % len(fat))
    many = pd.IconIndex(['pm%d.icon.png' % d for d in range(2000, 2400)], [], {0: 'Unset'}, {0: 'Unset'})
    for d in range(2000, 2400):
        bc.write('s', 'pm%d.icon.png' % d, fat)
    brows = [_row('b%d' % d, d, 'Big%d' % d) for d in range(2000, 2400)]
    bn = pd.Names(species={d: 'Big%d' % d for d in range(2000, 2400)})
    ba = prepare(brows, [r['uid_hex'] for r in brows], (), cache_dir=big_dir, offline=True, index=many, names=bn, workers=0)
    ck(ba.stats['bytes'] <= SPRITE_BUDGET and 0 < ba.stats['embedded'] < 400 and ba.stats['over_budget'] == 400 - ba.stats['embedded'],
       '400 sprites: embedded %d, %d bytes, over budget %d' % (ba.stats['embedded'], ba.stats['bytes'], ba.stats['over_budget']))
    bh = pile_card_html(ba, brows, bn)
    ck(bh.count('class="tile"') == 400 and len(bh) + len(json.dumps(ba.sprites)) <= 1_200_000, 'tiles must not depend on the budget; page %d B' % (len(bh) + len(json.dumps(ba.sprites))))
    ck(len(pile_card_html(art, rows, names_fx)) + len(json.dumps(art.sprites)) < 250_000, 'a normal pile stays small')

    # ---- fetch policy: injected fetcher, fake clocks
    def fresh(name):
        return P(tmp, name)
    fetchable = pd.IconIndex(['pm%d.icon.png' % d for d in range(3000, 3100)], [], {0: 'Unset'}, {0: 'Unset'})
    frows = [_row('f%d' % d, d, 'F%d' % d) for d in range(3000, 3100)]
    fn_ = pd.Names(species={d: 'F%d' % d for d in range(3000, 3100)})
    fuids = [r['uid_hex'] for r in frows]
    good = _fake_png(64, 64, hue=2)
    calls = []

    def ok_fetch(url):
        calls.append(url)
        return good
    a4 = prepare(frows, fuids, (), cache_dir=fresh('c4'), offline=False, fetch=ok_fetch, index=fetchable, names=fn_, workers=0)
    ck(len(calls) == MAX_SPRITE_FETCH and a4.stats['capped'] == 20 and a4.stats['fetched'] == MAX_SPRITE_FETCH, 'the 81st distinct sprite is not fetched: %d calls, stats %s' % (len(calls), dict(a4.stats)))
    ck(all(u.startswith(pd.RAW + 'Images/Pokemon%20-%20256x256/Addressable%20Assets/pm3') for u in calls), 'fetch URLs: %s' % calls[:1])
    calls.clear()
    a5 = prepare(frows[:10], fuids[:10], (), cache_dir=fresh('c4'), offline=False, fetch=ok_fetch, index=fetchable, names=fn_, workers=0)
    ck(not calls and a5.stats['cached'] == 10 and a5.stats['embedded'] == 10, 'a warm cache fetches nothing')
    clock = [0.0]

    def slow(url):
        calls.append(url)
        clock[0] += 10
        return good
    calls.clear()
    a6 = prepare(frows[:20], fuids[:20], (), cache_dir=fresh('c6'), offline=False, fetch=slow, index=fetchable, names=fn_, workers=0, clock=lambda: clock[0])
    ck(len(calls) == 3 and a6.stats['unavailable'] == 17, 'the 25 s wall budget stops fetching: %d calls' % len(calls))
    calls.clear()

    def down(url):
        calls.append(url)
        raise NetError('no route')
    a7 = prepare(frows[:20], fuids[:20], (), cache_dir=fresh('c7'), offline=False, fetch=down, index=fetchable, names=fn_, workers=0)
    ck(len(calls) == BREAKER and a7.stats['offline'] == 'network' and not a7.sprites, 'breaker after %d network errors: %d calls, %s' % (BREAKER, len(calls), a7.stats['offline']))
    ck(not os.path.exists(P(fresh('c7'), 'misses.json')), 'network errors are never negative-cached')
    calls.clear()

    def gone(url):
        calls.append(url)
        raise NotFound(url)
    wall = [1_000_000.0]
    cd = fresh('c8')
    prepare(frows[:1], fuids[:1], (), cache_dir=cd, offline=False, fetch=gone, index=fetchable, names=fn_, workers=0, now=lambda: wall[0])
    prepare(frows[:1], fuids[:1], (), cache_dir=cd, offline=False, fetch=gone, index=fetchable, names=fn_, workers=0, now=lambda: wall[0] + 86400)
    ck(len(calls) == 1, '404 is negative-cached: %d calls' % len(calls))
    prepare(frows[:1], fuids[:1], (), cache_dir=cd, offline=False, fetch=gone, index=fetchable, names=fn_, workers=0, now=lambda: wall[0] + 8 * 86400)
    ck(len(calls) == 2, 'an expired 404 entry is retried')
    for label, exc in (('403', NetError('HTTP 403')), ('429', NetError('HTTP 429')), ('503', NetError('HTTP 503')), ('non-PNG 200', BadBody('not a PNG'))):
        cdx = fresh('c9' + label)

        def fx_(url, exc=exc):
            raise exc
        prepare(frows[:1], fuids[:1], (), cache_dir=cdx, offline=False, fetch=fx_, index=fetchable, names=fn_, workers=0)
        ck(not os.path.exists(P(cdx, 'misses.json')), '%s must not be negative-cached' % label)
    prepare(frows[:1], fuids[:1], (), cache_dir=fresh('c10'), offline=False, fetch=lambda u: b'<html>portal</html>', index=fetchable, names=fn_, workers=0)
    prepare(frows[:1], fuids[:1], (), cache_dir=fresh('c11'), offline=False, fetch=lambda u: b'\x89PNG\r\n\x1a\nbroken', index=fetchable, names=fn_, workers=0)
    mj = json.load(open(P(fresh('c11'), 'misses.json')))
    ck(mj and all(v['why'].startswith('undecodable') for v in mj.values()), 'an undecodable complete body is negative-cached for a day: %s' % mj)
    a12 = prepare(frows[:1], fuids[:1], (), cache_dir=fresh('c12'), offline=False, fetch=lambda u: (_ for _ in ()).throw(BadBody('oversize')), index=fetchable, names=fn_, workers=0, now=lambda: wall[0])
    ck(json.load(open(P(fresh('c12'), 'misses.json')))['s:pm3000.icon.png']['until'] == wall[0] + 30 * 86400, 'oversize is a 30-day negative entry')
    # threads: a hung fetch must not hold the caller past the wall budget
    def hang(url):
        time.sleep(30)
        return good
    th0 = time.monotonic()
    prepare(frows[:12], fuids[:12], (), cache_dir=fresh('c13'), offline=False, fetch=hang, index=fetchable, names=fn_, workers=6, wall_s=0.5)
    ck(time.monotonic() - th0 < 5, 'a hung socket blocked the caller for %.1f s' % (time.monotonic() - th0))
    a14 = prepare(frows[:12], fuids[:12], (), cache_dir=fresh('c14'), offline=False, fetch=ok_fetch, index=fetchable, names=fn_, workers=6)
    ck(a14.stats['fetched'] == 12 and a14.stats['embedded'] == 12, 'threaded fetch: %s' % dict(a14.stats))

    # ---- cards
    ci = names_fx.card_info(7)
    ck((ci.kind, ci.name, ci.image_url) == ('Special Background', 'Team Red', 'sb_TeamRed'), 'card 7 -> %s' % (ci,))
    ci = names_fx.card_info(8)
    ck((ci.kind, ci.name, ci.image_url) == ('Location Background', '2026 Chicago Gofest', 'LC_2026_CHICAGO'), 'card 8 (no cardType, plain name) -> %s' % (ci,))
    ck(fx.card_stem('LC_2026_CHICAGO') == 'lc_2026_Chicago' and fx.card_stem('sb_TeamRed') == 'sb_TeamRed' and fx.card_stem('sb_newer') == 'sb_newer', 'card stems: exact, case-insensitive, or as given')
    ck(fx.card_stem('a/b') is None and fx.card_stem('..') is None and fx.card_stem('a.b') is None and fx.card_stem('') is None, 'an imageUrl with a slash or dots is rejected')
    ci = names_fx.card_info(9)
    ck(ci.image_url is None and ci.kind == 'Location Background' and 'Newer 2027' == ci.name, 'a card the game master lacks: text only %s' % (ci,))
    ck(names_fx.card_info(77).name == 'Card #77' and names_fx.card_info(77).image_url is None, 'an id not in the enum')
    ck(pd.Names(card_enum={4: 'LcSpecialbackgroundOld'}, gm=[]).card_info(4).kind == 'Special Background', 'a SPECIAL name with no cardType is a Special Background')
    ck(pd.card_id(_row('x', 1, 'X', fresh_has_location_card=0, fresh_loc_card_enum=7)) == 0 and pd.card_id(_row('x', 1, 'X', fresh_has_location_card=1, fresh_loc_card_enum=7)) == 7,
       'a stale fresh_loc_card_enum without fresh_has_location_card gets no card')
    ck(art.cards['u3'][1] == 'c:sb_TeamRed' and art.cards['u6'][1] is None, 'card thumbnail embedded when cached, text otherwise')
    # cards fetched: fixture GM -> stem -> CARD_DIR path, thumbnail written to c64
    calls.clear()
    Cache(fresh('c15')).write('s', 'pm902.icon.png', thumb(_fake_png(96, 96, hue=9), SPRITE_PX))

    def card_fetch(url):
        calls.append(url)
        return card_src
    a15 = prepare([rows[3]], ['u3'], ['u3'], cache_dir=fresh('c15'), offline=False, fetch=card_fetch, index=fx, names=names_fx, workers=0)
    ck(calls == [pd.RAW + 'Images/LocationCards/sb_TeamRed.png'] and a15.cards['u3'][1] == 'c:sb_TeamRed' and os.path.exists(P(fresh('c15'), CARD_SUB, 'sb_TeamRed.png')),
       'card fetch: %s %s' % (calls, a15.cards))

    # ---- names: real committed official_names_en.json, the enums, the fallbacks
    nm = pd.Names.load()
    ck(nm.on and nm.error is None and len(nm.species_map) > 900 and len(nm.forms) > 200, 'official_names_en.json unreadable: %s' % nm.error)
    fid = {v: k for k, v in nm.form_enum.items()}

    def lab(dex, name, form=None, **kw):
        return nm.label(_row('n', dex, name, form=fid.get(form, 0), fresh_form=fid.get(form, 0), **kw))
    ck(lab(29, 'Nidoran F') == 'Nidoran\u2640' and lab(32, 'Nidoran M') == 'Nidoran\u2642', 'Nidoran signs')
    ck(lab(122, 'Mr. Mime') == 'Mr. Mime' and lab(83, "Farfetch'd") == "Farfetch'd" and lab(250, 'Ho-Oh') == 'Ho-Oh' and lab(669, 'Flab\u00e9b\u00e9') == 'Flab\u00e9b\u00e9', 'punctuation names')
    ck(lab(1012, 'Poltchageist') == 'Poltchageist', 'a dex the game i18n lacks keeps the DB name')
    ck(lab(83, "Farfetch'd", 'FarfetchdGalarian') == "Galarian Farfetch'd" and lab(19, 'Rattata', 'RattataAlola') == 'Alolan Rattata', 'regional adjective')
    ck(lab(351, 'Castform', 'CastformRainy') == 'Castform (Rainy Form)', 'official form text')
    ck(lab(479, 'Rotom', 'RotomWash') == 'Wash Rotom', 'text that already names the species is used alone')
    ck(lab(128, 'Tauros', 'TaurosPaldeaAqua') == 'Paldean Tauros (Aqua Breed)', 'regional + official form text')
    ck(lab(555, 'Darmanitan', 'DarmanitanGalarianZen') == 'Galarian Darmanitan (Zen Mode)', 'species-qualified key under a regional prefix: %s' % lab(555, 'Darmanitan', 'DarmanitanGalarianZen'))
    ck(lab(664, 'Scatterbug', 'ScatterbugSun') == 'Scatterbug (Sun Pattern)' and lab(413, 'Wormadam', 'WormadamPlant') == 'Wormadam (Plant Cloak)',
       'a form keyed under the family\'s showcase species: %s / %s' % (lab(664, 'Scatterbug', 'ScatterbugSun'), lab(413, 'Wormadam', 'WormadamPlant')))
    ck(pd.humanize('Flying5ThAnniv') == 'Flying 5th Anniv' and pd.humanize('IcySnow') == 'Icy Snow' and pd.humanize('Holiday2016') == 'Holiday 2016', 'humanize')
    ck(lab(201, 'Unown', 'UnownA') == 'Unown (A)' and lab(25, 'Pikachu', 'PikachuNormal') == 'Pikachu' and lab(25, 'Pikachu') == 'Pikachu', 'humanised fallback / plain forms')
    ck(lab(931, 'Squawkabilly', 'SquawkabillyWhite') == 'Squawkabilly (White Plumage)', 'the typo\'d upstream key is fixed by the builder: %s' % lab(931, 'Squawkabilly', 'SquawkabillyWhite'))
    gn = pd.Names(species={931: 'Squawkabilly', 646: 'Kyurem'}, forms={'white': 'White Kyurem', 'kyuremwhite': 'White Kyurem'},
                  form_enum={0: 'Unset', 1: 'SquawkabillyWhite', 2: 'KyuremWhite'})
    ck(gn.label(_row('n', 931, 'Squawkabilly', form=1, fresh_form=1)) == 'Squawkabilly (White)', 'a species-less form key must not lend another species\' name')
    ck(gn.label(_row('n', 646, 'Kyurem', form=2, fresh_form=2)) == 'White Kyurem', 'a species-qualified key naming its own species is used alone')
    # 2026-10-24: a green-core Minior read 'Minior (Green Plumage)' -- the species-less form_green is Squawkabilly's
    mi = {k: lab(774, 'Minior', k) for k in fid if k.startswith('Minior')}
    ck(mi.get('MiniorGreen') == 'Minior (Green Core)' and mi.get('MiniorMeteorBlue') == 'Minior (Blue Meteor)' and mi.get('MiniorMeteor') == 'Minior (Meteor Form)'
       and len(mi) >= 15 and all(re.fullmatch(r'Minior \((?:[A-Z][a-z]+ (?:Core|Meteor)|Meteor Form)\)', t) for t in mi.values()), 'every Minior form wears its own words: %s' % mi)
    ck(lab(931, 'Squawkabilly', 'SquawkabillyGreen') == 'Squawkabilly (Green Plumage)', 'the plumage stays Squawkabilly\'s: %s' % lab(931, 'Squawkabilly', 'SquawkabillyGreen'))
    cf = [k for k in fid if k.startswith('Pikachu') and re.search(r'20\d\d', k)]
    if cf:
        ck(lab(25, 'Pikachu', cf[0]) == 'Pikachu' and nm.costume_bits(_row('n', 25, 'Pikachu', form=fid[cf[0]], fresh_form=fid[cf[0]])), 'a form-encoded costume stays out of the name and becomes a chip')
    ck(nm.costume_bits(_row('n', 26, 'Raichu', fresh_costume=28)) == ['Costume 2'] and nm.costume_bits(_row('n', 25, 'Pikachu', fresh_costume=1)) == ['Holiday 2016'], 'costume chips')
    ck(nm.fix_stamped('Nidoran F 71%') == 'Nidoran\u2640 71%' and nm.fix_stamped('Snorlax 40%') == 'Snorlax 40%' and nm.fix_stamped('') == '' and nm.fix_stamped('Nidoran Fx 1%') == 'Nidoran Fx 1%',
       'fix_stamped maps the DB prefix only')
    mm = pd.Names.load(path=P(tmp, 'no_such.json'))
    ck(not mm.on and mm.error and mm.label(_row('n', 122, 'Mr. Mime')) == 'Mr. Mime' and mm.species(29, 'Nidoran F') == 'Nidoran F' and mm.fix_stamped('Nidoran F 7%') == 'Nidoran F 7%', 'missing names file -> every call falls back')
    open(P(tmp, 'bad.json'), 'w').write('{"species": 5')
    ck(not pd.Names.load(path=P(tmp, 'bad.json')).on and not pd.Names.empty().on and pd.Names.empty().label(_row('n', 1, 'X')) == 'X', 'corrupt names file -> empty')
    chips = pd.look_chips(_row('c', 1, 'X', fresh_shiny=1, fresh_alignment=1, fresh_bread_mode=2, pokemon_size_category=5, is_lucky=1), nm)
    ck([c[0] for c in chips] == ['shiny', 'shadow', 'Gigantamax', 'XXL', 'lucky'], 'look chips: %s' % chips)

    # ---- html safety and the kill switch
    evil = '</script><img src=x onerror=alert(1)>"&'
    en = pd.Names(species={950: evil})
    er = [_row('e1', 950, evil)]
    ea = Art()
    eh = pile_card_html(ea, er, en)
    ck('<script' not in eh and '<img src=x' not in eh and '&lt;/script&gt;' in eh and '&quot;' in eh, 'labels must be escaped in text and alt')
    tpl = '<style>a{}\n__ART_CSS__</style>\n<div class="grid">\n    __PILE_CARD__<div class="card">x</div>\n<script>\nconst D = __DATA__;\n__ART_JS__const y = 1;\ncell = __PILE_CELL__;\n</script>'
    page = assemble(tpl, {'n': evil, 'spr': {}}, art, eh)
    ck('</script><img' not in page and page.count('</script>') == 1 and '\\u003c/script' in page and not re.search(r'__(DATA|ART_CSS|PILE_CARD|ART_JS|PILE_CELL)__', page), 'DATA JSON must never close the script element; no hook may be left')
    ck('pileCell' in page and 'id="pile_card"' in page and '.tiles{' in page and 'querySelectorAll' in page, 'art hooks filled when on')
    cl = '<script>\nconst D = {"passes": [{"pile_list": "Minior (Green Core) 11%, Taillow 89%"}, {"pile_list": "Minior (Green Core) 40%, Ekans 18% (released) ..."}]};\n</script>'
    ck(cull_log_names(cl) == 'Minior (Green Core) x2, Taillow, Ekans' and cull_log_names(page) == '' and cull_log_names('x') == '',
       '--text names the cull log the page script draws: %r' % cull_log_names(cl))
    off = assemble(tpl, {'a': 1}, None, '', on=False)
    ck(off == '<style>a{}\n</style>\n<div class="grid">\n    <div class="card">x</div>\n<script>\nconst D = {"a": 1};\nconst y = 1;\ncell = p.pile_list;\n</script>',
       'the kill switch leaves the template byte for byte as it was: %r' % off)
    ck(enabled() == (os.environ.get('BAG_ART', '1') != '0'), 'enabled() follows BAG_ART')
    bogus = pd.Names.empty()
    ck(pile_card_html(Art(), [], bogus).count('Nothing is tagged') == 1, 'an empty pile says so')
    # ---- maintenance commands: a saved listing round-trips, a shrink or a truncated listing is refused, nothing touches the committed files
    import io
    quiet, saved_out = io.StringIO(), sys.stdout

    def run_quiet(fn, *a, **k):
        sys.stdout = quiet
        try:
            return fn(*a, **k)
        finally:
            sys.stdout = saved_out
    full = [pd.ICON_DIR + n for n in real_icons_names(real)] + [pd.CARD_DIR + c + '.png' for c in sorted(real.cards)] + ['Images/Other/x.png', pd.ICON_DIR + 'pm1.portrait.png', pd.ICON_DIR + 'sub/pm2.icon.png']
    ic, cd = pd.split_listing(full)
    ck(len(ic) == len(real_icons_names(real)) and len(cd) == len(real.cards), 'split_listing keeps only real icons and card stems: %d %d' % (len(ic), len(cd)))
    lst = P(tmp, 'listing.txt')
    open(lst, 'w').write('\n'.join(full) + '\n')
    out_ix = P(tmp, 'index_out.txt')
    ck(run_quiet(refresh_index, tree=lst, commit='abc123', committed='2026-01-02', out=out_ix) == 0, 'refresh_index from a saved listing')
    i2, c2, m2, e2 = pd.read_index(out_ix)
    ck(sorted(i2) == sorted(real_icons_names(real)) and sorted(c2) == sorted(real.cards) and m2.get('commit') == 'abc123' and m2.get('committed') == '2026-01-02' and e2 is None,
       'the written index reads back as it was: %d icons, meta %s' % (len(i2), m2))

    def refused(**kw):
        try:
            run_quiet(refresh_index, out=out_ix, **kw)
            return False
        except SystemExit as e:
            return 'refusing' in str(e) or 'TRUNCATED' in str(e)
    small = P(tmp, 'small.txt')
    open(small, 'w').write('\n'.join(pd.ICON_DIR + 'pm%d.icon.png' % d for d in range(1, 11)))
    ck(refused(tree=small), 'a 10-icon listing must be refused (floor 3,000)')
    part = P(tmp, 'part.txt')
    open(part, 'w').write('\n'.join(full[:len(full) * 3 // 4]))
    ck(refused(tree=part), 'a listing 25% smaller than the committed index must be refused')
    trunc = P(tmp, 'trunc.json')
    json.dump({'sha': 'f' * 40, 'truncated': True, 'tree': [{'path': f, 'type': 'blob'} for f in full]}, open(trunc, 'w'))
    ck(refused(tree=trunc), 'a truncated trees-API listing must be refused')
    okjson = P(tmp, 'ok.json')
    json.dump({'sha': 'f' * 40, 'truncated': False, 'tree': [{'path': f, 'type': 'blob'} for f in full] + [{'path': 'Images', 'type': 'tree'}]}, open(okjson, 'w'))
    ck(run_quiet(refresh_index, tree=okjson, out=out_ix) == 0 and pd.read_index(out_ix)[2].get('commit') == 'tree-' + 'f' * 12, 'a complete trees-API listing is accepted, its tree sha stamped')
    # ---- the game's own words for the evolution quests (2026-09-30): templates shaped like the client game master's, the texts like
    # the game's i18n_english.json (committed reference = the same strings, rebuilt by refresh_names)
    import evolvable_forms as ef
    QTXT = {'challenge_buddy_affection_plural': 'Earn {0} hearts with your buddy', 'challenge_buddy_affection_single': 'Earn a heart with your buddy',
            'challenge_buddy_treat_plural': 'Give your buddy {0} treats', 'challenge_buddy_treat_single': 'Give your buddy a treat',
            'quest_buddy_walk_km_plural': 'Walk {0} km with your buddy',
            'quest_catch_type_dark_plural': 'Catch {0} Dark-type Pok\xe9mon', 'quest_catch_type_dark_singular': 'Catch a Dark-type Pok\xe9mon',
            'quest_defeat_dark_or_steel_type_raid': 'Defeat {0} Dark- or Steel-type Raid Bosses',
            'quest_defeat_dark_type_raid_and_max_battle': 'Defeat {0} Dark-type Pok\xe9mon in raids or Max Battles',
            'quest_defeat_water_type_raid_and_max_battle': 'Defeat {0} Water-type Pok\xe9mon in raids or Max Battles',
            'quest_fight_type_ghost_psychic_plural': 'Defeat {0} Psychic- or Ghost-type Pok\xe9mon',
            'quest_incense_plural': 'Use {0} Incense', 'quest_incense_singular': 'Use an Incense',
            'quest_land_excellent_plural': 'Make {0} Excellent Throws', 'quest_land_excellent_singular': 'Make an Excellent Throw',
            'quest_win_raid_plural': 'Win {0} raids', 'quest_win_raid_singular': 'Win a raid'}

    def qtpl(tid, qtype, n, key, *conds):
        return {'templateId': tid, 'data': {'templateId': tid, 'evolutionQuestTemplate': {
            'questTemplateId': tid, 'questType': qtype, 'goals': [dict({'target': n}, **({'condition': list(conds)} if conds else {}))],
            'context': 'EVOLUTION_QUEST', 'display': {'description': key, 'title': key}}}}
    ctype = lambda t: {'type': 'WITH_POKEMON_TYPE', 'withPokemonType': {'pokemonType': ['POKEMON_TYPE_' + x for x in t]}}
    cfight = lambda t: {'type': 'WITH_OPPONENT_POKEMON_BATTLE_STATUS', 'withOpponentPokemonBattleStatus': {'requireDefeat': True, 'opponentPokemonType': ['POKEMON_TYPE_' + x for x in t]}}
    ccomb = lambda c: {'type': 'WITH_COMBAT_TYPE', 'withCombatType': {'combatType': ['COMBAT_TYPE_' + x for x in c]}}
    cwin, craid, cthrow = {'type': 'WITH_WIN_BATTLE_STATUS'}, {'type': 'WITH_WIN_RAID_STATUS'}, {'type': 'WITH_THROW_TYPE', 'withThrowType': {'throwType': 'ACTIVITY_CATCH_EXCELLENT_THROW'}}
    HEARTS, WALK = 'QUEST_BUDDY_EARN_AFFECTION_POINTS', 'QUEST_BUDDY_EVOLUTION_WALK'
    # (what it is, the template, the game's text, the generated wording when the game's text is not on file)
    gold_q = [
        ("Sirfetch'd: Excellent (the old 'land throw 10 times' dropped it)", qtpl('SIRFETCHD_EVOLUTION_QUEST', 'QUEST_LAND_THROW', 10, 'quest_land_excellent_plural', cthrow),
         'Make 10 Excellent Throws', 'Make 10 Excellent Throws'),
        ("Bisharp: defeat the raid BOSSES (the old text read as raids won WITH Dark/Steel mons)", qtpl('BISHARP_KINGAMBIT_EVOLUTION_QUEST', 'QUEST_COMPLETE_BATTLE', 15, 'quest_defeat_dark_or_steel_type_raid', cwin, ccomb(['RAID']), ctype(['DARK', 'STEEL'])),
         'Defeat 15 Dark- or Steel-type Raid Bosses', 'Defeat 15 Dark- or Steel-type Raid Bosses'),
        ("Kubfu Rapid Strike: raids OR Max Battles (the old text said raids only)", qtpl('KUBFU_RAPID_STRIKE_EVOLUTION_QUEST', 'QUEST_COMPLETE_BATTLE', 30, 'quest_defeat_water_type_raid_and_max_battle', cwin, ccomb(['RAID', 'DMAX', 'GMAX']), ctype(['WATER'])),
         'Defeat 30 Water-type Pok\xe9mon in raids or Max Battles', 'Defeat 30 Water-type Pok\xe9mon in raids or Max Battles'),
        ("Kubfu Single Strike", qtpl('KUBFU_SINGLE_STRIKE_EVOLUTION_QUEST', 'QUEST_COMPLETE_BATTLE', 30, 'quest_defeat_dark_type_raid_and_max_battle', cwin, ccomb(['RAID', 'DMAX', 'GMAX']), ctype(['DARK'])),
         'Defeat 30 Dark-type Pok\xe9mon in raids or Max Battles', 'Defeat 30 Dark-type Pok\xe9mon in raids or Max Battles'),
        ("Overqwil: WIN raids (the old text said 'complete raid battle 10 times')", qtpl('OVERQWIL_EVOLUTION_QUEST', 'QUEST_COMPLETE_RAID_BATTLE', 10, 'quest_win_raid_plural', craid), 'Win 10 raids', 'Win 10 raids'),
        ("Runerigus", qtpl('RUNERIGUS_EVOLUTION_QUEST', 'QUEST_COMPLETE_RAID_BATTLE', 10, 'quest_win_raid_plural', craid), 'Win 10 raids', 'Win 10 raids'),
        ("Florges: the SINGULAR hearts key on a goal of 20 must say 20 hearts", qtpl('FLORGES_EVOLUTION_QUEST', HEARTS, 20, 'CHALLENGE_BUDDY_AFFECTION_SINGLE'), 'Earn 20 hearts with your buddy', 'Earn 20 hearts with your buddy'),
        ("Sylveon: the same key on a goal of 70", qtpl('SYLVEON_EVOLUTION_QUEST', HEARTS, 70, 'CHALLENGE_BUDDY_AFFECTION_SINGLE'), 'Earn 70 hearts with your buddy', 'Earn 70 hearts with your buddy'),
        ("Sylveon Community Day: a goal of 7", qtpl('SYLVEON_CD_EVOLUTION_QUEST', HEARTS, 7, 'CHALLENGE_BUDDY_AFFECTION_SINGLE'), 'Earn 7 hearts with your buddy', 'Earn 7 hearts with your buddy'),
        ("Snom: the plural key (the old 'earn hearts with 10 times')", qtpl('SNOM_FROSMOTH_EVOLUTION_QUEST', HEARTS, 10, 'CHALLENGE_BUDDY_AFFECTION_PLURAL'), 'Earn 10 hearts with your buddy', 'Earn 10 hearts with your buddy'),
        ("a singular key on a goal of 1 keeps the singular text", qtpl('X_EVOLUTION_QUEST', HEARTS, 1, 'CHALLENGE_BUDDY_AFFECTION_SINGLE'), 'Earn a heart with your buddy', 'Earn a heart with your buddy'),
        ("Swirlix (the old 'feed 25 times')", qtpl('SWIRLIX_EVOLUTION_QUEST', 'QUEST_BUDDY_FEED', 25, 'CHALLENGE_BUDDY_TREAT_PLURAL'), 'Give your buddy 25 treats', 'Give your buddy 25 treats'),
        ("Spritzee (the old 'use incense 1 times')", qtpl('SPRITZEE_EVOLUTION_QUEST', 'QUEST_USE_INCENSE', 1, 'quest_incense_singular'), 'Use an Incense', 'Use an Incense'),
        ("Sudowoodo: walk with your buddy", qtpl('SUDOWOODO_EVOLUTION_QUEST', WALK, 15, 'quest_buddy_walk_km_plural'), 'Walk 15 km with your buddy', 'Walk 15 km with your buddy'),
        ("Swoobat: a km gate of 1 stays 1 km", qtpl('SWOOBAT_EVOLUTION_QUEST', WALK, 1, 'quest_buddy_walk_km_plural'), 'Walk 1 km with your buddy', 'Walk 1 km with your buddy'),
        ("Annihilape: the game lists its types Psychic, Ghost", qtpl('ANNIHILAPE_EVOLUTION_QUEST', 'QUEST_FIGHT_POKEMON', 30, 'quest_fight_type_ghost_psychic_plural', cfight(['GHOST', 'PSYCHIC'])),
         'Defeat 30 Psychic- or Ghost-type Pok\xe9mon', 'Defeat 30 Ghost- or Psychic-type Pok\xe9mon'),
        ("a plural key on a goal of 1 takes the game's singular text", qtpl('Y_EVOLUTION_QUEST', 'QUEST_CATCH_POKEMON', 1, 'quest_catch_type_dark_plural', ctype(['DARK'])),
         'Catch a Dark-type Pok\xe9mon', 'Catch 1 Dark-type Pok\xe9mon'),
    ]
    fake_i18n = P(tmp, 'i18n.json')
    kvs = []
    for d in range(1, 951):
        kvs += ['pokemon_name_%04d' % d, 'Mon%d' % d]
    for k in range(260):
        kvs += ['form_x%d_y' % k, 'Form %d' % k]
    kvs += ['form_squakabilly_white', 'White Plumage', 'form_change_button', 'Change', 'form_warn_x', 'Warn', 'form_normal', ' ', 'pokemon_name_0025_0001', 'Mega X']
    for k_, v_ in sorted(QTXT.items()):
        kvs += [k_, v_]
    kvs += ['quest_spin_unreferenced_plural', 'Spin {0} PokeStops', 'quest_blank_plural', '  ']            # decoys: no template displays them
    json.dump({'data': kvs}, open(fake_i18n, 'w'))
    fake_gm = P(tmp, 'gm.json')
    tpls = [t_ for _w, t_, _g, _f in gold_q] + [qtpl('FILL%d_EVOLUTION_QUEST' % i, WALK, i + 1, 'quest_buddy_walk_km_plural') for i in range(8)]
    tpls += [{'templateId': 'V0001_POKEMON_BULBASAUR', 'data': {'pokemonSettings': {'pokemonId': 'BULBASAUR'}}}]
    json.dump(tpls, open(fake_gm, 'w'))
    out_nm = P(tmp, 'names_out.json')
    ck(run_quiet(refresh_names, fake_i18n, out=out_nm, gm=fake_gm, built='2026-01-01') == 0, 'refresh_names from an i18n file and a game master')
    nn = pd.Names.load(path=out_nm)
    ck(nn.on and nn.species(25, '') == 'Mon25' and len(nn.species_map) == 950 and 'x3y' in nn.forms and 'squawkabillywhite' in nn.forms
       and 'changebutton' not in nn.forms and 'warnx' not in nn.forms and 'normal' not in nn.forms, 'names file: species, forms, the typo fix, no UI strings, no blank text')
    try:
        run_quiet(refresh_names, small, out=out_nm)
        ck(False, 'a wrong file must be refused by refresh_names')
    except (SystemExit, ValueError, KeyError):
        ck(True, '')
    # ---- the 'quests' section: exactly the texts the game master's quests display + the other number of each pair, sorted, byte-reproducible
    b1 = open(out_nm, 'rb').read()
    q1 = json.loads(b1.decode('utf-8'))['quests']
    ck(q1 == QTXT and list(q1) == sorted(q1), 'quests section: every displayed text and its pair sibling, no decoy, sorted: %s' % sorted(set(q1) ^ set(QTXT)))
    ck('quest_spin_unreferenced_plural' not in q1 and 'quest_blank_plural' not in q1, 'an i18n text no quest displays (or a blank one) is not stored')
    run_quiet(refresh_names, fake_i18n, out=out_nm, gm=fake_gm, built='2026-01-01')
    ck(open(out_nm, 'rb').read() == b1 and b1.endswith(b'\n') and b'\r' not in b1, 'the refresh is byte-reproducible (same inputs, same bytes, LF)')
    ck(pd.Names.load(path=out_nm).on, 'Names.load ignores the quests section and still loads the names')
    ck(all(ef._quest_text(t_['data']['evolutionQuestTemplate'], q1) == want for _w, t_, want, _f in gold_q),
       'every golden template reads as the game words it from the file the refresh just wrote')

    def refuses(outp, **kw):
        before = open(outp, 'rb').read()
        try:
            run_quiet(refresh_names, fake_i18n, out=outp, built='2026-01-01', **kw)
            return False
        except SystemExit as e:
            return 'refusing' in str(e) and open(outp, 'rb').read() == before
    gm_few, gm_far, big = P(tmp, 'gm_few.json'), P(tmp, 'gm_far.json'), P(tmp, 'names_big.json')
    json.dump(tpls[:5], open(gm_few, 'w'))
    json.dump([qtpl('FAR%d_EVOLUTION_QUEST' % i, 'QUEST_CATCH_POKEMON', 5, 'quest_not_in_i18n_%d' % i) for i in range(25)], open(gm_far, 'w'))
    json.dump({'quests': {'k%d' % i: 'v' for i in range(40)}}, open(big, 'w'))
    ck(refuses(out_nm, gm=gm_few), 'a game master with 5 evolution quests is refused (floor %d), nothing written' % QUEST_MIN_TEMPLATES)
    ck(refuses(out_nm, gm=P(tmp, 'nope.json')), 'a missing game master is refused, nothing written')
    ck(refuses(out_nm, gm=gm_far), 'quests whose texts the i18n file lacks (0 texts) are refused as a shrink, nothing written')
    ck(refuses(big, gm=fake_gm), 'fewer quest texts (17) than 90% of the committed 40 is refused as a shrink, nothing written')
    # ---- how the wording is read: the game's text, the number agreement, and a generated fallback that is still TRUE
    qref = ef._quest_ref()
    ck(len(qref) >= QUEST_MIN_STRINGS and all(v.strip() and set(re.findall(r'\{\d+\}', v)) <= {'{0}'} for v in qref.values()),
       'the committed quests section is readable: %d texts, placeholders {0} only' % len(qref))
    for what, t_, want, gen in gold_q:
        q_ = t_['data']['evolutionQuestTemplate']
        ck(ef._quest_text(q_) == want, '%s: the game\'s words %r, got %r' % (what, want, ef._quest_text(q_)))
        ck(ef._quest_text(q_, {}) == gen, '%s: the generated fallback %r, got %r' % (what, gen, ef._quest_text(q_, {})))
    florges = gold_q[6][1]['data']['evolutionQuestTemplate']
    only_single = {'challenge_buddy_affection_single': QTXT['challenge_buddy_affection_single']}
    ck(ef._game_words('challenge_buddy_affection_single', 20, only_single) is None and ef._quest_text(florges, only_single) == 'Earn 20 hearts with your buddy',
       'a singular text is never used for a goal of 20 (no plural on file -> the generated wording)')
    ck(ef._game_words('k_plural', 3, {'k_plural': 'Win {0} of {1}'}) is None, 'a text with another placeholder is refused')
    ck(ef._quest_text({'questType': 'QUEST_BUDDY_PET', 'goals': [{'target': 5}]}, {}) == 'Play with your buddy 5 times', 'fallback: play with your buddy')
    ck(ef._quest_text({'questType': 'QUEST_CATCH_POKEMON', 'goals': [{'target': 5, 'condition': [ctype(['DARK']), {'type': 'WITH_DAILY_STREAK'}]}]}, {})
       == 'Catch 5 Dark-type Pok\xe9mon (also: daily streak)', 'a condition the fallback does not model is NAMED, never dropped')
    ck(ef._quest_text({'questType': 'QUEST_SPIN_POKESTOP', 'goals': [{'target': 7, 'condition': [{'type': 'WITH_FRIEND'}]}]}, {}) == 'spin pokestop 7 times (also: friend)',
       'an unknown quest type keeps its number and its conditions')
    ck(ef._quest_text({'questType': 'QUEST_COMPLETE_RAID_BATTLE', 'goals': [{'target': 4}]}, {}) == 'Complete 4 raids', 'without a win condition a raid quest says Complete, not Win')
    two = {'questType': 'QUEST_CATCH_POKEMON', 'display': {'description': 'quest_catch_type_dark_plural'},
           'goals': [{'target': 3, 'condition': [ctype(['DARK'])]}, {'target': 4, 'condition': [ctype(['FIRE'])]}]}
    ck(ef._quest_text(two) == 'Catch 3 Dark-type Pok\xe9mon; Catch 4 Fire-type Pok\xe9mon', 'a template with several goals is worded goal by goal, never by the one text')
    ck(ef._quest_text({'questType': 'QUEST_CATCH_POKEMON', 'display': {'description': 'quest_not_in_the_file'}, 'goals': [{'target': 9, 'condition': [ctype(['ICE'])]}]})
       == 'Catch 9 Ice-type Pok\xe9mon', 'a key the file lacks falls back to the generated wording')
    ck(all(isinstance(ef._quest_text(j), str) for j in (None, {}, {'goals': None}, {'goals': 'x'}, {'goals': [None]}, {'questType': 5, 'goals': [{'target': 'many'}]})),
       'a template this cannot read is a string, never an exception')
    ck(ef.quest_keys('CHALLENGE_BUDDY_AFFECTION_SINGLE') == ['challenge_buddy_affection_single', 'challenge_buddy_affection_singular', 'challenge_buddy_affection_plural']
       and ef.quest_keys('quest_defeat_dark_or_steel_type_raid') == ['quest_defeat_dark_or_steel_type_raid'] and ef.quest_keys('') == [], 'singular / plural pairing')
    # ---- the evolvable_forms cache holds RENDERED quest text: an old version or another wording must rebuild it, the same one must not
    gm_c = P(tmp, 'gm_cache.json')
    json.dump([gold_q[0][1]], open(gm_c, 'w'))
    SIR = 'SIRFETCHD_EVOLUTION_QUEST'
    saved_ef = (ef._GM, ef._CACHE, ef._qref)
    try:
        ef._GM, ef._CACHE, ef._qref = gm_c, P(tmp, 'ef_cache.json'), {'quest_land_excellent_plural': 'Make {0} Excellent Throws'}
        ef._table = None
        ef._load()
        c1 = json.load(open(ef._CACHE, encoding='utf-8'))
        ck(c1.get('v') == 11 and c1.get('qsig') == ef._quest_sig() != '' and c1['quests'] == {SIR: 'Make 10 Excellent Throws'}, 'the cache is written as version 11 with the wording fingerprint')
        c1['v'], c1['quests'] = 10, {SIR: 'land throw 10 times'}
        json.dump(c1, open(ef._CACHE, 'w'))
        ef._table = None
        ef._load()
        ck(ef._quests[SIR] == 'Make 10 Excellent Throws', 'a version-10 cache (the hand-built wording) is not trusted: rebuilt')
        ef._qref, ef._table = {'quest_land_excellent_plural': 'Land {0} Excellent Throws'}, None
        ef._load()
        ck(ef._quests[SIR] == 'Land 10 Excellent Throws', 'a refreshed reference rebuilds the cache though the game master did not change')
        c2 = json.load(open(ef._CACHE, encoding='utf-8'))
        c2['quests'] = {SIR: 'kept'}
        json.dump(c2, open(ef._CACHE, 'w'))
        ef._table = None
        ef._load()
        ck(ef._quests[SIR] == 'kept', 'an up-to-date cache (same game master, same wording) is reused')
    finally:
        ef._GM, ef._CACHE, ef._qref = saved_ef
        ef._table = None                                     # the fake game master's tables must not outlive this check
    # ---- against the REAL game master when this machine has the data store (CI does not): every evolution quest is worded, none falls back
    if os.path.exists(pd.GM_PATH):
        real_q = [t_['data']['evolutionQuestTemplate'] for t_ in json.load(open(pd.GM_PATH, encoding='utf-8')) if (t_.get('data') or {}).get('evolutionQuestTemplate')]
        texts = [ef._quest_text(q_) for q_ in real_q]
        ck(len(real_q) >= QUEST_MIN_TEMPLATES and all(t_ and '{' not in t_ for t_ in texts), 'the real game master: %d evolution quests, each worded, no placeholder left' % len(real_q))

        def has_text(q_):
            g_ = q_.get('goals') or []
            return len(g_) == 1 and any(ef._game_words((q_.get('display') or {}).get(k), g_[0].get('target') or 1, qref) for k in ('description', 'title'))
        gen = [q_['questTemplateId'] for q_ in real_q if not has_text(q_)]
        if gen:
            print('note: %d evolution quest(s) have no text in official_names_en.json yet (the generated wording is used; '
                  'python bag_art.py --refresh-names --i18n FILE): %s' % (len(gen), ', '.join(gen)))
    ck(pd.read_index()[3] is None and pd.Names.load().error is None, 'the committed reference files were not touched')
    # ---- CLI: unknown arguments print usage and run nothing
    saved = sys.stdout
    try:
        import io
        sys.stdout = io.StringIO()
        rcs = [main(a) for a in (['--help'], [], ['--refresh-index'], ['--refresh-index', '--tree'], ['--refresh-names'], ['--bogus'], ['--selftest', 'x'],
                                 ['--refresh-names', '--i18n', 'x', '--gm'], ['--refresh-names', '--i18n'], ['--refresh-names', '--i18n', 'x', '--commit'])]
    finally:
        sys.stdout = saved
    ck(rcs == [2] * 10, 'unknown / incomplete arguments must exit 2: %s' % rcs)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
