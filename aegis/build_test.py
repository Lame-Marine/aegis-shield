"""build_test.py - building-level bug tests (operator approved 2026-11-01). One UpgradeBuildingC2S {uuid, level} per call,
with the building's level/state, resources, gems and the server's answer recorded before and after.
    python aegis/build_test.py <uuid> <level> [wait_s]
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

STATE = r"""
local s for _, x in pairs(Data.BuildingData.buildingTab) do if string.format('%%d', x.uuid) == '%s' then s = x end end
if not s then return 'no building' end
local res = {}
for _, t in ipairs({1, 2, 3}) do local ok, v = pcall(function() return Data.ResourceData:GetResValueByType(t) end) res[#res + 1] = t .. '=' .. tostring(ok and v or '?') end
local okd, gd = pcall(function() return Data.ResourceData:GetDiamond() end)
return (Config.Building[s.buildingId] or {}).name .. ' level=' .. tostring(s.level) .. ' state=' .. tostring(s.state) .. ' res ' .. table.concat(res, ' ') .. ' gems=' .. tostring(okd and gd or '?')
"""

SEND = r"""
local s for _, x in pairs(Data.BuildingData.buildingTab) do if string.format('%%d', x.uuid) == '%s' then s = x end end
local MR = MessageReceive
AE_BT = {}
if not MR.__bt_err then MR.__bt_err = MR.ErrorCode end
MR.ErrorCode = function(d, ...) AE_BT[#AE_BT + 1] = 'ErrorCode ' .. tostring((d or {}).name) .. ' ' .. tostring((d or {}).code) return MR.__bt_err(d, ...) end
AE_BT_N = {}
for n, f in pairs(MR) do
  if type(f) == 'function' and (n:find('Building') or n:find('Queue')) and not n:find('^__') and not MR['__bt_' .. n] then
    MR['__bt_' .. n] = f
    AE_BT_N[#AE_BT_N + 1] = n
    MR[n] = function(d, ...) AE_BT[#AE_BT + 1] = n return MR['__bt_' .. n](d, ...) end
  end
end
require('Logic.Proto.Send.building').UpgradeBuildingC2S({ uuid = s.uuid, level = %d })
return 'sent level=%d'
"""

UNHOOK = r"""
local MR = MessageReceive
if MR.__bt_err then MR.ErrorCode = MR.__bt_err MR.__bt_err = nil end
for _, n in ipairs(AE_BT_N or {}) do if MR['__bt_' .. n] then MR[n] = MR['__bt_' .. n] MR['__bt_' .. n] = nil end end
return 'replies: ' .. (#AE_BT > 0 and table.concat(AE_BT, '; ') or 'none')
"""


def body(r): return r.split('\n', 1)[1].strip() if r.startswith('OK') else r


if __name__ == '__main__':
    uuid, level = sys.argv[1], int(sys.argv[2])
    wait = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    print('before:', body(R.run(STATE % uuid)))
    print(body(R.run(SEND % (uuid, level, level), allow_send=True)))
    time.sleep(wait)
    print(body(R.run(UNHOOK)))
    print('after: ', body(R.run(STATE % uuid)))
    with open(os.path.join(HERE, '..', 'logs', 'actions.log'), 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' build test: UpgradeBuildingC2S uuid=%s level=%d (approved by operator)\n' % (uuid, level))
