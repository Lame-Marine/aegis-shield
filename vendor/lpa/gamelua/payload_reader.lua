-- LPA reader payload: READ-ONLY command channel for the alliance sync tools.
-- Polls lpa_cmd.txt once a second, runs it under pcall, writes the result to lpa_out.txt.
-- It does no gameplay, sends no requests by itself and changes nothing in the game.
local LPA = { t = 0 }
local DIR = "/sdcard/Android/data/com.phs.global/files/"
local CMD, OUT = DIR .. "lpa_cmd.txt", DIR .. "lpa_out.txt"
GameLuaMain.AddUpdateFunAlways(function(self, dt)
  LPA.t = LPA.t + dt
  if LPA.t < 1 then return end
  LPA.t = 0
  local f0 = io.open(CMD, "r")
  if not f0 then return end
  local s = f0:read("*a"); f0:close(); os.remove(CMD)
  local fn, e = load(s, "lpa", "t")
  local ok, r
  if not fn then ok, r = false, "compile: " .. tostring(e) else ok, r = pcall(fn) end
  local o = io.open(OUT, "w")
  if o then o:write((ok and "OK\n" or "ERR\n") .. tostring(r)); o:close() end
end, LPA)
CS.UnityEngine.Debug.Log("[LPA] reader loaded")
