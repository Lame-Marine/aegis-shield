"""active.py - Aegis Shield active mode: watch the map for invaders and alert one group room.
Used by bot.py (shares its outbox, pace and map snapshot). State in config/active.json, wiped every KvK week:
    exclude   alliance tags not to alert on (truces); set with @aegis exclude [TAG] / include [TAG]
    seen      invaders already alerted: id -> [x, y, shield]; dropped when they leave the map
    override  'on' / 'off' set by @aegis active on/off, valid until the next scheduled switch
Schedule: on during Saturday SERVER time. Server = UTC-2 (TimeUtil.GetLocalServerTimeZoneOffset() = 15 h with the
emulator on UTC+13, checked 2026-11-01).
Re-alerts only when an invader moves more than MOVE tiles or their shield drops.
Grades compare invader power with the home kingdom's power ladder from the same snapshot.
"""
import json, os, time, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, '..', 'config', 'active.json')
ROOM_NAME = 'Aegis Test'          # alert room (War Council was too busy for this); config/active_room.json overrides it
try: ROOM_NAME = json.load(open(os.path.join(HERE, '..', 'config', 'active_room.json'), encoding='utf-8'))['room']
except Exception: pass
EVERY, MOVE, MAX_PER_CYCLE = 30, 20, 20   # 20 cards per 30 s scan = the 1.5 s outbox pace (raised from 8, operator 2026-11-07)
SUMMARY_MODE = False   # 'push it' test (operator, 2026-11-07): every invader gets a card, no surge/hourly/fight-window summaries.
                       # mode() still runs for the KvK winner watch. Watch bot.log for 21302/21304 and pace changes.
ALERT_GRADES = ('MR', 'UR', 'SSR', 'SR', 'R', 'N')   # every invader gets a card (operator, 2026-11-01)
# Grades use the game's rarity tiers: MR (stronger than all of K263) > UR (top 3) > SSR (top 10) > SR (top 50) > R (top 200) > N
SUMMARY_EVERY = 300
# Summary mode: only MR/UR/SSR get their own card, everything else is counted into one update line every DIGEST_EVERY s.
# It switches on by itself for (a) the royal city fight window (throne shieldEndTime - PRE_FIGHT .. fightEndTime),
# (b) an arrival surge (SURGE_N new invaders within SURGE_WIN s; ends after SURGE_QUIET s below that), (c) the hourly
# cap (HOUR_CAP alert messages in the last hour). Times from the throne are the game's own (unix s).
CALM_GRADES = ('MR', 'UR', 'SSR')     # still carded in summary mode (SSR added by operator, 2026-11-07)
DIGEST_EVERY, PRE_FIGHT = 600, 3600
SURGE_N, SURGE_WIN, SURGE_QUIET = 10, 600, 1200
HOUR_CAP = 40
# KvK royal city fight: Saturday 12:00 server time (operator; matches the fight on Sat 31 Oct), lasts ~2 h max.
# Quiet window: 1 h before until WIN_COOLDOWN after the winner shows up (holder/victory time changes in
# Data.TempleData), at the latest FIGHT_HOURS after the start.
FIGHT_DAY, FIGHT_START_H, FIGHT_PRE_H, FIGHT_HOURS = 5, 12, 1, 3   # weekday 5 = Saturday
WIN_COOLDOWN = 1800
SERVER_UTC_OFFSET_H = -2
AUTO = True            # on by itself for server Saturday (KvK day): 00:00-24:00 server = 15:00 Sat - 15:00 Sun NZDT (operator, 2026-11-07)

ON_TEXT = 'AEGIS SHIELD ACTIVATING. Invader watch online.'
OFF_TEXT = 'AEGIS SHIELD STANDING DOWN. Invader watch offline.'


def week_id(now=None):
    d = datetime.datetime.utcfromtimestamp((now or time.time()) + SERVER_UTC_OFFSET_H * 3600)
    y, w, _ = d.isocalendar()
    return '%d-W%02d' % (y, w)


def scheduled_on(now=None):
    return datetime.datetime.utcfromtimestamp((now or time.time()) + SERVER_UTC_OFFSET_H * 3600).weekday() == 5   # Saturday


def load():
    try: s = json.load(open(STATE, encoding='utf-8'))
    except Exception: s = {}
    if s.get('week') != week_id():
        s = {'week': week_id(), 'exclude': [], 'seen': {}, 'override': None, 'override_for': None}
    return s


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, 'w', encoding='utf-8'))


def server_day(now=None):
    return datetime.datetime.utcfromtimestamp((now or time.time()) + SERVER_UTC_OFFSET_H * 3600).strftime('%Y-%m-%d')


def is_on(s, now=None):
    # a manual on/off lasts until the server day ends (daily reset), then the schedule takes over again
    if s.get('override') and s.get('override_day') == server_day(now): return s['override'] == 'on'
    return AUTO and scheduled_on(now)


def fmt_power(p): return ('%.0fM' % (p / 1e6)) if p >= 1e6 else ('%.0fK' % (p / 1e3))


def grade(inv, ladder_top):
    """-> (letter, advice). ladder_top: [(name, power, level)] strongest first."""
    above = [t for t in ladder_top if t[1] > inv['power']]
    rank = len(above)
    if inv.get('garrison', 0) > 0: rank = max(0, rank - 5)               # reinforced: harder than power alone says
    need = fmt_power(inv['power'])
    if rank == 0:
        return 'MR', 'stronger than anyone in K263. Rally only, no solo hits.'
    if rank <= 3:
        return 'UR', 'only %s should try.' % (' or '.join(t[0] for t in above[:3]) if len(above) < 3 else '%s, %s or %s' % tuple(t[0] for t in above[:3]))
    if rank <= 10:
        return 'SSR', 'K263 top 10 only, e.g. %s.' % ', '.join(t[0] for t in above[:3])
    if rank <= 50:
        return 'SR', 'needs %s+ power and Lv%d+, or a rally.' % (need, inv.get('level', 0))
    if rank < len(ladder_top):                                          # inside K263 top 200
        return 'R', 'fine for %s+ power, Lv%d+.' % (need, inv.get('level', 0))
    return 'N', 'most active players can take them (%s+).' % need


def describe(inv, why, ladder_top):
    """Short advice line for S+/S/A (the card title already carries the stats)."""
    g, advice = grade(inv, ladder_top)
    return 'Grade %s: %s' % (g, advice)


def describe_long(inv, why, ladder_top):
    g, advice = grade(inv, ladder_top)
    bits = ['K%s' % inv['sid'], 'Lv%d' % inv.get('level', 0), fmt_power(inv['power'])]
    if inv.get('kills'): bits.append('%s kills' % fmt_power(inv['kills']).replace('M', 'M').replace('K', 'K'))
    bits.append('shielded' if inv['shield'] else 'NO SHIELD')
    if inv.get('garrison', 0) > 0: bits.append('%d reinforcing' % inv['garrison'])
    return '%s: %s. Grade %s. %s' % (why, ' | '.join(bits), g, advice)


def card_label(inv, why, ladder_top, where=''):
    """One card per invader; the title reads as a sentence: who, from where, how strong, shield, grade.
    where: territory text ('Inside [TAG]' / '~N tiles from [TAG]' / ''), appended after the grade."""
    g, _ = grade(inv, ladder_top)
    name = ('[%s] %s' % (inv['tag'], inv['name'])) if inv['tag'] else inv['name']
    bits = ['K%s' % inv['sid'], 'Lv%d' % inv.get('level', 0), '%s power' % fmt_power(inv['power']),
            'shielded' if inv['shield'] else 'no shield']
    if inv.get('garrison', 0) > 0: bits.append('%d reinforcing' % inv['garrison'])
    lead = {'New invader': '', 'Invader moved': 'Moved: ', 'Shield DOWN': 'Shield down: '}[why]
    return '%s%s - %s. Grade %s%s' % (lead, name, ', '.join(bits), g, ('. ' + where) if where else ''), g


def mode(s, holder, now=None, window=None):
    """-> (summary?, reason). Keeps the surge clock and the KvK winner watch in s. holder = FM.kingdom_holder().
    window = (start, end) unix seconds of the royal-city fight, from the throne's own timers, ONLY while a Kingdom War
    is running (operator 2026-11-21: weeks without one have no special window; the fixed Saturday-12:00 rule is gone). None = no window."""
    now = now or time.time()
    s['arrivals'] = [t for t in s.get('arrivals', []) if now - t < SURGE_WIN]
    s['sent_ts'] = [t for t in s.get('sent_ts', []) if now - t < 3600]
    if window and window[0] - FIGHT_PRE_H * 3600 <= now < window[1]:
        fid = datetime.datetime.utcfromtimestamp(window[0]).strftime('%Y-%m-%d')
        key = holder and (holder['holder_tag'], holder['holder_sid'], holder['victory_ms'])
        w = s.get('win') or {}
        if w.get('fight') != fid: w = s['win'] = {'fight': fid, 'base': key, 'at': 0}
        if key and w['base'] is None: w['base'] = key
        if key and w['base'] and key != w['base'] and not w['at'] and now >= window[0]:
            w['at'] = now; w['holder'] = '[%s] K%s' % (holder['holder_tag'], holder['holder_sid']) if holder['holder_tag'] else 'K263'
        if not (w['at'] and now - w['at'] >= WIN_COOLDOWN):    # winner known 30 min ago: people have cleared out
            return True, 'KvK fight window'
    if len(s['arrivals']) >= SURGE_N: s['surge_until'] = now + SURGE_QUIET
    if now < s.get('surge_until', 0): return True, 'large wave of invaders'
    if len(s['sent_ts']) >= HOUR_CAP: return True, 'hourly alert limit'
    return False, ''


def count_arrivals(s, invaders, now=None):
    """Record new (unseen, not excluded) invaders in the surge clock BEFORE mode() decides, so a wave switches at once."""
    excl = {t.lower() for t in s['exclude']}
    n = sum(1 for r in invaders if r['id'] not in s['seen'] and r['tag'].lower() not in excl)
    s.setdefault('arrivals', []).extend([now or time.time()] * n)
    return n


def digest(s, watching, now=None):
    """One update line for everything summary mode held back (every DIGEST_EVERY s, only if something happened)."""
    now = now or time.time()
    d = s.get('dg') or {}
    if now - s.get('dg_at', 0) < DIGEST_EVERY or not any(d.values()): return None
    s['dg'], s['dg_at'] = {}, now
    g = ', '.join('%d %s' % (d[k], k) for k in ('SR', 'R', 'N') if d.get(k))
    t = 'Update: %d new invaders%s' % (sum(d.get(k, 0) for k in ('SR', 'R', 'N')), (' (%s)' % g) if g else '')
    if d.get('shield'): t += ', %d shields down' % d['shield']
    if d.get('moved'): t += ', %d moved' % d['moved']
    return t + '. Watching %d.' % watching


def scan(s, invaders, ladder_top, summary=False):
    """Compare with what was already alerted. -> list of (invader, reason) to alert now (max MAX_PER_CYCLE).
    summary=True: only MR/UR alerts; the rest is counted into s['dg'] for digest()."""
    excl = {t.lower() for t in s['exclude']}
    present, alerts, low = {}, [], 0
    for r in sorted(invaders, key=lambda r: -r['power']):
        if r['tag'].lower() in excl: continue
        present[r['id']] = r
        old = s['seen'].get(r['id'])
        if old is None: why = 'New invader'
        elif abs(old[0] - r['x']) + abs(old[1] - r['y']) > MOVE: why = 'Invader moved'
        elif old[2] and not r['shield']: why = 'Shield DOWN'
        else:
            s['seen'][r['id']] = [r['x'], r['y'], r['shield']]                # keep shield state current
            continue
        if grade(r, ladder_top)[0] not in ALERT_GRADES:
            s['seen'][r['id']] = [r['x'], r['y'], r['shield']]
            if why == 'New invader': low += 1
            continue
        if summary and grade(r, ladder_top)[0] not in CALM_GRADES:
            s['seen'][r['id']] = [r['x'], r['y'], r['shield']]
            d = s.setdefault('dg', {})
            k = {'New invader': grade(r, ladder_top)[0], 'Shield DOWN': 'shield', 'Invader moved': 'moved'}[why]
            d[k] = d.get(k, 0) + 1
            continue
        if len(alerts) < MAX_PER_CYCLE:
            alerts.append((r, why)); s['seen'][r['id']] = [r['x'], r['y'], r['shield']]
    gone = [k for k in s['seen'] if k not in present]
    for k in gone: del s['seen'][k]
    s['low_new'] = s.get('low_new', 0) + low
    s['gone'] = s.get('gone', 0) + len(gone)
    return alerts, len(present), len(gone)


def baseline(s, invaders, ladder_top):
    """On switching on: mark everyone already on the map as seen and return one summary line instead of a card flood."""
    excl = {t.lower() for t in s['exclude']}
    counts = {}
    for r in invaders:
        if r['tag'].lower() in excl: continue
        s['seen'][r['id']] = [r['x'], r['y'], r['shield']]
        g = grade(r, ladder_top)[0]; counts[g] = counts.get(g, 0) + 1
    s['low_new'], s['gone'], s['summary_at'] = 0, 0, time.time()
    s['baselined'] = True
    total = sum(counts.values())
    parts = ', '.join('%d %s' % (counts[g], g) for g in ('MR', 'UR', 'SSR', 'SR', 'R', 'N') if counts.get(g))
    return 'Watching %d invaders already here: %s. Send @aegis invaders for their cards.' % (total, parts or 'none')


def summary(s, watching):
    """Every SUMMARY_EVERY s: one line for the low-grade traffic, only if something changed."""
    if time.time() - s.get('summary_at', 0) < SUMMARY_EVERY: return None
    s['summary_at'] = time.time()
    return None                                    # every invader now gets its own card; no summary needed
    if not s.get('low_new') and not s.get('gone'): return None
    t = 'Update: %d new low-grade invaders (R/N), %d left. Watching %d.' % (s.get('low_new', 0), s.get('gone', 0), watching)
    s['low_new'], s['gone'] = 0, 0
    return t
