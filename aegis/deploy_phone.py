"""deploy_phone.py - pack the Aegis bot for the S10's Termux copy and hand it over (run on the PC).
    python aegis/deploy_phone.py            build build/phone_bundle.tar and drop it into the phone's aegis-ctl folder:
                                            the phone watchdog unpacks it over ~/aegis-re and restarts the bot
    python aegis/deploy_phone.py --first    first install: put the bundle + install script in Download (run the script in Termux)
Bundle: aegis/*.py *.lua *.sh, config/*.json (device.json -> 127.0.0.1:5555), vendor/lpa = read-only copies of
vendor/lpa/kingdom_sweep.py + gamelua/payload_reader.lua and a stub lpa_run (covert only uses kingdom_sweep's
Lua strings). Never logs, never .env or anything else from operator's repos."""
import io, json, os, subprocess, sys, tarfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
LPA = os.path.join(ROOT, 'vendor', 'lpa')
ADB = os.path.expandvars(r'%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe')
PHONE = os.environ.get('PHONE', '')   # ip:port of the phone, e.g. 192.168.1.20:5555
STUB = b'def run(*a, **k):\n    raise RuntimeError("lpa_run is not available in the phone bundle (Aegis uses run.py)")\n'


def build():
    out = os.path.join(ROOT, 'build', 'phone_bundle.tar'); os.makedirs(os.path.dirname(out), exist_ok=True)
    def add(t, name, data):
        ti = tarfile.TarInfo(name); ti.size = len(data); ti.mtime = time.time(); ti.mode = 0o644; t.addfile(ti, io.BytesIO(data))
    with tarfile.open(out, 'w') as t:
        for f in sorted(os.listdir(HERE)):
            if f.endswith(('.py', '.lua', '.sh')): add(t, 'aegis/' + f, open(os.path.join(HERE, f), 'rb').read())
        for f in sorted(os.listdir(os.path.join(ROOT, 'config'))):
            if f.endswith('.json') and f not in ('device.json', 'active.json'):   # active.json = the phone's live shield state
                add(t, 'config/' + f, open(os.path.join(ROOT, 'config', f), 'rb').read())
        add(t, 'config/device.json', json.dumps({'serial': '127.0.0.1:5555'}).encode() + b'\n')
        add(t, 'vendor/lpa/kingdom_sweep.py', open(os.path.join(LPA, 'kingdom_sweep.py'), 'rb').read())
        add(t, 'vendor/lpa/gamelua/payload_reader.lua', open(os.path.join(LPA, 'gamelua', 'payload_reader.lua'), 'rb').read())
        add(t, 'vendor/lpa/gamelua/lpa_run.py', STUB)
        add(t, 'vendor/lpa/lpa_run.py', STUB)
    return out


def adb(*a): return subprocess.run([ADB, '-s', PHONE, *a], capture_output=True, text=True).stdout.strip()


if __name__ == '__main__':
    b = build(); print('built', b, os.path.getsize(b) // 1024, 'KB')
    if '--first' in sys.argv:
        print(adb('push', b, '/sdcard/Download/aegis_bundle.tar'))
        print(adb('push', os.path.join(HERE, 'phone_install.sh'), '/sdcard/Download/aegis_install.sh'))
    else:
        adb('shell', 'mkdir', '-p', '/sdcard/Download/aegis-ctl')
        print(adb('push', b, '/sdcard/Download/aegis-ctl/deploy.tar.part'))
        print(adb('shell', 'mv', '/sdcard/Download/aegis-ctl/deploy.tar.part', '/sdcard/Download/aegis-ctl/deploy.tar'))
        print('dropped: the phone watchdog unpacks it within 30 s')
