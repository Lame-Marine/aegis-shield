"""phone_ui.py - read and tap the phone's UI by element text / id / description (uiautomator dump), never by fixed
screen coordinates. For setting up the uptime-trial phone (Galaxy S10).
    python aegis/phone_ui.py dump
    python aegis/phone_ui.py tap "<text or id or desc>"      (exact match first, then case-insensitive substring)
"""
import os, re, subprocess, sys, time
SERIAL = os.environ['PHONE']
ADB = os.path.expandvars(r'%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe')


def adb(*a): return subprocess.run([ADB, '-s', SERIAL, *a], capture_output=True, text=True, errors='replace').stdout


def nodes():
    adb('shell', 'uiautomator', 'dump', '/sdcard/ui.xml')
    x = adb('shell', 'cat', '/sdcard/ui.xml')
    out = []
    for m in re.finditer(r'<node ([^>]*)>', x):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        b = [int(v) for v in re.findall(r'\d+', a.get('bounds', ''))]
        if len(b) == 4: out.append({'text': a.get('text', ''), 'id': a.get('resource-id', '').split('/')[-1], 'desc': a.get('content-desc', ''),
                                    'click': a.get('clickable') == 'true', 'cx': (b[0] + b[2]) // 2, 'cy': (b[1] + b[3]) // 2, 'cls': a.get('class', '').split('.')[-1]})
    return out


def find(q):
    ns = nodes()
    for n in ns:
        if q in (n['text'], n['id'], n['desc']): return n
    ql = q.lower()
    for n in ns:
        if ql in n['text'].lower() or ql in n['desc'].lower() or ql in n['id'].lower(): return n
    return None


def tap(q, wait=1.5):
    n = find(q)
    if not n: raise SystemExit('not on screen: %r' % q)
    adb('shell', 'input', 'tap', str(n['cx']), str(n['cy'])); time.sleep(wait)
    return n


if __name__ == '__main__':
    if sys.argv[1] == 'dump':
        for n in nodes():
            if n['text'] or n['desc'] or n['click']: print('%-10s %-28r %-26s %-22r (%d,%d)' % (n['cls'][:10], n['text'][:28], n['id'][:26], n['desc'][:22], n['cx'], n['cy']))
    elif sys.argv[1] == 'tap':
        print('tapped', tap(sys.argv[2]))
