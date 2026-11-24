"""sweep.py - fresh full-kingdom search on Halden (emulator-5554), for finding invaders / players of interest.
Uses Iris's tuned kingdom_sweep.sweep() (chained WorldMapViewC2S at game pacing, ~40 blocks of 140x200) and keeps
NOTHING on disk except the matches you asked for. Our comms guard is installed first.
Needs: game on the world map with Data.WorldData.serverId == 263 (if it reads 0, go back to the city and out again).
    python aegis/sweep.py --name BrewDr [--name X ...] [--foreign]     (--foreign = every city whose sid is not 263)
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'vendor', 'lpa'))
import run as R
import kingdom_sweep as KS

from device import SERIAL
HOME_SID = '263'


def ready():
    r = R.run("return tostring(Data.WorldData.serverId)..'|'..CS.UnityEngine.SceneManagement.SceneManager.GetActiveScene().name")
    sid, scene = (r.split('\n', 1)[1].strip().split('|') + ['', ''])[:2]
    if scene != 'WorldScene': raise RuntimeError('not on the world map (scene %s)' % scene)
    if sid != HOME_SID: raise RuntimeError('map server id is %s, not 263: go back to the city and out again' % sid)


def find(names=(), foreign=False, say=print):
    R.guard(); ready()
    t0 = time.time()
    res = KS.sweep(SERIAL, say=lambda *a: None)
    players = res[0] if isinstance(res, tuple) else res
    if isinstance(players, dict): players = [dict(v, id=k) for k, v in players.items()]
    dt = time.time() - t0
    want = {n.lower() for n in names}
    hits = [p for p in players if p.get('name', '').lower() in want or (foreign and str(p.get('sid')) != HOME_SID)]
    say('swept %d cities in %.0f s; %d match' % (len(players), dt, len(hits)))
    return hits, len(players), dt


if __name__ == '__main__':
    a = sys.argv[1:]
    names = [a[i + 1] for i, x in enumerate(a) if x == '--name']
    hits, n, dt = find(names, '--foreign' in a)
    for p in hits: print('%s (id %s) [%s] sid %s at %s,%s power %s shield %s' % (p['name'], p.get('id'), p.get('tag'), p.get('sid'), p['x'], p['y'], p.get('power'), p.get('shield')))
