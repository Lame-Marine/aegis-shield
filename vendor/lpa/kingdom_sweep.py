#!/usr/bin/env python3
"""kingdom_sweep.py -- find every player city on the world map. Read-only data requests, the same ones the game sends when you scroll.

How: for each 140x200 block of the map it sends WorldMapViewC2S at zoom level 4 (levels 1-4 return the same players; level 4 leaves out
monsters/resources, so it is the lightest; level 5 returns no players at all) and reads the SERVER REPLY directly through a temporary hook
on the game's reply handler. It does not depend on the camera, the zoom the screen is at, or the game's own map cache (which is pruned
whenever the camera moves). Each player arrives exactly once in the reply (the game later expands a city into 9 cells, which is why the
in-game cache lists everyone 9 times). The hook is always removed afterwards.

  python kingdom_sweep.py [--serial emulator-5556] [--test]      (--test = first 6 blocks only)
Writes kingdom_sweep_<date>.json. Needs the game logged in and showing the world map."""
import os, sys, json, time, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'gamelua'))
from lpa_run import run

W, H, LEVEL = 140, 200, 4
SEND = ("require('Logic.Proto.Send.world').WorldMapViewC2S({viewLevel=%d,width=%d,height=%d,"
        "center={sid=Data.WorldData.serverId,x=%d,y=%d},openView=false}) return 'sent'")

HOOK = """
local W=Data.WorldData
if not W.__lpa_orig then W.__lpa_orig=W.SetWorldMapView end
LPA_KS={seq=0,rows={},sec={}}
local function san(s) return (tostring(s):gsub('[|\\n]','/')) end
W.SetWorldMapView=function(self,data)
  local n=0
  for _,p in pairs(data.worldPointInfos or {}) do
    if (p.type==9916 or p.type==9917) and p.secretTaskInfo and p.point then
      local t=p.secretTaskInfo
      local pl={} for _,id in pairs(t.plunderedPlayerIds or {}) do pl[#pl+1]=tostring(id) end
      LPA_KS.sec[#LPA_KS.sec+1]=table.concat({tostring(t.uniqId),tostring(p.point.x),tostring(p.point.y),tostring(p.type),tostring(t.taskId),tostring(t.occupierId),
        san(t.occupierName),tostring(t.occupierUnionId),san(t.occupierUnionShortName),tostring(t.completeTime),table.concat(pl,',')},'|')
    end
    if p.type==1 and p.worldCityInfo and p.point then
      local c=p.worldCityInfo
      LPA_KS.rows[#LPA_KS.rows+1]=table.concat({tostring(c.playerId),san(c.playerName),san(c.playerUnionShortName),tostring(c.playerUnionId),
        tostring(p.point.x),tostring(p.point.y),tostring(math.floor(c.playerPower or 0)),tostring(c.level),tostring(c.shielding),
        tostring(c.playerSid),tostring(c.killEnemyCount)},'|')
      n=n+1
    end
  end
  LPA_KS.seq=LPA_KS.seq+1
  return W.__lpa_orig(self,data)
end
return 'hooked'
"""
UNHOOK = "if Data.WorldData.__lpa_orig then Data.WorldData.SetWorldMapView=Data.WorldData.__lpa_orig end LPA_KS=nil return 'unhooked'"


def body(r):
    return r.split('\n', 1)[1] if '\n' in r else ''


# Pacing: the game itself fires map requests from a 0.2 s timer (GameTimer), the next one only after the previous reply came back plus a random 0.45-0.95 s gap,
# so the rhythm is uneven. About 1.5 minutes for the whole kingdom (was 4-5). Each reply is matched to its request by the echoed centre.
CHAIN = """
local G=require('Ability.Tools.Timer.GameTimer')
local now=function() return CS.UnityEngine.Time.realtimeSinceStartup end
local h=Data.WorldData.SetWorldMapView
LPA_CH={i=1,t={%s},pending=false,sentAt=0,nextAt=0,tries=0,done=false,missed={},sent=0}
Data.WorldData.SetWorldMapView=function(self,data) local r=h(self,data)
  local c=LPA_CH local b=c and c.t[c.i] if c and c.pending and b and data.center and data.center.x==b[1] and data.center.y==b[2] then c.pending=false c.i=c.i+1 c.tries=0 c.nextAt=now()+0.45+math.random()*0.5 end return r end
local function send(b) local c=LPA_CH c.sent=c.sent+1 c.pending=true c.sentAt=now()
  require('Logic.Proto.Send.world').WorldMapViewC2S({viewLevel=%d,width=%d,height=%d,center={sid=Data.WorldData.serverId,x=b[1],y=b[2]},openView=false}) end
LPA_CH.timer=G.AddListener(0.2,function()
  local c=LPA_CH if not c or c.done then return end
  if c.pending then
    if now()-c.sentAt>6 then
      if c.tries>=3 then c.missed[#c.missed+1]=c.i c.i=c.i+1 c.pending=false c.tries=0
      else c.tries=c.tries+1 send(c.t[c.i]) end
    end
    return
  end
  if c.i>#c.t then c.done=true return end
  if now()>=c.nextAt then send(c.t[c.i]) end
end,-1)
return 'chained'
"""
UNCHAIN = ("local G=require('Ability.Tools.Timer.GameTimer') if LPA_CH and LPA_CH.timer then G.RemoveListener(LPA_CH.timer) end LPA_CH=nil "
           "if Data.WorldData.__lpa_orig then Data.WorldData.SetWorldMapView=Data.WorldData.__lpa_orig end LPA_KS=nil return 'unhooked'")


def _chunks(ser, name, n, step):
    out = []
    for i in range(1, n + 1, step):
        out += body(run("local o={} for i=%d,%d do o[#o+1]=LPA_KS.%s[i] end return table.concat(o,'\\n')" % (i, min(n, i + step - 1), name), ser, timeout=60)).splitlines()
    return out


def _good_baseline():
    """players per 140x200 block in the newest complete sweep file (kingdom_sweep_YYYY-MM-DD.json, not *_refused), plus its main sid"""
    import glob, re
    fs = sorted(f for f in glob.glob(os.path.join(HERE, 'kingdom_sweep_*.json')) if re.search(r'kingdom_sweep_\d{4}-\d{2}-\d{2}\.json$', f))
    if not fs:
        return {}, None
    ps = json.load(open(fs[-1], encoding='utf-8'))['players']
    cnt, sids = {}, {}
    for v in ps.values():
        k = (v['x'] // W, v['y'] // H)
        cnt[k] = cnt.get(k, 0) + 1
        sids[v['sid']] = sids.get(v['sid'], 0) + 1
    return cnt, max(sids, key=sids.get) if sids else None


def thin_blocks(players, blocks, share=0.6, minimum=50):
    """blocks whose reply came back with far fewer players than the last complete sweep had there (a reply can arrive
    nearly empty: on 2 Nov block x0 y0 returned 14 players instead of ~470, and the next test returned 462). Home kingdom only."""
    base, base_sid = _good_baseline()
    sids = {}
    for v in players.values():
        sids[v['sid']] = sids.get(v['sid'], 0) + 1
    if not base or not sids or max(sids, key=sids.get) != base_sid:
        return []
    now = {}
    for v in players.values():
        k = (v['x'] // W, v['y'] // H)
        now[k] = now.get(k, 0) + 1
    return [b for b in blocks if base.get((b[0] // W, b[1] // H), 0) >= minimum and now.get((b[0] // W, b[1] // H), 0) < share * base[(b[0] // W, b[1] // H)]]


def sweep(ser, test=False, say=print, level=LEVEL, secrets=None, blocks=None, recheck=True):
    """secrets: pass a list to also collect covert ops (secret bases); they only appear at zoom levels 1-3, so use level=3 then.
    blocks: only these block corners (default: the whole map). recheck: afterwards re-request blocks that came back far thinner than
    in the last complete sweep (up to 2 more tries each)."""
    ready = body(run("return tostring(require('Logic.Map.MapData.SingletonMapData'):GetWorldMap()~=nil)", ser)).strip()
    if ready != 'true':
        raise RuntimeError('the game is not showing the world map')
    if blocks is None:
        blocks = [(x, y) for y in range(0, 1000, H) for x in range(0, 1000, W)]
        if test:
            blocks = blocks[:6]
    t0 = time.time()
    for attempt in range(3):
        if body(run(HOOK, ser)).strip() == 'hooked':
            break
        time.sleep(2)
    else:
        raise RuntimeError('could not install the reader hook (game busy or not logged in?)')
    players, missed = {}, []
    try:
        lua_blocks = ','.join('{%d,%d}' % (x + W // 2, y + H // 2) for x, y in blocks)
        if body(run(CHAIN % (lua_blocks, level, W, H), ser, timeout=30)).strip() != 'chained':
            raise RuntimeError('could not start the paced sweep')
        last = -1
        while True:
            time.sleep(1.0)
            r = body(run("return tostring(LPA_CH.done)..'|'..tostring(LPA_CH.i)", ser)).strip().split('|')
            if len(r) < 2:
                continue            # a garbled read of the reply file; ask again
            if r[1] != last:
                last = r[1]
                say('block %s/%d | %ds' % (min(int(r[1]), len(blocks)), len(blocks), time.time() - t0))
            if r[0] == 'true':
                break
            if time.time() - t0 > 400:
                raise RuntimeError('sweep took too long; stopped')
        m = body(run("local o={} for _,i in ipairs(LPA_CH.missed) do o[#o+1]=i end return table.concat(o,',')", ser)).strip()
        missed = [blocks[int(i) - 1] for i in m.split(',') if i]
        nrows = int(body(run("return tostring(#LPA_KS.rows)", ser)).strip())
        for line in _chunks(ser, 'rows', nrows, 600):
            p = line.split('|')
            if len(p) < 11:
                continue
            players[p[0]] = {'name': p[1], 'tag': '' if p[2] in ('nil', '') else p[2],
                             'union_id': int(float(p[3])) if p[3] not in ('nil', '') else 0,
                             'x': int(float(p[4])), 'y': int(float(p[5])), 'power': int(float(p[6])),
                             'level': int(float(p[7])) if p[7] != 'nil' else None,
                             'shield': p[8] == 'true', 'sid': p[9],
                             'kills': int(float(p[10])) if p[10] not in ('nil', '') else 0}
        if secrets is not None:
            seen = set()
            nsec = int(body(run("return tostring(#LPA_KS.sec)", ser)).strip())
            for line in _chunks(ser, 'sec', nsec, 300):
                p = line.split('|')
                if len(p) >= 11 and p[0] not in seen:
                    seen.add(p[0])
                    secrets.append({'uniq': p[0], 'x': int(float(p[1])), 'y': int(float(p[2])), 'type': int(float(p[3])), 'task': int(float(p[4])),
                                    'occupier_id': p[5], 'occupier': p[6], 'union_id': p[7], 'tag': '' if p[8] in ('nil', '') else p[8],
                                    'complete_ms': int(float(p[9])), 'plundered': [x for x in p[10].split(',') if x]})
        say('done: %d players in %ds' % (len(players), time.time() - t0))
    finally:
        run(UNCHAIN, ser)
    if missed:
        raise RuntimeError('sweep incomplete: no reply for blocks %s, even after retries (nothing saved; run it again)' % missed)
    if recheck and not test:
        thin = thin_blocks(players, blocks)
        for attempt in range(2):
            if not thin:
                break
            say('%d block(s) came back much thinner than last time (%s); asking for them again' % (len(thin), ', '.join('x%d y%d' % t for t in thin)))
            time.sleep(2)
            more = sweep(ser, say=lambda t: None, level=level, secrets=secrets, blocks=thin, recheck=False)
            players.update(more)
            thin = thin_blocks(players, thin)
        if thin:
            say('still thin after retries: %s (the save check will decide)' % ', '.join('x%d y%d' % t for t in thin))
        say('total after rechecks: %d players' % len(players))
    return players


def save(players, suffix=''):
    out = os.path.join(HERE, 'kingdom_sweep_%s%s.json' % (dt.date.today().isoformat(), suffix))
    json.dump({'taken': dt.datetime.now().isoformat(timespec='seconds'), 'players': players}, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    return out


def alliance_rows(players, taken_at, source='lpa_sync'):
    """Alliance totals for one sweep, as kingdom_alliance_snapshots rows (site migration 0040): one per server + tag.
    Players without an alliance are not counted. taken_at: ISO time (UTC) shared by every row of the sweep."""
    acc = {}
    for v in players.values():
        tag = (v.get('tag') or '').strip()
        if not tag:
            continue
        sid = int(v['sid']) if str(v.get('sid', '')).isdigit() else None
        a = acc.setdefault((sid, tag), {'taken_at': taken_at, 'server_id': sid, 'alliance_tag': tag, 'union_id': v.get('union_id') or None,
                                        'members': 0, 'total_power': 0, 'top_power': 0, 'total_kills': 0, 'source': source})
        a['members'] += 1
        a['total_power'] += int(v.get('power') or 0)
        a['top_power'] = max(a['top_power'], int(v.get('power') or 0))
        a['total_kills'] += int(v.get('kills') or 0)
    return list(acc.values())


if __name__ == '__main__':
    a = sys.argv[1:]
    ser = a[a.index('--serial') + 1] if '--serial' in a else 'emulator-5556'
    try:
        pl = sweep(ser, test='--test' in a)
    except RuntimeError as e:
        sys.exit(str(e))
    print('saved', len(pl), 'players ->', save(pl))
