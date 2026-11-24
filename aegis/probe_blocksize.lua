-- probe: send one WorldMapViewC2S of the given size, count cities in the reply, catch ErrorCode. Params via AE_BS_ARGS.
local a = AE_BS_ARGS
local MR = MessageReceive
AE_BS = {n = 0, cities = 0, err = nil}
if not Data.WorldData.__bs_orig then Data.WorldData.__bs_orig = Data.WorldData.SetWorldMapView end
Data.WorldData.SetWorldMapView = function(self, data)
  if data.center and data.center.x == a.x and data.center.y == a.y then
    AE_BS.n = AE_BS.n + 1
    AE_BS.ids = AE_BS.ids or {} for _, p in pairs(data.worldPointInfos or {}) do if p.type == 1 and p.worldCityInfo then local id = tostring(p.worldCityInfo.playerId) if not AE_BS.ids[id] then AE_BS.ids[id] = 1 AE_BS.cities = AE_BS.cities + 1 end end end
  end
  return Data.WorldData.__bs_orig(self, data)
end
if not MR.__bs_ec then MR.__bs_ec = MR.ErrorCode end
MR.ErrorCode = function(d, ...) if (d or {}).name == 'WorldMapViewC2S' then AE_BS.err = tostring(d.code) end return MR.__bs_ec(d, ...) end
require('Logic.Proto.Send.world').WorldMapViewC2S({viewLevel = a.lv, width = a.w, height = a.h, center = {sid = Data.WorldData.serverId, x = a.x, y = a.y}, openView = false})
return 'sent'
