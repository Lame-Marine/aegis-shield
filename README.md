# Aegis Shield

A defensive helper bot for the mobile game **Last Asylum: Plague** (`com.phs.global`, Unity + xLua).
It runs a small Lua "reader" inside the game client over a file-polling channel, with a Python bot on top.
The bot watches the kingdom map and answers chat queries with coordinate cards: find a player,
list invaders from other kingdoms, alert a defence group when one lands.

The repo also holds the reverse-engineering notes (wire protocol, message schemas, client internals)
and the scripts used to produce them.

> **Read this first.** This injects code into a live game client. That is almost certainly against the
> game's Terms of Service. Use a throwaway account, expect a ban, never spend real money, and do not
> point it at accounts or chats you do not own. Provided as research material, with no warranty and no
> affiliation with the game's publisher. You are responsible for what you run.

## What is in here
| Path | What |
|---|---|
| `aegis/run.py`, `guard.lua` | Run Lua in the game; a guard that blocks every player-facing network send unless a narrow one-shot permit allows it |
| `aegis/build_reader.py` | Patches the reader into the game's Lua bundle (and re-patches after game updates) |
| `aegis/bot.py`, `active.py`, `covert.py`, `fastmap.*`, `territory.py` | Query bot, alert mode, map snapshot, alliance territory labels |
| `aegis/watchdog.py`, `phone_*.sh`, `deploy_phone.py` | Keep game and bot alive; host them on a spare Android phone via Termux |
| `aegis/*_test.py`, `test_guard.py` | Server-side bug tests and the guard self-test |
| `vendor/lpa/` | Reader payload (`payload_reader.lua`) and map-sweep helper |
| `dashboard/` | Local map and territory tuning page |
| `docs/` | Protocol notes, server checks that held up, and `docs/reference/` (devices, recovery, internals, bot design) |

## Quick start (for an AI agent or a human)
See **AGENTS.md** for the step-by-step. Short version:
1. You need an Android device you own: an LDPlayer/emulator instance, or a spare phone, reachable by adb. Log in with a guest account.
2. `python -m venv .venv`, then `pip install -r requirements.txt` into it.
3. `cp config/device.json.example config/device.json`, set your adb serial, and add the same serial to `ALLOWED` in `aegis/device.py`.
4. `python aegis/build_reader.py --check`, then `--install` (restarts the game once).
5. `python aegis/run.py "return 1+1"` should answer `OK ...`. Then `python aegis/test_guard.py` must print ALL PASS.
6. Copy the other `config/*.example` files to `.json` and fill them in, then run `python aegis/bot.py`.

## Status
Extracted from a working setup (a private bot on a spare phone). Paths and config were made generic for
publishing and **were not all re-tested after cleaning**, so expect small breakage. Issues and PRs welcome.

## License
MIT. See `LICENSE`.
