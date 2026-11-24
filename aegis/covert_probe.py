"""covert_probe.py - read-only: one covert scan of the home kingdom through covert.scan() (enters the world map, puts the
view back home, reinstalls the fast-map hook), keeping the raw rows so not-started / running / collectable ops can be
told apart. Nothing is stored. Pause bot.py + watchdog.py while it runs (one driver at a time)."""
import collections, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import covert as CV
import run as R

rows = {}
orig = CV._parse
def parse(line):                       # keep the point type (field 3) that _parse drops
    d = orig(line)
    if d: rows[d['uniq']] = dict(d, ptype=line.split('|')[3])
    return d
CV._parse = parse
now_ms = int(float(CV.body(R._raw(CV.STATE)).split('|')[0]))
t0 = time.time()
k, ops, maxed, hits = CV.scan(None)
st = {o['uniq']: o['status'] for o in ops}
c, ex = collections.Counter(), {}
for u, s in rows.items():
    occ = s['occupier_id'] not in ('', 'nil', '0')
    cm = s['complete_ms']
    key = (s['ptype'], 'occupier' if occ else 'no-occupier', 'complete=0' if cm <= 0 else ('finished' if cm <= now_ms else 'future'),
           'plundered' if s['plundered'] else 'unplundered', 'status=' + str(st.get(u)))
    c[key] += 1
    ex.setdefault(key, (s['task'], cm, s['occupier'][:12], len(s['plundered'])))
print('K%s sweep %.0fs, %d ops, server now %d, live hits that would have been shared: %d (%s)' % (
    k, time.time() - t0, len(rows), now_ms, len(hits), dict(collections.Counter(h['status'] for h in hits))))
for key, n in sorted(c.items(), key=lambda kv: -kv[1]):
    print('%5d  %-70s e.g. task %s complete %s occupier %r plundered %s' % ((n, ' '.join(key)) + ex[key]))
