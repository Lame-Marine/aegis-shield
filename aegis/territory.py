"""Alliance territory model (pure python, no game access).

Input: list of (x, y, tag) for allied home-kingdom cities. Players without an alliance are never passed in.
1. cluster each alliance's cities (DBSCAN: eps tiles, min_pts members); stragglers are dropped
2. a territory = convex hull of a cluster, padded by `margin` tiles (distance-to-hull test, no polygon offsetting)
3. locate(x, y): which territories contain the point, else the nearest territory edge within `cutoff` tiles
"""
import math
from collections import defaultdict

DEFAULTS = {'eps': 20.0, 'min_pts': 3, 'margin': 8.0, 'cutoff': 20.0}


def dbscan(pts, eps, min_pts):
    """pts: list of (x, y). Returns list of clusters (lists of points). Grid-accelerated."""
    cell = max(eps, 1e-6)
    grid = defaultdict(list)
    for i, (x, y) in enumerate(pts):
        grid[(int(x // cell), int(y // cell))].append(i)

    def nbrs(i):
        x, y = pts[i]
        cx, cy = int(x // cell), int(y // cell)
        out = []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for j in grid.get((gx, gy), ()):
                    if (pts[j][0] - x) ** 2 + (pts[j][1] - y) ** 2 <= eps * eps:
                        out.append(j)
        return out

    label = [None] * len(pts)  # None unvisited, -1 noise, >=0 cluster
    clusters = []
    for i in range(len(pts)):
        if label[i] is not None:
            continue
        nb = nbrs(i)
        if len(nb) < min_pts:
            label[i] = -1
            continue
        cid = len(clusters)
        clusters.append([])
        label[i] = cid
        queue = [j for j in nb if j != i]
        while queue:
            j = queue.pop()
            if label[j] == -1:
                label[j] = cid
                clusters[cid].append(pts[j])
                continue
            if label[j] is not None:
                continue
            label[j] = cid
            clusters[cid].append(pts[j])
            nb2 = nbrs(j)
            if len(nb2) >= min_pts:
                queue.extend(k for k in nb2 if label[k] is None or label[k] == -1)
        clusters[cid].append(pts[i])
    return clusters


def hull(points):
    """Convex hull (monotone chain). Returns list of vertices; 1 or 2 points for degenerate input."""
    p = sorted(set(points))
    if len(p) <= 2:
        return p

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo = []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    up = []
    for q in reversed(p):
        while len(up) >= 2 and cross(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    h = lo[:-1] + up[:-1]
    return h if len(h) >= 3 else p


def _seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _inside(px, py, poly):
    if len(poly) < 3:
        return False
    ins = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def dist_to_hull(px, py, poly):
    """0 inside the polygon, else distance to its boundary (works for 1-2 point hulls too)."""
    if len(poly) == 1:
        return math.hypot(px - poly[0][0], py - poly[0][1])
    if _inside(px, py, poly):
        return 0.0
    if len(poly) == 2:
        return _seg_dist(px, py, poly[0], poly[1])
    return min(_seg_dist(px, py, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def build(cities, eps=None, min_pts=None, margin=None, **_):
    """cities: iterable of (x, y, tag). Returns list of territories {tag, n, hull, cx, cy}."""
    eps = DEFAULTS['eps'] if eps is None else eps
    min_pts = DEFAULTS['min_pts'] if min_pts is None else min_pts
    by = defaultdict(list)
    for x, y, tag in cities:
        if tag:
            by[tag].append((x, y))
    out = []
    for tag, pts in by.items():
        for cl in dbscan(pts, eps, int(min_pts)):
            if len(cl) < min_pts:
                continue
            h = hull(cl)
            out.append({'tag': tag, 'n': len(cl), 'hull': h,
                        'cx': sum(p[0] for p in cl) / len(cl), 'cy': sum(p[1] for p in cl) / len(cl)})
    return out


def locate(terrs, x, y, margin=None, cutoff=None, **_):
    """What the model says about a point. Returns {'inside': [...], 'near': [...], 'text': str}."""
    margin = DEFAULTS['margin'] if margin is None else margin
    cutoff = DEFAULTS['cutoff'] if cutoff is None else cutoff
    best = {}  # tag -> (distance to padded edge, members in the matching cluster)
    for t in terrs:
        d = dist_to_hull(x, y, t['hull'])
        if d > cutoff + margin:
            continue
        cur = best.get(t['tag'])
        if cur is None or d < cur[0]:
            best[t['tag']] = (d, t['n'])
    inside, near = [], []
    for tag, (d, n) in best.items():
        if d <= margin:
            inside.append({'tag': tag, 'dist': round(d, 1), 'members': n, 'core': d == 0})
        elif d - margin <= cutoff:
            near.append({'tag': tag, 'dist': round(d - margin, 1), 'members': n})
    inside.sort(key=lambda r: (r['dist'], -r['members']))
    near.sort(key=lambda r: (r['dist'], -r['members']))
    if inside:
        text = 'Inside [%s]' % inside[0]['tag']  # one alliance only: deepest (core hull first, then most members)
    elif near:
        text = '~%d tiles from [%s]' % (round(near[0]['dist']), near[0]['tag'])
    else:
        text = ''
    return {'inside': inside, 'near': near, 'text': text}
