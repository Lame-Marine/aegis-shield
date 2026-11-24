"""relocate_test.py - teleport bounds bug test (operator approved 2026-11-01). Sends ONE WorldCityRelocateC2S
{relocateType = 2 (High / Direct Relocate), target = {sid, x, y, pid = 0}} and records the server's answer, our castle
position (fresh map snapshot), Direct Relocate item count and gems before and after.
    python aegis/relocate_test.py X Y [SID]
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R
import fastmap as FM

STATE = r"""
local o = {}
for id, r in pairs(AE_MAP.rows) do if r.name == 'Aegis Shield' then o[#o + 1] = 'castle ' .. r.x .. ',' .. r.y .. ' sid ' .. r.sid end end
o[#o + 1] = 'direct=' .. tostring(Data.ItemData:GetItemCountByItemId('item_UseUp_targetMove'))
o[#o + 1] = 'alliance=' .. tostring(Data.ItemData:GetItemCountByItemId('item_UseUp_unionMove'))
local ok, g = pcall(function() return Data.ResourceData:GetDiamond() end) o[#o + 1] = 'gems=' .. tostring(ok and g or '?')
return table.concat(o, ' ')
"""

SEND = r"""
local MR = MessageReceive
AE_RT = {}
if not MR.__rt_err then MR.__rt_err = MR.ErrorCode end
MR.ErrorCode = function(d, ...) AE_RT[#AE_RT + 1] = 'ErrorCode ' .. tostring((d or {}).name) .. ' ' .. tostring((d or {}).code) return MR.__rt_err(d, ...) end
if MR.WorldCityRelocateS2C and not MR.__rt_ok then
  MR.__rt_ok = MR.WorldCityRelocateS2C
  MR.WorldCityRelocateS2C = function(d, ...)
    local t = (d or {}).target or {}
    AE_RT[#AE_RT + 1] = 'WorldCityRelocateS2C success=' .. tostring((d or {}).success) .. ' type=' .. tostring((d or {}).relocateType) .. ' target=' .. tostring(t.sid) .. ':' .. tostring(t.x) .. ',' .. tostring(t.y)
    return MR.__rt_ok(d, ...)
  end
end
require('Logic.Proto.Send.world').WorldCityRelocateC2S({ relocateType = 2, target = { sid = %d, x = %d, y = %d, pid = 0 } })
return 'sent relocate to %d:%d,%d'
"""

UNHOOK = r"""
local MR = MessageReceive
if MR.__rt_err then MR.ErrorCode = MR.__rt_err MR.__rt_err = nil end
if MR.__rt_ok then MR.WorldCityRelocateS2C = MR.__rt_ok MR.__rt_ok = nil end
return 'replies: ' .. (#AE_RT > 0 and table.concat(AE_RT, '; ') or 'none')
"""


def body(r): return r.split('\n', 1)[1].strip() if r.startswith('OK') else r


if __name__ == '__main__':
    x, y = int(sys.argv[1]), int(sys.argv[2])
    sid = int(sys.argv[3]) if len(sys.argv) > 3 else 263
    FM.refresh()
    print('before:', body(R.run(STATE)))
    print(body(R.run(SEND % (sid, x, y, sid, x, y), allow_send=True)))
    time.sleep(5)
    print(body(R.run(UNHOOK)))
    FM.refresh()
    print('after: ', body(R.run(STATE)))
    with open(os.path.join(HERE, '..', 'logs', 'actions.log'), 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' relocate test: WorldCityRelocateC2S type 2 to %d:%d,%d (approved by operator)\n' % (sid, x, y))
