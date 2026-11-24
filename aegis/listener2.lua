-- listener.lua v6: queue incoming DM (channel 4) and group (channel 5) chat for the bot. Idempotent.
-- Wraps MessageReceive.PushChatMessageS2C (the game's handler still runs unchanged). Never stores public chat.
-- v6 (2026-11-15): the sweep only looks at messages younger than SWEEP_AGE (1 h), seen ids are kept 2 h. In v5 the window was
-- 'since install' while seen ids expired after 2 h, so every message since the install was re-queued every 2 h and the bot
-- answered old DMs again all night (Emmalyn's 'invaders'/'tutu' searches, join invites).
-- v5 (2026-11-14): a FIRST message from someone new (a brand-new DM room) does not come through PushChatMessageS2C
-- (a player's 'Join' at 12:14 sat in her new DM room, never queued). So take() also sweeps the DM and group rooms
-- every SCAN s for messages newer than the install time that were not queued yet (dedup by messageId).
--   AE_IN.q      = queued messages, each {key, ch, from, fromId, text, atMe, t}; the bot drains them with AE_IN.take()
--   AE_IN.rooms  = key -> the message's roomInfo table (replies go back to exactly this room)
if AE_IN and AE_IN.ver == 6 and MessageReceive.PushChatMessageS2C == AE_IN.wrapper then return 'listener ok (' .. #AE_IN.q .. ' queued)' end
local MR = MessageReceive
local old = AE_IN
AE_IN = { ver = 6, order = {}, q = {}, rooms = {}, n = 0, seen = {}, since = os.time(), scanAt = 0, swept = 0,
          me = string.format('%d', Data.UserData.gameUid or 0), orig = (old and old.orig) or MR.PushChatMessageS2C }
local SEP, RS, SCAN, SWEEP_AGE, SEEN_KEEP = string.char(31), string.char(30), 10, 3600, 7200   -- SWEEP_AGE must stay below SEEN_KEEP
local function idstr(v) return type(v) == 'number' and string.format('%d', v) or tostring(v) end

function AE_IN.add(ri, si, sm, how)
  if not ri or (ri.parentChannel ~= 4 and ri.parentChannel ~= 5) then return end
  si, sm = si or {}, sm or {}
  if sm.messageId == nil then return end
  local key = idstr(sm.messageId)
  if AE_IN.seen[key] then return end
  AE_IN.seen[key] = os.time()
  if idstr(sm.senderId) == AE_IN.me or tostring(si.name) == tostring(Data.CommanderData.commanderName) then return end
  local nm = ((sm.messageDetail or {}).normalMessage) or {}
  local text = tostring(((nm.message or {}).text) or '')
  if text == '' then return end
  local atMe = false
  for _, a in pairs(nm.atPlayer or {}) do local pid = type(a) == 'table' and (a.playerId or a.id) or a
    if idstr(pid) == AE_IN.me then atMe = true end end
  AE_IN.n = AE_IN.n + 1
  if how == 'sweep' then AE_IN.swept = AE_IN.swept + 1 end
  AE_IN.rooms[key] = ri
  AE_IN.order[#AE_IN.order + 1] = key
  while #AE_IN.order > 30 do AE_IN.rooms[table.remove(AE_IN.order, 1)] = nil end   -- keep only recent room refs
  AE_IN.q[#AE_IN.q + 1] = { key = key, ch = ri.parentChannel, from = tostring(si.name), fromId = idstr(sm.senderId), text = text, atMe = atMe, t = os.time() }
  if #AE_IN.q > 50 then table.remove(AE_IN.q, 1) end
end

AE_IN.wrapper = function(d, ...)
  pcall(function() local m = (d and d.message) or {} AE_IN.add(d and d.roomInfo, m.senderInfo, m.sourceMessage, 'push') end)
  return AE_IN.orig(d, ...)
end

function AE_IN.sweep()
  local since = math.max(AE_IN.since, os.time() - SWEEP_AGE) * 1000
  for _, ch in ipairs({ 4, 5 }) do
    for _, r in pairs(Data.ChatData:GetRoomListByChannelType(ch) or {}) do
      pcall(function()
        local ri = r.m_Dto and r.m_Dto.roomInfo
        for _, m in pairs(r.m_Messages or {}) do
          local sm = (m.m_Dto or {}).sourceMessage
          if sm and (sm.timeMills or 0) >= since and sm.messageId and not AE_IN.seen[idstr(sm.messageId)] then
            AE_IN.add(ri, m.senderInfo or (m.m_Dto or {}).senderInfo, sm, 'sweep')
          end
        end
      end)
    end
  end
  local now = os.time()
  for k, t in pairs(AE_IN.seen) do if now - t > SEEN_KEEP then AE_IN.seen[k] = nil end end
end

function AE_IN.take()
  if os.time() - AE_IN.scanAt >= SCAN then AE_IN.scanAt = os.time() pcall(AE_IN.sweep) end
  local out = {}
  for _, m in ipairs(AE_IN.q) do
    out[#out + 1] = table.concat({ m.key, m.ch, m.from, m.fromId, tostring(m.atMe), m.t, (m.text:gsub('[%c' .. SEP .. RS .. ']', ' ')) }, SEP)
  end
  AE_IN.q = {}
  return table.concat(out, RS)
end
MR.PushChatMessageS2C = AE_IN.wrapper
return 'listener installed v6 me=' .. AE_IN.me
