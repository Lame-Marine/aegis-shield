"""Local map dashboard for tuning the alliance-territory model. Offline: reads operator's newest kingdom_sweep_*.json in place
(his daily sync output), serves x/y/tag only (no names, ids or power), binds to 127.0.0.1, writes nothing.
Run: python dashboard/server.py [--port 8765] [--sweep path] [--home 263]"""
import argparse
import glob
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'aegis'))
import territory as T  # noqa: E402

SWEEPS = os.environ.get('SWEEP_GLOB', 'kingdom_sweep_*.json')   # sweep dumps with x/y/tag per city
ap = argparse.ArgumentParser()
ap.add_argument('--port', type=int, default=8765)
ap.add_argument('--sweep')
ap.add_argument('--home', default='263')
args = ap.parse_args()

path = args.sweep or max(f for f in glob.glob(SWEEPS) if 'refused' not in f and 'rerun' not in f and '_v1' not in f)
raw = json.load(open(path))
CITIES = [(p['x'], p['y'], p['tag'] or '') for p in raw['players'].values() if str(p['sid']) == args.home]
TAKEN = raw.get('taken')
del raw
ALLIED = [c for c in CITIES if c[2]]
print('loaded %s (taken %s): %d home cities, %d allied' % (os.path.basename(path), TAKEN, len(CITIES), len(ALLIED)), flush=True)
CACHE = {}


def params(q):
    def f(k, d):
        try:
            return float(q.get(k, [d])[0])
        except ValueError:
            return d
    return {k: f(k, v) for k, v in T.DEFAULTS.items()}


def terrs(p):
    key = (p['eps'], p['min_pts'], p['margin'])
    if key not in CACHE:
        if len(CACHE) > 40:
            CACHE.clear()
        CACHE[key] = T.build(ALLIED, **p)
    return CACHE[key]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == '/':
            return self.send(open(os.path.join(HERE, 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
        if u.path == '/api/data':
            return self.send({'taken': TAKEN, 'home': args.home, 'defaults': T.DEFAULTS,
                              'cities': [[x, y, t] for x, y, t in CITIES]})
        p = params(q)
        if u.path == '/api/territories':
            ts = terrs(p)
            return self.send([{'tag': t['tag'], 'n': t['n'], 'hull': t['hull'], 'cx': t['cx'], 'cy': t['cy']} for t in ts])
        if u.path == '/api/locate':
            x, y = float(q['x'][0]), float(q['y'][0])
            r = T.locate(terrs(p), x, y, **p)
            near_cities = sum(1 for cx, cy, _ in CITIES if (cx - x) ** 2 + (cy - y) ** 2 <= 100)
            r.update({'x': x, 'y': y, 'territories': len(terrs(p)), 'cities_within_10': near_cities})
            return self.send(r)
        self.send_response(404)
        self.end_headers()


ThreadingHTTPServer(('127.0.0.1', args.port), H).serve_forever()
