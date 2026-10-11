import copy
import json
import random
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from diplomacy import Game
from cpu_bot.board import Board, normalized
from cpu_bot.client import Client, orders_match, run, validate_config
from cpu_bot.strategy import choose_orders

VARIANT = json.loads((Path(__file__).parent / 'fixtures/classic.json').read_text())


def snapshot(engine=None):
    engine = engine or Game()
    dummy = dict(game=dict(gameID=5, turn=0, phase='Diplomacy', variantID=1))
    # Build the factual name mapping before populating units.
    empty = dict(turn=0, phase='Diplomacy', units=[], territories=[])
    mapper = Board(dummy, empty, VARIANT)
    countries = {name: cid for cid, name in mapper.countries.items()}
    state = engine.get_state()
    turn = (int(state['name'][1:5]) - 1901) * 2 + (state['name'][0] != 'S')
    phase = {'M': 'Diplomacy', 'R': 'Retreats', 'A': 'Builds'}[engine.phase_type]
    game = dict(gameID=5, turn=turn, phase=phase, variantID=1, gameOver='No', pressType='NoPress', processStatus='Not-processing')
    public = dict(turn=turn, phase=phase, units=[], territories=[], isSandbox=False)
    for cid, name in mapper.countries.items():
        for unit in engine.powers[name].units:
            public['units'].append(dict(id=len(public['units'])+1, countryID=cid, type='Army' if unit[0]=='A' else 'Fleet', terrID=mapper.ids[unit[2:]], retreating=False))
        for unit in engine.powers[name].retreats:
            public['units'].append(dict(id=len(public['units'])+1, countryID=cid, type='Army' if unit[0]=='A' else 'Fleet', terrID=mapper.ids[unit[2:]], retreating=True))
    for t in VARIANT['territories']:
        if t['coast']=='Child':continue
        loc=mapper.locations[t['id']]
        owner=next((countries[p] for p in engine.powers if loc in engine.powers[p].centers),None)
        public['territories'].append(dict(terrID=t['id'], ownerCountryID=owner, standoff=False, occupiedFromTerrID=None))
    context=dict(schema=1, game=game, viewer=dict(isMember=True), member=dict(countryID=2,status='Playing',orderStatus=[],votes=[]),files=dict(game=dict(url='cache/games/0/5/game.json',version='1'),variant=dict(url='variants/Classic/cache/variant.json',version='1')))
    return context,public


class BotTests(unittest.TestCase):
    def test_real_classic_names_and_initial_units(self):
        context, public = snapshot()
        board=Board(context,public,VARIANT)
        self.assertEqual(board.game.get_state()['units'],Game().get_state()['units'])
        self.assertEqual(board.locations[byname('Bulgaria (North Coast)')],'BUL/EC')
        self.assertEqual(board.translate('F STP/SC H',7)['terrID'],byname('St. Petersburg (South Coast)'))
        self.assertEqual(board.translate('F MAO - SPA/NC',2)['toTerrID'],byname('Spain (North Coast)'))
        self.assertEqual(board.translate('A PAR S A MAR - BUR',2)['type'],'Support move')
        self.assertEqual(board.translate('F STP/SC D',7)['type'],'Destroy')

    def test_stale_board_rejected(self):
        context,public=snapshot();public['turn']=1
        with self.assertRaises(ValueError):Board(context,public,VARIANT)

    def test_retreat_filters_attacker_occupation_standoff(self):
        engine=Game();state=engine.get_state()
        state['name']='S1901R';state['units']['FRANCE']=['*A PAR','A MAR','F BRE']
        state['units']['GERMANY']=['A BUR','A MUN','F KIE']
        state['retreats']['FRANCE']={'A PAR':['PIC']};engine.set_state(state)
        context,public=snapshot(engine)
        paris=next(t for t in public['territories'] if t['terrID']==byname('Paris'))
        paris['occupiedFromTerrID']=byname('Gascony')
        next(t for t in public['territories'] if t['terrID']==byname('Brest'))['standoff']=True
        board=Board(context,public,VARIANT)
        self.assertEqual(board.game.powers['FRANCE'].retreats['A PAR'],['PIC'])
        for order in choose_orders(board.game,'FRANCE'):
            self.assertIn(order, {'A PAR R PIC','A PAR D'})

    def test_retreat_destination_without_status_row(self):
        engine = Game()
        state = engine.get_state()
        state['name'] = 'F1902R'
        state['units']['AUSTRIA'] = ['*A RUM', 'A VIE', 'A BUD']
        state['retreats']['AUSTRIA'] = {'A RUM': ['SER']}
        engine.set_state(state)
        context, public = snapshot(engine)
        public['territories'] = [t for t in public['territories']
                                 if t['terrID'] != byname('Serbia')]
        next(t for t in public['territories']
             if t['terrID'] == byname('Rumania'))['occupiedFromTerrID'] = byname('Galicia')
        next(t for t in public['territories']
             if t['terrID'] == byname('Bulgaria'))['standoff'] = True
        board = Board(context, public, VARIANT)
        destinations = board.game.powers['AUSTRIA'].retreats['A RUM']
        self.assertIn('SER', destinations)
        self.assertNotIn('GAL', destinations)
        self.assertNotIn('BUL', destinations)
        for order in choose_orders(board.game, 'AUSTRIA'):
            self.assertIn(order, {'A RUM R ' + loc for loc in destinations} | {'A RUM D'})

    def test_self_play_and_api_conversion_all_phases(self):
        random.seed(42);engine=Game();phases=set()
        for _ in range(40):
            if engine.get_current_phase()=='COMPLETED':break
            context,public=snapshot(engine)
            board=Board(context,public,VARIANT)
            phases.add(engine.phase_type)
            legal=set().union(*(set(v) for v in engine.get_all_possible_orders().values()))
            for cid,power in board.countries.items():
                orders=choose_orders(engine,power)
                for order in orders:
                    self.assertTrue(order=='WAIVE' or order in legal,order)
                    row=board.translate(order,cid)
                    self.assertEqual(set(row),{'countryID','type','terrID','toTerrID','fromTerrID','viaConvoy'})
                engine.set_orders(power,orders)
            engine.process()
        self.assertEqual(phases,{'M','R','A'})

    def test_dry_run_submit_and_failed_validation(self):
        context,public=snapshot();posts=[];ready=[]
        class Fake:
            url='http://webdip.local/api.php'
            def __init__(self,*args):pass
            def context(self,_):
                result=copy.deepcopy(context)
                if ready:result['member']['orderStatus']=['Ready','Completed']
                return result
            def public_file(self,file):return public if 'game.json' in file['url'] else VARIANT
            def request(self,url,private,payload):
                posts.append(copy.deepcopy(payload))
                if payload['ready']=='Yes':ready.append(True)
                return payload['orders']
        config=dict(api_url=Fake.url,api_keys=dict(bot1='a'*64),game_ids=[5])
        self.assertEqual(run(config,log=lambda _:None,client_class=Fake),0)
        self.assertFalse(posts)
        self.assertEqual(run(config,submit=True,log=lambda _:None,client_class=Fake),0)
        self.assertEqual([p['ready'] for p in posts],['No','Yes'])
        posts.clear();ready.clear()
        class Invalid(Fake):
            def request(self,url,private,payload):posts.append(payload);return []
        self.assertEqual(run(config,submit=True,log=lambda _:None,client_class=Invalid),1)
        self.assertEqual([p['ready'] for p in posts],['No'])

    def test_order_response_normalization(self):
        row=dict(type='Build Fleet',terrID=78,toTerrID=78,fromTerrID=None,viaConvoy='No')
        saved=dict(row,terrID=None,fromTerrID=0)
        self.assertTrue(orders_match([row],[saved]))
        self.assertFalse(orders_match([row],[dict(saved,type='Wait')]))

    def test_config_requires_game_allowlist(self):
        with self.assertRaises(ValueError):validate_config(dict(api_url='http://webdip.local/api.php',api_keys={'bot1':'a'*64}))

    def test_http_authorization_and_redirect_blocking(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path,self.headers.get('Authorization')))
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location','/target');self.end_headers()
                else:
                    self.send_response(200);self.end_headers();self.wfile.write(b'{"schema":1}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_port}'
            client=Client(root+'/api.php','a'*64)
            client.request(root+'/api.php',True)
            client.request(root+'/public.json')
            with self.assertRaises(ValueError):client.request(root+'/redirect',True)
            self.assertEqual(requests[0][1],'Bearer '+'a'*64)
            self.assertIsNone(requests[1][1])
            self.assertEqual(len(requests),3)
        finally:server.shutdown();server.server_close();thread.join()


def byname(name):
    return next(t['id'] for t in VARIANT['territories'] if t['name']==name)

if __name__=='__main__':unittest.main()
