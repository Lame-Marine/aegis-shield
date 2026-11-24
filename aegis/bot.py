"""bot.py - Aegis Shield query bot. Private channels only (DM = 4, group = 5); replies go back to the origin room.
Queries (case-insensitive, * and ? wildcards):
    player <name>      cities whose name matches
    alliance <tag>     players of a matching tag from OTHER servers only (home-kingdom alliances are not searchable)
    invaders           every city on the map whose server is not ours
Group chats: only when the message tags @aegis / @aegis shield. Replies: coordinate cards + fixed texts (never echo).

Concurrency: every valid query starts at once from the current map snapshot (refreshed if older than REFRESH s) and
gets its "Found N" text first. Cards then go out round-robin across all active queries, so a one-player lookup is not
stuck behind a long invader list. The chat limit is PER ACCOUNT (ratetest2.py 2026-11-03, distinct cards: alternating
2-3 rooms is refused as often as one room; 21302 = 'Input too frequent', 21304 = 'Same input too frequent'), so ALL outgoing messages share one outbox and one adaptive pace: start at PACE, double on any
refusal (max MAX_PACE), ease back after OK_STREAK successes. A refused message is retried (up to RETRIES times).
Before each card the player's position is re-read from the snapshot; players who left are skipped.
Limits: 2 active queries per sender, 10 overall, 50 cards per query.
Keeps no player data on disk: logs/bot.log holds time, channel, query kind and counts only.
    python aegis/bot.py            (Ctrl+C to stop)
"""
import os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R
import fastmap as FM
import active as A
import territory as TERR
import covert as CV
import json

PACE, MAX_PACE, OK_STREAK, RETRIES, REFRESH = 1.5, 10.0, 5, 5, 20
MUTE_PAUSE = 1800      # after a 21307 ('Doctor is muted') on a text, skip texts this long, then try again
CARD_TEXT = 110        # while muted, a text goes out as a share card (royal city) with the text as its label (operator's OK)
DUP_WINDOW = 120       # the server refuses (21304) an identical card repeated in the same room; skip those instead
MAX_PER_QUERY = 50
MAX_PLAYER_MATCHES = 10   # player searches above this get a warning and only the strongest 10
MAX_TEXT = 100         # stay within what a player could type (server does not enforce a limit; client box does)
MAX_PER_SENDER, MAX_JOBS = 2, 10
INV_CAP = 20              # invader searches share only the strongest 20 (KvK can have hundreds)
SMALL_JOB = 3             # searches with this few cards left go before the long lists
BACKLOG_CAP = 100         # cards already waiting: above this a new multi-card search is turned away with a wait estimate
EGGS = {}   # per-player special replies: {(playerId, lowercase text): reply}; match on id, never on display name
ACTIVE_ALLOW = os.path.join(HERE, '..', 'config', 'active_allow.json')   # who may switch active mode on/off (operator decides)
COVERT_ROOMS = os.path.join(HERE, '..', 'config', 'covert_rooms.json')   # group names where every member may run covert (tagged)
COVERT_ALLOW = os.path.join(HERE, '..', 'config', 'covert_allow.json')   # name -> player id; covert answers these DMs only (operator decides)
TAG = re.compile(r'@\s*aegis(?:\s*shield)?\b', re.I)      # @aegis or @aegis shield
LOG = os.path.join(HERE, '..', 'logs', 'bot.log')
BUSY = os.path.join(HERE, '..', 'logs', 'bot_busy.txt')   # pending jobs + texts; 0 = safe to restart
HEART = os.path.join(HERE, '..', 'logs', 'bot_heart.txt')  # unix time of the last good game round-trip (watchdog.py reads it)
SEP, RS = chr(31), chr(30)
TEXT = {
    'usage': 'Unknown command. Send commands for the list. In groups, start with @aegis.',
    'none': 'No matching cities on the map right now.',
    'bare_none': 'No player by that name on the map. Send commands for the list.',
    'home_alliance': 'Home kingdom alliances are not searchable.',
    'full': 'Too many searches running. Try again in a minute.',
    'dup': 'Same result as shared above.',
    'running': 'Already sharing that here, see above.',
}


COMMANDS = [                 # operator's wording (2026-11-01); everyday use only, admin commands left out on purpose
    'Find a player: @aegis player <player_name> or @aegis <player_name>',
    'Wildcards work in names: * = any letters, ? = one letter (e.g. @aegis jen* or @aegis *fox)',
    'Find an alliance: @aegis alliance <alliance_tag> or @aegis [<alliance_tag>] (e.g. @aegis [CRWN])',
    'Find invaders: @aegis invaders.',
    'Can filter by kingdom with @aegis invaders <xxx> (e.g. @aegis invaders 264)',
    'Get kingdom coordinates: @aegis kingdom <xxx>',
    'Want to search privately, DM me. In DMs, @aegis is not required.',
    'Join the Aegis Defender group (K263 players): @aegis join, or DM me join',
]


def found_text(n, capped):
    return 'Found %d. Sharing now.' % n + (' Showing the first %d.' % MAX_PER_QUERY if capped else '')


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f: f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')


def body(r):
    if not r.startswith('OK'): raise RuntimeError(r[:300])
    return r.split('\n', 1)[1] if '\n' in r else ''


def install():
    R.guard()
    for f in ('listener2.lua', 'reply.lua', 'fastmap.lua'):
        r = R._raw(open(os.path.join(HERE, f), encoding='utf-8').read())
        if not r.startswith('OK'): raise RuntimeError('install %s failed: %s' % (f, r[:120]))
    if body(R._raw("return tostring(AE_IN ~= nil and AE_REPLY ~= nil and AE_MAP ~= nil)")).strip() != 'true':
        raise RuntimeError('install incomplete (game still loading?)')


def take():
    out = []
    for rec in body(R._raw('return AE_IN.take()')).split(RS):
        p = rec.split(SEP)
        if len(p) == 7: out.append({'key': p[0], 'ch': int(p[1]), 'from': p[2], 'fromId': p[3], 'atMe': p[4] == 'true', 't': int(p[5]), 'text': p[6]})
    return out


def reply(key, kind, *a):
    r = _reply(key, kind, *a)
    if r != 'sent': log('reply %s not sent: %s' % (kind, r[:120]))
    return r


def _reply(key, kind, *a):
    if kind == 'text' and len(a[0]) > MAX_TEXT: a = (a[0][:MAX_TEXT - 1].rstrip() + '…',) + a[1:]
    args = ', '.join(FM.lstr(x) if isinstance(x, str) else str(int(x)) for x in a)
    return body(R._raw('return AE_REPLY(%s, %s, %s)' % (FM.lstr(key), FM.lstr(kind), args))).strip()


def server_errors():
    return body(R._raw('return AE_REPLY_ERRS()')).strip()


CTL_DIR = '/sdcard/Download/aegis-ctl' if os.name != 'nt' else os.path.join(HERE, '..', 'logs')   # watchdog control files
HOME = 263
JOIN_CFG = os.path.join(HERE, '..', 'config', 'join.json')   # {"group": name, "home_only": true}; no file = join off
JOIN_EVERY, JOIN_HOUR = 30, 60     # per-player gap (s) against double sends; invites per hour
CHAT_EVERY = 300       # chat health check interval (s)
WIN_EVERY = 300           # re-read the Kingdom War / throne timers this often
KW_PRESENT = "local AM = require('AbyssEmpire.Logic.Activity.ActivityManager') for _, a in pairs(AM.Activities) do if rawget(a, 'zoneContestDetail') ~= nil then return 'true' end end return 'false'"
TERR_EVERY = 600          # rebuild alliance territories this often (they move slowly)
RECARD = 2             # 2: alert room moved to Aegis Defender (operator, 2026-11-07)
ROYAL = (500, 500)     # royal city (throne, world point type 10) at the map centre; checked on K263


def kingdom_exists(sid):
    """The game's own server list (Data.ServerInfosData, loaded at login; 421 kingdoms on 2026-11-01)."""
    r = body(R._raw('local D = Data.ServerInfosData return tostring(D:ExistServerId(%d) == true) .. " " .. tostring(D:GetMaxServerId())' % int(sid))).split()
    return r[0] == 'true', int(r[1])


def room_of(key):
    return body(R._raw('local G = _G.AEGIS_GUARD local ri = AE_IN.rooms[%s] return ri and G.ser(ri) or ""' % FM.lstr(key))).strip()


def set_active_room():
    """Point the synthetic reply key 'active' at the alert group (survives the listener's room-ref pruning)."""
    return body(R._raw('for _, r in pairs(Data.ChatData:GetRoomListByChannelType(5) or {}) do local ok, nm = pcall(function() return r:GetName() end) '
                       'if nm == %s then AE_IN.rooms["active"] = r.m_Dto.roomInfo return "ok" end end return "missing"' % FM.lstr(A.ROOM_NAME))).strip() == 'ok'


def in_group(key, names):
    """True if the message with this key came from one of the named group chats (compared by the game's room data)."""
    if not names: return False
    lua = ('local G = _G.AEGIS_GUARD local ri = AE_IN.rooms[%s] if not ri then return "no" end local me = G.ser(ri) '
           'local want = {%s} for _, r in pairs(Data.ChatData:GetRoomListByChannelType(5) or {}) do '
           'local ok, nm = pcall(function() return r:GetName() end) if ok and want[nm] and G.ser(r.m_Dto.roomInfo) == me then return "yes" end end return "no"'
           % (FM.lstr(key), ', '.join('[%s] = true' % FM.lstr(n) for n in names)))
    return body(R._raw(lua)).strip() == 'yes'


def parse(text):
    """-> (kind, query, tag_filter, bare). Bare text = player name; [TAG] = alliance; [TAG] name = player within tag."""
    t = TAG.sub(' ', text).strip()
    m = re.match(r'^(player|alliance)\s+(.+)$', t, re.I)
    if m:
        kind, q = m.group(1).lower(), m.group(2).strip()
        if kind == 'alliance': q = q.strip('[] ')                 # alliance [croc] -> croc
        else:
            b = re.match(r'^\[([^\]]+)\]\s*(.+)$', q)              # player [croc] name -> name within tag
            if b: return 'player', b.group(2).strip(), b.group(1).strip(), False
        if q: return kind, q, None, False
    m = re.match(r'^invaders?(?:\s+(?:from\s+)?(?:kingdom\s*|k|#)?(\d{1,4}))?$', t, re.I)   # invaders / invaders 264 / invaders K264
    if m: return 'invaders', '', m.group(1), False
    if re.match(r'^(status|ping)$', t, re.I): return 'status', '', None, False
    if re.match(r'^join$', t, re.I): return 'join', '', None, False
    if re.match(r'^(commands?|help|\?)$', t, re.I): return 'commands', '', None, False
    m = re.match(r'^coverts?(?:\s+ops?)?(?:\s+(?:kingdom\s*|k|#)?(\d{1,4}))?$', t, re.I)   # covert / coverts / covert ops / coverts 264
    if m: return 'covert', m.group(1), None, False
    m = re.match(r'^active\s+(on|off)$', t, re.I)
    if m: return 'active', m.group(1).lower(), None, False
    if re.match(r'^(excludes|exclusions|exclude list)$', t, re.I): return 'excludes', '', None, False
    m = re.match(r'^(exclude|include)\s*\[?\s*([^\]\s]+)\s*\]?$', t, re.I)
    if m: return m.group(1).lower(), m.group(2), None, False
    m = re.match(r'^kingdom\s*(\d{1,4})$', t, re.I)            # kingdom 217 -> that kingdom's royal city
    if m: return 'coord', (int(m.group(1)), ROYAL[0], ROYAL[1], 'royal'), None, False
    if re.match(r'^kingdom(\s*-?[\d.]+)?$', t, re.I): return 'badkingdom', '', None, False   # kingdom -2, kingdom 2.5, kingdom 99999
    m = re.match(r'^(?:(?:k|kingdom|#)?\s*(\d{1,4})\s*[\s:/]\s*)?(\d{1,4})\s*[,:\s]\s*(\d{1,4})$', t, re.I)
    if m: return 'coord', (int(m.group(1)) if m.group(1) else None, int(m.group(2)), int(m.group(3)), None), None, False
    m = re.match(r'^\[([^\]]+)\]\s*(.*)$', t)
    if m:
        tag, rest = m.group(1).strip(), m.group(2).strip()
        if not tag: return None, None, None, False
        return ('player', rest, tag, False) if rest else ('alliance', tag, None, False)
    if t and len(t) <= 40: return 'player', t, None, True
    return None, None, None, False


class Bot:
    def __init__(self):
        self.texts = []          # pending short texts: {key, ch, text, tries}
        self.jobs = []           # active queries: {key, ch, from, ids, sent, skipped, tries}
        self.redirected = {}           # alert room: playerId -> last 'DM me' pointer (memory only)
        self.joined, self.join_ts = {}, []   # join command: playerId -> last invite time (memory only), invites in the last hour
        self.rr = 0              # round-robin pointer into jobs
        self.pace, self.ok = PACE, 0
        self.next_send = 0
        self.last = None         # last message sent: ('text', item) or ('card', job, pid, tries)
        self.map_at = 0
        self.act = A.load(); self.act_next = 0
        self.act_was = self.act.get('was_on')                          # persisted: a restart neither re-announces nor misses an off
        self.recent = {}         # (room, x, y, label) -> time shared, kept DUP_WINDOW s, memory only
        self.muted_until = 0     # 21307 'Doctor is muted' on a text: texts are dropped until then, cards still go

    # ---- incoming ---------------------------------------------------------------------------------------------
    def send_now(self, key, kind, *a, what='message'):
        """Send outside the outbox (the covert scan blocks the loop): keeps the pace, checks the server's answer and
        retries once after backing off. Returns True when the server did not refuse it."""
        if kind == 'text' and self.text_muted():
            kind, a, what = 'share', self.as_card(a[0]), what + ' (as card, muted)'
        for attempt in range(2):
            wait = self.next_send - time.time()
            if wait > 0: time.sleep(wait)
            self.settle_last()                                       # earlier errors belong to the earlier send
            r = reply(key, kind, *a)
            self.next_send = time.time() + self.pace
            if r and r not in ('ok', 'sent', 'OK'): log('%s not sent: %s' % (what, r[:60])); return False
            time.sleep(1.5)
            errs = server_errors()
            if not errs or all('21304' in e for e in errs.split('; ')): log('%s sent' % what); return True
            if '21307' in errs and kind == 'text':
                self.muted_until = time.time() + MUTE_PAUSE
                log('%s refused: muted (21307), texts go out as cards for %d min' % (what, MUTE_PAUSE // 60))
                return self.send_now(key, 'text', *a, what=what)
            self.pace = min(MAX_PACE, self.pace * 2); self.ok = 0
            log('%s refused (%s), pace now %.1fs%s' % (what, errs[-24:], self.pace, ', retrying' if attempt == 0 else ''))
        return False

    def covert(self, m, kingdom):
        k = kingdom or str(HOME)
        self.send_now(m['key'], 'text', 'Covert scan of K%s started, about 2 minutes. Collectable top ops are shared as they turn up.' % k,
                      what='ch4 covert start notice')
        open(BUSY, 'w').write('1'); self._busy_written = None
        try:
            sid = int(k)
            def hit(o):                                              # top-tier op: share mid-scan, but keep the send pace
                self.send_now(m['key'], 'secret', *CV.card(o, sid), what='ch4 covert top op shared live')
            kk, ops, maxed, hits = CV.scan(int(k) if kingdom else None, on_hit=hit)
        except Exception as e:
            self.say(m, 'Covert scan failed: %s' % str(e)[:70]); log('ch4 covert failed: %s' % str(e)[:120]); return
        finally:
            self.map_at = 0                                          # map view moved: next query refreshes the snapshot
        if not ops:
            # a reachable kingdom always has covert ops (~1,500); 0 means the game session stopped delivering them
            # (seen 2026-11-09 23:00, fixed by a game restart): ask the watchdog for a restart instead of reporting 0
            self.say(m, 'Covert scan of K%d came back empty (game glitch). Restarting the game, send covert again in about 3 minutes.' % kk)
            try: open(os.path.join(CTL_DIR, 'restart_game'), 'w').write('covert K%d returned 0 ops' % kk)
            except OSError as e: log('restart_game request failed: %s' % e)
            log('ch4 covert K%d: 0 ops -> game restart requested' % kk); return
        soon = sorted((o for o in ops if o['status'] == 'running' and o['boxes'] >= 15), key=lambda o: o['ready_min'])
        self.say(m, CV.summary(kk, ops, maxed) + (' %d top op%s shared above.' % (len(hits), '' if len(hits) == 1 else 's') if hits else '')
                 + (' %d top op%s still running, first ready in %d min.' % (len(soon), '' if len(soon) == 1 else 's', soon[0]['ready_min']) if soon else ''))
        done = {o['uniq'] for o in hits}
        for o in [o for o in ops if o['status'] == 'ready' and o['uniq'] not in done][:CV.TOP]:
            self.texts.append({'key': m['key'], 'ch': 4, 'secret': CV.card(o, kk), 'tries': 0})
        log('ch4 covert K%d: %d ops, %d ready' % (kk, len(ops), sum(1 for o in ops if o['status'] == 'ready')))
        log('covert sweep: %s' % ', '.join('%s=%s' % kv for kv in CV.LAST.items()))

    def refresh(self, force=False):
        if force or time.time() - self.map_at > REFRESH:
            for attempt in range(3):
                try:
                    n, dt = FM.refresh(); break
                except RuntimeError as e:
                    if 'map server id' in str(e):
                        if attempt == 0: log('map view not on home kingdom: switching back'); CV.go_home()
                        time.sleep(3)                    # just after a switch the map reports nil for a moment
                    elif 'no full map reply' in str(e) and attempt < 2: time.sleep(2)   # first view after entering the map
                    else: raise
            else: raise RuntimeError('map not ready after 3 tries')
            self.map_at = time.time(); return n, dt
        return None, 0

    def join(self, m):
        """'join' (DM, or a group chat when tagged) -> an invite to the defence group (operator, 2026-11-07). No member
        tracking: the invite is always sent and the game handles members. K263 players only (config/join.json home_only);
        a JOIN_HOUR cap and a short per-player gap against double sends, in memory only."""
        cfg = json.load(open(JOIN_CFG, encoding='utf-8')) if os.path.exists(JOIN_CFG) else {}
        group = cfg.get('group')
        if not group: self.say(m, 'usage'); return
        now = time.time()
        self.join_ts = [t for t in self.join_ts if now - t < 3600]
        if now - self.joined.get(m['fromId'], 0) < JOIN_EVERY:
            log('ch%d join repeat ignored' % m['ch']); return
        if len(self.join_ts) >= JOIN_HOUR:
            self.say(m, 'Too many invites right now. Try again later.'); log('ch%d join hourly cap' % m['ch']); return
        if cfg.get('home_only', True):
            sid = body(R._raw('return AE_SENDER_SID(%s)' % FM.lstr(m['fromId']))).strip()   # home kingdom from chat, not the map
            if sid != str(HOME):
                self.say(m, '%s is for K%d players only.' % (group, HOME)); log('ch%d join refused: home K%s' % (m['ch'], sid)); return
        r = body(R._raw('return AE_INVITE(%s, %s)' % (FM.lstr(group), FM.lstr(m['fromId'])))).strip()
        log('ch%d join -> %s' % (m['ch'], r))
        if r != 'sent': self.say(m, 'Could not send the invite. Try again later.'); return
        self.joined[m['fromId']] = now; self.join_ts.append(now)
        self.say(m, 'Invite to %s sent to %s. Accept it in your chats.' % (group, m['from']))

    def say(self, m, key):
        self.texts.append({'key': m['key'], 'ch': m['ch'], 'text': TEXT.get(key, key), 'tries': 0})

    def handle(self, m):
        if m['ch'] == 5 and not (m['atMe'] or TAG.search(m['text'])): return
        kind, q, tagf, bare = parse(m['text'])
        if m['ch'] == 5 and kind not in ('active', 'exclude', 'include', 'excludes') and set_active_room() \
                and room_of(m['key']) == room_of('active'):
            # the alert room (Aegis Defender) is alerts only (operator, 2026-11-13): shield control stays, everything else
            # gets one 'DM me' pointer per person per hour, then silence
            if time.time() - self.redirected.get(m['fromId'], 0) > 3600:
                self.redirected[m['fromId']] = time.time()
                self.say(m, '%s is alerts only. DM me for searches and other commands.' % A.ROOM_NAME)
            log('ch5 alert room: %s redirected to DMs' % (kind or 'unknown')); return
        if kind == 'player' and not tagf:                         # temporary easter egg (operator, 2026-11-02)
            q = EGGS.get((m['fromId'], q.strip().lower()), q)
        if not kind: self.say(m, 'usage'); log('ch%d usage' % m['ch']); return
        if kind in ('active', 'exclude', 'include', 'excludes'):
            allowed = set(json.load(open(ACTIVE_ALLOW, encoding='utf-8')).values())   # re-read: edits apply without a restart
            in_room = set_active_room() and room_of(m['key']) == room_of('active')
            if kind == 'active' and m['fromId'] not in allowed:
                self.say(m, 'usage'); return                         # on/off: allowlisted people only, unlisted
            if not (in_room or (m['ch'] == 4 and m['fromId'] in allowed)):
                self.say(m, 'usage'); return
            if kind == 'active':
                self.act['override'], self.act['override_for'], self.act['override_day'] = q, A.scheduled_on(), A.server_day()
                if q == 'on': self.act['baselined'] = False
                A.save(self.act)
                if not in_room: self.say(m, 'Active mode %s. Alerts go to %s.' % (q.upper(), A.ROOM_NAME))
                self.act_next = 0; log('ch%d active %s' % (m['ch'], q)); return
            tags = self.act['exclude']
            if kind == 'exclude' and q.lower() not in [t.lower() for t in tags]: tags.append(q)
            if kind == 'include': self.act['exclude'] = tags = [t for t in tags if t.lower() != q.lower()]
            A.save(self.act)
            self.say(m, 'Excluded this KvK: %s.' % (', '.join('[%s]' % t for t in tags) if tags else 'none'))
            log('ch%d %s (%d excluded)' % (m['ch'], kind, len(tags))); return
        if kind == 'covert':
            allowed = set(json.load(open(COVERT_ALLOW, encoding='utf-8')).values())   # re-read: edits apply without a restart
            rooms = json.load(open(COVERT_ROOMS, encoding='utf-8')) if os.path.exists(COVERT_ROOMS) else []
            ok = (m['ch'] == 4 and m['fromId'] in allowed) or (m['ch'] == 5 and in_group(m['key'], rooms))
            if not ok:                                               # allowlisted DMs + listed groups only, unlisted: others get the normal reply
                self.say(m, 'usage'); return
            self.covert(m, q); return
        if kind == 'join':
            self.join(m); return
        if kind == 'commands':
            for line in COMMANDS: self.say(m, line)
            log('ch%d commands' % m['ch']); return
        if kind == 'badkingdom':
            self.say(m, 'Use kingdom <1-%d>, e.g. kingdom 217.' % kingdom_exists(HOME)[1]); log('ch%d coord bad kingdom' % m['ch']); return
        if kind == 'coord':
            sid, x, y, what = q
            sid = sid or HOME
            if not (0 <= x <= 1000 and 0 <= y <= 1000):
                self.say(m, 'x and y must be between 0 and 1000.'); log('ch%d coord bad' % m['ch']); return
            ok, top = kingdom_exists(sid)
            if not ok:
                self.say(m, 'Kingdom %d does not exist (max %d).' % (sid, top)); log('ch%d coord no kingdom' % m['ch']); return
            self.texts.append({'key': m['key'], 'ch': m['ch'], 'card': (x, y, ('K%d Royal City' % sid) if what == 'royal' else ('K%d %d,%d' % (sid, x, y)), sid), 'tries': 0})
            log('ch%d coord card' % m['ch']); return
        if kind == 'status':
            n = len(self.jobs); self.texts.insert(0, {'key': m['key'], 'ch': m['ch'], 'text': 'Online. %d search%s running. Active mode %s.' % (n, '' if n == 1 else 'es', 'ON' if A.is_on(self.act) else 'off'), 'tries': 0}); log('ch%d status' % m['ch']); return
        sig = (room_of(m['key']), kind, (q or '').lower(), str(tagf or '').lower())
        if any(j.get('sig') == sig for j in self.jobs):
            self.say(m, 'running'); log('ch%d %s merged with running search' % (m['ch'], kind)); return
        mine = sum(1 for j in self.jobs if j['from'] == m['fromId'])
        if mine >= MAX_PER_SENDER or len(self.jobs) >= MAX_JOBS:
            self.say(m, 'full'); log('ch%d full' % m['ch']); return
        n, dt = self.refresh()
        rows = FM.query(kind, q)
        if kind == 'invaders' and tagf:                    # tagf carries the kingdom number here
            rows = [r for r in rows if r['sid'] == str(int(tagf))]
        elif tagf:
            tp = re.compile('^' + re.escape(tagf).replace(r'\*', '.*').replace(r'\?', '.') + '$', re.I)
            rows = [r for r in rows if tp.match(r['tag'] or '')]
        if kind == 'alliance' and not rows and FM.query('hometag', q):
            self.say(m, 'home_alliance'); log('ch%d alliance home-refused' % m['ch']); return
        if not rows:
            self.say(m, 'bare_none' if bare else 'none'); log('ch%d %s none%s' % (m['ch'], kind, ' (bare)' if bare else '')); return
        rows.sort(key=lambda r: -r['power'])
        backlog = self.backlog()
        if len(rows) > 1 and backlog > BACKLOG_CAP:
            self.say(m, 'Busy: about %d min of results queued. Try again shortly%s.'
                     % (max(1, round(backlog * self.pace / 60)), ', or use invaders <kingdom>' if kind == 'invaders' else ''))
            log('ch%d %s turned away (backlog %d)' % (m['ch'], kind, backlog)); return
        capped = len(rows) > MAX_PER_QUERY
        if kind == 'invaders' and len(rows) > INV_CAP:
            self.say(m, 'Found %d invaders. Sharing the %d strongest.%s' % (len(rows), INV_CAP, '' if tagf else ' Use invaders <kingdom> for one kingdom.'))
            rows = rows[:INV_CAP]
        elif kind == 'player' and len(rows) > MAX_PLAYER_MATCHES:      # broad name / wildcard: warn, share only the strongest
            self.say(m, 'Found %d players matching. Sharing the %d strongest. Use more of the name to narrow it.'
                     % (len(rows), MAX_PLAYER_MATCHES))
            rows = rows[:MAX_PLAYER_MATCHES]
        else:
            rows = rows[:MAX_PER_QUERY]
            if len(rows) > 1: self.say(m, found_text(len(rows), capped))
        self.jobs.append({'key': m['key'], 'ch': m['ch'], 'from': m['fromId'], 'ids': [r['id'] for r in rows], 'sent': 0, 'skipped': 0, 'tries': {}, 'sig': sig})
        log('ch%d %s found %d (%d active)%s' % (m['ch'], kind, len(rows), len(self.jobs), (' map %d in %.1fs' % (n, dt)) if n else ''))

    # ---- outbox -----------------------------------------------------------------------------------------------
    def backlog(self):
        return sum(len(j['ids']) for j in self.jobs) + len(self.texts)

    def text_muted(self):
        return time.time() < self.muted_until

    @staticmethod
    def as_card(text):
        """muted-chat fallback: the text as the label of a point share on our royal city (shares are not muted)"""
        t = ' '.join(text.split())
        if len(t) > CARD_TEXT: t = t[:CARD_TEXT - 1].rstrip() + '…'
        return (ROYAL[0], ROYAL[1], t, HOME)

    def settle_last(self):
        """Errors that arrived since the previous send belong to it: retry it and back off; otherwise count a success."""
        if not self.last: return
        errs = server_errors()
        if errs and '21307' in errs and self.last[0] == 'text' and 'text' in self.last[1]:
            # chat mute: plain text is refused but shares still go through. Drop the text, no retry, no slowdown.
            self.muted_until = time.time() + MUTE_PAUSE
            self.texts.insert(0, self.last[1])
            log('muted (21307): texts go out as cards for %d min' % (MUTE_PAUSE // 60)); self.last = None; return
        if errs and all('21304' in e for e in errs.split('; ')):
            # 21304 = identical message already in that room (e.g. sent before a restart): skip it, no slowdown
            if self.last[0] == 'card': self.last[1]['sent'] -= 1
            log('duplicate skipped (21304)'); self.last = None; return
        if errs:
            self.pace = min(MAX_PACE, self.pace * 2); self.ok = 0
            if self.last[0] == 'text':
                it = self.last[1]; it['tries'] += 1
                if it['tries'] <= RETRIES: self.texts.insert(0, it)
            else:
                _, j, pid, tries = self.last
                j['sent'] -= 1
                if tries < RETRIES: j['ids'].insert(0, pid); j['tries'][pid] = tries + 1
                elif j not in self.jobs: pass
            log('refused (%s); pace now %.1fs' % (errs[-24:], self.pace))
        else:
            self.ok += 1
            if self.ok >= OK_STREAK and self.pace > PACE: self.pace = max(PACE, self.pace / 1.5); self.ok = 0
        self.last = None

    def is_dup(self, key, card):
        """True if this card already went to this room in the last DUP_WINDOW s; otherwise record it."""
        now = time.time()
        self.recent = {k: t for k, t in self.recent.items() if now - t < DUP_WINDOW}
        k = (room_of(key),) + tuple(card)
        if k in self.recent: return True
        self.recent[k] = now
        return False

    def finish_jobs(self):
        keep = []
        for j in self.jobs:
            if j['ids']: keep.append(j)
            else: log('ch%d job done: %d shared, %d left the map' % (j['ch'], j['sent'], j['skipped']))
        self.jobs = keep

    def send_one(self):
        if time.time() < self.next_send: return
        self.settle_last()                      # before anything else: a refused card goes back into its job
        self.finish_jobs()
        # people's replies and search results go before shield alert cards (key 'active'); alerts only when nothing else waits
        user = [i for i, it in enumerate(self.texts) if it['key'] != 'active']
        if self.texts and (user or not self.jobs):
            it = self.texts.pop(user[0] if user else 0)
            if 'secret' in it:
                reply(it['key'], 'secret', *it['secret'])
            elif 'card' in it:
                if not it.get('nodup') and self.is_dup(it['key'], it['card'][:3]):
                    it = {'key': it['key'], 'ch': it['ch'], 'text': TEXT['dup'], 'tries': 0}
                    if self.text_muted(): reply(it['key'], 'share', *self.as_card(it['text']))
                    else: reply(it['key'], 'text', it['text'])
                else: reply(it['key'], 'share', *it['card'])
            else:
                if self.text_muted(): reply(it['key'], 'share', *self.as_card(it['text']))
                else: reply(it['key'], 'text', it['text'])
            self.last = ('text', it)
        else:
            if not self.jobs: return
            self.refresh()
            sent = False
            small = [j for j in self.jobs if len(j['ids']) <= SMALL_JOB]     # one-off lookups jump the queue
            order = small + [self.jobs[(self.rr + i) % len(self.jobs)] for i in range(len(self.jobs)) if self.jobs[(self.rr + i) % len(self.jobs)] not in small]
            if not small: self.rr += 1
            for j in order:
                while j['ids'] and not sent:
                    pid = j['ids'].pop(0)
                    row = FM.at(pid)
                    if not row: j['skipped'] += 1; continue      # left the map since the search
                    r = FM.parse_row(row)
                    if not r: j['skipped'] += 1; continue
                    label = ('[%s] %s' % (r['tag'], r['name'])) if r['tag'] else r['name']
                    x, y = r['x'], r['y']
                    if self.is_dup(j['key'], (x, y, label)):
                        j['dups'] = j.get('dups', 0) + 1
                        if j['dups'] == 1: self.texts.append({'key': j['key'], 'ch': j['ch'], 'text': TEXT['dup'], 'tries': 0})
                        continue
                    reply(j['key'], 'share', x, y, label)
                    j['sent'] += 1
                    self.last = ('card', j, pid, j['tries'].get(pid, 0))
                    sent = True
                if sent: break
            if not sent: return
        self.next_send = time.time() + self.pace

    def fight_window(self):
        """(start, end) unix s of the royal-city fight from the throne's timers, but only while the Kingdom War activity exists
        on the account (no Kingdom War = no special window). Cached WIN_EVERY s; any failure = no window (normal alerts)."""
        if time.time() - getattr(self, 'win_at', 0) < WIN_EVERY: return getattr(self, 'win', None)
        self.win_at, win = time.time(), None
        try:
            has = FM.body(R._raw(KW_PRESENT)).strip() == 'true'
            th = FM.throne() if has else None
            if th and th['shield_end'] and th['fight_end'] > th['shield_end']: win = (th['shield_end'], th['fight_end'])
            if (win is None) != (getattr(self, 'win', 0) is None):
                log('active: fight window %s' % ('none (no Kingdom War)' if not has else 'unavailable' if win is None else 'set from the throne timers'))
        except Exception as e:
            log('active: fight window lookup failed: %r' % e)
        self.win = win
        return win

    def territories(self):
        """Alliance territories from the current map snapshot (positions + tags only, in memory), rebuilt every TERR_EVERY s.
        A failure keeps the old set (or none): alerts must never wait on this."""
        if time.time() - getattr(self, 'terr_at', 0) < TERR_EVERY and getattr(self, 'terr', None) is not None:
            return self.terr
        try:
            cities = FM.allied()
            if len(cities) >= 200:                       # an empty/thin snapshot is a glitch, not an answer
                self.terr = TERR.build(cities); self.terr_at = time.time()
                log('active: %d territories from %d allied cities' % (len(self.terr), len(cities)))
        except Exception as e:
            log('active: territory build failed: %r' % e); self.terr_at = time.time() - TERR_EVERY + 60   # retry in a minute
        return getattr(self, 'terr', None) or []

    def active_tick(self):
        if time.time() < self.act_next: return
        self.act_next = time.time() + A.EVERY
        if self.act.get('week') != A.week_id(): self.act = A.load()
        on = A.is_on(self.act)
        if on != self.act_was:
            if not set_active_room(): log('active: room %s not found' % A.ROOM_NAME); return
            if self.act_was is not None or on:
                self.texts.append({'key': 'active', 'ch': 5, 'text': A.ON_TEXT if on else A.OFF_TEXT, 'tries': 0})
            log('active mode %s' % ('ON' if on else 'off')); self.act_was = on
            self.act['was_on'] = on
            if not on: self.act['seen'], self.act['baselined'] = {}, False
            A.save(self.act)
        if not on or len(self.texts) > 12: return
        set_active_room()
        self.refresh(force=time.time() - self.map_at > A.EVERY - 5)
        n, top = FM.ladder(200)
        inv = FM.query('invaders')
        if not self.act.get('baselined'):              # first look after switching on: one summary, no card flood
            self.texts.append({'key': 'active', 'ch': 5, 'text': A.baseline(self.act, inv, top), 'tries': 0})
            A.save(self.act); log('active: baseline %d' % len(self.act['seen'])); return
        A.count_arrivals(self.act, inv)
        w0 = (self.act.get('win') or {}).get('at')
        summ, why_s = A.mode(self.act, FM.kingdom_holder(), window=self.fight_window())
        summ = summ and A.SUMMARY_MODE
        if self.act.get('recard') != RECARD:     # bump RECARD to re-card everyone on the map once (e.g. after moving the alert room)
            self.act['recard'] = RECARD; self.act['seen'] = {}; log('active: re-carding everyone on the map')
        w = self.act.get('win') or {}
        if w.get('at') and not w0:
            self.texts.append({'key': 'active', 'ch': 5, 'tries': 0, 'text': 'KvK result: royal city now held by %s.%s' % (
                w.get('holder'), ' Summary mode ends in 30 min.' if A.SUMMARY_MODE else '')})
            log('active: KvK winner seen: %s' % w.get('holder'))
        if summ != self.act.get('summary_on', False):            # announce switches once
            self.act['summary_on'] = summ
            self.texts.append({'key': 'active', 'ch': 5, 'tries': 0, 'text':
                ('Summary mode (%s): cards for MR/UR/SSR only, update every 10 min.' % why_s) if summ else 'Back to normal: a card for every invader.'})
            log('active: summary mode %s (%s)' % ('ON' if summ else 'off', why_s))
            if summ: self.act['dg_at'] = 0                         # first update goes out with this scan, then every 10 min
        alerts, watching, gone = A.scan(self.act, inv, top, summary=summ)
        dg = A.digest(self.act, watching) if summ else None
        if dg: self.texts.append({'key': 'active', 'ch': 5, 'text': dg, 'tries': 0}); self.act['sent_ts'].append(time.time())
        terrs = self.territories() if alerts else []
        for r, why in alerts:
            where = ''
            try: where = TERR.locate(terrs, r['x'], r['y'])['text'] if terrs else ''   # operator 2026-11-14: one alliance only, inside beats near
            except Exception as e: log('active: territory lookup failed: %r' % e)
            label, g = A.card_label(r, why, top, where)
            self.texts.append({'key': 'active', 'ch': 5, 'card': (r['x'], r['y'], label), 'tries': 0, 'nodup': True})
            self.act['sent_ts'].append(time.time())
            # (the 'Grade X: only ... should try' advice line was dropped, operator 2026-11-07: the card carries the grade)
        A.save(self.act)
        if alerts or gone: log('active: %d alerts, watching %d, %d left' % (len(alerts), watching, gone))

    def chat_health(self):
        """Every CHAT_EVERY s: Aegis is always in several groups, so 0 group rooms means the game's chat is not connected
        (2026-11-10: after a reconnect at 11:38 the game came back but chat stayed empty for 3 h while the reader and the
        heartbeat looked fine). Two empty checks in a row -> ask the watchdog for a game restart."""
        if time.time() < getattr(self, 'chat_next', 0): return
        self.chat_next = time.time() + CHAT_EVERY
        n = int(body(R._raw('local n = 0 for _ in pairs(Data.ChatData:GetRoomListByChannelType(5) or {}) do n = n + 1 end return n')).strip() or 0)
        self.chat_empty = 0 if n else getattr(self, 'chat_empty', 0) + 1
        if self.chat_empty == 2:
            log('chat not connected (0 group rooms twice): game restart requested')
            try: open(os.path.join(CTL_DIR, 'restart_game'), 'w').write('chat not connected (0 group rooms)')
            except OSError as e: log('restart_game request failed: %s' % e)
        if self.chat_empty >= 6: self.chat_empty = 0              # still empty 25 min later: ask again

    def loop(self):
        install()
        log('bot started (round-robin, adaptive pace from %.1fs)' % self.pace)
        last_install = time.time()
        while True:
            try:
                if time.time() - last_install > 60: install(); last_install = time.time()   # survives a game restart
                for m in take(): self.handle(m)
                open(HEART + '.tmp', 'w').write('%d' % time.time()); os.replace(HEART + '.tmp', HEART)   # atomic: watchdog.py reads it
                self.active_tick()
                self.chat_health()
                self.send_one()
            except Exception as e:
                log('error: %s' % str(e)[:200]); time.sleep(3)
                if re.search(r"AE_IN|AE_REPLY|AE_MAP|AEGIS_GUARD|guard not installed|install", str(e)):
                    last_install = 0                                     # game restarted: reinstall on the next pass
            time.sleep(0.1 if (self.jobs or self.texts or self.last) else 1.0)
            busy = len(self.jobs) + len(self.texts)
            if busy != getattr(self, '_busy_written', None):           # restart_bot.ps1 waits for 0
                open(BUSY, 'w').write(str(busy)); self._busy_written = busy


if __name__ == '__main__':
    Bot().loop()
