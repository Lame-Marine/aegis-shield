"""covert.py - covert ops (secret bases) on the map: which are finished, have free plunder slots and are not yet plundered
by us. Wraps vendor/lpa/kingdom_sweep.py zoom-3 sweep (covert ops only appear at zoom 1-3) and the game's own
"enter that kingdom's map" call. Owner-only feature of bot.py (operator's DM). Results stay in memory; nothing is written.
    python aegis/covert.py [kingdom]          (prints a summary; no sends)
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LPA = os.path.join(HERE, '..', 'vendor', 'lpa')   # copies of kingdom_sweep.py + a stub lpa_run
sys.path.insert(0, LPA)
sys.path.insert(0, os.path.join(LPA, 'gamelua'))
import run as R
import fastmap as FM
import kingdom_sweep as KS

from device import SERIAL          # never Iris's default (emulator-5556 is operator's instance)
TOP = 5

CFG = r"""
local ids = {%s}
local o = {}
local function count(list, want_box)
  local n = 0
  for _, it in ipairs(list or {}) do
    local name = ''
    if it.type == 99 and Config.Item and Config.Item[it.id] then name = tostring(GetTranslation(Config.Item[it.id].name)) end
    if want_box and name == 'Secret Reward' then n = n + (it.count or 0) end
    if not want_box and it.type == 5 then n = n + (it.count or 0) end
  end
  return n
end
for _, id in ipairs(ids) do
  local c = Config.SecretTask[id]
  if c then o[#o + 1] = table.concat({id, tostring(c.secretLevel), tostring(c.quality), count(c.grabReward, true), count(c.grabReward, false)}, '|') end
end
return table.concat(o, string.char(10))
"""
STATE = ("local d = Data.SecretData return string.format('%d', Data.TimeData:GetServerTimeStamp()) .. '|' .. tostring(Data.UserData.gameUid)"
         " .. '|' .. tostring(d and d.ReachMaxPlunder and d:ReachMaxPlunder())")
VIEW = ("local w = CS.UnityEngine.SceneManagement.SceneManager.GetActiveScene().name == 'WorldScene' "
        "return (w and tostring(Data.WorldData.serverId) or '0') .. '|' .. tostring(Data.UserData.serverId)")   # city screen = '0' (serverId keeps its old value there)
ENTER = "local ok, e = pcall(function() GlobalMapCtrlManager:GetManager():EnterNormalMap(%s, {x = 500, y = 500}) end) return tostring(ok)"
REACH = "local s = {} for _, v in pairs(Data.EscortData.serverIds or {}) do s[#s + 1] = tostring(v) end return table.concat(s, ',')"


def body(r):
    if not r.startswith('OK'): raise RuntimeError(r[:200])
    return r.split('\n', 1)[1].strip() if '\n' in r else ''


def view():
    v, home = body(R._raw(VIEW)).split('|')
    return v, home


def enter(kingdom):
    body(R._raw(ENTER % kingdom))
    target = str(kingdom) if kingdom != 'Data.UserData.serverId' else view()[1]
    for _ in range(20):
        time.sleep(1)
        if view()[0] == target: return True
    return False


def go_home():
    """Put the map view back on the home kingdom's world map; retries, raises if it will not switch."""
    for attempt in range(3):
        v, home = view()
        if v == home: return True
        if enter('Data.UserData.serverId'): return True
        time.sleep(2)
    raise RuntimeError('map view stuck on K%s (home K%s)' % view())


def reachable():
    """Kingdoms the game lets us view (the caravan screen's list); asks the server for a fresh copy first."""
    body(R._raw("Data.EscortData.serverIds = nil Data.EscortData:ReqQueryCanBeRobbedEscortCartList() return 'sent'"))
    for _ in range(16):
        time.sleep(0.5)
        r = body(R._raw(REACH))
        if r: return sorted(int(x) for x in r.split(','))
    return []


BW, BH = 150, 200        # largest zoom-3 view the server accepts (140x220 / 160x180 / 200x200 are refused with 1023)
JACKPOT = r"""
local o = {}
for id, c in pairs(Config.SecretTask) do
  if type(c) == 'table' and c.secretLevel == 5 then
    local b = 0
    for _, it in pairs(c.grabReward or {}) do
      if type(it) == 'table' and it.type == 99 then
        local ok, nm = pcall(function() return tostring(GetTranslation(Config.Item[it.id].name)) end)
        if ok and nm == 'Secret Reward' then b = b + (it.count or 0) end
      end
    end
    if b >= 15 then o[#o + 1] = tostring(id) end
  end
end
return table.concat(o, ',')
"""
FETCH = "local o = {} for i = %d, %d do o[#o + 1] = LPA_KS.sec[i] end return table.concat(o, string.char(10))"


def _parse(line):
    p = line.split('|')
    if len(p) < 11: return None
    return {'uniq': p[0], 'x': int(float(p[1])), 'y': int(float(p[2])), 'task': int(float(p[4])), 'occupier_id': p[5], 'occupier': p[6],
            'tag': '' if p[8] in ('nil', '') else p[8], 'complete_ms': int(float(p[9])), 'plundered': [x for x in p[10].split(',') if x]}


def _cfg(ids):
    cfg = {}
    if ids:
        for line in body(R._raw(CFG % ','.join(map(str, sorted(ids))), timeout=30)).splitlines():
            p = line.split('|')
            if len(p) == 5: cfg[int(p[0])] = {'level': int(float(p[1])), 'quality': int(float(p[2])), 'boxes': int(float(p[3])), 'antitoxin': int(float(p[4]))}
    return cfg


def _status(s, cfg, now_ms, my_uid):
    c = cfg.get(s['task'], {'level': 0, 'quality': 0, 'boxes': 0, 'antitoxin': 0})
    finished = s['complete_ms'] <= now_ms
    slots = max(0, 3 - len(s['plundered']))
    status = ('mine' if s['occupier_id'] == my_uid else 'done_by_me' if my_uid in s['plundered'] else
              'ready' if finished and slots else 'full' if finished else 'running')
    return dict(c, x=s['x'], y=s['y'], tag=s['tag'], slots=slots, status=status, uniq=s['uniq'], task=s['task'],
                owner=(('[%s]' % s['tag']) if s['tag'] else '') + (s['occupier'] if s['occupier'] not in ('nil',) else ''),
                ready_min=0 if finished else round((s['complete_ms'] - now_ms) / 60000))


# Fast sweep (operator 2026-11-21, 'going unsafe is fine'): several map requests in flight. Measured on the S10, 35 blocks of K263:
# one at a time with the game-like 0.45-0.95 s gap 69-71 s; 2..10 in flight all 35.3-35.6 s, no missed blocks, no ErrorCode, same op counts
# (the server answers about one block per second, so more than 2 in flight buys nothing). Any missed block or server error falls back to
# the old sequential pace for the rest of this bot run and redoes the sweep that way.
FAST = {'on': True, 'par': 2, 'gap': 0.0, 'jit': 0.1}
LAST = {}
CHAIN2 = r"""
local G=require('Ability.Tools.Timer.GameTimer')
local now=function() return CS.UnityEngine.Time.realtimeSinceStartup end
local h=Data.WorldData.SetWorldMapView
local MR=MessageReceive
LPA_ERR={}
LPA_CH={i=1,t={@BLOCKS@},pend={},nextAt=0,done=false,missed={},sent=0,gap=@GAP@,jit=@JIT@,par=@PAR@,got=0}
Data.WorldData.SetWorldMapView=function(self,data) local r=h(self,data)
  local c=LPA_CH
  if c and data.center then local k=data.center.x..','..data.center.y
    if c.pend[k] then c.pend[k]=nil c.got=c.got+1 if c.par==1 then c.nextAt=now()+c.gap+math.random()*c.jit end end end
  return r end
if not MR.__ls_ec then MR.__ls_ec=MR.ErrorCode
  MR.ErrorCode=function(d,...) if LPA_ERR and d then LPA_ERR[#LPA_ERR+1]=tostring(d.name)..':'..tostring(d.code) end return MR.__ls_ec(d,...) end end
local function send(b) local c=LPA_CH c.sent=c.sent+1 c.pend[b[1]..','..b[2]]=now()
  if c.par>1 then c.nextAt=now()+c.gap+math.random()*c.jit end
  require('Logic.Proto.Send.world').WorldMapViewC2S({viewLevel=3,width=@W@,height=@H@,center={sid=Data.WorldData.serverId,x=b[1],y=b[2]},openView=false}) end
LPA_CH.timer=G.AddListener(0.05,function()
  local c=LPA_CH if not c or c.done then return end
  local npend=0
  for k,t in pairs(c.pend) do npend=npend+1
    if now()-t>6 then c.pend[k]=nil c.missed[#c.missed+1]=k end end
  if c.i>#c.t and npend==0 then c.done=true return end
  if c.i<=#c.t and npend<c.par and now()>=c.nextAt then local b=c.t[c.i] c.i=c.i+1 send(b) end
end,-1)
return 'chained'
"""
UNCHAIN2 = ("local G=require('Ability.Tools.Timer.GameTimer') if LPA_CH and LPA_CH.timer then G.RemoveListener(LPA_CH.timer) end LPA_CH=nil "
            "if MessageReceive.__ls_ec then MessageReceive.ErrorCode=MessageReceive.__ls_ec MessageReceive.__ls_ec=nil end LPA_ERR=nil "
            "if Data.WorldData.__lpa_orig then Data.WorldData.SetWorldMapView=Data.WorldData.__lpa_orig end LPA_KS=nil return 'unhooked'")


def _sweep_once(on_new, blocks, fast):
    """One pass over `blocks`. Returns (missed blocks, server errors). fast = chain with several requests in flight, else the old sequential chain."""
    if body(R._raw(KS.HOOK)) != 'hooked': raise RuntimeError('could not install the map hook')
    try:
        if fast:
            code = (CHAIN2.replace('@BLOCKS@', ','.join('{%d,%d}' % b for b in blocks)).replace('@GAP@', str(FAST['gap'])).replace('@JIT@', str(FAST['jit']))
                    .replace('@PAR@', str(FAST['par'])).replace('@W@', str(BW)).replace('@H@', str(BH)))
        else:
            code = KS.CHAIN % (','.join('{%d,%d}' % b for b in blocks), 3, BW, BH)
        if body(R._raw(code, timeout=30)) != 'chained': raise RuntimeError('could not start the sweep')
        got, t0 = 0, time.time()
        while True:
            time.sleep(0.5 if fast else 1.0)
            r = body(R._raw("return tostring(LPA_CH.done) .. '|' .. #LPA_KS.sec")).split('|')
            if len(r) < 2: continue
            n = int(r[1])
            while got < n:
                hi = min(n, got + 300)
                on_new([x for x in (_parse(l) for l in body(R._raw(FETCH % (got + 1, hi), timeout=60)).splitlines()) if x])
                got = hi
            if r[0] == 'true': break
            if time.time() - t0 > 400: raise RuntimeError('sweep took too long')
        missed = int(body(R._raw("return tostring(#LPA_CH.missed)")) or 0)
        errs = int(body(R._raw("return tostring(LPA_ERR and #LPA_ERR or 0)")) or 0) if fast else 0
        return missed, errs, time.time() - t0
    finally:
        R._raw(UNCHAIN2 if fast else KS.UNCHAIN)


def _sweep(on_new):
    """Paced zoom-3 sweep; calls on_new(list of raw ops) as replies arrive. Fast (2 in flight) unless it has failed before in this run."""
    blocks = [(x + BW // 2, y + BH // 2) for y in range(0, 1000, BH) for x in range(0, 1000, BW)]
    if FAST['on']:
        missed, errs, secs = _sweep_once(on_new, blocks, True)
        LAST.update(mode='fast', secs=round(secs), missed=missed, errors=errs, fallback=False)
        if not missed and not errs: return len(blocks), 0
        FAST['on'] = False                      # trouble: slow down for good (until the bot restarts) and redo it the old way
        LAST['fallback'] = True
    missed, _, secs = _sweep_once(on_new, blocks, False)
    LAST.update(mode='slow', secs=round(secs) + (LAST.get('secs', 0) if LAST.get('fallback') else 0), missed=missed)
    return len(blocks), missed


def scan(kingdom=None, on_hit=None):
    """-> (kingdom, ops with status, daily limit reached, hits). on_hit(op) fires DURING the sweep for every top-tier op
    (secret level 5, 15 boxes) that is ready to collect (finished, free slot); running ones are not shared because the
    native card shows no timer and people only see an op they cannot collect yet. The map view is put back on the home kingdom."""
    v, home = view()
    target = str(kingdom or home)
    if target != home:
        ok = reachable()
        if int(target) not in ok:
            raise RuntimeError('K%s is not reachable now. Reachable: %s' % (target, ', '.join('K%d' % k for k in ok) or 'none'))
    now_ms, my_uid, maxed = body(R._raw(STATE)).split('|')
    now_ms = int(float(now_ms))
    jack = {int(x) for x in body(R._raw(JACKPOT, timeout=30)).split(',') if x}
    jcfg = _cfg(jack)
    raw, hits = {}, []

    def on_new(batch):
        for s in batch:
            seen = s['uniq'] in raw
            raw[s['uniq']] = s                       # keep the newest copy: an op can be re-occupied (new timer) mid-sweep
            if seen: continue
            if s['task'] in jack:
                o = _status(s, jcfg, now_ms, my_uid)
                if o['status'] == 'ready':
                    hits.append(o)
                    if on_hit: on_hit(o)
    try:
        if v != target and not enter(target): raise RuntimeError('the game did not switch to K%s' % target)
        _sweep(on_new)
    finally:
        go_home()
        # Iris's unhook can restore an older SetWorldMapView and drop the bot's fast-map hook: reinstall it
        body(R._raw("Data.WorldData.__lpa_orig = nil if AE_MAP then AE_MAP.ver = 0 end return 'ok'"))
        FM.install()
    cfg = _cfg({s['task'] for s in raw.values()})
    out = [_status(s, cfg, now_ms, my_uid) for s in raw.values()]
    out.sort(key=lambda o: (o['status'] != 'ready', -o['boxes'], -o['antitoxin'], -o['slots'], o['ready_min']))
    return int(target), out, maxed == 'true', hits


def card(o, sid):
    """Arguments for AE_REPLY(key, 'secret', ...): the game's own covert-op share card (it shows stars and rewards itself)."""
    return (o['x'], o['y'], int(o['uniq']), o['task'], sid, o['owner'])


def label(o):
    if o['status'] == 'running':
        return ('TOP COVERT ' if o['boxes'] >= 15 else 'Covert ') + 'Lv%d | %d boxes | ready in %d min | %s' % (o['level'], o['boxes'], o['ready_min'], ('[%s]' % o['tag']) if o['tag'] else 'no alliance')
    return ('TOP COVERT ' if o['boxes'] >= 15 else 'Covert ') + 'Lv%d | %d boxes | %dk antitoxin | %d slot%s | %s' % (o['level'], o['boxes'], o['antitoxin'] // 1000, o['slots'],
                                                                   '' if o['slots'] == 1 else 's', ('[%s]' % o['tag']) if o['tag'] else 'no alliance')


def summary(k, ops, maxed):
    ready = [o for o in ops if o['status'] == 'ready']
    t = 'K%d covert: %d found, %d ready.' % (k, len(ops), len(ready))
    if ready: t += ' Best %d below.' % min(TOP, len(ready))
    else:
        soon = [o for o in ops if o['status'] == 'running']
        if soon: t += ' Next ready in %d min.' % min(o['ready_min'] for o in soon)
    if maxed: t += ' Plunder limit reached.'
    return t


if __name__ == '__main__':
    R.guard()
    t0 = time.time()
    k, ops, maxed, hits = scan(int(sys.argv[1]) if len(sys.argv) > 1 else None,
                               on_hit=lambda o: print('  LIVE HIT at %.0fs:' % (time.time() - t0), o['x'], o['y'], label(o)))
    print('scan %.0fs' % (time.time() - t0)); print(summary(k, ops, maxed))
    for o in [o for o in ops if o['status'] == 'ready'][:TOP]: print('  ', o['x'], o['y'], label(o))
