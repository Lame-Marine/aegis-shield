-- reply.lua: send ONE reply into the room a queued message came from. Installed once; called as
--   AE_REPLY(key, 'share', x, y, label[, sid]) -> coordinate card (sid defaults to the current map server) (same message the in-game Share button sends)
--   AE_REPLY(key, 'text', text)           -> fixed-template text chosen by bot.py (never the sender's words)
--   AE_REPLY(key, 'pic', file, w, h)      -> picture message (JPEG file in the game's folder); results in AE_PIC_LOG()
-- Each call opens a one-shot guard permit bound to that exact roomInfo, sends, and closes the permit.
if AE_REPLY_V == 11 then return 'reply ok' end
AE_REPLY_V = 11
-- capture server errors for our chat sends (e.g. sending too fast); the game's own handler still runs
AE_REPLY_ERR = AE_REPLY_ERR or {}
local MR = MessageReceive
if not MR.__ar_ec then MR.__ar_ec = MR.ErrorCode
  MR.ErrorCode = function(d, ...) if d and d.name == 'SendChatMessageC2S' then AE_REPLY_ERR[#AE_REPLY_ERR + 1] = os.date('%H:%M:%S') .. ' code ' .. tostring(d.code) end
    return MR.__ar_ec(d, ...) end end
-- picture send results (the server answers a picture with PushChatPicReceiveS2C or PushChatPicErrorS2C)
AE_PIC = AE_PIC or {}
for _, nm in ipairs({ 'PushChatPicReceiveS2C', 'PushChatPicErrorS2C' }) do
  if type(MR[nm]) == 'function' and not MR['__ae_' .. nm] then
    MR['__ae_' .. nm] = MR[nm]
    MR[nm] = function(d, ...) AE_PIC[#AE_PIC + 1] = os.date('%H:%M:%S') .. ' ' .. nm .. ' uuid=' .. tostring(d and d.clientUuid) return MR['__ae_' .. nm](d, ...) end
  end
end
function AE_PIC_LOG() local r = table.concat(AE_PIC, '; ') AE_PIC = {} return r end
-- home kingdom of a DM sender (senderInfo.serverId on their DM messages; works while they are away on KvK)
function AE_SENDER_SID(pid)
  local id = math.tointeger(tonumber(pid)) if not id then return 'nil' end
  for _, ch in ipairs({ 4, 5 }) do for _, r in pairs(Data.ChatData:GetRoomListByChannelType(ch) or {}) do
    for _, m in pairs(r.m_Messages or {}) do
      local si = m.senderInfo
      if si and si.playerId == id and si.serverId then return tostring(si.serverId) end
    end
  end end
  return 'nil'
end
-- group invite for the DM 'join' command: AE_INVITE(groupName, playerId) -> 'sent' | 'no_group' | 'failed ...'
function AE_INVITE(gname, pid)
  local G = _G.AEGIS_GUARD
  local id = math.tointeger(tonumber(pid)) if not id then return 'bad_id' end
  for _, r in pairs(Data.ChatData:GetRoomListByChannelType(5) or {}) do
    local ok, nm = pcall(function() return r:GetName() end)
    if ok and nm == gname then
      -- no membership check: always sent, the game handles members (operator, 2026-11-07)
      local ri = r.m_Dto.roomInfo
      local gid = ri.roomIdentId.groupCommonIdent.chatGroupId
      G.permit = { msg = 'ChatGroupInviteC2S', group = tostring(gid), member = tostring(id), left = 1, untilT = os.time() + 30 }
      local ok2, err = pcall(require('Logic.Proto.Send.chat').ChatGroupInviteC2S, { roomInfo = r:GetChatRoomDto() or ri, memberId = { id } })   -- memberId is a repeated field (as the game's UIChatGroupPanel sends it)
      local passed = G.permit.left == 0
      G.permit = nil
      return (ok2 and passed) and 'sent' or ('failed ' .. tostring(err) .. ' passed=' .. tostring(passed))
    end
  end
  return 'no_group'
end
function AE_REPLY_ERRS() local r = table.concat(AE_REPLY_ERR, '; ') AE_REPLY_ERR = {} return r end
function AE_REPLY(key, kind, a, b, c, d, e, f)
  local G = _G.AEGIS_GUARD
  local ri = AE_IN and AE_IN.rooms[key]
  if not G or not ri then return 'no_room' end
  if ri.parentChannel ~= 4 and ri.parentChannel ~= 5 then return 'not_private' end
  local data
  if kind == 'share' then
    local content = string.format('{"name":%q,"shareType":1,"sid":%d,"treasureId":0,"x":%d,"y":%d}', c, tonumber(d) or Data.WorldData.serverId, a, b)
    data = { roomInfo = ri, messageType = 19, messageDetail = { shareMessageDto = { pointMessage = { x = a, y = b, content = content } } } }
    G.permit = { msg = 'point_share', roomKey = G.ser(ri), left = 1, untilT = os.time() + 30 }
  elseif kind == 'secret' then                    -- covert op card: AE_REPLY(key, 'secret', x, y, uniqueId, taskId, sid, ownerLabel)
    local content = string.format('{"playerName":%q,"secretTaskId":%d,"shareType":6,"sid":%d,"x":%d,"y":%d}', f or '', d, e, a, b)
    data = { roomInfo = ri, messageType = 19, messageDetail = { shareMessageDto = { secretTask = { x = a, y = b, uniqueId = c, content = content } } } }
    G.permit = { msg = 'secret_share', roomKey = G.ser(ri), left = 1, untilT = os.time() + 30 }
  elseif kind == 'pic' then                       -- picture: AE_REPLY(key, 'pic', fileInGameFolder, width, height) (JPEG, <= 750x1664, <= 2 MB)
    local f = io.open(a, 'rb') if not f then return 'no_file' end
    local bytes = f:read('*a') f:close()
    if #bytes == 0 or #bytes > 2097152 then return 'bad_size ' .. #bytes end
    local uuid = os.time() * 1000 + math.random(0, 999)
    data = { roomInfo = ri, messageType = 18, messageDetail = { chatPicDto = { data = bytes, width = b, height = c, clientUuid = uuid, chatName = '', chatThumbnailName = '' } } }
    G.permit = { msg = 'pic', size = #bytes, roomKey = G.ser(ri), left = 1, untilT = os.time() + 30 }
    local ok, err = pcall(require('Logic.Proto.Send.chat').SendChatPicC2S, data)
    local passed = G.permit.left == 0
    G.permit = nil
    return (ok and passed) and ('sent uuid=' .. uuid) or ('failed ' .. tostring(err) .. ' passed=' .. tostring(passed))
  elseif kind == 'text' then
    data = { roomInfo = ri, messageType = 1, messageDetail = { normalMessage = { message = { text = a } } } }
    G.permit = { msg = 'text', text = a, roomKey = G.ser(ri), left = 1, untilT = os.time() + 30 }
  else return 'bad_kind' end
  local ok, err = pcall(require('Logic.Proto.Send.chat').SendChatMessageC2S, data)
  local passed = G.permit.left == 0
  G.permit = nil
  return (ok and passed) and 'sent' or ('failed ' .. tostring(err) .. ' passed=' .. tostring(passed))
end
return 'reply installed'
