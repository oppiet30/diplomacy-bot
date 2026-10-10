"""Load the existing MIT ruleset without importing the training package."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / 'diplomacy_research/players/rulesets/dumbbot_ruleset.py'
_spec = importlib.util.spec_from_file_location('cpu_dumbbot_ruleset', _path)
_rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rules)


def choose_orders(game, power):
    """Use DumbBot's choices, falling back only when an order is illegal."""
    possible = game.get_all_possible_orders()
    legal = set().union(*(set(rows) for rows in possible.values()))
    chosen = _rules.run_game(game, power)
    if game.phase_type == 'A':
        count = len(game.powers[power].centers) - len(game.powers[power].units)
        result = []
        locations = set()
        for order in chosen:
            loc = order.split()[1][:3]
            if order in legal and loc not in locations:
                result.append(order)
                locations.add(loc)
        if count < 0:
            for unit in game.powers[power].units:
                order = unit + ' D'
                if len(result) >= -count:
                    break
                if unit[2:5] not in locations and order in legal:
                    result.append(order)
                    locations.add(unit[2:5])
            return result[: -count]
        return result[:count] + (['WAIVE'] if len(result) < count else [])
    units = game.powers[power].retreats if game.phase_type == 'R' else game.powers[power].units
    result = []
    for unit in units:
        candidates = [order for order in chosen if order.startswith(unit + ' ') and order in legal]
        result.append(candidates[0] if candidates else unit + (' D' if game.phase_type == 'R' else ' H'))
    return result
