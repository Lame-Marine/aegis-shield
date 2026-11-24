"""fastmap.py - whole-kingdom refresh in one request (~4 s) and queries answered in game memory.
    python aegis/fastmap.py player "brew*"     |  alliance "ABC"  |  invaders
Wildcards: * = any run of characters, ? = one character. Case-insensitive, whole-name match.
Nothing is written to disk.
"""
import os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

FASTMAP = open(os.path.join(HERE, 'fastmap.lua'), encoding='utf-8').read()


def body(r): return r.split('\n', 1)[1] if r.startswith('OK') else (_ for _ in ()).throw(RuntimeError(r[:300]))


def glob_to_lua(q):
    out = []
    for ch in q.lower():
        if ch == '*': out.append('.*')
        elif ch == '?': out.append('.')
        elif re.match(r'[%^$().\[\]+\-]', ch): out.append('%' + ch)
        else: out.append(ch)
    return '^' + ''.join(out) + '$'


def lstr(s): return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ') + '"'


def install():
    R.guard(); return body(R._raw(FASTMAP)).strip()


def refresh(timeout=20):
    install()
    sid = body(R._raw("return CS.UnityEngine.SceneManagement.SceneManager.GetActiveScene().name == 'WorldScene' and tostring(Data.WorldData.serverId) or 'city'")).strip()
    if sid != body(R._raw('return tostring(Data.UserData.serverId)')).strip():
        raise RuntimeError('map server id is %s: go back to the city and out to the world map again' % sid)
    t0 = time.time()
    body(R._raw('return AE_MAP.refresh()'))
    while time.time() - t0 < timeout:
        r = body(R._raw("return tostring(AE_MAP.done)..'|'..AE_MAP.n")).strip().split('|')
        if r[0] == 'true': return int(r[1]), time.time() - t0
        time.sleep(0.3)
    raise RuntimeError('no full map reply in %d s' % timeout)


def parse_row(p):
    """id|name|tag|x|y|power|sid|shield|level|garrison|kills|defend|state. Names may contain '|': parse from both ends."""
    if isinstance(p, str): p = p.split('|')
    if len(p) < 13: return None
    t = p[-11:]
    return {'id': p[0], 'name': '|'.join(p[1:-11]), 'tag': '' if t[0] in ('nil', '') else t[0], 'x': int(float(t[1])), 'y': int(float(t[2])),
            'power': int(float(t[3])), 'sid': t[4], 'shield': t[5] == '1', 'level': int(float(t[6])), 'garrison': int(float(t[7])),
            'kills': int(float(t[8])), 'defend': float(t[9]), 'state': int(float(t[10]))}


def ladder(n=200):
    """Home kingdom power ladder from the current snapshot: (count, [(name, power, level), ...] strongest first)."""
    out = body(R._raw('return AE_MAP.ladder(%d)' % n, timeout=30)).strip().split(chr(10))
    top = []
    for l in out[1:]:
        q = l.rsplit('|', 2)
        if len(q) == 3: top.append((q[0], int(float(q[1])), int(float(q[2]))))
    return int(out[0] or 0), top


def query(kind, pat=''):
    lp = glob_to_lua(pat) if kind != 'invaders' else ''
    out = body(R._raw('return AE_MAP.query(%s, %s)' % (lstr(kind), lstr(lp)), timeout=30)).strip()
    rows = []
    for l in out.split('\n'):
        p = l.split('|')
        r = parse_row(p)
        if r: rows.append(r)
    return rows


def allied():
    """Allied home-kingdom cities as [(x, y, tag)], for the territory model. Positions and tags only."""
    out = body(R._raw('return AE_MAP.allied()', timeout=30)).strip()
    rows = []
    for l in out.split(chr(10)):
        p = l.split('|', 2)
        if len(p) == 3 and p[2]: rows.append((int(float(p[0])), int(float(p[1])), p[2]))
    return rows


def throne():
    """Royal city state from the last refresh: dict(shield, shield_end, fight_end, truce_end (unix s), occupied, tag, union,
    sid, state, cross, marches) or None if the refresh did not include it."""
    r = body(R._raw('return tostring(AE_MAP.throne)')).strip()
    p = r.split('|')
    if len(p) != 11: return None
    ms = lambda v: int(float(v)) // 1000
    return {'shield': p[0] == 'true', 'shield_end': ms(p[1]), 'fight_end': ms(p[2]), 'truce_end': ms(p[3]), 'occupied': p[4] == 'true',
            'tag': p[5], 'union': p[6], 'sid': p[7], 'state': p[8], 'cross': p[9] == 'true', 'marches': int(float(p[10] or 0))}


def kingdom_holder(sid=None):
    """Who holds a kingdom's royal city after KvK and who its own king is (Data.TempleData, cached by the game):
    -> dict(holder_tag, holder_sid, king, king_tag) or None."""
    code = ("local T = Data.TempleData local sid = %s local o = T:GetKingdomOccupyInfo(sid) local k = (T.kingdomInfos or {})[sid] or {} "
            "local u = (o or {}).unionSimpleInfo or {} local ku = (k.kingUnionSimpleInfo or {}) "
            "return tostring(u.unionAlias or '') .. '|' .. tostring((o or {}).serverId or '') .. '|' .. tostring(k.kingPlayerName or '') .. '|' .. tostring(ku.unionAlias or '') .. '|' .. string.format('%%d', k.victoryTimeMs or 0)")
    r = body(R._raw(code % (int(sid) if sid else 'Data.UserData.serverId'))).strip().split('|')
    if len(r) != 5: return None
    return {'holder_tag': r[0], 'holder_sid': r[1], 'king': r[2], 'king_tag': r[3], 'victory_ms': int(float(r[4] or 0))}


def at(pid):
    r = body(R._raw('return tostring(AE_MAP.at(%s))' % lstr(str(pid)))).strip()
    return None if r == 'nil' else r


if __name__ == '__main__':
    n, dt = refresh()
    print('map: %d cities in %.1f s' % (n, dt))
    kind = sys.argv[1] if len(sys.argv) > 1 else 'invaders'
    rows = query(kind, sys.argv[2] if len(sys.argv) > 2 else '')
    print(len(rows), 'match')
    for r in sorted(rows, key=lambda r: -r['power'])[:20]: print(r)
