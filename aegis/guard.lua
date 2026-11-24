-- Aegis comms guard (installed in memory by run.py before every command; idempotent, versioned).
-- Wraps the game's single send function Network.Send(name, data) and DROPS every message that
-- talks to or about other players: chat, DMs, groups, mail to players, notices, likes, shares, invites,
-- reports, renames, map marks. The game's own traffic (Pong, reads, everything else) passes unchanged.
-- Exceptions: a one-shot permit (G.permit) set by share.py / rename.py. point_share: (G.permit) lets exactly one coordinate-share message
-- (SendChatMessageC2S carrying only a pointMessage share) go to one allowlisted player's DM room, within 30 s.
-- Blocked attempts are counted in AEGIS_GUARD.blocked.
local VER = 12
local G = _G.AEGIS_GUARD
if G and Network.Send == G.wrapper and G.ver == VER then return 'guard ok v' .. VER .. ' (blocked ' .. G.n .. ')' end
if not (G and Network.Send == G.wrapper) then
  G = G or { n = 0, blocked = {} }
  G.orig = Network.Send   -- fresh game, or the game rebuilt Network (an older guard version keeps its saved real send)
end
G.ver = VER
G.permit = nil
local BLOCK = {}
for _, n in ipairs({
  'SendChatMessageC2S', 'SendChatPicC2S', 'ChatGroupCreateC2S', 'ChatGroupInviteC2S', 'ChatGroupChangeNameC2S',
  'ChatGroupConfirmC2S', 'ChatGroupKickOutC2S', 'ChatGroupTransferLeaderC2S', 'ChatGroupQuitC2S', 'ChatGroupSetUpPushC2S',
  'CommentUnionNoticeC2S', 'SpecialPublishUnionNoticeC2S', 'VoteUnionNoticeC2S', 'MarkUnionNoticeC2S', 'LikeMessageC2S',
  'RecallMessageC2S', 'DeleteMessageC2S', 'EditChatNoticeC2S', 'SetPrivateChatSwitchC2S', 'SetPrivateChatCastleLevelC2S',
  'SendUnionMailC2S', 'ShareMailC2S', 'TempleSendMailC2S', 'TempleChangeAnnouncementC2S',
  'ActivityRankLikeC2S', 'BurstLikeMvpC2S', 'AEArenaLikeTopNC2S', 'SpecificLikeC2S', 'VolcanoLikeC2S', 'WeekendBossLikeC2S',
  'ShareQuestionC2S', 'ShareSquadBattleC2S', 'PlayerReportC2S', 'CommanderRenameC2S', 'EditBlockPlayerC2S',
  'InviteJoinUnionC2S', 'UnionEscortInviteConfirmC2S', 'PlaceUnionMarkPointC2S',
}) do BLOCK[n] = true end
local PAT = { 'Chat', 'Mail', 'Like', 'Share', 'Notice', 'Announce', 'Invite', 'Present', 'Friend', 'Rename', 'Report' }
local SAFE = { '^Get', '^SelectLikeRecord', '^Translate', '^Query', '^Read', '^Leave', 'AtClear', '^Login', 'ClearNotice', 'TakeReward', 'ViewMail', 'StorePlayerMail', 'DeletePlayerMail', 'DelAllMail' }
local function allows(name)
  name = tostring(name)
  if BLOCK[name] then return false end
  for _, p in ipairs(PAT) do if name:find(p) then
    for _, s in ipairs(SAFE) do if name:find(s) then return true end end
    return false end end
  return true
end
-- deterministic serializer: a permit names the exact room (roomInfo) a reply may go to
local function ser(v, d) d = d or 0 if type(v) ~= 'table' or d > 6 then return tostring(v) end
  local ks = {} for k in pairs(v) do ks[#ks + 1] = k end table.sort(ks, function(a, b) return tostring(a) < tostring(b) end)
  local t = {} for _, k in ipairs(ks) do local x = v[k] if type(x) ~= 'function' and type(x) ~= 'userdata' then t[#t + 1] = tostring(k) .. '=' .. ser(x, d + 1) end end
  return '{' .. table.concat(t, ',') .. '}' end
G.ser = ser
-- permitted chat shapes: private rooms only (4 = DM, 5 = group), and either
--   point_share: only a pointMessage share, to permit.player's DM or to the exact room permit.roomKey
--   secret_share: only a secretTask (covert op) share with shareType 6, to the exact room permit.roomKey
--   text:        only normalMessage.message.text == permit.text, to the exact room permit.roomKey
--   pic:         only SendChatPicC2S (messageType 18) carrying just a chatPicDto whose data is exactly permit.size bytes,
--                to the exact room permit.roomKey (v10: picture replies while chat text is muted)
--   ChatGroupInviteC2S (v11, the DM 'join' command): one invite of exactly permit.member to exactly group permit.group
local function permitted(name, data)
  local p = G.permit
  if not p or p.left < 1 or os.time() > p.untilT or type(data) ~= 'table' then return false end
  if p.msg == 'ChatGroupConfirmC2S' then
    if name ~= p.msg then return false end
    G.permitData = ser(data)   -- record what the game's own UI sends
    local gid = (((data.groupRoomInfo or {}).roomIdentId or {}).groupCommonIdent or {}).chatGroupId
    return p.any == true or (data.agree == true and tostring(gid) == p.group) end
  if p.msg == 'ChatGroupInviteC2S' then
    if name ~= p.msg then return false end
    local gid = ((((data.roomInfo or {}).roomIdentId or {}).groupCommonIdent) or {}).chatGroupId
    local ids = data.memberId   -- repeated int64: exactly one id, the requester (v12)
    return tostring(gid) == p.group and type(ids) == 'table' and #ids == 1 and next(ids, next(ids)) == nil and tostring(ids[1]) == p.member
  end
  if p.msg == 'SetPrivateChatCastleLevelC2S' then return name == p.msg and data.castleLevel == p.level end
  if p.msg == 'CommanderRenameC2S' then return name == 'CommanderRenameC2S' and type(data.newName) == 'string' and data.newName == p.newName end
  if p.msg == 'pic' then
    if name ~= 'SendChatPicC2S' or data.messageType ~= 18 then return false end
    local ri = data.roomInfo or {}
    if (ri.parentChannel ~= 4 and ri.parentChannel ~= 5) or p.roomKey == nil or ser(ri) ~= p.roomKey then return false end
    local md = data.messageDetail or {}
    local keys = {} for k in pairs(md) do keys[#keys + 1] = k end
    local pic = md.chatPicDto
    return #keys == 1 and keys[1] == 'chatPicDto' and type(pic) == 'table' and type(pic.data) == 'string' and #pic.data == p.size
  end
  if name ~= 'SendChatMessageC2S' then return false end
  local ri = data.roomInfo or {}
  if ri.parentChannel ~= 4 and ri.parentChannel ~= 5 then return false end
  local md = data.messageDetail or {}
  local keys = {} for k in pairs(md) do keys[#keys + 1] = k end
  local roomOk = (p.roomKey ~= nil and ser(ri) == p.roomKey) or
                 (p.player ~= nil and ri.parentChannel == 4 and tostring(((ri.roomIdentId or {}).PersonalCommonIdent or {}).playerId) == tostring(p.player))
  if not roomOk or #keys ~= 1 then return false end
  if p.msg == 'point_share' or p.msg == 'secret_share' then
    local sm = md.shareMessageDto
    if keys[1] ~= 'shareMessageDto' or type(sm) ~= 'table' then return false end
    local n = 0 for _ in pairs(sm) do n = n + 1 end
    if n ~= 1 then return false end                        -- exactly one kind of card, nothing riding along
    if p.msg == 'point_share' then return type(sm.pointMessage) == 'table' end
    return type(sm.secretTask) == 'table' and type(sm.secretTask.content) == 'string' and sm.secretTask.content:find('"shareType":6', 1, true) ~= nil
  end
  if p.msg == 'text' then local nm = md.normalMessage
    return keys[1] == 'normalMessage' and type(nm) == 'table' and type(nm.message) == 'table' and nm.message.text == p.text end
  return false
end
G.allows = allows
G.permitted = permitted
G.wrapper = function(name, data, ...)
  if permitted(name, data) then
    G.permit.left = G.permit.left - 1
    G.sent = (G.sent or 0) + 1; G.lastSent = os.date('%H:%M:%S') .. ' ' .. tostring(name) .. ' ' .. tostring(G.permit.player or G.permit.newName)
    return G.orig(name, data, ...)
  end
  if not allows(name) then
    G.n = G.n + 1; G.blocked[#G.blocked + 1] = os.date('%H:%M:%S') .. ' ' .. tostring(name)
    if #G.blocked > 50 then table.remove(G.blocked, 1) end
    return nil
  end
  return G.orig(name, data, ...)
end
Network.Send = G.wrapper
_G.AEGIS_GUARD = G
return 'guard installed v' .. VER
