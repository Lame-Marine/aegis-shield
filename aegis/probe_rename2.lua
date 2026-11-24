local out = {}
local function consts(f) local ok, b = pcall(string.dump, f) local cs = {} if ok then for s in b:gmatch('[%a_][%w_]+') do if #s > 2 and #s < 40 then cs[#cs + 1] = s end end end
  return table.concat(cs, ' '):gsub('svndata MiddleAges_Release_android Assets Script LuaScript ', '') end
for k, v in pairs(UIPanelType) do local l = tostring(k):lower() if l:find('name') or l:find('rename') then out[#out + 1] = 'PANEL ' .. tostring(k) .. ' ' .. tostring(type(v) == 'table' and v.assetName or v) end end
for name, m in pairs(package.loaded) do if type(name) == 'string' and (name:lower():find('rename') or name:lower():find('changename') or name:lower():find('modifyname') or name:lower():find('editname')) and type(m) == 'table' then
  local fs, seen = {}, {}
  local function walk(t, d) if type(t) ~= 'table' or seen[t] or d > 5 then return end seen[t] = 1 for a, b in pairs(t) do if type(b) == 'function' and type(a) == 'string' then fs[a] = b end end
    local mt = getmetatable(t) if mt then walk(mt.__index, d + 1) end walk(rawget(t, 'super'), d + 1) end
  walk(m, 0)
  out[#out + 1] = 'MOD ' .. name
  for a, b in pairs(fs) do if a:find('Click') or a:find('Confirm') or a:find('Send') or a:find('Check') or a:find('Rename') then out[#out + 1] = '  ' .. a .. ' :: ' .. consts(b):sub(1, 700) end end
end end
return table.concat(out, '\n')
