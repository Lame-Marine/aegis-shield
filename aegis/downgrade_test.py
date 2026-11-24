"""downgrade_test.py - bug test (operator approved 2026-11-01): does the server accept UpgradeBuildingC2S with a LOWER level?
Sends exactly one UpgradeBuildingC2S {uuid = Sanctuary, level = <target>} and records the server's answer plus the
Sanctuary's level/state and resources before and after. Nothing else is sent.
    python aegis/downgrade_test.py 13
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

STATE = r"""
local s for _, x in pairs(Data.BuildingData.buildingTab) do if x.buildingId == 1001 then s = x end end
local res = {}
for _, t in ipairs({1, 2, 3}) do local ok, v = pcall(function() return Data.ResourceData:GetResValueByType(t) end) res[#res + 1] = t .. '=' .. tostring(ok and v or '?') end
local okd, gd = pcall(function() return Data.ResourceData:GetDiamond() end) res[#res + 1] = 'gems=' .. tostring(okd and gd or '?')
return 'uuid=' .. string.format('%d', s.uuid) .. ' level=' .. tostring(s.level) .. ' state=' .. tostring(s.state) .. ' res ' .. table.concat(res, ' ')
"""

SEND = r"""
local s for _, x in pairs(Data.BuildingData.buildingTab) do if x.buildingId == 1001 then s = x end end
local MR = MessageReceive
AE_DG = {}
if not MR.__dg_err then MR.__dg_err = MR.ErrorCode end
MR.ErrorCode = function(d, ...) AE_DG[#AE_DG + 1] = 'ErrorCode ' .. tostring((d or {}).name) .. ' ' .. tostring((d or {}).code) return MR.__dg_err(d, ...) end
for _, n in ipairs({'UpgradeBuildingS2C', 'BuildingUpdateS2C', 'BuildingInfoS2C', 'PlayerQueueS2C', 'PlayerQueueUpdateS2C'}) do
  if MR[n] and not MR['__dg_' .. n] then
    MR['__dg_' .. n] = MR[n]
    MR[n] = function(d, ...) AE_DG[#AE_DG + 1] = n .. ' ' .. tostring(d and (d.level or (d.building and d.building.level)) or '') return MR['__dg_' .. n](d, ...) end
  end
end
require('Logic.Proto.Send.building').UpgradeBuildingC2S({ uuid = s.uuid, level = %d })
return 'sent level=%d for uuid ' .. string.format('%%d', s.uuid)
"""

UNHOOK = r"""
local MR = MessageReceive
if MR.__dg_err then MR.ErrorCode = MR.__dg_err MR.__dg_err = nil end
for _, n in ipairs({'UpgradeBuildingS2C', 'BuildingUpdateS2C', 'BuildingInfoS2C', 'PlayerQueueS2C', 'PlayerQueueUpdateS2C'}) do
  if MR['__dg_' .. n] then MR[n] = MR['__dg_' .. n] MR['__dg_' .. n] = nil end
end
return 'replies: ' .. (#AE_DG > 0 and table.concat(AE_DG, '; ') or 'none')
"""


def body(r): return r.split('\n', 1)[1].strip() if r.startswith('OK') else r


if __name__ == '__main__':
    target = int(sys.argv[1])
    print('before:', body(R.run(STATE)))
    print(body(R.run(SEND % (target, target), allow_send=True)))
    time.sleep(5)
    print(body(R.run(UNHOOK)))
    print('after: ', body(R.run(STATE)))
    with open(os.path.join(HERE, '..', 'logs', 'actions.log'), 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' downgrade test: UpgradeBuildingC2S Sanctuary level=%d (approved by operator)\n' % target)
