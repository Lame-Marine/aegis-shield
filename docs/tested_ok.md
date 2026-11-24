# Tested and working as intended (not for the developers)

Internal record of server checks that held up, so they are not re-tested.

## Building level checks

`UpgradeBuildingC2S {uuid, level}`: `level` is the building's CURRENT level as the client believes it. The server compares it
with its own record:
- a lumberyard at Lv1 sent with level 2 or 3: refused, **20205**;
- the same lumberyard with level 1: accepted, normal cost charged;
- the Sanctuary at Lv14 sent with level 13: refused, **20200** (its Lv15 requirements are unmet).

No way was found to skip levels or roll a building back through this message.

## Teleport bounds

The client only allows tiles 1-999 on each axis (`WorldMapHelper.IsValidTile`). A direct `WorldCityRelocateC2S`
`{relocateType = 2, target = {sid = 263, x, y, pid = 0}}` was sent to (0,0) and to (0,1000):
- both were refused with `WorldCityRelocateS2C success=false` and **ErrorCode 80002**;
- no item or gems were used, and the city did not move;
- the reply echoes the target as 35535,35535 (looks like a placeholder for an invalid point). Sending to 35535,35535
  itself, and to 35520,35520, was refused the same way (80002, reply target 35535,35535, nothing used).

## Cross-kingdom teleport outside KvK

`WorldCityRelocateC2S {relocateType = 2, target = {sid = 264, x = 300, y = 300, pid = 0}}` (2026-11-01, after the KvK
reset): refused with **ErrorCode 1001** and no `WorldCityRelocateS2C` reply (out-of-range tiles get 80002 with a reply
instead). City stayed at 263:932,62, no item or gems used. Untested: the cross-kingdom relocate types
(`CrossRelocateActivityType` 110/112/120) and the same request during KvK.
