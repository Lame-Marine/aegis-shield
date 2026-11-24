-- fastmap.lua: whole-kingdom map in game memory, refreshed with ONE world-map request.
-- The server only sends cities that are new compared with the previous view in this session, so we
-- first send a 2x2 "reset" view, then one 1000x1000 view at zoom 4: the reply holds every city (~14.6k, ~4 s).
-- Idempotent install. API (called by fastmap.py):
--   AE_MAP.refresh()            -> sends the two requests; AE_MAP.done becomes true when the full reply arrives
--   AE_MAP.query(kind, pat)     -> matching rows as text lines id|name|tag|x|y|power|sid|shield
--                                  kind: 'player' (Lua pattern on lowercased name), 'alliance' (pattern on tag,
--                                  foreign-server cities only), 'invaders' (every city whose sid is not home)
--   AE_MAP.at(id)               -> current row for a player id, or nil
if AE_MAP and AE_MAP.ver == 5 then return 'fastmap ok' end
AE_MAP = { ver = 5, rows = {}, n = 0, done = false, t = 0, home = tostring(Data.UserData.serverId) }
local W = Data.WorldData
if not W.__am_orig then W.__am_orig = W.SetWorldMapView end
W.SetWorldMapView = function(self, data)
  local M = AE_MAP
  if M and M.pending and data and data.width == 1000 and data.center and data.center.x == 500 and data.center.y == 500 then
    local rows, n = {}, 0
    for _, p in pairs(data.worldPointInfos or {}) do
      if p.type == 1 and p.worldCityInfo and p.point then local c = p.worldCityInfo
        n = n + 1
        rows[tostring(c.playerId)] = { name = tostring(c.playerName or ''), tag = tostring(c.playerUnionShortName or ''),
          x = p.point.x, y = p.point.y, power = math.floor(c.playerPower or 0), sid = tostring(c.playerSid), shield = c.shielding and 1 or 0,
          level = c.level or 0, garrison = c.garrisonNum or 0, kills = math.floor(c.killEnemyCount or 0), defend = c.defendReducedValue or 0, state = c.state or 0 }
      end
      if p.type == 10 and p.worldThroneInfo then                  -- royal city: owner, shield, fight window
        local b = p.worldThroneInfo.worldTempleBattleBuildingInfo or {}
        M.throne = table.concat({ tostring(b.shield), string.format('%d', b.shieldEndTime or 0), string.format('%d', b.fightEndTime or 0),
          string.format('%d', b.truceEndTime or 0), tostring(b.occupied), tostring(b.occupiedUnionShortName or ''), tostring(b.occupiedUnionName or ''),
          tostring(b.occupiedUnionSid or ''), tostring(b.state), tostring(b.isCross), tostring(b.occupiedMarchAmount or 0) }, '|')
      end
    end
    M.rows, M.n, M.t, M.pending, M.done = rows, n, os.time(), false, true
  end
  return W.__am_orig(self, data)
end
function AE_MAP.refresh()
  local S = require('Logic.Proto.Send.world')
  local sid = Data.WorldData.serverId
  AE_MAP.done, AE_MAP.pending = false, true
  S.WorldMapViewC2S({ viewLevel = 4, width = 2, height = 2, center = { sid = sid, x = 1, y = 1 }, openView = false })
  S.WorldMapViewC2S({ viewLevel = 4, width = 1000, height = 1000, center = { sid = sid, x = 500, y = 500 }, openView = false })
  return 'refreshing'
end
local function line(id, r) return table.concat({ id, r.name, r.tag, r.x, r.y, r.power, r.sid, r.shield, r.level, r.garrison, r.kills, r.defend, r.state }, '|') end
function AE_MAP.query(kind, pat)
  local out = {}
  for id, r in pairs(AE_MAP.rows) do
    local hit = false
    if kind == 'player' then hit = r.name:lower():find(pat) ~= nil
    elseif kind == 'alliance' then hit = r.sid ~= AE_MAP.home and r.tag:lower():find(pat) ~= nil
    elseif kind == 'invaders' then hit = r.sid ~= AE_MAP.home
    elseif kind == 'hometag' then hit = r.sid == AE_MAP.home and r.tag:lower():find(pat) ~= nil end
    if hit then out[#out + 1] = line(id, r) end
  end
  return table.concat(out, '\n')
end
-- home-kingdom power ladder: total count, then the top N as name|power|level (for grading invaders)
function AE_MAP.ladder(n)
  local L = {}
  for _, r in pairs(AE_MAP.rows) do if r.sid == AE_MAP.home then L[#L + 1] = r end end
  table.sort(L, function(a, b) return a.power > b.power end)
  local out = { tostring(#L) }
  for i = 1, math.min(n or 200, #L) do out[#out + 1] = L[i].name .. '|' .. L[i].power .. '|' .. L[i].level end
  return table.concat(out, string.char(10))
end
-- allied home-kingdom cities for the territory model: x|y|tag lines (no names, no ids)
function AE_MAP.allied()
  local out = {}
  for _, r in pairs(AE_MAP.rows) do
    if r.sid == AE_MAP.home and r.tag ~= '' then out[#out + 1] = r.x .. '|' .. r.y .. '|' .. r.tag end
  end
  return table.concat(out, string.char(10))
end
function AE_MAP.at(id) local r = AE_MAP.rows[tostring(id)] return r and line(tostring(id), r) or nil end
return 'fastmap installed'
