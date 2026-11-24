"""kvk_sync.py - Kingdom War (ZoneContest) points -> YOUR OWN database. Ships WITHOUT a database: until you configure one
it only does a dry run (read from the game and print). Read-only in the game (the same requests the Kingdom War screen sends):
    QueryZoneContestInfoC2S{activityId}                    refresh the kingdom totals (PushZoneContestInfoS2C)
    GetActivityRankInfoC2S{activityId, rankType=7 / 6}     alliance ranking / player ranking (top 100)
Needs sanctuary (castle) level 15 on the account.
    python aegis/kvk_sync.py            dry run: read and print, write nothing
    python aegis/kvk_sync.py --apply    write the three tables

To store the data, bring your own PostgREST-compatible database (Supabase works; so does plain PostgREST over Postgres):
  1. create the tables with docs/kingdom_war_schema.sql
  2. set KVK_DB_URL (e.g. https://<project>.supabase.co/rest/v1) and KVK_DB_KEY (a service key) in the environment
  3. optionally KVK_HOME=<kingdom id> (default 263): only that kingdom's rows are stored
The rows hold player names, ids, power and kills: keep that database private and check the game's and your
alliance's rules before storing other people's data. Nothing here is on by default."""
import os, sys, time, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

HOME = int(os.environ.get('KVK_HOME', '263'))   # only this kingdom's rows are stored
CATS = ['alliance_duel', 'alliance_duel_vip', 'arena', 'elixir_scramble', 'world_boss', 'world_boss_damage',
        'escort_raids', 'arms_race', 'arena_3v3', 'peak_arena']          # ZoneContestScoreTypeEnum 0..9

FIND = r'''local AM = require('AbyssEmpire.Logic.Activity.ActivityManager')
for id, a in pairs(AM.Activities) do if rawget(a, 'zoneContestDetail') ~= nil then return tostring(id) end end
return 'none' '''

REFRESH = "local ok = pcall(require('Logic.Proto.Send.activity').QueryZoneContestInfoC2S, {activityId = %d}) return tostring(ok)"

KINGDOMS = r'''local a = require('AbyssEmpire.Logic.Activity.ActivityManager').Activities[%d]
local d = rawget(a, 'zoneContestDetail') or {} local m = rawget(a, 'zoneContestMatch') or {}
local E = require('Logic.Proto.Enum.ZoneContestActivityStageEnum') local G = require('Logic.Proto.Enum.ZoneContestGameServerStageEnum')
local function en(t, v) for k, x in pairs(t) do if x == v then return tostring(k) end end return tostring(v) end
local function s(v) return (tostring(v or ''):gsub('[|%%c]', ' ')) end
local o = { 'H|' .. en(E, d.activityStage) .. '|' .. en(G, d.gameServerStage) .. '|' .. string.format('%%d', d.gameServerStageEndTime or 0) }
for _, g in pairs(d.gameServerInfos or {}) do
  local c = {} for i = 0, 9 do c[i] = 0 end
  for k, v in pairs(g.scoreMap or {}) do local key, val = k, v if type(v) == 'table' then key, val = v.key or k, v.value end c[tonumber(key) or -1] = val end
  local u, p = g.unionInfo or {}, g.playerInfo or {}
  local row = { 'K', g.gameServerId, g.templeScore or 0, (m.winCountMap or {})[g.gameServerId] or 0, s(u.alias or u.unionAlias), s(p.name), string.format('%%d', g.playerScore or 0) }
  for i = 0, 9 do row[#row + 1] = string.format('%%d', c[i] or 0) end
  o[#o + 1] = table.concat(row, '|')
end
return table.concat(o, '\n')'''

HOOK = r'''AE_KW = { log = {}, orig = {} }
for k, f in pairs(MessageReceive) do if type(f) == 'function' and tostring(k):find('ActivityRankInfo') then AE_KW.orig[k] = f
  MessageReceive[k] = function(d, ...) AE_KW.log[#AE_KW.log + 1] = d return f(d, ...) end end end
local S = require('Logic.Proto.Send.activity')
pcall(S.GetActivityRankInfoC2S, {activityId = %d, rankType = 7}) pcall(S.GetActivityRankInfoC2S, {activityId = %d, rankType = 6})
return 'sent' '''

RANKS = r'''if not AE_KW then return '' end
for k, f in pairs(AE_KW.orig) do MessageReceive[k] = f end
local function s(v) return (tostring(v or ''):gsub('[|%c]', ' ')) end
local function n(v) return string.format('%d', tonumber(v) or 0) end
local o = {}
for _, d in ipairs(AE_KW.log) do for _, e in ipairs(d.topRankInfos or {}) do
  if d.rankType == 7 then local u = e.unionSimpleInfo or {}
    o[#o + 1] = table.concat({ 'A', n(e.rank), n(e.score), n(u.serverId), n(u.unionId), s(u.unionAlias), s(u.unionName), s(u.leaderName) }, '|')
  elseif d.rankType == 6 then local p = e.playerSimpleData or {} local u = p.unionSimpleInfo or {}
    o[#o + 1] = table.concat({ 'P', n(e.rank), n(e.score), n(p.serverId), n(p.playerId), s(p.name), s(u.unionAlias), n(u.unionId), n(p.totalAbility), n(p.killCount), n(p.level) }, '|')
  end end end
AE_KW = nil return table.concat(o, '\n')'''


def body(r):
    if not r.startswith('OK'): raise RuntimeError(r[:200])
    return r.split('\n', 1)[1].strip() if '\n' in r else ''


def lua(code, timeout=20):
    return body(R.run(code, allow_send=True, timeout=timeout))


def read():
    """-> snapshot dict (nothing written). Raises if the account cannot see Kingdom War."""
    aid = lua(FIND)
    if not aid.isdigit(): raise RuntimeError('Kingdom War not in the account\'s activity list (needs sanctuary 15)')
    aid = int(aid)
    lua(REFRESH % aid); time.sleep(3)                            # fresh kingdom totals
    kings, head = [], None
    for l in lua(KINGDOMS % aid).splitlines():
        p = l.split('|')
        if p[0] == 'H': head = p
        elif p[0] == 'K' and len(p) >= 17:
            c = [int(x) for x in p[7:17]]
            kings.append(dict(server_id=int(p[1]), temple_score=int(p[2]), season_wins=int(p[3]), top_alliance_tag=p[4] or None,
                              top_player_name=p[5] or None, top_player_score=int(p[6]) or None, total=sum(c),
                              scores={str(i): v for i, v in enumerate(c) if v}, **dict(zip(CATS, c))))
    lua(HOOK % (aid, aid)); time.sleep(5)
    alli, play = [], []
    for l in lua(RANKS).splitlines():
        p = l.split('|')
        if p[0] == 'A' and len(p) >= 8:
            alli.append(dict(rank=int(p[1]), score=int(p[2]), server_id=int(p[3]) or None, union_id=int(p[4]), alliance_tag=p[5] or None,
                             alliance_name=p[6] or None, leader_name=p[7] or None))
        elif p[0] == 'P' and len(p) >= 11:
            play.append(dict(rank=int(p[1]), score=int(p[2]), server_id=int(p[3]) or None, game_player_id=int(p[4]), name=p[5] or None,
                             alliance_tag=p[6] or None, union_id=int(p[7]) or None, power=int(p[8]), kills=int(p[9]), castle_level=int(p[10])))
    end_ms = int(head[3]) if head else 0
    return dict(activity_id=aid, round=head[1] if head else None, phase=head[2] if head else None,
                phase_ends_at=dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc).isoformat() if end_ms else None,
                kingdoms=kings, alliances=alli, players=play)


def sync(apply, rest=None, say=print):
    snap = read()
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    ks = sorted(snap['kingdoms'], key=lambda k: -k['total'])
    say('kingdom war: activity %d %s %s (phase ends %s)' % (snap['activity_id'], snap['round'], snap['phase'], snap['phase_ends_at']))
    say('kingdom war: kingdoms ' + ', '.join('K%d %s' % (k['server_id'], format(k['total'], ',')) for k in ks))
    by = {}
    for a in snap['alliances']: by.setdefault(a['server_id'], []).append(a['score'])
    say('kingdom war: %d alliances on the board (%s), %d players' % (len(snap['alliances']),
        ', '.join('K%s %d / %s' % (s, len(v), format(sum(v), ',')) for s, v in sorted(by.items(), key=lambda kv: str(kv[0]))), len(snap['players'])))
    if not snap['kingdoms']: raise RuntimeError('no kingdom rows read')
    snap['kingdoms'] = [k for k in snap['kingdoms'] if k['server_id'] == HOME]
    snap['alliances'] = [a for a in snap['alliances'] if a['server_id'] == HOME]
    snap['players'] = [p for p in snap['players'] if p['server_id'] == HOME]
    say('kingdom war: storing K%d only: %d kingdom row, %d alliances, %d players' % (HOME, len(snap['kingdoms']), len(snap['alliances']), len(snap['players'])))
    if not apply:
        say('kingdom war: preview only, nothing saved'); return snap
    common = dict(taken_at=now, activity_id=snap['activity_id'])
    rest('POST', 'kingdom_war_kingdom_scores?on_conflict=taken_at,server_id',
         [dict(common, round=snap['round'], phase=snap['phase'], phase_ends_at=snap['phase_ends_at'], **k) for k in snap['kingdoms']],
         'resolution=merge-duplicates,return=minimal')
    if snap['alliances']:
        rest('POST', 'kingdom_war_alliance_scores?on_conflict=taken_at,union_id', [dict(common, **a) for a in snap['alliances']],
             'resolution=merge-duplicates,return=minimal')
    if snap['players']:
        rest('POST', 'kingdom_war_player_scores?on_conflict=taken_at,game_player_id', [dict(common, **p) for p in snap['players']],
             'resolution=merge-duplicates,return=minimal')
    say('kingdom war: saved %d kingdoms, %d alliances, %d players at %s' % (len(snap['kingdoms']), len(snap['alliances']), len(snap['players']), now))
    return snap


def make_rest():
    """PostgREST client from KVK_DB_URL / KVK_DB_KEY. Raises if they are not set."""
    import urllib.request
    url, key = os.environ.get('KVK_DB_URL'), os.environ.get('KVK_DB_KEY')
    if not url or not key:
        raise SystemExit('--apply needs a database: set KVK_DB_URL and KVK_DB_KEY (see the top of this file)')
    def rest(method, path, rows=None, prefer=None):
        req = urllib.request.Request(url.rstrip('/') + '/' + path, method=method,
                                     data=json.dumps(rows).encode() if rows is not None else None)
        req.add_header('apikey', key); req.add_header('Authorization', 'Bearer ' + key)
        req.add_header('Content-Type', 'application/json')
        if prefer: req.add_header('Prefer', prefer)
        with urllib.request.urlopen(req, timeout=30) as r: return r.read()
    return rest


if __name__ == '__main__':
    apply = '--apply' in sys.argv
    sync(apply, make_rest() if apply else None)
