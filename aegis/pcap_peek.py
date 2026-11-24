"""pcap_peek.py - read-only look at a capture of the game's TCP stream (port 9929): is it plaintext protobuf, compressed,
or encrypted? Prints framing guesses, entropy and whether known strings appear. Prints no player data.
    python aegis/pcap_peek.py logs/pcap/<file>.pcap
"""
import math, struct, sys, zlib, collections

f = open(sys.argv[1], 'rb').read()
magic, = struct.unpack('<I', f[:4])
le = magic == 0xa1b2c3d4
E = '<' if le else '>'
linktype = struct.unpack(E + 'I', f[20:24])[0]
off, pkts = 24, []
while off + 16 <= len(f):
    ts, tu, incl, orig = struct.unpack(E + 'IIII', f[off:off + 16]); off += 16
    pkts.append((ts + tu / 1e6, f[off:off + incl])); off += incl
print('linktype', linktype, 'packets', len(pkts))

streams = collections.defaultdict(list)          # (src,dst) -> [(seq, payload)]
for t, p in pkts:
    if linktype == 1: p = p[14:]                  # ethernet
    elif linktype == 113: p = p[16:]              # linux cooked
    v = p[0] >> 4
    if v == 4:
        ihl = (p[0] & 15) * 4; proto = p[9]; src, dst = p[12:16], p[16:20]; tcp = p[ihl:]
    else:
        proto = p[6]; src, dst = p[8:24], p[24:40]; tcp = p[40:]
    if proto != 6: continue
    sp, dp, seq = struct.unpack('>HHI', tcp[:8]); doff = (tcp[12] >> 4) * 4
    pay = tcp[doff:]
    if pay: streams[(sp, dp)].append((seq, t, pay))

def entropy(b):
    c = collections.Counter(b); n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values()) if n else 0

for (sp, dp), segs in streams.items():
    segs.sort(); data, seen = b'', set()
    for seq, t, pay in segs:
        if seq in seen: continue
        seen.add(seq); data += pay
    way = 'client->server' if dp == 9929 else 'server->client'
    print('\n== %s  %d bytes in %d segments, entropy %.2f bits/byte' % (way, len(data), len(segs), entropy(data)))
    print('   first 48 bytes:', data[:48].hex(' '))
    # framing guess: walk 4-byte big/little-endian length prefixes
    for name, fmt, hdr in (('u32 BE len', '>I', 4), ('u32 LE len', '<I', 4), ('u16 BE len', '>H', 2)):
        i, n, ok = 0, 0, True
        while i + hdr <= len(data) and n < 400:
            L = struct.unpack(fmt, data[i:i + hdr])[0]
            if L <= 0 or L > 2_000_000: ok = False; break
            i += L + (0 if 'incl' in name else hdr); n += 1
        if ok and n > 3 and abs(i - len(data)) < 64 * 1024:
            print('   framing fits %s: %d frames' % (name, n))
    for s in (b'WorldMapView', b'Aegis', b'Shield', b'serverId', b'K263'):
        print('   contains %-14r %s' % (s, s in data))
    hits = 0
    for i in range(0, min(len(data), 200000)):
        if data[i] == 0x78 and data[i + 1:i + 2] in (b'\x9c', b'\x01', b'\xda', b'\x5e'):
            try: zlib.decompressobj().decompress(data[i:i + 4096]); hits += 1
            except Exception: pass
    print('   zlib stream starts found:', hits)
    print('   gzip magic (1f8b) found:', data.count(b'\x1f\x8b'), ' zstd magic found:', data.count(b'\x28\xb5\x2f\xfd'), ' lz4 frame magic found:', data.count(b'\x04\x22\x4d\x18'))


def frames(data):
    """70 a3 | u16 ? | u16 name_len | name | u32 body_len | body"""
    i, out = 0, []
    while i + 10 <= len(data):
        if data[i:i + 2] != b'\x70\xa3': return out, i
        x, nl = struct.unpack('>HH', data[i + 2:i + 6]); name = data[i + 6:i + 6 + nl]
        bl, = struct.unpack('>I', data[i + 6 + nl:i + 10 + nl]); body = data[i + 10 + nl:i + 10 + nl + bl]
        if len(body) < bl: return out, i
        out.append((x, name.decode('latin1'), body)); i += 10 + nl + bl
    return out, i


if __name__ == '__main__' and '--frames' in sys.argv:
    for (sp, dp), segs in streams.items():
        segs.sort(); data, seen = b'', set()
        for seq, t, pay in segs:
            if seq not in seen: seen.add(seq); data += pay
        fr, end = frames(data)
        print('\n## %s: %d frames parsed, %d of %d bytes' % ('client->server' if dp == 9929 else 'server->client', len(fr), end, len(data)))
        for x, name, body in fr[:40]:
            print('  x=%5d %-34s body %6d  %s' % (x, name, len(body), body[:20].hex(' ')))
