"""watchdog.py - keeps the Aegis Shield bot up without anyone watching. Runs detached (start_watchdog.ps1).

Every CHECK s, in order (the first problem found is fixed, then the next pass checks again):
  1. device (device.py) offline: emulator -> ldconsole launch --index 0; phone -> adb connect (re-enable Wi-Fi adb over USB)
  2. device does not report its model -> do nothing at all (wrong device; never touch anything else)
  3b. phone only: wake the screen, bring the game back to the front, log battery/heat problems
  'logged in elsewhere' boxes ([-10013], [1019]) are never pressed: that would kick the other device
  3. game process missing -> start the game
  4. bot.py not running -> restart_bot.ps1
  4b. the game's 'Network connection lost. Reconnect?' dialog -> press its OK button through NGUI (SendMessage OnClick
     on the button object, exactly what a touch does; no screen coordinates). Only for one-button dialogs whose text
     matches RECONNECT_TEXT, after it has been up DIALOG_WAIT s; anything else is only logged.
  5. bot heartbeat older than STALE s -> probe the game; game answers = bot is stuck -> restart the bot;
     game silent for GAME_DEAD s -> force-stop + start the game (bot reinstalls its hooks by itself)
Never restarts the game while one of operator's own tools (invader_watch etc.) is running. Rate limits:
max GAME_MAX game restarts and BOT_MAX bot restarts per hour; beyond that it only logs.
Log: logs/watchdog.log
"""
import os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
from device import SERIAL, MODEL, EMULATOR, INFO       # config/device.json: emulator-5554 or the S10 only
PKG = 'com.phs.global'
GLES = ['-e', 'unity', '-force-gles30'] if EMULATOR else []   # LDPlayer renderer workaround; not on the phone
ACT = PKG + '/com.games37.sdk.AtlasPluginDemoActivity'
WIN = os.name == 'nt'                                   # False = running in Termux on the phone itself
ADB = os.path.join(os.environ['LOCALAPPDATA'], 'Android', 'Sdk', 'platform-tools', 'adb.exe') if WIN else 'adb'
LDC = r'C:\LDPlayer\LDPlayer14\ldconsole.exe'
LOG = os.path.join(ROOT, 'logs', 'watchdog.log')
HEART = os.path.join(ROOT, 'logs', 'bot_heart.txt')
CTL = '/sdcard/Download/aegis-ctl'                       # Termux only: deploy.tar / restart_bot dropped here by the PC
CHECK, STALE, GAME_DEAD, BOOT_GRACE = 30, 180, 300, 240
GAME_MAX, BOT_MAX = 3, 6
DIALOG_WAIT, PRESS_MAX = 10, 12
RECONNECT_TEXT = r'(?i)reconnect|connection lost|network|timed out'     # one-button connection boxes: OK retries
ELSEWHERE_TEXT = r'\[-10013\]|\[1019\]'   # account logged in on another device: pressing Reconnect kicks that device
# operator 2026-11-08: the phone has priority. After ELSE_WAIT s the phone takes the account back (kicking the other device),
# at most ELSE_MAX times an hour so two devices never fight forever. To use Aegis elsewhere, drop aegis-ctl/pause first.
ELSE_WAIT, ELSE_MAX = 60, 4
LOGOUT_TEXT = r'\[1021\]|(?i:logged out due to inactivity)'   # session dropped (seen 2026-11-08 after a reconnect loop): only a fresh start helps
NET_WAIT = 120         # NetworkErrorPanel: seconds before pressing its OK
PRESS_LOOP = 4         # this many OK presses within 10 min = the reconnects are not working: restart the game instead
MAINT_TEXT = r'(?i)maintenance'                     # 'Under maintenance [1004]': restart the game every MAINT_RETRY s until it gets in
MAINT_RETRY = 900
VENV_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.venv', 'Scripts', 'python.exe') if os.name == 'nt' else sys.executable   # has UnityPy
# connection boxes: ConfirmBoxPanel (one OK button; emulator) and NetworkErrorPanel (OK + a 'Network' gateway picker; seen on
# the S10 with [10060]). OK is m_Button1 in both. The gateway picker (m_selectGateway) is never pressed.
PANELS = ('UI Root/Layer_TIPS/ConfirmBoxPanel(Clone)', 'UI Root/Layer_TIPS/NetworkErrorPanel(Clone)')
DIALOG = r"""
for _, P in ipairs({ %s }) do
  local root = CS.UnityEngine.GameObject.Find(P)
  if root and root.activeInHierarchy then
    local a = {}
    for _, ty in ipairs({ CS.UILabel, CS.TMPro.TextMeshPro }) do      -- message is an NGUI UILabel, buttons are TMP
      local ts = root:GetComponentsInChildren(typeof(ty)) for i = 0, ts.Length - 1 do local t = tostring(ts[i].text) if t ~= '' then a[#a + 1] = t end end
    end
    local grid = CS.UnityEngine.GameObject.Find(P .. '/PanelContent/m_btnGrid') local n = 0
    if grid then for i = 0, grid.transform.childCount - 1 do local c = grid.transform:GetChild(i)
      if c.gameObject.activeSelf and c.name ~= 'm_selectGateway' then n = n + 1 end end end
    return 'open|' .. P .. '|' .. n .. '|' .. (table.concat(a, ' / '):gsub('[|%%c]', ' '))
  end
end
return 'none'
""" % ', '.join("'%s'" % p for p in PANELS)
PRESS = "local go = CS.UnityEngine.GameObject.Find('%s/PanelContent/m_btnGrid/m_Button1') if not go then return 'no button' end " \
        "go:SendMessage('OnClick', CS.UnityEngine.SendMessageOptions.DontRequireReceiver) return 'pressed'"
FOREIGN = ('invader_watch', 'lpa_sync', 'covert_ops.py', 'kingdom_sweep.py')   # operator's tools: hands off the game


def log(t):
    open(LOG, 'a', encoding='utf-8').write(time.strftime('%Y-%m-%d %H:%M:%S ') + t + '\n')


def sh(args, timeout=30):
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000 if WIN else 0).stdout.decode('utf-8', 'replace').strip()
    except Exception as e:
        return 'ERR %s' % e


def adb(*a, timeout=30): return sh([ADB, '-s', SERIAL] + list(a), timeout)


def pythons():
    if not WIN:                                   # Termux: read the process table directly
        out = []
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try: out.append(open('/proc/%s/cmdline' % pid, 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace'))
                except OSError: pass
        return out
    out = sh(['powershell.exe', '-NoProfile', '-Command',
              "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }"], 60)
    return out.splitlines()


def restart_bot_local():
    """Termux version of restart_bot.ps1: wait (max 3 min) for the bot to be idle, stop it, start a new one detached."""
    busy = os.path.join(ROOT, 'logs', 'bot_busy.txt')
    t0 = time.time()
    while time.time() - t0 < 180 and os.path.exists(busy) and open(busy).read().strip() not in ('0', ''):
        time.sleep(2)
    for pid in os.listdir('/proc'):
        if pid.isdigit() and pid != str(os.getpid()):
            try:
                cl = open('/proc/%s/cmdline' % pid, 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace')
                if 'aegis/bot.py' in cl: os.kill(int(pid), 9)
            except (OSError, ValueError): pass
    time.sleep(1)
    lg = os.path.join(ROOT, 'logs')
    subprocess.Popen([sys.executable, 'aegis/bot.py'], cwd=ROOT, stdin=subprocess.DEVNULL, start_new_session=True,
                     stdout=open(os.path.join(lg, 'bot_out.log'), 'w'), stderr=open(os.path.join(lg, 'bot_err.log'), 'w'))
    return 'bot restarted (detached)'


class Dog:
    def __init__(self):
        self.restarts = {'game': [], 'bot': [], 'ld': [], 'press': [], 'reader': [], 'else': []}
        self.grace_until = 0            # after starting something, give it time before judging
        self.silent_since = 0
        self.dialog_seen = 0

    def dialog(self):
        """-> True if a dialog was handled (or is being waited on) this pass."""
        import run as R
        r = R._raw(DIALOG, timeout=20)
        if not r.startswith('OK'):                   # reader silent: tracked separately, the bot's heartbeat can stay fresh
            self.reader_bad = getattr(self, 'reader_bad', 0) or time.time(); return False
        self.reader_bad = 0
        b = r.split(chr(10), 1)[1].strip()
        if not b.startswith('open|'): self.dialog_seen = 0; return False
        _, panel, n, text = b.split('|', 3)
        now = time.time()
        if not self.dialog_seen:
            self.dialog_seen = now; log('dialog up: %s button(s): %s' % (n, text[:150]))
            self.net_evidence(text); return True
        if now - self.dialog_seen < DIALOG_WAIT: return True
        if re.search(ELSEWHERE_TEXT, text):
            if now - self.dialog_seen < ELSE_WAIT: return True
            self.restarts.setdefault('else', [])
            if not self.allowed('else', ELSE_MAX):
                if int(now - self.dialog_seen) % 1800 < CHECK: log('logged in elsewhere again, %d take-backs this hour already: standing down' % ELSE_MAX)
                return True
            log('account logged in elsewhere (%s): phone has priority, taking it back -> %s' % (text[:60], R._raw(PRESS % panel).replace(chr(10), ' ')))
            self.dialog_seen = 0; self.grace_until = now + 60
            return True
        if 'NetworkErrorPanel' in panel:
            # the S10's network box. With [10060] the game kept working behind it (2026-11-07), but [10054] on 2026-11-10 was a
            # real disconnect: no chat arrived for 45 min while the reader still answered. So: leave it NET_WAIT s (a short
            # blip clears itself), then press OK like any reconnect box (the press-loop rule and repair_reader cover the rest).
            if now - self.dialog_seen < NET_WAIT: return False
            recent = [t for t in self.restarts['press'] if now - t < 600]
            if len(recent) >= PRESS_LOOP:
                self.dialog_seen = 0; self.restarts['press'] = []
                self.start_game('%d reconnect presses in 10 min did not hold (%s)' % (len(recent), text[:50]), force_stop=True)
                return True
            if not self.allowed('press', PRESS_MAX): return True
            log('network box up %d s, pressing OK: %s -> %s' % (now - self.dialog_seen, text[:70], R._raw(PRESS % panel).replace(chr(10), ' ')))
            self.dialog_seen = 0; self.grace_until = now + 60
            return True
        if re.search(LOGOUT_TEXT, text):
            self.dialog_seen = 0
            self.start_game('logged out box (%s)' % text[:50], force_stop=True)
            return True
        if re.search(MAINT_TEXT, text):
            if now - self.dialog_seen >= MAINT_RETRY:
                mins = int(now - self.dialog_seen) // 60; self.dialog_seen = 0
                self.start_game('maintenance box up %d min, trying again' % mins, force_stop=True)
            return True
        if n != '1' or not re.search(RECONNECT_TEXT, text):
            if int(now - self.dialog_seen) % 600 < CHECK: log('dialog still up, not a plain reconnect box, leaving it: %s' % text[:150])
            return True
        recent = [t for t in self.restarts['press'] if now - t < 600]
        if len(recent) >= PRESS_LOOP:
            self.dialog_seen = 0; self.restarts['press'] = []
            self.start_game('%d reconnect presses in 10 min did not hold (%s)' % (len(recent), text[:50]), force_stop=True)
            return True
        if not self.allowed('press', PRESS_MAX): return True
        log('pressing OK on: %s -> %s' % (text[:100], R._raw(PRESS % panel).replace(chr(10), ' ')))
        self.dialog_seen = 0; self.grace_until = now + 45
        return True

    def net_evidence(self, text):
        """On a connection box: keep the last minutes of VPN / Wi-Fi / connectivity log lines next to watchdog.log, so the
        cause of a drop (tunnel, Wi-Fi or game server) can be told apart afterwards (logcat only holds ~2 h)."""
        if not re.search(RECONNECT_TEXT + r'|10054|10060|-2000', text): return
        try:
            out = adb('shell', 'logcat -d -v time -t 6000 2>/dev/null | grep -aiE "wireguard|GoBackend|wpa_supplicant|CTRL-EVENT|WifiClientModeImpl|ConnectivityService|NetworkMonitor/100|dhcp|Unity.*(socket|connect)" | tail -250', timeout=60)
            f = os.path.join(os.path.dirname(LOG), 'net_%s.txt' % time.strftime('%Y%m%d_%H%M%S'))
            with open(f, 'w', encoding='utf-8') as fh: fh.write('dialog: %s' % text + chr(10) + out)
            log('  network evidence saved: %s' % os.path.basename(f))
        except Exception as e: log('  network evidence failed: %s' % e)

    def allowed(self, kind, cap):
        now = time.time()
        self.restarts[kind] = [t for t in self.restarts[kind] if now - t < 3600]
        if len(self.restarts[kind]) >= cap:
            log('%s restart needed but %d already this hour: waiting' % (kind, cap)); return False
        self.restarts[kind].append(now); return True

    def restart_bot(self, why):
        if not self.allowed('bot', BOT_MAX): return
        log('restarting bot: ' + why)
        # output to a file, not a pipe: the detached bot inherits the handles and a pipe would never close
        out = os.path.join(ROOT, 'logs', 'watchdog_restart.txt')
        if not WIN:
            with open(out, 'w') as f: f.write(restart_bot_local())
            log('  ' + open(out).read().strip()); self.grace_until = time.time() + 60; return
        with open(out, 'w') as f:
            try: subprocess.run(['powershell.exe', '-NoProfile', '-File', os.path.join(HERE, 'restart_bot.ps1')], stdout=f, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, timeout=300, creationflags=0x08000000)
            except Exception as e: f.write('ERR %s' % e)
        log('  ' + open(out).read().strip().replace('\n', ' | '))
        self.grace_until = time.time() + 60

    def start_game(self, why, force_stop=False):
        foreign = [l for l in pythons() if any(f in l for f in FOREIGN)]
        if foreign:
            log('game needs a restart (%s) but one of operator\'s tools is running: leaving it. %s' % (why, foreign[0][:120])); return
        if not self.allowed('game', GAME_MAX): return
        log('starting game: ' + why)
        if force_stop: adb('shell', 'am', 'force-stop', PKG); time.sleep(3)
        log('  ' + adb('shell', 'am', 'start', '-n', ACT, *GLES)[:150].replace('\n', ' | '))
        self.grace_until = time.time() + BOOT_GRACE; self.silent_since = 0

    def repair_reader(self):
        """A game update that replaces the bundle the reader lives in removes the reader (the game then never answers).
        If the update has finished (bundle == Version.txt) and the reader is gone, rebuild + install it (build_reader.py,
        which also gives the files back to the game's uid so the NEXT update can write them). True if it ran."""
        out = sh([VENV_PY, os.path.join(HERE, 'build_reader.py'), '--check'], 120)
        m = re.search(r'entry md5 (\w+) \| device bundle md5 (\w+) \| reader in bundle: (\w+)', out)
        if not m: log('reader check failed: %s' % out[-150:]); return False
        if m.group(3) == 'True' or m.group(1) != m.group(2): return False     # reader there, or update still running
        if not self.allowed('reader', 2): return False
        log('reader missing after a game update (bundle %s): rebuilding' % m.group(1)[:8])
        r = sh([VENV_PY, os.path.join(HERE, 'build_reader.py'), '--install'], 300)
        log('  ' + r[-300:].replace(chr(10), ' | '))
        self.grace_until = time.time() + BOOT_GRACE; self.silent_since = 0
        return True

    def probe(self):
        import run as R
        try:
            return R._raw('return 1', timeout=20).startswith('OK')
        except Exception:
            return False

    def ctl(self):
        """Termux only: remote control through shared storage (the PC can write there over adb, Termux can read it).
        CTL/deploy.tar -> unpack over ROOT (code + config, never logs), restart the bot; CTL/restart_bot -> restart it."""
        import tarfile
        tar, rb = os.path.join(CTL, 'deploy.tar'), os.path.join(CTL, 'restart_bot')
        if os.path.exists(tar):
            try:
                with tarfile.open(tar) as t:
                    names = [m for m in t.getmembers() if not m.name.startswith(('logs', '/', '..')) and '..' not in m.name]
                    t.extractall(ROOT, members=names, filter='data')
                log('deployed %d files from %s' % (len(names), tar))
            except Exception as e: log('deploy failed: %s' % e)
            os.remove(tar)
            log('restarting the watchdog itself to load the new code (it restarts the bot)')
            restart_bot_local()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        rg = os.path.join(CTL, 'restart_game')
        if os.path.exists(rg):                                    # the bot saw the game misbehave (e.g. covert scan with 0 ops)
            why = open(rg).read().strip()[:80]; os.remove(rg)
            self.start_game('requested by the bot: ' + why, force_stop=True)
        if os.path.exists(rb):
            os.remove(rb); log('restart requested over CTL'); log('  ' + restart_bot_local()); self.grace_until = time.time() + 60
        pause = os.path.exists(os.path.join(CTL, 'pause'))
        if pause and not getattr(self, 'paused', False):
            for pid in os.listdir('/proc'):
                try:
                    if pid.isdigit() and 'aegis/bot.py' in open('/proc/%s/cmdline' % pid, 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace'):
                        os.kill(int(pid), 9)
                except (OSError, ValueError): pass
            log('paused over CTL: bot stopped, the PC may drive the game')
        elif not pause and getattr(self, 'paused', False):
            log('pause lifted: the bot starts again')
        self.paused = pause

    def tick(self):
        now = time.time()
        if not WIN:
            self.ctl()
            if self.paused: return                    # the PC is driving: hands off everything
        if now < self.grace_until: return
        # 1. device reachable
        if not EMULATOR:
            if SERIAL + '\tdevice' not in sh([ADB, 'devices']):
                r = sh([ADB, 'connect', SERIAL])
                if 'connected' not in r and INFO.get('usb') and INFO['usb'] + '\tdevice' in sh([ADB, 'devices']):
                    r += ' | usb: ' + sh([ADB, '-s', INFO['usb'], 'tcpip', '5555']); time.sleep(4); r += ' | ' + sh([ADB, 'connect', SERIAL])
                if SERIAL + '\tdevice' not in sh([ADB, 'devices']):
                    if int(now) % 600 < CHECK: log('phone %s not reachable over Wi-Fi adb (%s); after a reboot it needs USB once' % (SERIAL, r[:120]))
                    return
                log('phone reconnected: ' + r[:120])
        elif SERIAL + '\tdevice' not in sh([ADB, 'devices']):
            running = sh(['cmd.exe', '/c', LDC + ' isrunning --index 0'])
            log('%s offline (ldconsole isrunning: %s)' % (SERIAL, running))
            if running != 'running' and self.allowed('ld', 2):
                log('  launching LDPlayer instance 0: ' + sh(['cmd.exe', '/c', LDC + ' launch --index 0']))
                self.grace_until = now + 180
            return
        # 2. right device only
        model = adb('shell', 'getprop', 'ro.product.model')
        if model != MODEL:
            log('device on %s reports %r, not %s: doing nothing' % (SERIAL, model, MODEL)); self.grace_until = now + 600; return
        # 3. game process
        if not adb('shell', 'pidof', PKG):
            self.start_game('game process not running'); return
        # 3b. phone: screen awake and the game in front (Unity stops running when the screen is off or it is in the background)
        if not EMULATOR:
            if 'mWakefulness=Awake' not in adb('shell', 'dumpsys power | grep mWakefulness='):
                log('phone screen off: waking it'); adb('shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'); return
            if PKG not in adb('shell', 'dumpsys activity activities | grep -m1 mResumedActivity'):
                log('game not in front: bringing it back'); adb('shell', 'am', 'start', '-n', ACT); return
            if now - getattr(self, 'batt_at', 0) > 1800:
                self.batt_at = now
                b = adb('shell', 'dumpsys battery')
                lv = re.search(r'level: (\d+)', b); tp = re.search(r'temperature: (\d+)', b); pw = re.findall(r'(AC|USB|Wireless) powered: true', b)
                lv, tp = int(lv.group(1)) if lv else -1, int(tp.group(1)) / 10 if tp else -1
                if lv < 25 or tp > 45 or not pw: log('phone battery %d%%, %.1f C, charging via %s' % (lv, tp, ','.join(pw) or 'NOTHING'))
        # 4. bot process
        if not any('aegis/bot.py' in l or 'aegis\\bot.py' in l for l in pythons()):
            self.restart_bot('bot process not running'); return
        # 4b. network-loss dialog
        if self.dialog(): return
        # 5. heartbeat
        try: age = now - int(open(HEART).read().strip())
        except Exception: return                     # missing / mid-write: judge on the next pass
        bad = getattr(self, 'reader_bad', 0)
        if age < STALE and not (bad and now - bad >= GAME_DEAD):
            self.silent_since = 0; return
        if age < STALE:                              # heartbeat fresh but the game has not answered the reader for GAME_DEAD s
            log('reader silent %ds while the bot heartbeat is fresh (game update removed the reader?)' % (now - bad))
            self.silent_since = self.silent_since or bad
        if self.probe():
            self.silent_since = 0
            if age < STALE: self.reader_bad = 0; return  # reader is answering again: nothing to do
            self.restart_bot('no heartbeat for %ds but the game answers' % age); return
        self.silent_since = self.silent_since or now
        log('game not answering (heartbeat %ds old, silent %ds)' % (age, now - self.silent_since))
        if now - self.silent_since >= GAME_DEAD:
            if self.repair_reader(): return
            self.start_game('game not answering for %ds' % (now - self.silent_since), force_stop=True)

    def loop(self):
        log('watchdog started')
        while True:
            try: self.tick()
            except Exception as e: log('watchdog error: %s' % str(e)[:200])
            time.sleep(CHECK)


if __name__ == '__main__':
    if '--once' in sys.argv: d = Dog(); d.tick(); print(open(LOG, encoding='utf-8').read()[-600:] if os.path.exists(LOG) else 'no log')
    else: Dog().loop()
