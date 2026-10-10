"""Translate webDiplomacy's public JSON files into the standard game engine."""
import re
from diplomacy import Game


def normalized(name):
    return re.sub(r'[^A-Z0-9]', '', name.upper())


class Board:
    def __init__(self, context, public, variant):
        current = context['game']
        if variant['variantID'] != 1 or current['variantID'] != 1:
            raise ValueError('Only Classic is supported')
        if (public['turn'], public['phase']) != (current['turn'], current['phase']):
            raise ValueError('Public board is stale; retry next run')
        if public.get('isSandbox'):
            raise ValueError('Sandbox games are not supported')
        self.game = Game()
        self.countries = {c['countryID']: c['name'].upper() for c in variant['countries']}
        if set(self.countries.values()) != set(self.game.powers):
            raise ValueError('Unexpected Classic countries')
        self.territories = {t['id']: t for t in variant['territories']}
        names = {normalized(n): loc.upper() for n, loc in self.game.map.loc_name.items()}
        names.update({normalized(n): loc for n, loc in {'Skagerrack': 'SKA', 'Heligoland Bight': 'HEL', 'Gulf of Lyons': 'LYO', 'Bulgaria (North Coast)': 'BUL/EC'}.items()})
        self.locations = {i: names[normalized(t['name'])] for i, t in self.territories.items()}
        self.ids = {loc: i for i, loc in self.locations.items()}
        phase = {'Diplomacy': 'M', 'Retreats': 'R', 'Builds': 'A'}[current['phase']]
        turn = current['turn']
        date = ('W' if phase == 'A' else ('S' if turn % 2 == 0 else 'F')) + str(1901 + turn // 2) + phase
        units = {p: [] for p in self.game.powers}
        centers = {p: [] for p in self.game.powers}
        retreats = {p: {} for p in self.game.powers}
        status = {t['terrID']: t for t in public['territories']}
        occupied = {self.locations[u['terrID']][:3] for u in public['units'] if not u['retreating']}
        for row in public['territories']:
            owner = row['ownerCountryID']
            tid = row['terrID']
            if owner and self.territories[tid]['supply']:
                centers[self.countries[owner]].append(self.locations[tid][:3])
        for row in public['units']:
            tid = row['terrID']
            power = self.countries[row['countryID']]
            unit = ('A' if row['type'] == 'Army' else 'F') + ' ' + self.locations[tid]
            units[power].append(('*' if row['retreating'] else '') + unit)
            if row['retreating']:
                parent = self.ids[self.locations[tid][:3]]
                origin = status[parent]['occupiedFromTerrID']
                excluded = self.locations[origin][:3] if origin else None
                dests = []
                territory = self.territories[tid]
                edges = territory['coastalBorders'] if row['type'] == 'Fleet' else territory['borders']
                for edge in edges:
                    loc = self.locations[edge['id']]
                    parent_id = self.ids[loc[:3]]
                    if (edge['army' if row['type'] == 'Army' else 'fleet']
                            and loc[:3] not in occupied and loc[:3] != excluded
                            and not status[parent_id]['standoff']):
                        dests.append(loc)
                retreats[power][unit] = dests
        self.game.set_state({'name': date, 'units': units, 'centers': centers, 'retreats': retreats})

    def territory_id(self, loc, parent=False):
        return self.ids[loc[:3] if parent else loc]

    def translate(self, order, country):
        row = dict(type='', terrID=None, toTerrID=None, fromTerrID=None, viaConvoy='No', countryID=country)
        if order == 'WAIVE':
            row['type'] = 'Wait'
            return row
        words = order.split()
        unit_type, location, action = words[:3]
        row['terrID'] = self.territory_id(location, parent=self.game.phase_type == 'A')
        if action == 'H':
            row['type'] = 'Hold'
        elif action in ('-', 'R'):
            row['type'] = 'Move' if action == '-' else 'Retreat'
            row['toTerrID'] = self.territory_id(words[3])
            row['viaConvoy'] = 'Yes' if 'VIA' in words else 'No'
        elif action == 'D':
            row['type'] = 'Disband' if self.game.phase_type == 'R' else 'Destroy'
            if row['type'] == 'Destroy':
                row['toTerrID'] = row['terrID']
        elif action == 'B':
            row['type'] = 'Build Army' if unit_type == 'A' else 'Build Fleet'
            row['toTerrID'] = self.territory_id(location)
        elif action in ('S', 'C'):
            if len(words) == 5:
                row['type'] = 'Support hold'
                row['toTerrID'] = self.territory_id(words[4], parent=True)
            else:
                row['type'] = 'Convoy' if action == 'C' else 'Support move'
                row['fromTerrID'] = self.territory_id(words[4], parent=True)
                row['toTerrID'] = self.territory_id(words[6], parent=True)
        else:
            raise ValueError('Unsupported engine order: ' + order)
        return row
