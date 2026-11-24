"""run.py - run Lua in Halden's game (LDPlayer 0, emulator-5554 ONLY) through the LPA reader channel.

Safety, in this order:
  1. Serial comes from device.py (emulator-5554 or the S10 only). Anything else (emulator-5556 is operator's) raises.
  2. Static check of the code: refuses anything that sends player-facing messages, touches the guard,
     or (unless allow_send=True) makes ANY server request (Network.Send / *C2S( / :Send* / Request*).
  3. guard.lua is installed in the game before every command: Network.Send drops all chat/mail/social sends
     even if something gets past step 2 or a human taps the chat box.
Usage:  python aegis/run.py "return Data.UserData.level"     |  python aegis/run.py -f probe.lua  [--allow-send]
Import: from run import run;  run(code, allow_send=False, timeout=15)
"""
import ctypes, os, re, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ADB = os.path.expandvars(r'%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe') if os.name == 'nt' else 'adb'   # Termux: pkg android-tools
D = '/sdcard/Android/data/com.phs.global/files/'
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
import sys as _s; _s.path.insert(0, HERE)
from device import SERIAL, ALLOWED           # config/device.json: emulator-5554 or the S10, nothing else
GUARD = open(os.path.join(HERE, 'guard.lua'), encoding='utf-8').read()
LOG = os.path.join(HERE, '..', 'logs', 'run.log')

# Player-facing sends: never allowed, not even with allow_send.
COMMS = re.compile(r'SendChat|ChatGroup|SendUnionMail|ShareMail|TempleSendMail|Announcement|UnionNotice|EditChatNotice|PrivateChat|'
                   r'Like\w*C2S|Share\w*C2S|PlayerReport|CommanderRename|InviteJoinUnion|EscortInvite|UnionMarkPoint|BlockPlayer|'
                   r'RecallMessage|DeleteMessage|:SendChat|SendMessage|AEGIS_GUARD|Network\s*\.\s*Send\s*=|rawset\s*\(\s*Network', re.I)
# Any server request at all: needs allow_send=True (RE/bug tests that deliberately send, logged).
ANYSEND = re.compile(r'Network\s*\.\s*Send|\w+C2S\s*\(|EyuNetWorkManager|SimpleInstrSendByPb|:Req\w*\(|:Request\w*\(|\.Request\w*\(|:Do\w*\(|:Send\w*\(', re.I)

if os.name == 'nt':
    _K = ctypes.windll.kernel32
    _K.CreateMutexW.restype = ctypes.c_void_p
    _K.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _K.ReleaseMutex.argtypes = [ctypes.c_void_p]
    _MUTEX = _K.CreateMutexW(None, False, 'Global\\lpa_game_channel')   # same lock as the LPA tools: one user of the channel at a time

    def _lock(): return _K.WaitForSingleObject(_MUTEX, 120000) in (0, 0x80)
    def _unlock(): _K.ReleaseMutex(_MUTEX)
else:                                                  # Termux on the phone: a lock file does the same job between processes
    import fcntl
    _LF = open(os.path.join(tempfile.gettempdir(), 'aegis_game_channel.lock'), 'a')

    def _lock():
        t0 = time.time()
        while time.time() - t0 < 120:
            try: fcntl.flock(_LF, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
            except OSError: time.sleep(0.05)
        return False
    def _unlock(): fcntl.flock(_LF, fcntl.LOCK_UN)
_LOCK = threading.RLock()


class Refused(Exception):
    pass


def check(code, allow_send=False):
    m = COMMS.search(code)
    if m: raise Refused('player-facing send or guard tampering: %r' % m.group(0))
    if not allow_send:
        m = ANYSEND.search(code)
        if m: raise Refused('server request without allow_send: %r' % m.group(0))


def _adb(*a, **k):
    return subprocess.run([ADB, '-s', SERIAL, *a], capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, **k)


_PHONE_OK = 0


def _phone_free():
    """PC driving the S10 over Wi-Fi: refuse while the phone's own bot (Termux) is running, unless it is paused
    (/sdcard/Download/aegis-ctl/pause). Two drivers corrupt each other's commands (their locks cannot see each other)."""
    global _PHONE_OK
    if os.name != 'nt' or SERIAL.startswith(('emulator-', '127.0.0.1')) or time.time() - _PHONE_OK < 60: return
    r = _adb('shell', 'cat /sdcard/Download/aegis-logs/bot_heart.txt; echo; date +%s; ls /sdcard/Download/aegis-ctl/pause 2>/dev/null').stdout.decode().split()
    try: beat, now = int(r[0]), int(r[1])
    except (ValueError, IndexError): beat, now = 0, 1 << 40
    if now - beat < 120 and not any(x.endswith('/pause') for x in r):
        raise RuntimeError('the phone bot is running on %s: pause it first (adb shell touch /sdcard/Download/aegis-ctl/pause)' % SERIAL)
    _PHONE_OK = time.time()


MARK = chr(1) + 'AEGIS_END'      # appended to every answer: the answer is complete only when it ends with this


def _wrap(code):
    """run the snippet as a function and tag its (first) result with MARK; same value as before ('nil' for nothing)"""
    return 'local __aegis_v = (function()\n%s\nend)()\nreturn tostring(__aegis_v) .. "\\1AEGIS_END"' % code


def _raw(code, timeout=15):
    """Send code over the reader channel with no checks. Internal: guard install and tests only."""
    with _LOCK:
        _phone_free()
        got = _lock()
        try:
            _adb('shell', 'rm', '-f', D + 'lpa_out.txt')
            f = os.path.join(tempfile.gettempdir(), 'aegis_cmd_%d.txt' % os.getpid())
            open(f, 'w', encoding='utf-8').write(_wrap(code))
            # write under a temp name, then rename: the game polls lpa_cmd.txt every second and could otherwise run a
            # half-written command (seen on the phone as 'OK nil' answers)
            _adb('push', f, D + 'lpa_cmd.tmp')
            _adb('shell', 'mv', '-f', D + 'lpa_cmd.tmp', D + 'lpa_cmd.txt')
            t0 = time.time()
            while time.time() - t0 < timeout:
                time.sleep(0.2)
                r = _adb('exec-out', 'cat', D + 'lpa_out.txt').stdout.decode('utf-8', 'replace').replace(chr(13), '')
                if r.startswith('OK') and r.endswith(MARK):
                    return r[:-len(MARK)]
                if r.startswith('ERR'):
                    # errors carry no marker (the payload writes them itself): trust once a later read matches
                    time.sleep(0.3)
                    if _adb('exec-out', 'cat', D + 'lpa_out.txt').stdout.decode('utf-8', 'replace').replace(chr(13), '') == r: return r
                # anything else: not written yet ('cat: No such file') or only partly written (the game writes it in
                # place; on the phone a read can see just 'OK' for a moment, which once ate queued chat messages)
            return 'TIMEOUT'
        finally:
            if got: _unlock()


def guard():
    r = _raw(GUARD)
    if not r.startswith('OK'): raise RuntimeError('guard not installed: ' + r[:200])
    return r[3:].strip()


def run(code, allow_send=False, timeout=15):
    if SERIAL not in ALLOWED: raise RuntimeError('serial %s is not an Aegis device' % SERIAL)
    check(code, allow_send)
    g = guard()
    r = _raw(code, timeout)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('%s send=%s guard=[%s] code_chars=%d result_chars=%d ok=%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), allow_send, g, len(code), len(r), r.startswith('OK')))   # no code or results: they can hold names/coordinates
    return r


if __name__ == '__main__':
    a = sys.argv[1:]
    allow = '--allow-send' in a
    a = [x for x in a if x != '--allow-send']
    if not a: sys.exit(__doc__)
    code = open(a[1], encoding='utf-8').read() if a[0] == '-f' else a[0]
    try: print(run(code, allow))
    except Refused as e: sys.exit('REFUSED: %s' % e)
