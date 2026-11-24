"""build_reader.py - rebuild + install the read-only Lua reader (lpa_cmd.txt/lpa_out.txt bridge) on the Aegis device (device.py) after a
game update changed the bundle it lives in. Own copy for Aegis: never writes into vendor/ (the original build in
gamelua/out is shared with his instance). Reuses its payload_reader.lua read-only.

    .venv/Scripts/python.exe aegis/build_reader.py --check     what is on the device now
    .venv/Scripts/python.exe aegis/build_reader.py --install   build from the device's CURRENT bundle, push, restart the game

Steps: pull ABAsset/25/<bundle> + Version.txt; the bundle must match Version.txt's md5 (the game's own file); decode the
MiniGame TextAsset (xor key), append the payload, re-encode, save; force-stop; push bundle; set its md5/size in
Version.txt; push; give BOTH files back to the game's uid (adb pushes them as 'shell', read-only for the game, which made
the 1.0.801 update fail with 'Sync AB Update ... LuaScript/GamePlay/Hotels/Game'); start the game (-force-gles30).
"""
import hashlib, json, os, subprocess, sys, time
import UnityPy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from device import SERIAL as SER, MODEL, ROOT
ADB = os.path.expandvars(r'%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe') if os.name == 'nt' else 'adb'
PKG = 'com.phs.global'
ACT = PKG + '/com.games37.sdk.AtlasPluginDemoActivity'
BASE = '/sdcard/Android/data/%s/files/ABAsset' % PKG
NAME = 'luascript_gameplay_hotels_game.assetbundles'
K = b'eyugame_lua_zombiesrpg'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'build')
PAYLOAD = os.path.join(HERE, '..', 'vendor', 'lpa', 'gamelua', 'payload_reader.lua')
xor = lambda b: bytes(c ^ K[i % len(K)] for i, c in enumerate(b))


def adb(*a, binary=False):
    r = subprocess.run([ADB, '-s', SER, *a], capture_output=True)
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace').strip()


def su(cmd): return adb('shell', "su -c '%s'" % cmd) if ROOT else adb('shell', cmd)   # phone: no root, shell can read Android/data


def state():
    vt = adb('exec-out', 'cat', BASE + '/Version.txt', binary=True)
    j = json.loads(vt.decode('utf-8-sig'))
    entry = next(x for x in j['abList'] if x['fileName'] == NAME)
    dev = adb('exec-out', 'cat', '%s/25/%s' % (BASE, NAME), binary=True)
    return j, entry, dev


def check():
    j, e, dev = state()
    md5 = hashlib.md5(dev).hexdigest() if dev else None
    patched = bool(dev) and any(b'lpa_cmd' in xor(bytes(d.m_Script.encode('utf-8', 'surrogateescape') if isinstance(d.m_Script, str) else d.m_Script))
                                for d in (o.read() for o in UnityPy.load(dev).objects if o.type.name == 'TextAsset') if d.m_Name == 'MiniGame')
    d = BASE.replace('/sdcard', '/data/media/0') if ROOT else BASE
    owners = su('stat -c "%%U %%a %%n" %s/Version.txt %s/25/%s' % (d, d, NAME))
    print('Version.txt entry md5 %s | device bundle md5 %s | reader in bundle: %s' % (e['md5'], md5, patched))
    print(owners)
    return e, dev, md5, patched


def build(dev):
    env = UnityPy.load(dev)
    payload = open(PAYLOAD, 'rb').read()
    done = False
    for o in env.objects:
        if o.type.name == 'TextAsset':
            d = o.read()
            if d.m_Name == 'MiniGame':
                cur = d.m_Script.encode('utf-8', 'surrogateescape') if isinstance(d.m_Script, str) else bytes(d.m_Script)
                src = xor(cur)
                assert b'lpa_cmd' not in src, 'bundle already has the reader'
                if src.startswith(b'\x1bLua'):
                    # 1.0.801+: the script ships as compiled Lua 5.4 bytecode; appended source would be ignored. Wrap it:
                    # a source chunk that loads the original bytecode unchanged, runs it, then starts the reader.
                    esc = ''.join('\\%03d' % c for c in src).encode()
                    new = (b'local __lpa_f = assert(load("' + esc + b'", "@MiniGame", "b"))\n'
                           b'local __lpa_r = table.pack(__lpa_f(...))\n' + payload +
                           b'\nreturn table.unpack(__lpa_r, 1, __lpa_r.n)\n')
                else:
                    assert b'GameLuaMain' in src or b'MiniGame' in src, 'MiniGame did not decode: xor key changed?'
                    new = src + b'\n\n' + payload + b'\n'
                d.m_Script = xor(new).decode('utf-8', 'surrogateescape'); d.save(); done = True
    assert done, 'no MiniGame TextAsset in the bundle'
    return env.file.save()


def install():
    assert adb('shell', 'getprop', 'ro.product.model') == MODEL, 'wrong device'
    e, dev, md5, patched = check()
    if patched and '--force' in sys.argv:                          # rebuild from the saved original of this version
        orig = os.path.join(OUT, [f for f in sorted(os.listdir(OUT), key=lambda f: os.path.getmtime(os.path.join(OUT, f)))
                                  if f.startswith('pristine_')][-1])
        dev = open(orig, 'rb').read(); md5 = hashlib.md5(dev).hexdigest(); patched = False
        e = dict(e, md5=md5); print('rebuilding from', os.path.basename(orig))
    if patched: print('reader already installed'); return
    assert dev and md5 == e['md5'], 'device bundle does not match Version.txt (update still running?)'
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, 'pristine_%s_%s' % (md5[:8], NAME)), 'wb').write(dev)
    data = build(dev)
    new = hashlib.md5(data).hexdigest()
    open(os.path.join(OUT, NAME), 'wb').write(data)
    print('built %s -> %s (%d KB)' % (md5[:8], new[:8], len(data) // 1024))
    adb('shell', 'am', 'force-stop', PKG); time.sleep(2)
    j, e, _ = state()                                              # re-read after stop: the game may have rewritten it
    open(os.path.join(OUT, 'Version_%s.txt.orig' % md5[:8]), 'wb').write(b'\xef\xbb\xbf' + json.dumps(j, ensure_ascii=False, separators=(',', ':')).encode())
    e['md5'], e['size'] = new, len(data) // 1024
    vt = os.path.join(OUT, 'Version.txt')
    open(vt, 'wb').write(b'\xef\xbb\xbf' + json.dumps(j, ensure_ascii=False, separators=(',', ':')).encode())
    adb('push', os.path.join(OUT, NAME), '%s/25/%s' % (BASE, NAME))
    adb('push', vt, BASE + '/Version.txt')
    if ROOT:                                       # emulator (Android 9 sdcardfs): pushed files belong to 'shell', give them back
        d = BASE.replace('/sdcard', '/data/media/0')
        uid = su('stat -c %%u %s' % d)
        print('owner fix:', su('chown %s:ext_data_rw %s/Version.txt %s/25/%s; chmod 660 %s/Version.txt %s/25/%s; echo ok' % (uid, d, d, NAME, d, d, NAME)))
    else:                                          # phone (Android 12 FUSE): files under the game's folder get the game's owner
        print('owner (no root, FUSE):', su('stat -c "%%U %%a" %s/Version.txt %s/25/%s' % (BASE, BASE, NAME)).replace(chr(10), ' / '))
    check()
    adb('shell', 'am', 'start', '-n', ACT, *(['-e', 'unity', '-force-gles30'] if ROOT else []))   # GLES flag: LDPlayer only
    print('game started')


if __name__ == '__main__':
    install() if '--install' in sys.argv else check()
