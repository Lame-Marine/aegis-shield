"""locate.py - find players on the world map near a point, live. One WorldMapViewC2S (the request the game sends when
you scroll the map) with a temporary hook on the reply handler; the hook is always removed. Read-only for the game state.
    python aegis/locate.py X Y [W H] [--name NAME]
Returns rows: playerId|name|tag|x|y|power|level|shield|sid
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run import run

HOOK = r"""
local W=Data.WorldData
if not W.__ae_orig then W.__ae_orig=W.SetWorldMapView end
AE_LOC={rows={},replies=0}
W.SetWorldMapView=function(self,data)
  AE_LOC.replies=AE_LOC.replies+1
  for _,p in pairs(data.worldPointInfos or {}) do
    if p.type==1 and p.worldCityInfo and p.point then local c=p.worldCityInfo
      AE_LOC.rows[#AE_LOC.rows+1]=table.concat({tostring(c.playerId),tostring(c.playerName),tostring(c.playerUnionShortName),
        tostring(p.point.x),tostring(p.point.y),tostring(math.floor(c.playerPower or 0)),tostring(c.level),tostring(c.shielding),tostring(c.playerSid)},'|')
    end end
  return W.__ae_orig(self,data)
end
require('Logic.Proto.Send.world').WorldMapViewC2S({viewLevel=%d,width=%d,height=%d,center={sid=Data.UserData.serverId,x=%d,y=%d},openView=false})
return 'sent'
"""
READ = r"""local r=AE_LOC or {rows={},replies=0} return r.replies..'\n'..table.concat(r.rows,'\n')"""
UNHOOK = r"""local W=Data.WorldData if W.__ae_orig then W.SetWorldMapView=W.__ae_orig W.__ae_orig=nil end AE_LOC=nil return 'unhooked'"""


def locate(x, y, w=40, h=60, level=4, wait=4):
    try:
        r = run(HOOK % (level, w, h, x, y), allow_send=True)
        if not r.startswith('OK'): raise RuntimeError(r)
        time.sleep(wait)
        out = run(READ).split('\n')[1:]
        replies = int(out[0]) if out and out[0].isdigit() else 0
        return replies, [l.split('|') for l in out[1:] if l.count('|') == 8]
    finally:
        run(UNHOOK)


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    name = sys.argv[sys.argv.index('--name') + 1].lower() if '--name' in sys.argv else None
    if name in a: a.remove(sys.argv[sys.argv.index('--name') + 1])
    x, y = int(a[0]), int(a[1]); w, h = (int(a[2]), int(a[3])) if len(a) >= 4 else (40, 60)
    replies, rows = locate(x, y, w, h)
    print('replies', replies, 'cities', len(rows))
    for r in rows:
        if not name or name in r[1].lower(): print('|'.join(r))
