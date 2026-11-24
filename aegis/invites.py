"""invites.py - group invites are approved MANUALLY, together with operator. The bot never accepts anything itself.
    python aegis/invites.py                 list pending group invites (read-only)
    python aegis/invites.py accept "NAME"   accept the one invite whose group name matches exactly (one-shot permit)
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R
from fastmap import lstr

FIND = r"""
local joined = {} for _, r in pairs(Data.ChatData:GetRoomListByChannelType(5) or {}) do local ok, nm = pcall(function() return r:GetName() end) joined[tostring(nm)] = true end
local out, pick = {}, nil
for _, r in pairs(Data.ChatData:GetRoomListByChannelType(4) or {}) do local ok, from = pcall(function() return r:GetName() end)
  for _, m in pairs(r.m_Messages or {}) do local d = (m.m_Dto or {}).sourceMessage or {}
    local inv = (d.messageDetail or {}).groupInviteMessageDto
    if inv then local name = tostring(inv.chatRoomName)
      out[#out + 1] = os.date('%%m-%%d %%H:%%M', math.floor((d.timeMills or 0) / 1000)) .. ' | ' .. name .. ' | from ' .. tostring(from) .. (joined[name] and ' | already joined' or '')
      if name == %s and not joined[name] then pick = {inv = inv, d = d, r = r} end end end end
"""
LIST = FIND % 'nil' + "return table.concat(out, '\\n')"
ACCEPT = FIND + r"""
if not pick then return 'no pending invite with that exact name' end
local G = _G.AEGIS_GUARD
local gid = pick.inv.chatRoomDto.roomIdentId.groupCommonIdent.chatGroupId
G.permit = {msg = 'ChatGroupConfirmC2S', group = tostring(gid), left = 1, untilT = os.time() + 30}
local ok, err = pcall(require('Logic.Proto.Send.chat').ChatGroupConfirmC2S,
  {agree = true, groupRoomInfo = pick.inv.chatRoomDto, messageId = pick.d.messageId, roomInfo = pick.r.m_Dto.roomInfo})
local passed = G.permit.left == 0
G.permit = nil
return 'accept sent=' .. tostring(ok and passed) .. ' ' .. tostring(err or '')
"""


def body(r): return r.split('\n', 1)[1].strip() if r.startswith('OK') else r


if __name__ == '__main__':
    R.guard()
    if len(sys.argv) >= 3 and sys.argv[1] == 'accept':
        print(body(R._raw(ACCEPT % lstr(sys.argv[2]))))
        time.sleep(3)
        open(os.path.join(HERE, '..', 'logs', 'actions.log'), 'a', encoding='utf-8').write(time.strftime('%Y-%m-%d %H:%M:%S') + ' accepted group invite %r (approved by operator)\n' % sys.argv[2])
    print(body(R._raw(LIST)) or 'no invites')
