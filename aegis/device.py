"""device.py - which device the Aegis tools drive. config/device.json picks one of ALLOWED; nothing else can be chosen
(any device not listed here is never driven). Every tool imports SERIAL/MODEL from here.
    {"serial": "<phone-ip>:5555"}          a phone over Wi-Fi adb (add its ip:port to ALLOWED below)
    {"serial": "emulator-5554"}          LDPlayer instance 0
"""
import json, os
ALLOWED = {
    'emulator-5554': {'model': 'SM-S9110', 'kind': 'emulator', 'root': True},
    # '<phone-ip>:5555': {'model': '<ro.product.model>', 'kind': 'phone', 'root': False},   # your phone: copy this line
    # the same S10 driving itself from Termux (adb to its own adbd). NOT 'emulator-5554': inside Termux adb also lists the
    # phone's own port under that name, which on the PC means the LDPlayer instance.
    '127.0.0.1:5555': {'model': 'SM-G973F', 'kind': 'phone', 'root': False, 'local': True},
}
CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'device.json')
SERIAL = json.load(open(CFG, encoding='utf-8'))['serial'] if os.path.exists(CFG) else 'emulator-5554'
if SERIAL not in ALLOWED: raise RuntimeError('device %r is not an Aegis device (allowed: %s)' % (SERIAL, ', '.join(ALLOWED)))
INFO = ALLOWED[SERIAL]
MODEL, EMULATOR, ROOT = INFO['model'], INFO['kind'] == 'emulator', INFO['root']
