"""rename.py - rename the commander (one try per call) through a one-shot guard permit.
    python aegis/rename.py "Aegis"
Reports: server reply, any error tip shown, rename-card and gem counts before/after, name before/after.
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

PROBE = r"""
local function nm() return 'name=' .. tostring(Data.CommanderData.commanderName) end
local card = 0 pcall(function() for _, it in pairs(Data.ItemData.itemsTab) do if it.itemId == 'item_UseUp_userName1' then card = it.count end end end)
return nm() .. ' card=' .. card .. ' gems=' .. tostring(Data.ResourceData:GetResValueByType(11))
"""
SEND = r"""
local G = _G.AEGIS_GUARD
local MR = MessageReceive
AE_RN = {tips = {}, reply = nil}
if not MR.__ae_rn then MR.__ae_rn = MR.CommanderRenameS2C end
MR.CommanderRenameS2C = function(d, ...) local t = {} for k, v in pairs(d or {}) do t[#t + 1] = k .. '=' .. tostring(v) end AE_RN.reply = table.concat(t, ',') return MR.__ae_rn(d, ...) end
if not MR.__ae_ec then MR.__ae_ec = MR.ErrorCode end
MR.ErrorCode = function(d, ...) local t = {} for k, v in pairs(d or {}) do t[#t + 1] = k .. '=' .. tostring(v) end AE_RN.err = table.concat(t, ',') return MR.__ae_ec(d, ...) end
for _, f in ipairs({'ShowTips', 'ShowTipsBig'}) do if _G[f] and not _G['__ae_' .. f] then local o = _G[f] _G['__ae_' .. f] = o
  _G[f] = function(a, ...) AE_RN.tips[#AE_RN.tips + 1] = tostring(a) return o(a, ...) end end end
G.permit = {msg = 'CommanderRenameC2S', newName = %s, left = 1, untilT = os.time() + 30}
require('Logic.Proto.Send.commander').CommanderRenameC2S({newName = %s})
local passed = G.permit.left == 0
G.permit = nil
return 'passed_guard=' .. tostring(passed)
"""
READ = r"""
local r = AE_RN or {tips = {}}
MessageReceive.CommanderRenameS2C = MessageReceive.__ae_rn or MessageReceive.CommanderRenameS2C MessageReceive.__ae_rn = nil
MessageReceive.ErrorCode = MessageReceive.__ae_ec or MessageReceive.ErrorCode MessageReceive.__ae_ec = nil
for _, f in ipairs({'ShowTips', 'ShowTipsBig'}) do if _G['__ae_' .. f] then _G[f] = _G['__ae_' .. f] _G['__ae_' .. f] = nil end end
AE_RN = nil
return 'reply=' .. tostring(r.reply) .. ' error=' .. tostring(r.err) .. ' tips=' .. table.concat(r.tips, ' | ')
"""


def lstr(s): return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def rename(new):
    R.guard()
    before = R._raw(PROBE).split('\n', 1)[-1].strip()
    sent = R._raw(SEND % (lstr(new), lstr(new))).split('\n', 1)[-1].strip()
    time.sleep(4)
    res = R._raw(READ).split('\n', 1)[-1].strip()
    after = R._raw(PROBE).split('\n', 1)[-1].strip()
    line = '%s rename %r | before: %s | %s | %s | after: %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), new, before, sent, res, after)
    os.makedirs(os.path.join(HERE, '..', 'logs'), exist_ok=True)
    open(os.path.join(HERE, '..', 'logs', 'actions.log'), 'a', encoding='utf-8').write(line + '\n')
    return line


if __name__ == '__main__':
    print(rename(sys.argv[1]))
