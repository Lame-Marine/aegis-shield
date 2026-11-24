local out, seen = {}, {}
local function consts(f) local ok, b = pcall(string.dump, f) local cs = {} if ok then for s in b:gmatch('[%a_][%w_]+') do if #s > 2 and #s < 40 then cs[#cs + 1] = s end end end
  return table.concat(cs, ' '):gsub('svndata MiddleAges_Release_android Assets Script LuaScript ', '') end
for name, m in pairs(package.loaded) do if type(m) == 'table' and not seen[m] then seen[m] = 1
  for k, v in pairs(m) do if type(v) == 'function' and type(k) == 'string' then local l = k:lower()
    if l:find('rename') or l:find('checkname') or l:find('changename') and not l:find('group') then
      out[#out + 1] = tostring(name):gsub('.*%.', '') .. '.' .. k .. ' :: ' .. consts(v):sub(1, 600) end end end end end
local items = {}
pcall(function() for _, it in pairs(Data.ItemData.itemsTab) do if tostring(it.itemId):lower():find('name') then items[#items + 1] = it.itemId .. 'x' .. it.count end end end)
out[#out + 1] = 'items: ' .. table.concat(items, ',')
out[#out + 1] = 'name now: ' .. tostring(Data.UserData.name) .. ' / ' .. tostring(Data.CommanderData and Data.CommanderData.name)
return table.concat(out, '\n')
