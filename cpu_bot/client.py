"""Run once for cron; private keys are never used when fetching public files."""
import hashlib
import json
import random
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from .board import Board
from .strategy import choose_orders


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, url, key):
        self.url, self.key = url, key
        self.opener = build_opener(NoRedirect())

    def request(self, url, private=False, payload=None):
        headers = {'Accept': 'application/json', 'User-Agent': 'CPU-DumbBot/1'}
        if private:
            headers['Authorization'] = 'Bearer ' + self.key
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        try:
            with self.opener.open(Request(url, data=body, headers=headers), timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            raise ValueError('HTTP request failed: ' + str(error.code)) from None
        except URLError:
            raise ValueError('Cannot connect to webDiplomacy') from None

    def context(self, game_id):
        result = self.request(self.url + '?' + urlencode({'route': 'game/playercontext', 'gameID': game_id, 'orders': 1}), True)
        if result.get('schema') != 1 or result.get('game', {}).get('gameID') != game_id:
            raise ValueError('Unexpected API context')
        return result

    def public_file(self, file):
        path = file['url']
        if not re.fullmatch(r'(cache/games/[0-9/]+/game|variants/Classic/cache/variant)\.json', path):
            raise ValueError('Unexpected public file path')
        return self.request(urljoin(self.url, path) + '?' + urlencode({'v': file['version']}))


def validate_config(config):
    url = urlsplit(config.get('api_url', ''))
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.query or url.fragment or not url.path.endswith('/api.php')):
        raise ValueError('api_url must end in /api.php')
    keys = config.get('api_keys')
    if not isinstance(keys, dict) or not keys or any(not isinstance(k, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', k) for k in keys.values()):
        raise ValueError('api_keys must contain 64-character hexadecimal keys')
    ids = config.get('game_ids')
    if not isinstance(ids, list) or any(type(i) is not int or i < 1 for i in ids):
        raise ValueError('game_ids must contain positive integers')
    return config


def playable(context):
    game, member = context['game'], context.get('member') or {}
    return (context.get('viewer', {}).get('isMember') and game.get('variantID') == 1
            and game.get('gameOver') == 'No' and game.get('pressType') == 'NoPress'
            and game.get('processStatus') == 'Not-processing'
            and game.get('phase') in ('Diplomacy', 'Retreats', 'Builds')
            and member.get('status') == 'Playing' and 'Ready' not in member.get('orderStatus', [])
            and 'Pause' not in member.get('votes', []))


def orders_match(expected, saved):
    """Build/removal placeholders have no unit territory; Wait can expand to several rows."""
    def signature(row):
        kind = row['type']
        free = kind in ('Build Army', 'Build Fleet', 'Destroy', 'Wait')
        return (kind, 0 if free else (row.get('terrID') or 0), row.get('toTerrID') or 0,
                row.get('fromTerrID') or 0, row.get('viaConvoy') in ('Yes', True))
    from collections import Counter
    wanted = Counter(signature(row) for row in expected)
    actual = Counter(signature(row) for row in saved)
    wait = ('Wait', 0, 0, 0, False)
    if wanted[wait] and actual[wait] >= wanted[wait]:
        actual[wait] = wanted[wait]
    return actual == wanted


def run(config, submit=False, log=print, client_class=Client):
    validate_config(config)
    errors = 0
    if not config['game_ids']:
        log('No game IDs configured; no orders sent.')
    for label, key in config['api_keys'].items():
        client = client_class(config['api_url'], key)
        for game_id in config['game_ids']:
            try:
                context = client.context(game_id)
                if not playable(context):
                    log(f'{label} game {game_id}: skipped')
                    continue
                board = Board(context, client.public_file(context['files']['game']), client.public_file(context['files']['variant']))
                country = context['member']['countryID']
                power = board.countries[country]
                game = context['game']
                random.seed(int.from_bytes(hashlib.sha256(f'{game_id}:{country}:{game["turn"]}:{game["phase"]}'.encode()).digest(), 'big'))
                orders = choose_orders(board.game, power)
                payload = {k: game[k] for k in ('gameID', 'turn', 'phase')}
                payload.update(countryID=country, ready='Yes', orders=[board.translate(o, country) for o in orders])
                if submit:
                    # Recheck the snapshot before writing; the server also rejects stale turn/phase.
                    latest = client.context(game_id)
                    if not playable(latest) or any(latest['game'][k] != game[k] for k in ('turn', 'phase')):
                        raise ValueError('Game changed before submission; retry next run')
                    payload['ready'] = 'No'
                    received = client.request(client.url + '?route=game/orders', True, payload)
                    if not isinstance(received, list) or not orders_match(payload['orders'], received):
                        raise ValueError('Server did not save the requested orders; left unready')
                    payload['ready'] = 'Yes'
                    client.request(client.url + '?route=game/orders', True, payload)
                    saved = client.context(game_id)
                    if (saved['game']['turn'], saved['game']['phase']) == (game['turn'], game['phase']):
                        status = saved['member']['orderStatus']
                        if not {'Ready', 'Completed'}.issubset(status):
                            raise ValueError('Server did not confirm complete, ready orders')
                    log(f'{label} game {game_id}: submitted {orders}')
                else:
                    log(f'{label} game {game_id}: dry run {json.dumps(payload)}')
            except (ValueError, KeyError, TypeError, OSError) as error:
                errors += 1
                message = str(error)
                for secret in config['api_keys'].values():
                    message = message.replace(secret, '[REDACTED]')
                log(f'{label} game {game_id}: ERROR {message}')
    return 1 if errors else 0
