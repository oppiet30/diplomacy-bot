# CPU DumbBot for your local webDiplomacy

This fork adds a small client using the existing **rule-based DumbBot** strategy.
It runs on CPU, needs no GPU, and downloads no trained weights or datasets.
It is a baseline opponent, not the supervised/RL neural model described in the
original README. Only Classic (variant 1), no-press, non-sandbox games are supported.
Movement, retreats, builds, removals and waiving builds are supported. The
strategy does not plan convoys or negotiate with other players.

The client uses the current `game/playercontext` API and its public game/variant
JSON files. It does not use the removed `players/missing_orders` route. It only
acts in game IDs you explicitly configure, for accounts that are playing and not
already ready. Finished, processing, paused and unsupported games are skipped.

## Install on Dell

Use Python 3.11 or 3.12. Keep this checkout outside Apache's document root:

```bash
cd ~
git clone --branch feature/cpu-webdip-bot https://github.com/oppiet30/diplomacy-bot.git
cd diplomacy-bot
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-cpu.txt
.venv/bin/python -m unittest discover -s tests/cpu -v
```

If `python3.12` is unavailable, install Fedora's `python3.12` package or use
`python3.11`. Do **not** install the original `requirements.txt` or run
`pip install -e .`: those install the older neural-training stack.

## Private configuration

Your existing bot1–bot7 users and API keys can be reused. The bots need membership
in a started Classic no-press game; creating API keys does not join a game.
The site's gamemaster must also be running for turns to advance.

Create a private file outside your web root and the checkout:

```bash
mkdir -p ~/.config
install -m 600 /dev/null ~/.config/diplomacy-bot.json
nano ~/.config/diplomacy-bot.json
```

Paste this, then replace each placeholder with that account's existing 64-character
hexadecimal key. Add bot2 through bot7 the same way. Do not commit or share keys.

```json
{
  "api_url": "http://webdip.local/api.php",
  "api_keys": {
    "bot1": "REPLACE_WITH_BOT1_API_KEY"
  },
  "game_ids": []
}
```

An empty `game_ids` list sends nothing. Set it to `[5]`, for example, only after
creating a test game whose actual game ID is 5 and joining the bot accounts.
Start with one account to verify its orders, then add the others.

## Dry run, then submit

From the checkout:

```bash
.venv/bin/python -m cpu_bot --config ~/.config/diplomacy-bot.json
```

This prints the planned API request without sending orders. After reviewing it:

```bash
.venv/bin/python -m cpu_bot --config ~/.config/diplomacy-bot.json --submit
```

Submission first saves orders **unready**, checks that the server returned the
requested orders, then marks them ready and checks completion. If orders are
rejected, it reports an error and leaves the country unready. A changed phase
is retried on the next invocation. Network/authentication errors return a nonzero
exit status without printing API keys or server response bodies.

This runs once and exits. After a successful live test, use `crontab -e` to run
every minute, with a lock preventing overlapping invocations:

```cron
* * * * * /usr/bin/flock -n /home/oppie/.config/diplomacy-bot.lock /bin/sh -c 'cd /home/oppie/diplomacy-bot && .venv/bin/python -m cpu_bot --config /home/oppie/.config/diplomacy-bot.json --submit' >> /home/oppie/.config/diplomacy-bot.log 2>&1
```

The bot submits orders; webDiplomacy's gamemaster processes turns. Jenkins and
Docker are not required. GitHub Actions runs isolated tests, not your live bots.

## Validation and limits

Run `python -m unittest discover -s tests/cpu -v` using the virtual environment.
Tests cover real Classic territory names/coasts, initial units, retreat
restrictions, multiple phases of self-play, JSON order conversion, dry runs,
submission verification, authorization headers and redirect rejection.
The map fixture contains factual Classic board metadata matching webDiplomacy's
`variants/Classic/install.php`; it contains no credentials or player data.

The API adapter has been tested with fixtures and a local HTTP test server.
A live test against your Dell is still required before enabling cron.
Existing research/training code remains available through its original entry
point; its legacy dependencies have not been modernized or tested here.
