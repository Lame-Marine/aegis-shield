# Game protocol notes (read-only capture of our own traffic, 2026-11-03)

How it was done: `tcpdump -i tun0 tcp port 9929` inside the rooted instance (emulator-5554) for 40 s while the bot did
one map refresh, then `aegis/pcap_peek.py` (framing, entropy, `--frames`) and `aegis/scramble_fit.py` (per-frame key
fit). The capture held other players' march data, so it was deleted after the analysis; only these notes are kept.

## Transport
- One TCP connection to the game server (166.117.33.252:9929 on 2026-11-03, an AWS Global Accelerator address),
  inside the instance's VPN tunnel. Two other connections were plain HTTPS (443).
- No TLS on 9929. Overall entropy 7.99 bits/byte only because the bodies are scrambled (below).

## Framing (every byte of the capture parsed: 516 server frames, 6 client frames)
```
70 a3 | u16 x | u16 name_len | name (ASCII, e.g. "WorldMapViewC2S") | u32 body_len | body
```
- Message names travel in plain text, the same names as the Lua protobuf schema (`pb.fields(name)`).
- `x` looks random per frame (0-255 seen). Its role is unknown (checksum? padding?).

## Body scramble
- body = protobuf (`pb.encode(name, table)`), then per byte: `cipher = ((plain + a) & 0xFF) ^ b`.
- `(a, b)` changes every frame in each direction: `a` goes down by 1 and `b` goes up by 16 (mod 256).
  Verified on 2 client frames (known plaintext from the game's own encoder) and 5 consecutive server frames (fitted by
  requiring valid protobuf for the named message).
- So it is an obfuscation keyed by a per-connection start value and a frame counter, not encryption. Anyone holding
  one known frame per direction can decode the rest of the connection.

## Login capture (dummy account, 2026-11-21) - answers most of the open questions
Capture: `tcpdump -i tun0 -s 0 -w x.pcap tcp` on the rooted dummy (LDPlayer 2, own WireGuard exit) while the game started once; pcap deleted after
analysis (it held the dummy's login token). Tools: `re_src/login_peek.py` (connections, SNI hosts, 9929 frames), `login_fit.py` (scramble
start fit), `login_fields.py` (generic protobuf dump of LoginReqC2S). Scripts expect the pcap path edited in.
- **Scramble start is FIXED, the same in both directions, counted from the first frame of each direction on a fresh connection:** frame k uses
  `a = (126 - k) & 255`, `b = (144 + 16k) & 255` (the pair (254, 16) is the same mapping). `plain = ((cipher ^ b) - a) & 255`; encrypt is the
  inverse. Found by requiring every frame of the login (2 client, 6 server) to parse as protobuf: exactly one pair survives. Empty-body frames
  still advance the counter.
- **`x` (the 2 bytes after the 70 a3 magic):** random-looking (203, 34 client; 0, 24, 202, 26, 33, 104 server); not the sum/xor of the plain or
  cipher body. Whether the server checks it is still unknown (only an injected frame can show that).
- **Login order on 9929:** C: `LoginNoticeC2S` {4: gameId 441, 3: language, 2: userId}; S: `LoginNoticeS2C` (empty), `AckCode`("LoginNoticeC2S");
  C: `LoginReqC2S`; S: `AckCode`("LoginReqC2S"), `LoginReconnectTokenKeyS2C` {1: number, 2: 96 hex chars}, `AppVersionInfoS2C` {2: "1.0.845"},
  then either the session or `DisconnectCode` {1: {2: code}}.
- **`LoginReqC2S` fields:** 10/8 package name, 2 userId, 19 unix time, 12 '37hw', 17 'ANDROID', 103 varint, 101 repeated {1 key, 2 value} (info JSON,
  ram, gpu, rating, cid, appsFlyerId, distinctId, cpu), 4 gameId, 15/16 device brand+model, 20 a 344-char SDK token (the thing a headless client must
  get from the HTTPS login), 13 language, 23 device cid, 25 resource version, 9 app version code, 104 JSON with a tick/time, 18 user agent, 14 net type,
  3 android id. The SDK config also carries a client-side `LOGIN_SALT` (signing of the HTTPS login, not captured).
- **Before the game socket, over HTTPS:** gpassport.laasglobal.com (SDK login, guest `auto_login`: loginAccount `MVFN:<userId>`), metadata / geventsapi
  .laasglobal.com, appsflyer, an eyugame/37games report host hit about once a second (hw-slg-report.eyugame.com), notice fetch, then 166.117.33.252:9929.
- **A brand-new guest account from the dummy gets through the whole handshake and is then dropped:** server sends `DisconnectCode` 1003 ('Status error'
  in the game's text) right after `AppVersionInfoS2C`. Cause unknown (new-account/server assignment, emulator or IP flag are the candidates).
- Still open for a headless client: how the SDK token (field 20) is produced (needs the decrypted HTTPS exchange: system-CA MITM or a hook),
  what the server checks in field 104 / `x`, and why a fresh guest is refused with 1003.
