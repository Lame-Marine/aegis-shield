# Instructions for an AI agent setting this up

Goal: get the reader, guard and bot running against ONE Android device the user owns. Work in this order and verify each step with real output before moving on.

## Ground rules
- Drive only the device the user names. Always pass `-s <serial>` to adb, check `adb -s <serial> shell getprop ro.product.model` first, and add the serial to `ALLOWED` in `aegis/device.py`. Never touch other devices.
- Throwaway or guest account only. No real money. Do not type passwords or codes; if a login wall appears, stop and ask.
- One driver per game: the game polls `files/lpa_cmd.txt` and writes `files/lpa_out.txt` once a second. Never run two bridges at once (bot plus a manual script) without pausing the bot.
- No Lua or adb input while the game process is under about 3 minutes old (login breaks).
- Player-facing sends (chat, mail, invites, renames) go through the guard. Do not widen the guard or add permits without the user's explicit yes; every new permit kind needs a `test_guard.py` case.
- Some `aegis/*.py` files use CRLF line endings. Edit them CRLF-safely and run `ast.parse` on the file after every edit.
- Logs must hold no player data (counts, kinds, timestamps only). Keep it that way.

## Steps
1. Environment: Python 3.10+, `pip install -r requirements.txt`, adb on PATH, the game installed and logged in as a guest on the target device, fully updated (resource download finished).
2. Device config: `config/device.json` -> `{"serial": "..."}`, plus an `ALLOWED` entry in `aegis/device.py` (`model` from getprop, `kind` emulator or phone, `root`).
3. Reader: `python aegis/build_reader.py --check`. If the reader is missing and the bundle md5 matches `Version.txt`, run `--install`. A game update replaces the bundle: rerun `--check` / `--install`. Failure modes (bytecode wrapper, file ownership on non-root phones): `docs/reference/devices-and-recovery.md`.
4. Smoke test: `python aegis/run.py "return 1+1"`, then `python aegis/test_guard.py` must print ALL PASS (it sends nothing; it uses a spy).
5. Fresh map: the game must be on the world map with `Data.WorldData.serverId` equal to the home kingdom. `python aegis/sweep.py --name <x>` runs a search. If replies are empty, see `docs/reference/game-internals.md` (World map).
6. Config: copy each `config/*.json.example` to `.json`. `recipients.json`, `active_allow.json` and `covert_allow.json` map an in-game name to a playerId (always match ids, never names). Leave `covert_rooms.json` as `[]`.
7. Bot: run `python aegis/bot.py` detached with output sent to a file, not pipes. Design, commands and rate limits: `docs/reference/query-bot.md`. Confirm `bot started` in `logs/bot.log`.
8. Optional phone hosting (Termux): `docs/reference/devices-and-recovery.md`, then `PHONE=<ip>:5555 python aegis/deploy_phone.py --first`.
9. Uptime: `aegis/watchdog.py` (start scripts are in `aegis/`).

## Known gaps after cleaning
- The daily sync to an external database and the author's private tooling were removed.
- Some docs mention `lpa_*` bridge names: the vendored copies are in `vendor/lpa/`.
- Not everything was re-run after the cleanup: start with `test_guard.py` and fix path assumptions as they show up.
