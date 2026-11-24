"""share.py - share a map coordinate to an allowlisted player's DM, the same message the in-game Share button sends
(UIChatShareCell:OnClick -> ChatUtils.Share(channel, child, roomId, {pointMessage={x,y,content=json}})).
The guard only lets it through with a one-shot permit: one point share, to that player id, within 30 s.
    python aegis/share.py <Recipient> 566 452 "[Meow] BrewDr" [--dry]
Recipients: config/recipients.json {"InGameName": "playerId"}. Nothing else can be sent.
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

RECIPIENTS = json.load(open(os.path.join(HERE, '..', 'config', 'recipients.json'), encoding='utf-8'))
LOG = os.path.join(HERE, '..', 'logs', 'shares.log')

LUA = r"""
local G = _G.AEGIS_GUARD
local CU = require('Logic.Datas.Chat.ChatUtils')
local room
for _, r in pairs(Data.ChatData:GetRoomListByChannelType(4) or {}) do
  local ok, nm = pcall(function() return r:GetName() end)
  if ok and nm == %(name)s then room = r end
end
if not room then return 'NO_ROOM' end
local content = {pointMessage = {x = %(x)d, y = %(y)d, content = %(content)s}}
local sent0 = G.sent or 0
local DRY = %(dry)s
local rec
if DRY then rec = {} G.orig_saved = G.orig G.orig = function(n, d) rec[#rec + 1] = {n, d} end end
G.permit = {msg = 'point_share', player = %(pid)s, left = 1, untilT = os.time() + 30}
local ok, err = pcall(CU.Share, 4, 1, room:GetId(), content)
G.permit = nil
if DRY then G.orig = G.orig_saved G.orig_saved = nil end
local res = 'ok=' .. tostring(ok) .. ' err=' .. tostring(err) .. ' passed_guard=' .. tostring((G.sent or 0) - sent0) .. ' blocked_total=' .. G.n
if DRY then G.sent = sent0 res = res .. ' recorded=' .. #rec .. (rec[1] and (' ' .. tostring(rec[1][1])) or '') end
return res
"""


def lstr(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def share(to, x, y, label, sid=263, dry=False):
    if to not in RECIPIENTS: raise SystemExit('%s is not in config/recipients.json' % to)
    content = json.dumps({'name': label, 'shareType': 1, 'sid': sid, 'treasureId': 0, 'x': x, 'y': y}, ensure_ascii=False, separators=(',', ':'))
    R.guard()
    r = R._raw(LUA % {'name': lstr(to), 'x': x, 'y': y, 'content': lstr(content), 'dry': 'true' if dry else 'false', 'pid': int(RECIPIENTS[to])})
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('%s %s ok=%s\n' % (__import__('time').strftime('%Y-%m-%d %H:%M:%S'), 'DRY' if dry else 'SEND', 'passed_guard=1' in r))   # no recipient, target or coordinates
    return r


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if x != '--dry']
    print(share(a[0], int(a[1]), int(a[2]), a[3], dry='--dry' in sys.argv))
