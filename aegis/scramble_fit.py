"""scramble_fit.py - recover the per-frame (a, b) of the body scramble  cipher = ((plain + a) & 255) ^ b  for every frame
in a capture, by keeping the pair whose output is valid protobuf for that message's top-level fields (schema.json, read
from the game). Then look for how (a, b) relates to the frame header and order. Read-only analysis of our own capture.
    python aegis/scramble_fit.py logs/pcap/<file>.pcap
"""
import json, os, struct, sys
sys.argv.append('--quiet')
HERE = os.path.dirname(os.path.abspath(__file__))
SCH = json.load(open(os.path.join(HERE, '..', 'logs', 'pcap', 'schema.json')))
import importlib.util
spec = importlib.util.spec_from_file_location('peek', os.path.join(HERE, 'pcap_peek.py'))
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    peek = importlib.util.module_from_spec(spec); sys.argv = [sys.argv[0], sys.argv[1]]; spec.loader.exec_module(peek)

VARINT = {'int32', 'int64', 'uint32', 'uint64', 'bool', 'sint32', 'sint64', 'enum'}


def valid(buf, fields):
    """strict top-level wire check: every key is a known field with the right wire type, lengths fit exactly"""
    want = {int(n): t for n, t in fields}
    i, n = 0, len(buf)
    while i < n:
        key = 0; s = 0
        while True:
            if i >= n or s > 28: return False
            c = buf[i]; i += 1; key |= (c & 127) << s; s += 7
            if c < 128: break
        fn, wt = key >> 3, key & 7
        if fn not in want: return False
        t = want[fn]
        if wt == 0:
            if t not in VARINT: return False
            for _ in range(10):
                if i >= n: return False
                c = buf[i]; i += 1
                if c < 128: break
            else: return False
        elif wt == 2:
            if t in VARINT and t != 'bool':
                pass                                   # packed repeated scalars are allowed
            L = 0; s = 0
            while True:
                if i >= n or s > 28: return False
                c = buf[i]; i += 1; L |= (c & 127) << s; s += 7
                if c < 128: break
            i += L
            if i > n: return False
        elif wt in (1, 5):
            i += 8 if wt == 1 else 4
            if i > n: return False
        else: return False
    return True


def fit(name, body):
    if name not in SCH or not body: return None
    out = []
    head = body[:64]
    for a in range(256):
        for b in range(256):
            p = bytes(((c ^ b) - a) & 255 for c in head)
            if len(body) <= 64:
                if valid(p, SCH[name]): out.append((a, b))
            else:
                full = bytes(((c ^ b) - a) & 255 for c in body)
                if p[0] & 7 in (0, 2) and valid(full, SCH[name]): out.append((a, b))
    return out


rows = []
for (sp, dp), segs in peek.streams.items():
    segs.sort(); data, seen = b'', set()
    for seq, t, pay in segs:
        if seq not in seen: seen.add(seq); data += pay
    fr, _ = peek.frames(data)
    way = 'C>S' if dp == 9929 else 'S>C'
    for k, (x, name, body) in enumerate(fr[:60] if way == 'S>C' else fr):
        if name not in SCH or len(body) > 600: continue
        sols = fit(name, body)
        rows.append((way, k, x, name, len(body), sols))
        print('%s #%-3d x=%3d (0x%02x) %-22s %4dB  ab=%s' % (way, k, x, x, name, len(body), sols[:4] if sols else sols))
