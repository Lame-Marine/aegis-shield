-- listener.lua: queue incoming DM (channel 4) and group (channel 5) chat in game memory for the bot to poll.
-- Idempotent. Wraps MessageReceive.PushChatMessageS2C (the game's handler still runs unchanged).
-- AE_IN.q = list of {id, ch, child, room (serialized roomIdentId), roomKey, from, fromId, text, t}
-- AE_IN.raw = last few raw messages (shape capture while developing)
local MR = MessageReceive
if AE_IN and MR.PushChatMessageS2C == AE_IN.wrapper then return 'listener ok (' .. #AE_IN.q .. ' queued)' end
local function ser(v, d) d = d or 0 if type(v) ~= 'table' or d > 6 then return type(v) == 'string' and ('"' .. v .. '"') or tostring(v) end
  local ks = {} for k in pairs(v) do ks[#ks + 1] = k end table.sort(ks, function(a, b) return tostring(a) < tostring(b) end)
  local t = {} for _, k in ipairs(ks) do local x = v[k] if type(x) ~= 'function' and type(x) ~= 'userdata' then t[#t + 1] = tostring(k) .. '=' .. ser(x, d + 1) end end
  return '{' .. table.concat(t, ',') .. '}' end
AE_IN = AE_IN or { q = {}, raw = {}, seen = {} }
AE_IN.ser = ser
AE_IN.orig = MR.PushChatMessageS2C
AE_IN.wrapper = function(d, ...)
  pcall(function()
    AE_IN.raw[#AE_IN.raw + 1] = ser(d) if #AE_IN.raw > 6 then table.remove(AE_IN.raw, 1) end
  end)
  return AE_IN.orig(d, ...)
end
MR.PushChatMessageS2C = AE_IN.wrapper
return 'listener installed'
