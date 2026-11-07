"""Full-coverage park loop for GPS Joystick.

Touch EVERY PokeStop and gym inside a park (within 80 m = FortSettings.InteractionRangeMeters) with ONE closed walk on
the park's paths that never walks a path segment twice, and keep the Pokemon radius (140 m =
MapSettings.PokemonVisibleRange / EncounterRangeMeters, client dump 2026-09-24) on fresh ground as much as the stops
allow.

  python -I park_sweep.py TOOLS_DIR PARK.json OUT_DIR [START_LAT,START_LNG]

PARK.json = a Nominatim jsonv2 search result with polygon_geojson (the park outline). Stops/gyms come from the
scanner's bank (system/map/pogo_wigle.db), paths from OpenStreetMap (route_planner.load_graph).

Method:
  anchors  greedy set cover of the stops: graph nodes within 74 m (80 m less half the 12 m node spacing)
  order    TSP on path distances (nearest neighbour + 2-opt + or-opt, several starts)
  legs     A* between consecutive anchors; a path segment another leg already uses costs REUSE (never needed if
           the paths allow it), walking where another leg's 140 m swath already is costs extra (negotiated over
           rounds, as in PathFinder routing)
  improve  anchor drops / relocations and 2-opt / or-opt moves, kept when length + overlap goes down
Reported: km, lap minutes, stops/gyms touched, repeated path metres (0 = no backtracking) and the fresh share of the
ground that enters the 140 m radius (100% = nothing is ever seen twice in a lap).
"""
import base64, heapq, html, io, json, math, os, random, re, sqlite3, sys, time

TOOLS, PARK, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
START = tuple(float(x) for x in sys.argv[4].split(",")) if len(sys.argv) > 4 else None
sys.path.insert(0, TOOLS)
import route_planner as rp  # noqa: E402

R_TOUCH, R_SWEEP = 80.0, 140.0            # FortSettings.InteractionRangeMeters, MapSettings.EncounterRangeMeters
R_PLAN = 74.0                              # plan to 74 m so the walked line is within 80 m everywhere
BUF, STEP, CELL = 60.0, 12.0, 10.0         # paths up to 60 m outside the fence; node spacing; raster cell
BETA, NODE_PEN, REUSE, LAMBDA = 0.0, 5.0, 1.0e5, 0.0     # with every stop to reach, fresh ground ~ 1 / length
SPEEDS = (20.0, 10.6)                      # his joystick speed now; full egg/walk credit speed
random.seed(7)
os.makedirs(OUT, exist_ok=True)
t_start = time.time()

# ---------------------------------------------------------------- park outline, local metres
d = json.load(open(PARK, encoding="utf-8"))
rec = next(x for x in d if x.get("geojson", {}).get("type") == "Polygon" and x.get("category") in ("leisure", "boundary", "place"))
NAME = rec.get("name") or "Park"
poly = [(b, a) for a, b in rec["geojson"]["coordinates"][0]]
LAT0, LNG0 = sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly)
KX, KY = 111320.0 * math.cos(math.radians(LAT0)), 110574.0
xy = lambda p: ((p[1] - LNG0) * KX, (p[0] - LAT0) * KY)
ll = lambda q: (LAT0 + q[1] / KY, LNG0 + q[0] / KX)
PX = [xy(p) for p in poly]
PXMIN, PXMAX = min(q[0] for q in PX), max(q[0] for q in PX)
PYMIN, PYMAX = min(q[1] for q in PX), max(q[1] for q in PX)


def inside(q):
    c, n = False, len(PX)
    for i in range(n):
        a, b = PX[i], PX[(i + 1) % n]
        if (a[1] > q[1]) != (b[1] > q[1]) and q[0] < (b[0] - a[0]) * (q[1] - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
    return c


def seg_d(q, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1.0)))
    return math.hypot(q[0] - a[0] - t * dx, q[1] - a[1] - t * dy)


def to_park(q):
    if not (PXMIN - BUF <= q[0] <= PXMAX + BUF and PYMIN - BUF <= q[1] <= PYMAX + BUF):
        return 1e9
    return 0.0 if inside(q) else min(seg_d(q, PX[i], PX[(i + 1) % len(PX)]) for i in range(len(PX)))


class Grid2:
    def __init__(self, cell):
        self.c, self.b = cell, {}

    def add(self, q, item):
        self.b.setdefault((int(q[0] // self.c), int(q[1] // self.c)), []).append(item)

    def near(self, q, r):
        i0, j0, n = int(q[0] // self.c), int(q[1] // self.c), int(r // self.c) + 1
        for i in range(i0 - n, i0 + n + 1):
            for j in range(j0 - n, j0 + n + 1):
                yield from self.b.get((i, j), ())


# ---------------------------------------------------------------- walking graph: park paths, densified
pad = 0.004
BBOX = (round(min(p[0] for p in poly) - pad, 3), round(min(p[1] for p in poly) - pad, 3),
        round(max(p[0] for p in poly) + pad, 3), round(max(p[1] for p in poly) + pad, 3))
pos0, adj0 = rp.load_graph(BBOX)
keep = {u for u, p in pos0.items() if to_park(xy(p)) <= BUF}
P, A, nxt, done = {}, {}, [-1], set()
for u in keep:
    P[u] = xy(pos0[u])
    A.setdefault(u, [])


def link(u, v, L):
    A[u].append((v, L))
    A[v].append((u, L))


for u in keep:
    for v, L in adj0.get(u, ()):
        if v not in keep or (u, v) in done or (v, u) in done or u == v:
            continue
        done.add((u, v))
        k, prev = max(1, math.ceil(L / STEP)), u
        for j in range(1, k):
            w = nxt[0]
            nxt[0] -= 1
            P[w] = (P[u][0] + (P[v][0] - P[u][0]) * j / k, P[u][1] + (P[v][1] - P[u][1]) * j / k)
            A[w] = []
            link(prev, w, L / k)
            prev = w
        link(prev, v, L / k)
seen, best = set(), []
for s0 in A:
    if s0 in seen:
        continue
    comp, st = [], [s0]
    seen.add(s0)
    while st:
        u = st.pop()
        comp.append(u)
        for v, _ in A[u]:
            if v not in seen:
                seen.add(v)
                st.append(v)
    if len(comp) > len(best):
        best = comp
big = set(best)
A = {u: [(v, L) for v, L in A[u] if v in big] for u in big}
P = {u: P[u] for u in big}
DEG = {u: len(A[u]) for u in A}
NG = Grid2(40.0)
for u, q in P.items():
    NG.add(q, u)
graph_m = sum(L for u in A for v, L in A[u]) / 2
area_m2 = len({(int(q[0] // 50), int(q[1] // 50)) for q in P.values()}) * 2500.0
RHO = len(P) / max(area_m2, 1.0)           # graph nodes per m2 where the paths are (overlap proxy -> metres)
print(f"{NAME}: {len(P)} path nodes, {graph_m / 1000:.1f} km of paths inside the fence + {BUF:.0f} m", flush=True)

# ---------------------------------------------------------------- targets: every banked stop/gym inside the fence
db = sqlite3.connect(f"file:{rp.BANK}?mode=ro", uri=True, timeout=15)
rows = db.execute("SELECT id, lat, lng, kind, team, last_seen FROM forts WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? "
                  "AND COALESCE(enabled, 1) = 1", (BBOX[0], BBOX[2], BBOX[1], BBOX[3])).fetchall()
read_at = max((r[5] or "" for r in rows), default="")
db.close()
T, NEARBY = [], []
for fid, la, lo, kind, team, _ in rows:
    f = {"id": fid, "p": (la, lo), "q": xy((la, lo)), "stop": kind == "stop", "team": int(team or 0)}
    (T if inside(f["q"]) else NEARBY).append(f)
cov = []
for t in T:
    s = {u for u in NG.near(t["q"], R_PLAN) if math.dist(P[u], t["q"]) <= R_PLAN}
    if not s:
        s = {u for u in NG.near(t["q"], R_TOUCH) if math.dist(P[u], t["q"]) <= R_TOUCH}
    cov.append(s)
unreach = [i for i, s in enumerate(cov) if not s]
print(f"targets: {sum(t['stop'] for t in T)} stops + {sum(not t['stop'] for t in T)} gyms inside the fence"
      + (f"; {len(unreach)} have no path within 80 m" if unreach else "; every one has a path within 80 m"), flush=True)

# ---------------------------------------------------------------- anchors: greedy set cover (dead ends only if forced)
node_t = {}
for i, s in enumerate(cov):
    for u in s:
        node_t.setdefault(u, set()).add(i)
need = {i for i, s in enumerate(cov) if s}
anchors = []
while need:
    u = max(node_t, key=lambda u: (len(node_t[u] & need), DEG[u] > 1))
    anchors.append(u)
    need -= node_t[u]


def sssp(src, goals):
    dist, pq, left = {src: 0.0}, [(0.0, src)], set(goals)
    while pq and left:
        g, u = heapq.heappop(pq)
        if g > dist[u]:
            continue
        left.discard(u)
        for v, L in A[u]:
            ng = g + L
            if ng < dist.get(v, 1e18):
                dist[v] = ng
                heapq.heappush(pq, (ng, v))
    return dist


def matrix(anc):
    D = {}
    for a in anc:
        dd = sssp(a, anc)
        for b in anc:
            D[a, b] = dd.get(b, 1e9)
    return D


def tsp(anc, D, starts=12):
    def length(o):
        return sum(D[o[i], o[(i + 1) % len(o)]] for i in range(len(o)))

    def improve(o):
        n, better = len(o), True
        while better:
            better = False
            for i in range(n - 1):                                   # 2-opt
                for j in range(i + 2, n if i else n - 1):
                    a, b, c, e = o[i], o[i + 1], o[j], o[(j + 1) % n]
                    if D[a, c] + D[b, e] < D[a, b] + D[c, e] - 1e-6:
                        o[i + 1:j + 1] = o[i + 1:j + 1][::-1]
                        better = True
            for seg in (1, 2, 3):                                    # or-opt
                for i in range(n):
                    if seg >= n - 2:
                        break
                    s_ = [o[(i + k) % n] for k in range(seg)]
                    rest = [x for x in o if x not in s_]
                    cut = D[o[(i - 1) % n], s_[0]] + D[s_[-1], o[(i + seg) % n]] - D[o[(i - 1) % n], o[(i + seg) % n]]
                    bestgain, bestpos, bestrev = 1e-6, None, False
                    for p in range(len(rest)):
                        x, y = rest[p], rest[(p + 1) % len(rest)]
                        for rev in (False, True):
                            a1, a2 = (s_[-1], s_[0]) if rev else (s_[0], s_[-1])
                            add = D[x, a1] + D[a2, y] - D[x, y]
                            if cut - add > bestgain:
                                bestgain, bestpos, bestrev = cut - add, p, rev
                    if bestpos is not None:
                        ins = s_[::-1] if bestrev else s_
                        o[:] = rest[:bestpos + 1] + ins + rest[bestpos + 1:]
                        better = True
                        break
        return o

    best_o, best_l = None, 1e18
    for k in range(min(starts, len(anc))):
        cur = [anc[(k * 7) % len(anc)]]
        left = set(anc) - set(cur)
        while left:
            nx = min(left, key=lambda b: D[cur[-1], b])
            cur.append(nx)
            left.discard(nx)
        cur = improve(cur)
        L = length(cur)
        if L < best_l:
            best_o, best_l = cur[:], L
    return best_o, best_l


# ---------------------------------------------------------------- negotiated leg routing
class Route:
    def __init__(self, order):
        self.order = list(order)
        self.legs = [None] * len(order)
        self.sw = [None] * len(order)
        self.edge_use, self.node_use, self.paint = {}, {}, {}
        self.over = 0                                  # nodes swept by 2+ legs (sum of extra sweeps)
        self.length = 0.0

    @staticmethod
    def ekey(a, b):
        return (a, b) if a < b else (b, a)

    def swath(self, path):
        s = set()
        for u in path:
            s.update(v for v in NG.near(P[u], R_SWEEP) if math.dist(P[v], P[u]) <= R_SWEEP)
        return s

    def add(self, k, path):
        self.legs[k] = path
        for a, b in zip(path, path[1:]):
            e = self.ekey(a, b)
            self.edge_use[e] = self.edge_use.get(e, 0) + 1
            self.length += math.dist(P[a], P[b])
        for v in path[1:-1]:
            self.node_use[v] = self.node_use.get(v, 0) + 1
        sw = self.swath(path)
        self.sw[k] = sw
        for v in sw:
            c = self.paint.get(v, 0)
            if c >= 1:
                self.over += 1
            self.paint[v] = c + 1

    def remove(self, k):
        path = self.legs[k]
        if path is None:
            return
        for a, b in zip(path, path[1:]):
            e = self.ekey(a, b)
            self.edge_use[e] -= 1
            self.length -= math.dist(P[a], P[b])
        for v in path[1:-1]:
            self.node_use[v] -= 1
        for v in self.sw[k]:
            c = self.paint[v]
            if c >= 2:
                self.over -= 1
            self.paint[v] = c - 1
        self.legs[k], self.sw[k] = None, None

    def route_leg(self, k):
        n = len(self.order)
        src, dst = self.order[k], self.order[(k + 1) % n]
        prv, nxl = self.sw[(k - 1) % n], self.sw[(k + 1) % n]
        ps, pd = P[src], P[dst]

        def pen(v):
            c = self.paint.get(v, 0)
            if c and prv is not None and v in prv and math.dist(P[v], ps) <= R_SWEEP:
                c -= 1                                  # the turn at the shared anchor always overlaps a little
            if c and nxl is not None and v in nxl and math.dist(P[v], pd) <= R_SWEEP:
                c -= 1
            return min(c, 2)

        dist, prev, pq = {src: 0.0}, {}, [(math.dist(ps, pd), 0.0, src)]
        while pq:
            _, g, u = heapq.heappop(pq)
            if u == dst:
                break
            if g > dist.get(u, 1e18):
                continue
            for v, L in A[u]:
                c = L * (1.0 + BETA * pen(v))
                if self.edge_use.get(self.ekey(u, v), 0) > 0:
                    c += REUSE
                if v != dst and self.node_use.get(v, 0) > 0:
                    c += NODE_PEN
                ng = g + c
                if ng < dist.get(v, 1e18):
                    dist[v], prev[v] = ng, u
                    heapq.heappush(pq, (ng + math.dist(P[v], pd), ng, v))
        path, u = [dst], dst
        while u != src:
            u = prev[u]
            path.append(u)
        return path[::-1]

    def build(self, rounds=3):
        n = len(self.order)
        for k in range(n):
            self.add(k, self.route_leg(k))
        for _ in range(rounds):
            ks = list(range(n))
            random.shuffle(ks)
            for k in ks:
                self.remove(k)
                self.add(k, self.route_leg(k))
        return self

    def reuse_m(self):
        return sum(math.dist(P[e[0]], P[e[1]]) * (c - 1) for e, c in self.edge_use.items() if c > 1)

    def cost(self):
        return self.length + LAMBDA * self.over / (RHO * 2 * R_SWEEP) + REUSE / 1000 * self.reuse_m()

    def seq(self):
        out = []
        for path in self.legs:
            out += path[:-1]
        return out + [self.legs[0][0]]


def covered_by(paths, radius):
    """Indices of targets within radius of the walked line (exact segment distance). paths = list of node lists."""
    sg = Grid2(60.0)
    for path in paths:
        for a, b in zip(path, path[1:]):
            sg.add(((P[a][0] + P[b][0]) / 2, (P[a][1] + P[b][1]) / 2), (a, b))
    got = set()
    for i, t in enumerate(T):
        for a, b in sg.near(t["q"], radius + 60):
            if seg_d(t["q"], P[a], P[b]) <= radius:
                got.add(i)
                break
    return got


reach = {i for i, s in enumerate(cov) if s}
SP = {}


def sp(a, b):
    """Plain shortest path (A*), cached both ways."""
    if (a, b) in SP:
        return SP[a, b]
    pb = P[b]
    dist, prev, pq = {a: 0.0}, {}, [(math.dist(P[a], pb), 0.0, a)]
    while pq:
        _, g, u = heapq.heappop(pq)
        if u == b:
            break
        if g > dist.get(u, 1e18):
            continue
        for v, L in A[u]:
            ng = g + L
            if ng < dist.get(v, 1e18):
                dist[v], prev[v] = ng, u
                heapq.heappush(pq, (ng + math.dist(P[v], pb), ng, v))
    path, u = [b], b
    while u != a:
        u = prev[u]
        path.append(u)
    path = path[::-1]
    SP[a, b], SP[b, a] = path, path[::-1]
    return path


def legs_of(order):
    return [sp(order[k], order[(k + 1) % len(order)]) for k in range(len(order))]


def chain_len(order):
    return sum(math.dist(P[x], P[y]) for path in legs_of(order) for x, y in zip(path, path[1:]))


def full_cover(order):
    return not (reach - covered_by(legs_of(order), R_PLAN))


def shortcut(order):
    """Drop every anchor the rest of the loop already reaches (largest detour first)."""
    changed = True
    while changed and len(order) > 3:
        changed = False
        n = len(order)
        gain = lambda k: (math.dist(P[order[k - 1]], P[order[k]]) + math.dist(P[order[k]], P[order[(k + 1) % n]])
                          - math.dist(P[order[k - 1]], P[order[(k + 1) % n]]))
        for k in sorted(range(n), key=lambda k: -gain(k)):
            trial = order[:k] + order[k + 1:]
            if full_cover(trial):
                order, changed = trial, True
                break
    return order


def relocate(order):
    """Slide each anchor to the node that still reaches its private stops with the shortest detour."""
    n, moved = len(order), 0
    for k in range(n):
        legs = legs_of(order)
        priv = reach - covered_by([legs[j] for j in range(n) if j not in ((k - 1) % n, k)], R_PLAN)
        if not priv:
            continue
        cand = set.intersection(*(cov[i] for i in priv))
        if not cand:
            continue
        a_prev, a, a_next = order[k - 1], order[k], order[(k + 1) % n]
        dp, dn = sssp(a_prev, cand | {a}), sssp(a_next, cand | {a})
        score = lambda x: dp.get(x, 1e9) + dn.get(x, 1e9) + (60.0 if DEG[x] == 1 else 0.0)
        x = min(cand, key=score)
        if x != a and x not in order and score(x) < score(a) - 1.0:
            order[k] = x
            moved += 1
    return order, moved


def repair(order):
    """Re-reach stops a re-ordering lost: insert the cheapest node of each missed stop at its cheapest position."""
    order = order[:]
    miss = reach - covered_by(legs_of(order), R_PLAN)
    while miss:
        i = min(miss)
        n = len(order)
        cands = sorted(cov[i], key=lambda u: (DEG[u] == 1, math.dist(P[u], T[i]["q"])))[:12]
        best = min(((math.dist(P[order[k]], P[u]) + math.dist(P[u], P[order[(k + 1) % n]])
                     - math.dist(P[order[k]], P[order[(k + 1) % n]]), k, u) for u in cands if u not in order for k in range(n)),
                   default=None)
        if best is None:
            break
        order.insert(best[1] + 1, best[2])
        miss = reach - covered_by(legs_of(order), R_PLAN)
    return order


def optimise(order, label):
    best_o, best_l = order, chain_len(order)
    for it in range(8):
        o = shortcut(best_o[:])
        o, moved = relocate(o)
        o, _ = tsp(o, matrix(o), starts=6)
        o = shortcut(repair(o))
        L, ok = chain_len(o), full_cover(o)
        print(f"  {label} round {it + 1}: {len(o)} anchors, {L / 1000:.2f} km{'' if ok else ' (MISSES STOPS)'}, {moved} slid", flush=True)
        if ok and L < best_l - 1:
            best_o, best_l = o, L
        else:
            break
    return best_o, best_l


# ---------------------------------------------------------------- build + improve
starts = []
o_cover, tl = tsp(anchors, matrix(anchors))
print(f"start A: greedy cover, {len(anchors)} anchors, TSP {tl / 1000:.2f} km", flush=True)
starts.append(optimise(o_cover, "A"))
dense = []
for i, s in enumerate(cov):
    if s:
        u = min(s, key=lambda u: (DEG[u] == 1, math.dist(P[u], T[i]["q"])))
        if u not in dense:
            dense.append(u)
o_dense, tl2 = tsp(dense, matrix(dense), starts=3)
print(f"start B: one anchor per stop, {len(dense)} anchors, TSP {tl2 / 1000:.2f} km", flush=True)
starts.append(optimise(o_dense, "B"))
order = min(starts, key=lambda x: x[1])[0]
print(f"best plain chain: {chain_len(order) / 1000:.2f} km with {len(order)} anchors", flush=True)


def rebuild(order, rounds=2):
    return Route(order).build(rounds)


route = rebuild(order, 3)
print(f"negotiated legs: {route.length / 1000:.2f} km, reused path {route.reuse_m():.0f} m", flush=True)


# order moves (2-opt / or-opt) on the routed loop (length + 100 x reused metres), kept only with every stop touched
tries, kept = 0, 0
deadline = time.time() + float(os.environ.get("SWEEP_SECONDS", "120"))
while time.time() < deadline:
    n = len(route.order)
    o = route.order[:]
    if random.random() < 0.5:
        i, j = sorted(random.sample(range(n), 2))
        if j - i < 2:
            continue
        o[i:j + 1] = o[i:j + 1][::-1]
    else:
        seg = random.randint(1, 3)
        i = random.randrange(n)
        s_ = [o[(i + k) % n] for k in range(seg)]
        rest = [x for x in o if x not in s_]
        p = random.randrange(len(rest))
        if random.random() < 0.5:
            s_ = s_[::-1]
        o = rest[:p + 1] + s_ + rest[p + 1:]
    tries += 1
    trial = rebuild(o)
    if trial.cost() < route.cost() - 1 and not (reach - covered_by(trial.legs, R_PLAN)):
        route, kept = trial, kept + 1
print(f"order moves: {tries} tried, {kept} kept -> {route.length / 1000:.2f} km, reused {route.reuse_m():.0f} m", flush=True)
for e, c in route.edge_use.items():
    if c > 1:
        p_ = ll(P[e[0]])
        print(f"  walked {c}x: {p_[0]:.6f},{p_[1]:.6f} (path ends: deg {DEG[e[0]]}/{DEG[e[1]]})")

# ---------------------------------------------------------------- exact metrics
seq = route.seq()
# rotate the loop to start where the joystick is now (no jump), else at the southernmost point
if START:
    s0 = min(range(len(seq) - 1), key=lambda i: math.dist(P[seq[i]], xy(START)))
else:
    s0 = min(range(len(seq) - 1), key=lambda i: P[seq[i]][1])
seq = seq[s0:-1] + seq[:s0] + [seq[s0]]
L = sum(math.dist(P[a], P[b]) for a, b in zip(seq, seq[1:]))
use = {}
for a, b in zip(seq, seq[1:]):
    e = Route.ekey(a, b)
    use[e] = use.get(e, 0) + 1
reused = sum(math.dist(P[e[0]], P[e[1]]) * (c - 1) for e, c in use.items() if c > 1)
touched = covered_by([seq], R_TOUCH)
# the 140 m radius, walked every 10 m: a cell's "passes" = separate times it comes into range during one lap
samples, acc = [P[seq[0]]], 0.0
for a, b in zip(seq, seq[1:]):
    pa, pb = P[a], P[b]
    seg = math.dist(pa, pb)
    t = 10.0 - acc
    while t <= seg:
        samples.append((pa[0] + (pb[0] - pa[0]) * t / seg, pa[1] + (pb[1] - pa[1]) * t / seg))
        t += 10.0
    acc = (acc + seg) % 10.0
disk = [(i, j) for i in range(-14, 15) for j in range(-14, 15) if math.hypot(i * CELL, j * CELL) <= R_SWEEP]
last, first, passes = {}, {}, {}
for k, s in enumerate(samples):
    ci, cj = int(round(s[0] / CELL)), int(round(s[1] / CELL))
    for di, dj in disk:
        c = (ci + di, cj + dj)
        if last.get(c) != k - 1:
            passes[c] = passes.get(c, 0) + 1
            first.setdefault(c, k)
        last[c] = k
for c, k in first.items():                 # the loop closes: in range at the end AND the start = one pass, not two
    if k == 0 and last[c] == len(samples) - 1 and passes[c] > 1:
        passes[c] -= 1
fresh = len(passes) / max(1, sum(passes.values()))
park_cells = [c for c in passes if inside((c[0] * CELL, c[1] * CELL))]
grid_park = sum(1 for i in range(int(PXMIN // CELL), int(PXMAX // CELL) + 1) for j in range(int(PYMIN // CELL), int(PYMAX // CELL) + 1)
                if inside((i * CELL, j * CELL)))
once = sum(1 for c in passes if passes[c] == 1)
print(f"\nLOOP {L / 1000:.2f} km | {', '.join(f'{L / 1000 / v * 60:.0f} min at {v:g} km/h' for v in SPEEDS)}")
print(f"touched (<= 80 m): {sum(T[i]['stop'] for i in touched)} of {sum(t['stop'] for t in T)} stops, "
      f"{sum(not T[i]['stop'] for i in touched)} of {sum(not t['stop'] for t in T)} gyms")
print(f"repeated path: {reused:.0f} m | fresh share of the 140 m radius: {fresh:.0%} "
      f"(ground swept {len(passes) * CELL * CELL / 1e4:.0f} ha, {once / len(passes):.0%} of it once) | "
      f"park ground in range: {len(park_cells) / max(1, grid_park):.0%}")

# ---------------------------------------------------------------- outputs: GPX, waypoints, JSON, page
line = [ll(P[u]) for u in seq]


def simplify(pts, tol=4.0):
    if len(pts) < 3:
        return list(pts)
    keepf = [False] * len(pts)
    keepf[0] = keepf[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        bd, bi = 0.0, None
        for k in range(i + 1, j):
            dd = seg_d(xy(pts[k]), xy(pts[i]), xy(pts[j]))
            if dd > bd:
                bd, bi = dd, k
        if bi is not None and bd > tol:
            keepf[bi] = True
            stack += [(i, bi), (bi, j)]
    return [p for p, k in zip(pts, keepf) if k]


way = simplify(line)
slug = re.sub(r"[^a-z0-9]+", "_", NAME.lower()).strip("_")
title = f"{NAME} full sweep"
gpx = "\n".join(['<?xml version="1.0" encoding="UTF-8"?>',
                 '<gpx version="1.1" creator="pogo-route-planner park_sweep" xmlns="http://www.topografix.com/GPX/1/1">',
                 f"<rte><name>{html.escape(title)}</name>"] + [f'<rtept lat="{a:.6f}" lon="{b:.6f}"/>' for a, b in way] + ["</rte></gpx>"])
wp = ";".join(f"{a:.6f},{b:.6f}" for a, b in way)
open(os.path.join(OUT, f"{slug}_sweep.gpx"), "w", encoding="utf-8").write(gpx)
open(os.path.join(OUT, f"{slug}_sweep.waypoints.txt"), "w").write(wp)
stats = {"name": NAME, "km": round(L / 1000, 3), "lap_min": {str(v): round(L / 1000 / v * 60, 1) for v in SPEEDS},
         "stops": sum(t["stop"] for t in T), "gyms": sum(not t["stop"] for t in T),
         "touched_stops": sum(T[i]["stop"] for i in touched), "touched_gyms": sum(not T[i]["stop"] for i in touched),
         "reused_m": round(reused, 1), "fresh_share": round(fresh, 4), "swept_ha": round(len(passes) * CELL * CELL / 1e4, 2),
         "park_in_range": round(len(park_cells) / max(1, grid_park), 4), "read_at": read_at, "waypoints": len(way),
         "anchors": len(route.order), "seconds": round(time.time() - t_start)}
json.dump({"stats": stats, "line": [list(p) for p in line]}, open(os.path.join(OUT, f"{slug}_sweep.json"), "w"))
print(f"GPX {len(way)} points -> {os.path.join(OUT, slug + '_sweep.gpx')}")

# page: OSM base map + the 140 m radius coloured by how often each spot comes into range
UA = {"User-Agent": "pogo-route-preview/1.0 (personal one-off route preview)"}
SECRETISH = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|tskey-(?:auth|client|api)-[0-9A-Za-z]{8,}|gh[pousr]_[0-9A-Za-z]{30,}")
TILES = os.path.join(os.path.dirname(os.path.abspath(OUT)), "data", "tiles")
os.makedirs(TILES, exist_ok=True)


def wpx(lat, lng, z):
    n = 256 * 2 ** z
    s = math.sin(math.radians(lat))
    return (lng + 180) / 360 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def tile(z, x, y):
    import requests
    from PIL import Image
    f = os.path.join(TILES, f"{z}_{x}_{y}.png")
    if not os.path.exists(f):
        r = requests.get(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png", headers=UA, timeout=30)
        r.raise_for_status()
        open(f, "wb").write(r.content)
        time.sleep(0.15)
    return Image.open(f).convert("RGB")


def basemap(pts, maxpx=1700, margin=60):
    from PIL import Image
    lats, lngs = [p[0] for p in pts], [p[1] for p in pts]
    for z in (17, 16, 15):
        x0, y0 = wpx(max(lats), min(lngs), z)
        x1, y1 = wpx(min(lats), max(lngs), z)
        if max(x1 - x0, y1 - y0) + 2 * margin <= maxpx:
            break
    x0, y0, x1, y1 = int(x0 - margin), int(y0 - margin), int(x1 + margin), int(y1 + margin)
    img = Image.new("RGB", (x1 - x0, y1 - y0))
    for tx in range(x0 // 256, x1 // 256 + 1):
        for ty in range(y0 // 256, y1 // 256 + 1):
            img.paste(tile(z, tx, ty), (tx * 256 - x0, ty * 256 - y0))
    for q in range(78, 60, -1):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        jpg = base64.b64encode(buf.getvalue()).decode()
        if not SECRETISH.search(jpg):
            break
    return z, x0, y0, img.width, img.height, jpg


z, X0, Y0, W, H, jpg = basemap(line + [ll(q) for q in PX])
Pp = lambda la, lo: (wpx(la, lo, z)[0] - X0, wpx(la, lo, z)[1] - Y0)
unit = max(W, H) / 1000.0
# radius layer: run-length rects per raster row, once = green, twice+ = orange
cells_by_row = {}
for (ci, cj), n in passes.items():
    cells_by_row.setdefault(cj, []).append((ci, n))
rects = []
for cj, row in cells_by_row.items():
    runs = []
    for ci, n in sorted(row):
        k = "once" if n == 1 else "again"
        if runs and runs[-1][1] == ci - 1 and runs[-1][2] == k:
            runs[-1][1] = ci
        else:
            runs.append([ci, ci, k])
    for c0, c1, k in runs:
        a = Pp(*ll(((c0 - 0.5) * CELL, (cj + 0.5) * CELL)))     # north-west corner
        b = Pp(*ll(((c1 + 0.5) * CELL, (cj - 0.5) * CELL)))     # south-east corner
        rects.append(f'<rect class="{k}" x="{a[0]:.1f}" y="{a[1]:.1f}" width="{b[0] - a[0] + 0.3:.1f}" height="{b[1] - a[1] + 0.3:.1f}"/>')
fence = " ".join(f"{x:.1f},{y:.1f}" for x, y in (Pp(*p) for p in poly))
route_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (Pp(*p) for p in way))
arrows, acc, nxta = [], 0.0, 120.0
for a, b in zip(way, way[1:]):
    seg = math.dist(xy(a), xy(b))
    while seg > 0 and acc + seg >= nxta:
        t = (nxta - acc) / seg
        pa, pb = Pp(*a), Pp(*b)
        ang = math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0]))
        arrows.append(f'<path class="arr" d="M{-6 * unit:.1f} {-5 * unit:.1f} L{7 * unit:.1f} 0 L{-6 * unit:.1f} {5 * unit:.1f} Z" '
                      f'transform="translate({pa[0] + (pb[0] - pa[0]) * t:.1f} {pa[1] + (pb[1] - pa[1]) * t:.1f}) rotate({ang:.0f})"/>')
        nxta += 300.0
    acc += seg
TEAM = ["#9e9e9e", "#1565c0", "#e53935", "#f9a825"]
dots = []
for i, t in enumerate(T):
    x, y = Pp(*t["p"])
    on = "" if i in touched else " miss"
    if t["stop"]:
        dots.append(f'<circle class="stop{on}" cx="{x:.1f}" cy="{y:.1f}" r="{4.0 * unit:.1f}"/>')
    else:
        k = 6.5 * unit
        dots.append(f'<path class="gym{on}" style="fill:{TEAM[t["team"] % 4]}" d="M{x:.1f} {y - k:.1f} L{x + k:.1f} {y:.1f} L{x:.1f} {y + k:.1f} L{x - k:.1f} {y:.1f} Z"/>')
sx, sy = Pp(*way[0])
start_mark = (f'<g class="hub"><circle cx="{sx:.1f}" cy="{sy:.1f}" r="{13 * unit:.1f}"/>'
              f'<text x="{sx:.1f}" y="{sy + 13 * unit * 0.38:.1f}" font-size="{13 * unit * 1.05:.1f}">S</text></g>')
st = stats
rep_txt = "no repeated path" if st["reused_m"] < 1 else f"{st['reused_m']:.0f} m repeated path"
chips = (f'<span class="chip strong">{st["touched_stops"]}/{st["stops"]} stops + {st["touched_gyms"]}/{st["gyms"]} gyms touched</span>'
         f'<span class="chip">{st["km"]:.2f} km loop</span>'
         + "".join(f'<span class="chip">{m:.0f} min at {float(v):g} km/h</span>' for v, m in st["lap_min"].items())
         + f'<span class="chip strong">{st["fresh_share"]:.0%} fresh ground</span><span class="chip">{rep_txt}</span>')
page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(NAME)} Sweep</title>
<style>
:root {{ --bg:#f6f5f1; --card:#ffffff; --fg:#1d1d1b; --mut:#66645e; --line:#e2dfd7; --accent:#00a383; --accent-ink:#ffffff; --chip:#efece5; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141412; --card:#1d1d1a; --fg:#ecebe6; --mut:#a5a39b; --line:#2f2e2a; --chip:#2a2925; }} }}
:root[data-theme="dark"] {{ --bg:#141412; --card:#1d1d1a; --fg:#ecebe6; --mut:#a5a39b; --line:#2f2e2a; --chip:#2a2925; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:880px; margin:0 auto; padding:20px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} .sub {{ color:var(--mut); margin:0 0 14px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px; }}
.chip {{ background:var(--chip); border-radius:999px; padding:2px 10px; font-size:13px; }}
.chip.strong {{ background:var(--accent); color:var(--accent-ink); font-weight:600; }}
.map {{ margin:0; border-radius:10px; overflow:hidden; border:1px solid var(--line); }}
.map svg {{ display:block; width:100%; height:auto; max-height:85vh; }}
.once {{ fill:#2e7d32; opacity:.16; }} .again {{ fill:#ef6c00; opacity:.30; }}
.fence {{ fill:none; stroke:#1d1d1b; stroke-width:2; stroke-dasharray:6 5; opacity:.55; vector-effect:non-scaling-stroke; }}
.route {{ fill:none; stroke:#7b3fe4; stroke-width:4.5; stroke-linejoin:round; stroke-linecap:round; vector-effect:non-scaling-stroke; }}
.casing {{ fill:none; stroke:#fff; stroke-width:8; stroke-linejoin:round; opacity:.85; vector-effect:non-scaling-stroke; }}
.arr {{ fill:#7b3fe4; }}
.stop {{ fill:#1e88e5; stroke:#fff; stroke-width:1.2; vector-effect:non-scaling-stroke; }}
.gym {{ stroke:#fff; stroke-width:1.4; vector-effect:non-scaling-stroke; }}
.miss {{ fill:#d50000 !important; }}
.hub circle {{ fill:#1d1d1b; stroke:#fff; stroke-width:2.5; vector-effect:non-scaling-stroke; }}
.hub text {{ fill:#fff; font-weight:700; text-anchor:middle; font-family:system-ui,sans-serif; }}
.key {{ display:flex; flex-wrap:wrap; gap:12px; color:var(--mut); font-size:13px; margin:10px 0; }}
.actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; }}
button {{ font:inherit; font-size:14px; border:1px solid var(--line); background:var(--chip); color:var(--fg); border-radius:8px; padding:7px 12px; cursor:pointer; }}
footer {{ color:var(--mut); font-size:12.5px; margin-top:22px; }} footer a {{ color:inherit; }}
</style></head>
<body><main>
<h1>{html.escape(NAME)}: full sweep</h1>
<p class="sub">One loop on the park's paths that passes within 80 m of every stop and gym inside the fence, never walks a path
twice, and keeps the 140 m Pokemon radius on new ground wherever the stops allow. Stops from your scanner, read {html.escape(read_at)}.</p>
<div class="card">
  <div class="chips">{chips}</div>
  <figure class="map"><svg viewBox="0 0 {W} {H}" role="img" aria-label="Map of the {html.escape(title)}">
    <image href="data:image/jpeg;base64,{jpg}" width="{W}" height="{H}"/>
    <g>{''.join(rects)}</g>
    <polygon class="fence" points="{fence}"/>
    <polyline class="casing" points="{route_pts}"/><polyline class="route" points="{route_pts}"/>{''.join(arrows)}
    {''.join(dots)}{start_mark}
  </svg></figure>
  <div class="key">
    <span><svg width="14" height="14"><rect width="14" height="14" fill="#2e7d32" opacity=".35"/></svg> in Pokemon range once per lap</span>
    <span><svg width="14" height="14"><rect width="14" height="14" fill="#ef6c00" opacity=".5"/></svg> in range twice or more</span>
    <span><svg width="14" height="14"><circle cx="7" cy="7" r="5" fill="#1e88e5" stroke="#fff"/></svg> stop</span>
    <span><svg width="16" height="16"><path d="M8 1 L15 8 L8 15 L1 8 Z" fill="#e53935" stroke="#fff"/></svg> gym (team colour)</span>
    <span><svg width="16" height="16"><circle cx="8" cy="8" r="7" fill="#1d1d1b"/><text x="8" y="12" font-size="10" fill="#fff" text-anchor="middle" font-weight="700">S</text></svg> start</span>
  </div>
  <div class="actions"><button type="button" id="gpx">Download GPX</button><button type="button" id="copy">Copy waypoints</button></div>
  <script type="application/json" id="data">{json.dumps({"name": title, "gpx": gpx, "wp": wp})}</script>
</div>
<footer><p>Ranges are the game's own: 80 m to spin (FortSettings.InteractionRangeMeters), 140 m to see and catch Pokemon
(MapSettings.PokemonVisibleRange / EncounterRangeMeters). "Fresh ground" = the share of everything that comes into the 140 m
range during one lap that is seen for the first time in that lap. Waypoints = the loop simplified to 4 m.</p>
<p>Map tiles and paths &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>.</p></footer>
</main>
<script>
var D = JSON.parse(document.getElementById('data').textContent);
document.getElementById('gpx').onclick = function () {{
  var a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([D.gpx], {{type: 'application/gpx+xml'}}));
  a.download = '{slug}_sweep.gpx'; document.body.appendChild(a); a.click(); a.remove(); }};
document.getElementById('copy').onclick = function (e) {{
  var b = e.target, t = b.textContent, done = function (s) {{ b.textContent = s; setTimeout(function () {{ b.textContent = t; }}, 1400); }};
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(D.wp).then(function () {{ done('Copied'); }}, function () {{ done('Copy failed'); }});
  else {{ var ta = document.createElement('textarea'); ta.value = D.wp; document.body.appendChild(ta); ta.select();
    try {{ document.execCommand('copy'); done('Copied'); }} catch (x) {{ done('Copy failed'); }} ta.remove(); }} }};
</script>
</body></html>"""
pf = os.path.join(OUT, f"{slug}_sweep.html")
open(pf, "w", encoding="utf-8").write(page)
print(f"page {os.path.getsize(pf) / 1024:.0f} KB -> {pf} ({time.time() - t_start:.0f} s)")
