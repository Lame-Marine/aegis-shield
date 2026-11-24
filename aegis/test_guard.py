"""test_guard.py - prove the comms block works. Sends NOTHING to the server.
1. static: run() refuses chat/mail/social code and any server request without allow_send.
2. in game: guard installed and Network.Send is the wrapper.
3. in game, spy test: the real send is swapped for a recorder inside one pcall, blocked and allowed names
   are pushed through the wrapper, the real send is restored. Blocked names must never reach the recorder.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run as R

fails = 0
def ok(cond, what):
    global fails
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond: fails += 1

for code in ["require('Logic.Proto.Send.chat').SendChatMessageC2S({})", "room:SendChat('hi')", "Network.Send('SendUnionMailC2S',{})",
             "_G.AEGIS_GUARD=nil", "Network.Send=print", "MessageSend_union.InviteJoinUnionC2S({})", "x.ShareMailC2S({})"]:
    try: R.check(code, allow_send=True); ok(False, 'refused even with allow_send: ' + code)
    except R.Refused: ok(True, 'refused even with allow_send: ' + code)
for code in ["Network.Send('Pong',{})", "require('Logic.Proto.Send.mail').ReadMailC2S({})", "Data.RescueData:DoReciveRescueReward()"]:
    try: R.check(code); ok(False, 'refused without allow_send: ' + code)
    except R.Refused: ok(True, 'refused without allow_send: ' + code)
try: R.check("return Data.UserData.level"); ok(True, 'plain read allowed')
except R.Refused: ok(False, 'plain read allowed')

print('guard:', R.guard())
r = R._raw("return tostring(Network.Send == _G.AEGIS_GUARD.wrapper)")
ok(r.strip().endswith('true'), 'Network.Send is the guard wrapper in game')

SPY = r"""
local G = _G.AEGIS_GUARD
local real, seen, n0, b0 = G.orig, {}, G.n, #G.blocked
G.orig = function(name) seen[#seen + 1] = tostring(name) end
local ok, err = pcall(function()
  for _, n in ipairs({'SendChatMessageC2S', 'SendChatPicC2S', 'SendUnionMailC2S', 'ChatGroupInviteC2S', 'LikeMessageC2S',
                      'InviteJoinUnionC2S', 'PlaceUnionMarkPointC2S', 'SomeNewChatThingC2S', 'Pong', 'GetPlayerMailsC2S'}) do
    Network.Send(n, {})
  end
end)
G.orig = real
G.n = n0; for i = #G.blocked, b0 + 1, -1 do table.remove(G.blocked, i) end   -- test drops are not real attempts
return 'restored=' .. tostring(G.orig == real) .. ' err=' .. tostring(err) .. ' reached=' .. table.concat(seen, ',')
"""
r = R._raw(SPY)
print('spy:', r.strip().replace('\n', ' '))
ok('restored=true' in r, 'real send restored after spy test')
ok('reached=Pong,GetPlayerMailsC2S' in r, 'only Pong and GetPlayerMailsC2S got through; all 8 social sends dropped')

PERMIT = r"""
local G = _G.AEGIS_GUARD
local real, seen, n0, b0, s0 = G.orig, {}, G.n, #G.blocked, G.sent
G.orig = function(name, d) seen[#seen + 1] = d.tag end
local function dm(pid, md, tag) return {tag = tag, roomInfo = {parentChannel = 4, childChannel = 1,
  roomIdentId = {roomIdentDetail = 'PersonalCommonIdent', PersonalCommonIdent = {playerId = pid, otherPlayerId = 1}}}, messageDetail = md, messageType = 19} end
local point = {shareMessageDto = {pointMessage = {x = 1, y = 2, content = '{}'}}}
local ok, err = pcall(function()
  G.permit = {msg = 'point_share', player = 111, left = 1, untilT = os.time() + 30}
  Network.Send('SendChatMessageC2S', dm(111, {normalMessage = {content = 'hi'}}, 'text_to_allowed'))
  Network.Send('SendChatMessageC2S', dm(222, point, 'point_to_other'))
  Network.Send('SendChatMessageC2S', dm(111, {shareMessageDto = point.shareMessageDto, normalMessage = {content = 'x'}}, 'point_plus_text'))
  Network.Send('SendUnionMailC2S', dm(111, point, 'mail_with_permit'))
  Network.Send('SendChatMessageC2S', dm(111, point, 'point_to_allowed'))
  Network.Send('SendChatMessageC2S', dm(111, point, 'second_point_used_up'))
  G.permit = {msg = 'point_share', player = 111, left = 1, untilT = os.time() - 1}
  Network.Send('SendChatMessageC2S', dm(111, point, 'expired_permit'))
  G.permit = {msg = 'CommanderRenameC2S', newName = 'Aegis', left = 1, untilT = os.time() + 30}
  Network.Send('SendChatMessageC2S', dm(111, point, 'point_under_rename_permit'))
  Network.Send('CommanderRenameC2S', {tag = 'rename_other_name', newName = 'Other'})
  Network.Send('CommanderRenameC2S', {tag = 'rename_ok', newName = 'Aegis'})
  Network.Send('CommanderRenameC2S', {tag = 'rename_reuse', newName = 'Aegis'})
end)
G.permit = nil; G.orig = real
G.n = n0; G.sent = s0; for i = #G.blocked, b0 + 1, -1 do table.remove(G.blocked, i) end
return 'restored=' .. tostring(G.orig == real) .. ' err=' .. tostring(err) .. ' reached=' .. table.concat(seen, ',')
"""
r = R._raw(PERMIT)
print('permit:', r.strip().replace('\n', ' '))
ok('restored=true' in r and 'err=nil' in r, 'permit test ran and restored the real send')
ok(r.strip().endswith('reached=point_to_allowed,rename_ok'), 'permit lets ONLY one point share to the permitted player and one exact rename (text, other player, mixed, mail, reuse, expired, wrong name all dropped)')

SECRET = r"""
local G = _G.AEGIS_GUARD
local real, seen, n0, b0, s0 = G.orig, {}, G.n, #G.blocked, G.sent
G.orig = function(name, d) seen[#seen + 1] = d.tag end
local function room(pid) return {parentChannel = 4, childChannel = 1,
  roomIdentId = {roomIdentDetail = 'PersonalCommonIdent', PersonalCommonIdent = {playerId = pid, otherPlayerId = 1}}} end
local function msg(pid, md, tag) return {tag = tag, roomInfo = room(pid), messageDetail = md, messageType = 19} end
local sec = {secretTask = {x = 1, y = 2, uniqueId = 5, content = '{"playerName":"x","secretTaskId":10510,"shareType":6,"sid":263,"x":1,"y":2}'}}
local fake = {secretTask = {x = 1, y = 2, uniqueId = 5, content = '{"shareType":1}'}}
local point = {pointMessage = {x = 1, y = 2, content = '{}'}}
local ok, err = pcall(function()
  local key = G.ser(room(111))
  G.permit = {msg = 'secret_share', roomKey = key, left = 1, untilT = os.time() + 30}
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = point}, 'point_under_secret_permit'))
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = {secretTask = sec.secretTask, pointMessage = point.pointMessage}}, 'secret_plus_point'))
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = fake}, 'secret_wrong_sharetype'))
  Network.Send('SendChatMessageC2S', msg(222, {shareMessageDto = sec}, 'secret_other_room'))
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = sec, normalMessage = {content = 'x'}}, 'secret_plus_text'))
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = sec}, 'secret_ok'))
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = sec}, 'secret_reuse'))
  G.permit = {msg = 'point_share', roomKey = key, left = 1, untilT = os.time() + 30}
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = sec}, 'secret_under_point_permit'))
  Network.Send('SendChatMessageC2S', msg(111, {shareMessageDto = {pointMessage = point.pointMessage, secretTask = sec.secretTask}}, 'point_plus_secret'))
end)
G.permit = nil; G.orig = real
G.n = n0; G.sent = s0; for i = #G.blocked, b0 + 1, -1 do table.remove(G.blocked, i) end
return 'restored=' .. tostring(G.orig == real) .. ' err=' .. tostring(err) .. ' reached=' .. table.concat(seen, ',')
"""
r = R._raw(SECRET)
print('secret:', r.strip().replace('\n', ' '))
ok('restored=true' in r and 'err=nil' in r, 'covert-share test ran and restored the real send')
ok(r.strip().endswith('reached=secret_ok'), 'secret_share permit lets ONLY one covert card (shareType 6) into the exact room; point, mixed, fake type, other room, text, reuse all dropped; point permit does not pass a covert card')
print('ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
