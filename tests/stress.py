"""
Revisão geral / teste de estresse — exercita CADA subsistema e produz um
scorecard com % funcional por sistema.

Uso:
    DATABASE_URL=postgresql://...banco descartável... python tests/stress.py

NÃO usar em banco de produção.
"""
import os
import sys
import random
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

if not os.environ.get('DATABASE_URL'):
    print('ERRO: defina DATABASE_URL para um banco de teste descartável.')
    sys.exit(1)

import app as appmod
from app import app, socketio
import database as db
import pokemon_scaling as scaling
import pvp_battle as pvp

random.seed()
app.config['TESTING'] = True

# ────────────────────────── scorecard ──────────────────────────
RESULTS = {}   # system -> [(check, ok, note)]

def check(system, name, ok, note=''):
    RESULTS.setdefault(system, []).append((name, bool(ok), note))
    mark = '✅' if ok else '❌'
    print(f'  {mark} [{system}] {name}{" — " + note if note and not ok else ""}')
    return ok

def section(title):
    print(f'\n{"─"*62}\n▶ {title}\n{"─"*62}')

def recv(sio, name=None):
    pkts = sio.get_received()
    if name is None:
        return pkts
    return [p for p in pkts if p['name'] == name]

def pvp_hp(p):
    hp = p.get('currentHp')
    return hp if isinstance(hp, (int, float)) else p.get('maxHp', 20)

def dmg_move(poke):
    """Primeiro move de DANO do pokémon (status agora dá 0 dano — precisa
    de um golpe de dano para as batalhas de teste progredirem)."""
    for mv in (poke.get('moves') or []):
        md = appmod.MOVES_BY_NAME.get(mv.lower()) or appmod.MOVES_DB.get(mv) or {}
        if md.get('category') in ('physical', 'special') and md.get('baseDamage'):
            return mv
    return (poke.get('moves') or ['Tackle'])[0]

# ────────────────────────── setup ──────────────────────────
def register(client, username, role, invite=None):
    data = {'username': username, 'password': 'senha123', 'role': role}
    if invite:
        data['invite_code'] = invite
    return client.post('/register', data=data)

def login(client, username):
    return client.post('/login', data={'username': username, 'password': 'senha123'})

def uid_of(username):
    return next((u for u, v in db.get_users().items() if v['username'] == username), None)

def make_poke(species, level, **extras):
    base = appmod.POKEMON_BY_NAME[species.lower()]
    sc = scaling.calculate_pokemon_stats(base, level)
    moves = list(base.get('startingMoves', []))
    for lv, ms in (base.get('levelMoves') or {}).items():
        if int(lv) * 5 <= level:
            moves.extend(ms)
    moves = [m for m in moves if m.lower() in appmod.MOVES_BY_NAME][-4:] or ['Tackle']
    poke = dict(name=base['name'], number=base['number'], level=level,
                types=base['types'], maxHp=sc['maxHp'], currentHp=sc['hp'],
                hp=sc['hp'], ac=sc['ac'], stats=sc['stats'],
                proficiency=sc['proficiency'], stab=sc['stab'], moves=moves,
                vulnerabilities=base.get('vulnerabilities', []),
                resistances=base.get('resistances', []),
                immunities=base.get('immunities', []),
                ability=(base.get('ability') or {}).get('name', ''),
                evolutionInfo=base.get('evolutionInfo', ''),
                xp=0, totalXp=0, battle_wins=0)
    poke.update(extras)
    return poke

def give_team(uid, specs, money=5000, wis=14):
    users = db.get_users()
    t = users[uid]['trainer_data']
    t['team'] = [make_poke(sp, lv) for sp, lv in specs]
    t['money'] = money
    t['wis'] = wis
    t['bag'] = [{'name': 'Pokébola', 'qty': 99}, {'name': 'Potion', 'qty': 5}]
    users[uid]['trainer_data'] = t
    db.save_users(users)

TID = None

def gstate():
    return db.get_game_state(TID)


def main():
    global TID
    print('🔬 REVISÃO GERAL — teste de estresse de todos os sistemas')

    m = app.test_client()
    p1 = app.test_client()
    p2 = app.test_client()

    # ══════════ 1. AUTH & MESAS ══════════
    section('1. Autenticação & Mesas')
    S = 'Auth/Mesas'
    # O super-admin (lusmar) é o único mestre que cria mesa direto no cadastro
    r = register(m, 'lusmar', 'master')
    check(S, 'registro do super-admin (lusmar)', r.status_code in (200, 302))
    check(S, 'login do super-admin', login(m, 'lusmar').status_code == 302)
    mid = uid_of('lusmar')
    tables = db.get_tables_for_master(mid)
    check(S, 'mesa criada automaticamente c/ convite', bool(tables) and bool(tables[0].get('invite_code')))
    TID = tables[0]['id']
    invite = tables[0]['invite_code']
    register(p1, 'rev_p1', 'player')  # sem convite → deve recusar
    check(S, 'jogador sem convite é recusado', uid_of('rev_p1') is None)
    register(p1, 'rev_p1', 'player', 'CONVITE_ERRADO')
    check(S, 'convite inválido é recusado', uid_of('rev_p1') is None)
    register(p1, 'rev_p1', 'player', invite)
    register(p2, 'rev_p2', 'player', invite)
    check(S, 'jogadores entram com convite', uid_of('rev_p1') and uid_of('rev_p2'))
    login(p1, 'rev_p1'); login(p2, 'rev_p2')
    u1, u2 = uid_of('rev_p1'), uid_of('rev_p2')
    r = p1.post('/login', data={'username': 'rev_p1', 'password': 'errada'})
    check(S, 'senha errada não loga', r.status_code == 200)

    give_team(u1, [('Charmander', 20), ('Squirtle', 18), ('Pidgey', 15)])
    give_team(u2, [('Bulbasaur', 20), ('Rattata', 12)])

    msio = socketio.test_client(app, flask_test_client=m)
    s1 = socketio.test_client(app, flask_test_client=p1)
    s2 = socketio.test_client(app, flask_test_client=p2)
    for c in (msio, s1, s2):
        c.get_received()

    # ══════════ 2. SEGURANÇA ══════════
    section('2. Segurança')
    S = 'Segurança'
    for route, payload in [('/master/xp', {'player_id': u2, 'xp': 999}),
                           ('/master/calendar/advance', {'days': 1}),
                           ('/master/hunts', {'player_id': u1, 'action': 'grant'}),
                           ('/master/hunt/random', {'player_id': u1, 'hunt_mode': 'normal'}),
                           ('/master/npcs', {'name': 'hack'}),
                           ('/master/quests', {'title': 'hack'})]:
        r = p1.post(route, json=payload)
        check(S, f'jogador bloqueado em {route}', r.status_code == 403)
    # Caçada aleatória (mestre): nível derivado do time real do alvo, não do body
    r = m.post('/master/hunt/random', json={'player_id': u1, 'hunt_mode': 'normal',
                                            'route_id': 'route1', 'player_level': 99})
    d = (r.get_json() or {}).get('encounter', {})
    check(S, 'player_level do body é ignorado (usa time real)',
          d.get('level', 999) <= 30, f"nível gerado {d.get('level')}")
    anon = app.test_client()
    r = anon.post('/api/hunt/roll', json={})
    check(S, 'rolagem exige login', r.status_code in (302, 401))
    for c in (msio, s1, s2):
        c.get_received()

    # ── Aprovação de conta de MESTRE (super-admin lusmar) ──
    appmod._rate_store.clear()
    gm2 = app.test_client()
    register(gm2, 'gm_pendente', 'master')
    _pend_uid = uid_of('gm_pendente')
    check(S, 'mestre comum é criado como PENDENTE', _pend_uid is not None)
    check(S, 'mestre pendente NÃO tem mesa',
          not db.get_tables_for_master(_pend_uid))
    check(S, 'mestre pendente NÃO consegue logar',
          login(gm2, 'gm_pendente').status_code == 200)   # 200 = re-render (bloqueado), 302 = logou
    # jogador comum não acessa a fila de aprovação
    check(S, 'jogador não vê fila de aprovação',
          p1.get('/admin/pending-masters').status_code == 403)
    # lusmar vê o pendente e aprova
    _fila = m.get('/admin/pending-masters').get_json() or {}
    check(S, 'lusmar vê o cadastro pendente na fila',
          any(x['id'] == _pend_uid for x in _fila.get('pending', [])))
    _ap = m.post(f'/admin/masters/{_pend_uid}/approve').get_json() or {}
    check(S, 'lusmar aprova → mesa criada + convite', _ap.get('ok') and _ap.get('invite'))
    check(S, 'mestre aprovado agora tem mesa', bool(db.get_tables_for_master(_pend_uid)))
    check(S, 'mestre aprovado agora consegue logar',
          login(gm2, 'gm_pendente').status_code == 302)
    # jogador não consegue aprovar/rejeitar (rota de super-admin)
    check(S, 'jogador não aprova mestre',
          p1.post(f'/admin/masters/{_pend_uid}/approve').status_code == 403)
    # rejeição remove o cadastro pendente
    appmod._rate_store.clear()
    gm3 = app.test_client()
    register(gm3, 'gm_recusar', 'master')
    _rej_uid = uid_of('gm_recusar')
    check(S, 'segundo mestre pendente criado', _rej_uid is not None)
    check(S, 'lusmar recusa o cadastro', (m.post(f'/admin/masters/{_rej_uid}/reject').get_json() or {}).get('ok'))
    check(S, 'cadastro recusado é removido', uid_of('gm_recusar') is None)
    # não dá para roubar o nome reservado do super-admin
    appmod._rate_store.clear()
    gm4 = app.test_client()
    register(gm4, 'lusmar', 'master')
    check(S, 'nome do super-admin não pode ser duplicado',
          sum(1 for u in db.get_users().values() if u['username'].lower() == 'lusmar') == 1)

    # ── IDOR entre mesas: mestre A não age em jogador de outra mesa ──
    # o mestre aprovado (gm_pendente) cria sua mesa; um jogador entra nela
    appmod._rate_store.clear()
    _t2 = db.get_tables_for_master(_pend_uid)[0]
    pB = app.test_client()
    register(pB, 'rev_pB', 'player', _t2['invite_code'])
    _uB = uid_of('rev_pB')
    check(S, 'jogador entra na mesa do 2º mestre', _uB is not None)
    # lusmar (mesa 1) tenta mexer no jogador da mesa 2 → bloqueado
    for route, payload in [('/master/xp', {'player_id': _uB, 'xp': 999999}),
                           ('/master/pokemon-xp', {'player_id': _uB, 'pokemon_idx': 0, 'xp': 999}),
                           ('/master/hunt/random', {'player_id': _uB, 'hunt_mode': 'normal'})]:
        r = m.post(route, json=payload)
        check(S, f'IDOR cross-mesa bloqueado em {route}', r.status_code == 403)
    r = m.get(f'/master/player-team/{_uB}')
    check(S, 'IDOR cross-mesa bloqueado em /master/player-team', r.status_code == 403)
    # relogar o lusmar (o login do gm_pendente trocou a sessão do client? não,
    # gm2 é outro client) — garante que m ainda é o lusmar
    login(m, 'lusmar')
    for c in (msio, s1, s2):
        c.get_received()

    # ── Economia: cliente não é autoridade sobre dinheiro/nível/espécie ──
    users = db.get_users(); users[u1]['trainer_data']['money'] = 1000; db.save_users(users)
    p1.post('/player/trainer', json={'money': 999999999, 'badges': [0,1,2,3,4,5,6,7],
                                     'pokeslots': 6, 'name': 'Ash'})
    _td = db.get_users()[u1]['trainer_data']
    check(S, 'jogador NÃO edita o próprio dinheiro', _td.get('money') == 1000)
    check(S, 'jogador NÃO edita as próprias insígnias', not _td.get('badges'))
    check(S, 'campo legítimo (nome) ainda salva', _td.get('name') == 'Ash')
    # bolsa: quantidade sanitizada (sem forjar 99999 itens)
    p1.post('/player/trainer', json={'bag': [{'name': 'Master Ball', 'qty': 99999}]})
    _bag = db.get_users()[u1]['trainer_data'].get('bag', [])
    check(S, 'bolsa clampa quantidade forjada (≤999)',
          _bag and _bag[0]['qty'] == 999)

    # /player/team: nível não salta para 100, espécie inventada é descartada
    _cur = db.get_users()[u1]['trainer_data']['team']
    _cur_lvl = _cur[0]['level'] if _cur else 20
    p1.post('/player/team', json={'team': [
        dict(_cur[0], level=100, is_shiny=True) if _cur else
        {'name': 'Charmander', 'number': 4, 'level': 100},
        {'name': 'Fakemon', 'number': 99999, 'level': 100,
         'maxHp': 99999, 'stats': {'ATK': 9999}}]})
    _saved = db.get_users()[u1]['trainer_data']['team']
    check(S, 'nível não salta (máx +5 por save)',
          _saved[0]['level'] <= _cur_lvl + 5)
    check(S, 'shiny não é ligado pelo cliente num Pokémon existente',
          _saved[0].get('is_shiny') is False)
    check(S, 'espécie inventada é descartada (anti-forja de stats)',
          all(p['name'] != 'Fakemon' for p in _saved))

    # BUG do shiny: dois Pokémon da MESMA espécie SEM apelido não podem
    # trocar/herdar shiny entre si (colisão de chave (number, nickname)).
    _uu = db.get_users()
    _uu[u1]['trainer_data']['team'] = [
        {'name': 'Rattata', 'number': 19, 'level': 10, 'nickname': '',
         'is_shiny': False, 'sv': 2, 'stats': {'ATK': 10}, 'maxHp': 20},
        {'name': 'Rattata', 'number': 19, 'level': 10, 'nickname': '',
         'is_shiny': True, 'sv': 2, 'stats': {'ATK': 10}, 'maxHp': 20},
    ]
    db.save_users(_uu)
    # cliente reenvia o mesmo time (ordem preservada) — cada um mantém seu shiny
    p1.post('/player/team', json={'team': [
        {'name': 'Rattata', 'number': 19, 'level': 10, 'nickname': ''},
        {'name': 'Rattata', 'number': 19, 'level': 10, 'nickname': ''}]})
    _sv = db.get_users()[u1]['trainer_data']['team']
    check(S, 'duplicatas sem apelido não trocam shiny (slot 0 normal)',
          len(_sv) == 2 and _sv[0].get('is_shiny') is False)
    check(S, 'duplicatas sem apelido preservam o shiny do slot certo',
          _sv[1].get('is_shiny') is True)
    # restaura o time original
    give_team(u1, [('Charmander', 20), ('Squirtle', 18), ('Pidgey', 15)])

    # Pokédex: número inexistente não dá XP
    appmod._rate_store.clear()
    _xp0 = db.get_users()[u1]['trainer_data'].get('xp', 0)
    r = p1.post('/player/pokedex/register', json={'pokemon_number': 999999})
    check(S, 'Pokédex rejeita número inexistente', r.status_code == 400)
    check(S, 'XP não sobe com número falso',
          db.get_users()[u1]['trainer_data'].get('xp', 0) == _xp0)

    # Transfer: quantidade negativa não duplica
    users = db.get_users()
    users[u1]['trainer_data']['bag'] = [{'name': 'Ultra Bola', 'qty': 1}]
    users[u1]['trainer_data']['money'] = 500
    db.save_users(users)
    p1.post('/player/transfer', json={'target_id': u2,
                                      'items': [{'name': 'Ultra Bola', 'qty': -100}],
                                      'money': -100})
    _b1 = db.get_users()[u1]['trainer_data'].get('bag', [])
    _ub = next((b for b in _b1 if b['name'] == 'Ultra Bola'), None)
    check(S, 'transfer com qty negativo não duplica item',
          _ub is None or _ub['qty'] <= 1)
    check(S, 'transfer com dinheiro negativo não rouba',
          db.get_users()[u1]['trainer_data'].get('money') == 500)

    # _apply_xp nunca rebaixa nível definido pelo mestre
    _t = {'level': 10, 'xp': 50}
    appmod._apply_xp(_t, 10)
    check(S, '_apply_xp não rebaixa nível manual do mestre', _t['level'] == 10)

    # stat_mods de história só o mestre aplica
    _rn = p1.post('/api/pokemon/stats', json={'number': 25, 'level': 30}).get_json()
    _rp = p1.post('/api/pokemon/stats', json={'number': 25, 'level': 30,
                  'stat_mods': {'HP': 500}}).get_json()
    check(S, 'jogador não infla stats via stat_mods', _rp['maxHp'] == _rn['maxHp'])

    # ── Endurecimento de autenticação/headers ──
    appmod._rate_store.clear()
    # headers de segurança em toda resposta
    _rh = p1.get('/login')
    check(S, 'headers de segurança presentes',
          _rh.headers.get('X-Frame-Options') == 'DENY'
          and _rh.headers.get('X-Content-Type-Options') == 'nosniff'
          and bool(_rh.headers.get('Referrer-Policy')))
    # honeypot: bot que preenche o campo invisível não cria conta
    px = app.test_client()
    px.post('/register', data={'username': 'bot_honeypot', 'password': 'senha12345',
                               'role': 'master', 'website': 'http://spam.com'})
    check(S, 'honeypot descarta bot em silêncio', uid_of('bot_honeypot') is None)
    # senha curta e username inválido são recusados
    px.post('/register', data={'username': 'senha_curta', 'password': 'abc',
                               'role': 'master'})
    check(S, 'senha < 8 caracteres é recusada', uid_of('senha_curta') is None)
    px.post('/register', data={'username': 'no me!<x>', 'password': 'senha12345',
                               'role': 'master'})
    check(S, 'username com caracteres inválidos é recusado', uid_of('no me!<x>') is None)
    # lockout por conta: 5 falhas trancam o usuário (mesmo trocando de IP)
    import time as _t_
    appmod._login_fails['alvo_lockout'] = [_t_.time()] * 5
    _rl = px.post('/login', data={'username': 'alvo_lockout', 'password': 'x' * 8})
    check(S, 'lockout por conta após 5 falhas de login',
          'bloqueada' in _rl.get_data(as_text=True))
    appmod._login_fails.clear()
    for c in (msio, s1, s2):
        c.get_received()

    # ══════════ 3. CAÇADA MANUAL & CALENDÁRIO ══════════
    section('3. Caçada manual, rolagem e calendário')
    S = 'Caçada/Calendário'
    m.post('/master/calendar/advance', json={'days': 1})
    msio.get_received()
    totals = []
    for i in range(6):
        appmod._rate_store.clear()
        r = p1.post('/api/hunt/roll', json={})
        d = r.get_json()
        totals.append(d.get('total'))
        check(S, f'rolagem {i+1} válida (1-20)', 1 <= d.get('roll', 0) <= 20, f"{d.get('roll')}")
    check(S, '6 rolagens consumidas',
          all(t is not None for t in totals), f'{totals}')
    # o mestre recebe as rolagens (socket hunt_roll)
    hr = recv(msio, 'hunt_roll')
    hr_arg = hr[0]['args'][0] if hr and hr[0].get('args') else {}
    check(S, 'mestre recebe rolagem do jogador', bool(hr) and 'total' in hr_arg)
    # rolagem manual (dado físico) respeita o valor
    appmod._rate_store.clear()
    m.post('/master/hunts', json={'player_id': u1, 'action': 'reset'})
    r = p1.post('/api/hunt/roll', json={'manual_roll': 15})
    d = r.get_json() or {}
    check(S, 'dado físico (manual_roll) respeitado', d.get('roll') == 15 and d.get('manual') is True)
    check(S, 'rolagem não gera encontro sozinha', 'pokemon' not in d and 'found' not in d)
    # esgota as caçadas → 403 cansaço na rolagem
    for _ in range(8):
        appmod._rate_store.clear()
        r = p1.post('/api/hunt/roll', json={})
        if r.status_code == 403:
            break
    check(S, 'esgotar caçadas → 403', r.status_code == 403)
    check(S, 'mensagem de cansaço', 'cansad' in (r.get_json() or {}).get('error', '').lower(),
          (r.get_json() or {}).get('error'))
    # Energy Drink: compra + usa → +1 caçada
    users = db.get_users(); users[u1]['trainer_data']['money'] = 5000; db.save_users(users)
    r = p1.post('/api/shop/buy', json={'item_id': 'energy-drink', 'qty': 1})
    check(S, 'comprar Energy Drink', (r.get_json() or {}).get('success'))
    # QA LOOP 2: qty malformado NÃO derruba a request com 500 (int robusto)
    for _bad in ['abc', None, 2.9]:
        _rq = p1.post('/api/shop/buy', json={'item_id': 'energy-drink', 'qty': _bad})
        check(S, f'buy qty={_bad!r} não crasha (400/200, nunca 500)',
              _rq.status_code < 500, f'status {_rq.status_code}')
    r = p1.post('/player/use-energy-drink', json={})
    check(S, 'usar Energy Drink dá +1 caçada', (r.get_json() or {}).get('limit') == 7)
    appmod._rate_store.clear()
    r = p1.post('/api/hunt/roll', json={})
    check(S, 'rola de novo após Energy Drink', r.status_code == 200)
    # mestre libera caçada aleatória respeitando horário+terreno (dungeon perigosa)
    r = m.post('/master/hunt/random', json={'player_id': u1, 'hunt_mode': 'dungeon_night',
                                            'route_id': 'route1'})
    d = (r.get_json() or {}).get('encounter', {})
    check(S, 'caçada aleatória gera encontro', d.get('found') is True)
    check(S, 'hunt_mode respeitado', d.get('hunt_mode') == 'dungeon_night', f"{d.get('hunt_mode')}")
    check(S, 'jogador recebe forced_encounter', bool(recv(s1, 'master_action')))
    r = m.post('/master/hunts', json={'player_id': u1, 'action': 'grant', 'amount': 1})
    check(S, 'mestre concede caçada extra', (r.get_json() or {}).get('limit') == 8)
    r = p1.get('/api/hunts/status')
    check(S, 'status de caçadas coerente', (r.get_json() or {}).get('limit') == 8)
    r = m.post('/master/calendar/set', json={'day': 29, 'month': 12, 'year': 1})
    check(S, 'definir data', r.status_code == 200)
    r = m.post('/master/calendar/advance', json={'days': 3})
    cal = (r.get_json() or {}).get('calendar')
    check(S, 'virada de mês/ano', cal == {'day': 2, 'month': 1, 'year': 2}, f'{cal}')
    r = m.post('/master/calendar/events', json={'title': 'Evento Rev', 'city': 'Pallet',
                                                'day': 5, 'month': 1, 'year': 2, 'notify_days_before': 3})
    evt = r.get_json() or {}
    check(S, 'criar evento', 'id' in evt)
    r = p1.get('/api/calendar')
    evs = {e['id']: e for e in (r.get_json() or {}).get('events', [])}
    check(S, 'jogador vê evento com days_until', evs.get(evt.get('id'), {}).get('days_until') == 3)
    r = m.put(f"/master/calendar/events/{evt.get('id')}", json={'title': 'Evento Rev 2'})
    check(S, 'editar evento', (r.get_json() or {}).get('title') == 'Evento Rev 2')
    r = m.delete(f"/master/calendar/events/{evt.get('id')}")
    check(S, 'deletar evento', (r.get_json() or {}).get('ok'))

    # ══════════ 4. BATALHA SELVAGEM ══════════
    section('4. Batalha selvagem (socket)')
    S = 'Batalha Selvagem'
    m.post('/master/calendar/advance', json={'days': 1})
    s1.get_received()
    r = m.post('/master/hunt/random', json={'player_id': u1, 'hunt_mode': 'normal',
                                            'route_id': 'route1'})
    enc = (r.get_json() or {}).get('encounter')
    check(S, 'encontro gerado', enc is not None and enc.get('found') is True)
    if enc:
        s1.emit('start_encounter', {'pokemon': enc['pokemon'], 'level': enc['level'],
                                    'is_shiny': enc['is_shiny'], 'route_id': 'route1',
                                    'player_pokemon': 'Charmander', 'player_pokemon_idx': 0,
                                    'wild_moves': enc['wild_moves']})
        init = recv(s1, 'initiative_result')
        check(S, 'iniciativa automática', bool(init))
        e0 = gstate()['active_encounters'].get(u1)
        check(S, 'encontro salvo por mesa', e0 is not None)
        if e0:
            bs = e0['battle_state']
            wrong_actor = 'master' if bs['turn'] == 'player' else 'player'
            hp_before = (bs['wild_hp_current'], bs['player_hp_current'])
            s1.emit('battle_action', {'action_by': wrong_actor, 'action_type': 'attack',
                                      'move_name': 'Scratch', 'damage': 50, 'attack_roll': 15})
            recv(s1)
            bs2 = gstate()['active_encounters'][u1]['battle_state']
            check(S, 'ação fora do turno ignorada',
                  (bs2['wild_hp_current'], bs2['player_hp_current']) == hp_before)
            rounds = 0
            for _ in range(80):
                st = gstate()['active_encounters'].get(u1)
                if not st:
                    break
                bs = st['battle_state']
                if bs['wild_hp_current'] <= 0 or bs['player_hp_current'] <= 0:
                    s1.emit('end_encounter', {
                        'result': 'defeated' if bs['wild_hp_current'] <= 0 else 'fainted',
                        'active_pokemon_name': 'Charmander'})
                    recv(s1)
                    break
                rounds += 1
                if bs['turn'] == 'player':
                    s1.emit('battle_action', {'action_by': 'player', 'action_type': 'attack',
                                              'move_name': 'Ember', 'attack_roll': random.randint(1, 20)})
                else:
                    calc = appmod._calc_pvp_attack(dict(enc['pokemon'], level=enc['level']),
                                                   db.get_users()[u1]['trainer_data']['team'][0], 'Tackle')
                    s1.emit('battle_action', {'action_by': 'master', 'action_type': 'attack',
                                              'move_name': 'Tackle', 'damage': calc['damage']})
                recv(s1)
            check(S, 'batalha completa terminou e limpou estado',
                  u1 not in gstate()['active_encounters'], f'{rounds} rounds')
    # GATE: sem liberação do mestre o start_encounter é NEGADO
    s1.get_received()
    s1.emit('start_encounter', {'pokemon': {'number': 999, 'hp': 30}, 'level': 10,
                                'player_pokemon': 'Charmander', 'player_pokemon_idx': 0})
    check(S, 'start_encounter sem liberação é negado', bool(recv(s1, 'encounter_denied')))

    # Status on-hit do SELVAGEM é rolado no SERVIDOR (não depende de o cliente ter
    # carregado statusEffectsData). Selvagem usa Poison Sting → jogador envenenado.
    # (libera o encontro pelo mestre antes — o grant anterior já foi consumido)
    msio.emit('master_action', {'type': 'forced_encounter', 'player_id': u1,
                                'pokemon': enc['pokemon'], 'level': enc['level'],
                                'wild_moves': ['Poison Sting']})
    recv(msio)
    s1.get_received()
    s1.emit('start_encounter', {'pokemon': dict(enc['pokemon'], hp=enc['pokemon'].get('maxHp', enc['pokemon'].get('hp', 30))),
                                'level': enc['level'], 'is_shiny': False, 'route_id': 'route1',
                                'player_pokemon': 'Charmander', 'player_pokemon_idx': 0,
                                'wild_moves': ['Poison Sting']})
    recv(s1)
    server_poisoned = False
    for _ in range(60):
        st = gstate()['active_encounters'].get(u1)
        if not st:
            break
        bs = st['battle_state']
        bs['turn'] = 'wild'; bs['player_status'] = None
        bs['player_hp_current'] = bs['player_hp_max']
        gs = gstate(); gs['active_encounters'][u1]['battle_state'] = bs; db.save_game_state(gs, TID)
        s1.get_received()
        # Poison Sting é on:'hit' (30%) — dano>0 dispara a rolagem no servidor
        s1.emit('battle_action', {'action_by': 'master', 'action_type': 'attack',
                                  'move_name': 'Poison Sting', 'move_type': 'poison',
                                  'damage': 5, 'attack_roll': 12})
        recv(s1)
        ps = gstate()['active_encounters'][u1]['battle_state'].get('player_status')
        if ps and ps.get('condition') == 'badly_poisoned':
            server_poisoned = True
            break
    check(S, 'status on-hit do selvagem aplicado pelo servidor', server_poisoned)
    s1.emit('end_encounter', {'result': 'fainted', 'active_pokemon_name': 'Charmander'}); recv(s1)
    # ESPECTADOR: o OUTRO jogador da mesa (u2) acompanha a batalha do u1
    _spec = recv(s2, 'spectate_update')
    check(S, 'espectador: u2 recebe snapshots da batalha do u1',
          any(p['args'][0].get('kind') == 'wild' and u1 in (p['args'][0].get('players') or [])
              for p in _spec if p.get('args')))
    check(S, 'espectador: fim da batalha chega com finished=True',
          any(p['args'][0].get('finished') for p in _spec if p.get('args')))

    # ══════════ 4b. MODO MANUAL (AUTO OFF): mestre conduz wild/NPC ══════════
    section('4b. Modo manual (AUTO OFF)')
    S = 'Modo Manual'
    msio.get_received(); s1.get_received()
    msio.emit('set_auto_mode', {'enabled': False})
    _amc = recv(msio, 'auto_mode_changed')
    check(S, 'toggle OFF re-emite auto_mode_changed',
          any((p['args'][0] or {}).get('enabled') is False for p in _amc if p.get('args')))
    # mestre libera novo encontro e o jogador inicia
    msio.emit('master_action', {'type': 'forced_encounter', 'player_id': u1,
                                'pokemon': enc['pokemon'], 'level': enc['level'],
                                'wild_moves': ['Tackle']})
    recv(msio); s1.get_received()
    s1.emit('start_encounter', {'pokemon': dict(enc['pokemon'], hp=enc['pokemon'].get('maxHp', enc['pokemon'].get('hp', 30))),
                                'level': enc['level'], 'is_shiny': False, 'route_id': 'route1',
                                'player_pokemon': 'Charmander', 'player_pokemon_idx': 0,
                                'wild_moves': ['Tackle']})
    recv(s1)
    check(S, 'com AUTO OFF a iniciativa NÃO rola sozinha',
          not gstate()['active_encounters'][u1]['battle_state'].get('initiative_rolled'))
    # mestre rola a iniciativa manualmente
    msio.get_received(); s1.get_received()
    msio.emit('roll_initiative', {'player_id': u1})
    _init = recv(s1, 'initiative_result')
    check(S, 'initiative_result (manual) chega ao jogador com wild_auto=False',
          any((p['args'][0] or {}).get('wild_auto') is False for p in _init if p.get('args')))
    # força o turno do selvagem para testar o gate
    _gs = gstate()
    _bsm = _gs['active_encounters'][u1]['battle_state']
    _bsm['turn'] = 'wild'
    db.save_game_state(_gs, TID)
    _hp_antes = _bsm['player_hp_current']
    # JOGADOR tenta conduzir o selvagem (é o que o cliente antigo fazia) → bloqueado
    s1.get_received()
    s1.emit('battle_action', {'action_by': 'master', 'action_type': 'attack',
                              'move_name': 'Tackle', 'damage': 50})
    _blk = recv(s1, 'action_blocked')
    check(S, 'ação de selvagem vinda do JOGADOR é bloqueada no modo manual',
          any((p['args'][0] or {}).get('manual_wild') for p in _blk if p.get('args')))
    _bsm2 = gstate()['active_encounters'][u1]['battle_state']
    check(S, 'HP e turno intactos após o bloqueio',
          _bsm2['player_hp_current'] == _hp_antes and _bsm2['turn'] == 'wild')
    # MESTRE conduz: dano forjado (999) é ignorado — o v3 recalcula no servidor
    msio.get_received()
    msio.emit('battle_action', {'player_id': u1, 'action_by': 'master',
                                'action_type': 'attack', 'move_name': 'Tackle',
                                'damage': 999})
    _upd = [p['args'][0] for p in recv(msio, 'battle_update') if p.get('args')]
    _mup = next((u for u in _upd if u.get('server_calc')), None)
    check(S, 'ataque do mestre é recalculado no motor v3 (server_calc)', _mup is not None)
    _bsm3 = gstate()['active_encounters'][u1]['battle_state']
    check(S, 'dano aplicado é do motor, não o forjado',
          (_mup or {}).get('damage') != 999 and _hp_antes - _bsm3['player_hp_current'] < 999)
    check(S, 'battle_update carrega wild_auto=False',
          (_mup or {}).get('wild_auto') is False)
    check(S, 'turno voltou ao jogador após a ação do mestre', _bsm3['turn'] == 'player')
    s1.emit('end_encounter', {'result': 'fled'}); recv(s1)

    # NPC também respeita o modo manual: IA não age; mestre usa Forçar Ação
    r = m.post('/master/npcs/generate', json={'npc_class': 'Trainer', 'level': 12, 'team_size': 1})
    _npcm = r.get_json()
    for q in _npcm['team']:
        q['moves'] = ['Tackle']
    db.save_npc(_npcm, TID)
    s1.get_received(); msio.get_received()
    s1.emit('pvp_challenge', {'target_id': _npcm['id'], 'mode': 'street'})
    _cr = recv(s1, 'pvp_battle_created')
    _bidm = _cr[0]['args'][0]['battle_id'] if _cr else None
    check(S, 'desafio a NPC criado (modo manual)', _bidm is not None)
    if _bidm:
        s1.emit('pvp_select_pokemon', {'battle_id': _bidm, 'pokemon_idx': 0}); recv(s1)
        _btm = appmod.ACTIVE_PVP.get(_bidm)
        _npck = 'player2' if _btm['player2'].get('is_npc') else 'player1'
        _plk = 'player1' if _npck == 'player2' else 'player2'
        # se o jogador começa, ataca uma vez para passar o turno ao NPC
        if _btm['turn'] == _plk:
            _pk = _btm[_plk]['team'][_btm[_plk]['active_idx']]
            s1.emit('pvp_attack', {'battle_id': _bidm, 'move_name': dmg_move(_pk),
                                   'attack_roll': random.randint(1, 20)})
            recv(s1)
        check(S, 'NPC NÃO age sozinho no modo manual (turno preso no NPC)',
              _btm['turn'] == _npck and _btm['phase'] == 'battle')
        check(S, 'mestre é avisado (npc_awaiting_master)',
              bool(recv(msio, 'npc_awaiting_master')))
        check(S, 'log da batalha registra a espera pelo mestre',
              any('aguardando o Mestre' in (e.get('message') or '') for e in _btm['log']))
        # Forçar Ação destrava: a IA joga UMA vez a mando do mestre
        msio.emit('master_force_npc_action', {'battle_id': _bidm, 'player_key': _npck})
        recv(msio)
        check(S, 'Forçar Ação do mestre faz o NPC agir', _btm['turn'] == _plk
              or _btm['phase'] != 'battle')
        appmod.ACTIVE_PVP.pop(_bidm, None)
    # religa o AUTO para o resto da suíte
    msio.emit('set_auto_mode', {'enabled': True}); recv(msio)
    check(S, 'AUTO religado', db.get_game_state(TID).get('wild_auto_mode') is True)

    # ══════════ 4c. ANTI-EXPLOIT (auditoria QA): cliente forjando payloads ══════════
    section('4c. Anti-exploit de client-side')
    S = 'Anti-Exploit'
    # semeia um encontro com o jogador no turno e HP baixo
    def _seed_exploit_enc(php=30, pmax=60, whp=40, wmax=40):
        _gs = gstate()
        _team = db.get_users()[u1]['trainer_data']['team']
        _gs.setdefault('active_encounters', {})[str(u1)] = {
            'player_id': str(u1), 'player_name': 'rev_p1',
            'pokemon': dict(enc['pokemon'], hp=wmax, currentHp=whp),
            'level': enc['level'], 'is_shiny': False,
            'player_pokemon': _team[0],
            'battle_state': {'turn': 'player', 'round': 1,
                             'wild_hp_current': whp, 'wild_hp_max': wmax,
                             'player_hp_current': php, 'player_hp_max': pmax,
                             'wild_status': None, 'player_status': None,
                             'initiative_rolled': True}}
        db.save_game_state(_gs, TID)

    # A1: heal forjado em action_type='status' é ignorado (cura vem do motor)
    _seed_exploit_enc(php=30, pmax=60)
    s1.get_received()
    s1.emit('battle_action', {'action_by': 'player', 'action_type': 'status',
                              'move_name': 'Growl', 'heal': 9999})
    recv(s1)
    _php = gstate()['active_encounters'][u1]['battle_state']['player_hp_current']
    check(S, 'heal forjado (9999) em status não cura', _php <= 60)

    # A1b: status_effect forjado no selvagem é ignorado (Growl não causa status)
    _seed_exploit_enc()
    s1.get_received()
    s1.emit('battle_action', {'action_by': 'player', 'action_type': 'status',
                              'move_name': 'Growl', 'status_effect': 'congelado'})
    recv(s1)
    check(S, 'status_effect forjado no selvagem é ignorado',
          not gstate()['active_encounters'][u1]['battle_state'].get('wild_status'))

    # A2: apply_wild_status é no-op (não congela o selvagem de graça)
    _seed_exploit_enc()
    s1.get_received()
    s1.emit('apply_wild_status', {'status': 'congelado'})
    recv(s1)
    check(S, 'apply_wild_status não aplica status cru',
          not gstate()['active_encounters'][u1]['battle_state'].get('wild_status'))

    # A2b: status_resolved não limpa veneno (permanente) do próprio jogador
    _gs = gstate()
    _gs['active_encounters'][u1]['battle_state']['player_status'] = {
        'condition': 'badly_poisoned', 'turns_active': 1}
    db.save_game_state(_gs, TID)
    s1.emit('status_resolved', {'target': 'player'}); recv(s1)
    check(S, 'status_resolved não zera veneno permanente do jogador',
          (gstate()['active_encounters'][u1]['battle_state'].get('player_status') or {}).get('condition') == 'badly_poisoned')

    # C2: troca com HP forjado é ignorada (usa o HP do time real)
    _seed_exploit_enc()
    _real = db.get_users()[u1]['trainer_data']['team']
    if len(_real) >= 2:
        s1.get_received()
        s1.emit('battle_action', {'action_by': 'player', 'action_type': 'switch',
                                  'new_index': 1, 'new_pokemon_hp': 9999,
                                  'new_pokemon_max_hp': 9999})
        recv(s1)
        _bsx = gstate()['active_encounters'][u1]['battle_state']
        check(S, 'HP na troca vem do time real (não 9999)',
              _bsx['player_hp_max'] == int(_real[1].get('maxHp')))
    else:
        check(S, 'HP na troca vem do time real (não 9999)', True, 'time <2 — pulado')
    _gs = gstate(); _gs['active_encounters'].pop(str(u1), None); db.save_game_state(_gs, TID)

    # C2b: cura grátis via PIVOT na troca é fechada. Durante a batalha selvagem
    # o dano vive só no battle_state; o currentHp ARMAZENADO do time nunca é
    # decrementado. Sem persistir o HP de quem SAI, pivotar (banco→ativo)
    # restaurava o Pokémon ao currentHp cheio armazenado — sustain infinito
    # sem item. Agora a troca grava o HP de batalha no time.
    _real = db.get_users()[u1]['trainer_data']['team']
    if len(_real) >= 2:
        _hp_snap = [p.get('currentHp') for p in _real]   # restaura no fim
        _p0max = int(_real[0].get('maxHp') or 20)
        _gs = gstate()
        _gs.setdefault('active_encounters', {})[str(u1)] = {
            'player_id': str(u1), 'player_name': 'rev_p1',
            'pokemon': dict(enc['pokemon'], hp=40, currentHp=40),
            'level': enc['level'], 'is_shiny': False,
            'player_pokemon': _real[0], 'player_pokemon_idx': 0,
            'battle_state': {'turn': 'player', 'round': 3,
                             'wild_hp_current': 40, 'wild_hp_max': 40,
                             'player_hp_current': 5, 'player_hp_max': _p0max,
                             'wild_status': None, 'player_status': None,
                             'initiative_rolled': True}}
        db.save_game_state(_gs, TID)
        s1.get_received()
        s1.emit('battle_action', {'action_by': 'player', 'action_type': 'switch', 'new_index': 1})
        recv(s1)
        # selvagem joga o turno → volta pro jogador
        _gs = gstate(); _gs['active_encounters'][str(u1)]['battle_state']['turn'] = 'player'
        db.save_game_state(_gs, TID)
        s1.emit('battle_action', {'action_by': 'player', 'action_type': 'switch', 'new_index': 0})
        recv(s1)
        _hp_back = gstate()['active_encounters'][str(u1)]['battle_state']['player_hp_current']
        check(S, 'pivô na troca NÃO cura (HP de batalha persiste)',
              _hp_back <= 5, f'voltou com {_hp_back}/{_p0max}')
        _gs = gstate(); _gs['active_encounters'].pop(str(u1), None); db.save_game_state(_gs, TID)
        # restaura o currentHp do time (a troca gravou o HP de batalha nele)
        _uu = db.get_users()
        for _p, _hp in zip(_uu[u1]['trainer_data']['team'], _hp_snap):
            _p['currentHp'] = _hp
        db.save_users(_uu)
    else:
        check(S, 'pivô na troca NÃO cura (HP de batalha persiste)', True, 'time <2 — pulado')

    # A3: terceiro (msio=mestre não é jogador) não encerra PvP alheio via forfeit
    _rn = m.post('/master/npcs/generate', json={'npc_class': 'Trainer', 'level': 12, 'team_size': 1}).get_json()
    for q in _rn['team']:
        q['moves'] = ['Tackle']
    db.save_npc(_rn, TID)
    s1.get_received()
    s1.emit('pvp_challenge', {'target_id': _rn['id'], 'mode': 'street'})
    _cr = recv(s1, 'pvp_battle_created')
    if _cr:
        _bx = _cr[0]['args'][0]['battle_id']
        s1.emit('pvp_select_pokemon', {'battle_id': _bx, 'pokemon_idx': 0}); recv(s1)
        _bt = appmod.ACTIVE_PVP.get(_bx)
        # s2 (rev_p2) NÃO é participante desta batalha — forfeit deve ser ignorado
        s2.emit('pvp_forfeit', {'battle_id': _bx}); recv(s2)
        check(S, 'terceiro não encerra PvP alheio (forfeit ignorado)',
              _bt and _bt.get('phase') == 'battle')
        appmod.ACTIVE_PVP.pop(_bx, None)
    else:
        check(S, 'terceiro não encerra PvP alheio (forfeit ignorado)', True, 'sem batalha — pulado')

    # Lote 2 — CONCORRÊNCIA: save_users grava só quem MUDOU. Dois snapshots
    # (como 2 greenlets) mutando jogadores diferentes não se sobrescrevem.
    _m1_bak = db.get_users()[u1]['trainer_data'].get('money')
    _m2_bak = db.get_users()[u2]['trainer_data'].get('money')
    _ua = db.get_users(); _ub = db.get_users()   # dois loads (estado obsoleto em _ub)
    _ua[u1]['trainer_data']['money'] = 111
    db.save_users(_ua)                            # grava só u1
    _ub[u2]['trainer_data']['money'] = 222
    db.save_users(_ub)                            # grava só u2 — NÃO reverte u1
    _fin = db.get_users()
    check(S, 'save concorrente não faz clobber cross-player',
          _fin[u1]['trainer_data']['money'] == 111
          and _fin[u2]['trainer_data']['money'] == 222)
    # restaura o dinheiro para não interferir nos testes de economia adiante
    _rs = db.get_users()
    _rs[u1]['trainer_data']['money'] = _m1_bak
    _rs[u2]['trainer_data']['money'] = _m2_bak
    db.save_users(_rs)

    # Lote 3 — pokemon-center bloqueado durante encontro ativo
    _gs = gstate()
    _gs.setdefault('active_encounters', {})[str(u1)] = {
        'player_id': str(u1), 'pokemon': {'name': 'Pidgey', 'number': 16, 'level': 12},
        'level': 12, 'battle_state': {'wild_hp_current': 5, 'wild_hp_max': 40,
                                      'player_hp_current': 10, 'player_hp_max': 60, 'turn': 'player'}}
    db.save_game_state(_gs, TID)
    r = p1.post('/player/pokemon-center', json={})
    check(S, 'Centro Pokémon bloqueado durante batalha', r.status_code == 400)
    _gs = gstate(); _gs['active_encounters'].pop(str(u1), None); db.save_game_state(_gs, TID)
    r = p1.post('/player/pokemon-center', json={})
    check(S, 'Centro Pokémon funciona fora de batalha', (r.get_json() or {}).get('ok'))

    # Lote 3 — item X aplica estágio real no servidor e consome da bolsa
    _u = db.get_users(); _u[u1]['trainer_data']['bag'] = [{'name': 'X Attack', 'qty': 2}]
    _u[u1]['trainer_data']['team'][0]['stat_stages'] = None
    db.save_users(_u)
    _gs = gstate()
    _team0 = db.get_users()[u1]['trainer_data']['team'][0]
    _gs.setdefault('active_encounters', {})[str(u1)] = {
        'player_id': str(u1), 'pokemon': dict(enc['pokemon'], hp=40, currentHp=40),
        'level': enc['level'], 'player_pokemon': _team0,
        'battle_state': {'turn': 'player', 'round': 1, 'wild_hp_current': 40, 'wild_hp_max': 40,
                         'player_hp_current': 60, 'player_hp_max': 60,
                         'wild_status': None, 'player_status': None, 'initiative_rolled': True}}
    db.save_game_state(_gs, TID)
    s1.get_received()
    s1.emit('battle_action', {'action_by': 'player', 'action_type': 'use_item',
                              'item_name': 'X Attack'})
    recv(s1)
    _stg = gstate()['active_encounters'][u1]['battle_state'].get('player_stat_stages') or {}
    _bag_after = next((it for it in db.get_users()[u1]['trainer_data'].get('bag', [])
                       if it.get('name') == 'X Attack'), {})
    check(S, 'item X aplica +1 estágio de ATK (server-autoritativo)', _stg.get('ATK') == 1)
    check(S, 'item X é consumido da bolsa no servidor', int(_bag_after := _bag_after.get('qty', 0)) == 1)
    # item X sem estoque é bloqueado (reseta o turno p/ passar do gate de turno)
    _u = db.get_users(); _u[u1]['trainer_data']['bag'] = []; db.save_users(_u)
    _gs = gstate(); _gs['active_encounters'][u1]['battle_state']['turn'] = 'player'
    db.save_game_state(_gs, TID)
    s1.get_received()
    s1.emit('battle_action', {'action_by': 'player', 'action_type': 'use_item', 'item_name': 'X Attack'})
    _blk = recv(s1, 'action_blocked')
    check(S, 'item X sem estoque é bloqueado', bool(_blk))
    _gs = gstate(); _gs['active_encounters'].pop(str(u1), None); db.save_game_state(_gs, TID)

    # Lote 3 — double-spend guard reentrante na loja (o flag existe)
    check(S, 'guard de economia (_ECON_BUSY) definido', hasattr(appmod, '_ECON_BUSY'))

    # Habilidade do ATACANTE (Poison Touch) envenena o alvo no contato físico.
    pt_procs = sum(1 for _ in range(400)
                   if (appmod.ab.check_attacker_contact_ability('Poison Touch') or {}).get('status') == 'badly_poisoned')
    check(S, 'Poison Touch (habilidade do atacante) envenena', 60 <= pt_procs <= 180, f'{pt_procs}/400 ~30%')
    check(S, 'Poison Touch aceita formato dict {name}',
          any(appmod.ab.check_attacker_contact_ability({'name': 'Poison Touch'}) for _ in range(50)))
    check(S, 'habilidade sem efeito de contato retorna None',
          appmod.ab.check_attacker_contact_ability('Overgrow') is None)

    # Venoshock: dano dobra contra alvo envenenado (sinergia de veneno).
    # (atacante FRESCO por chamada — isola o estado _v3 entre os cenários)
    import statistics as _stat

    def _veno(status):
        _enc = {'player_pokemon': make_poke('Croagunk', 30),
                'pokemon': make_poke('Rattata', 20), 'level': 20,
                'battle_state': {'wild_status': status}}
        return appmod._calc_player_attack(_enc, 'Venoshock', 18)['damage']
    _clean = [_veno(None) for _ in range(150)]
    _pois = [_veno({'condition': 'badly_poisoned', 'turns_active': 0})
             for _ in range(150)]
    check(S, 'Venoshock x2 vs alvo envenenado',
          _stat.mean(_pois) > 1.6 * max(1, _stat.mean(_clean)),
          f'limpo={_stat.mean(_clean):.1f} envenenado={_stat.mean(_pois):.1f}')

    # Imunidade de tipo com fallback da espécie: pokémon salvo pela ficha vem
    # sem 'immunities' — Ghost NÃO pode tomar dano de move Normal.
    _gastly = make_poke('Gastly', 30)
    _gastly['immunities'] = []   # como a ficha salva
    _imm_hits = sum(1 for _ in range(30)
                    if appmod._calc_pvp_attack(make_poke('Rattata', 30), _gastly, 'Tackle', 18)['damage'] > 0)
    check(S, 'imunidade Ghost×Normal (fallback da espécie)', _imm_hits == 0, f'{_imm_hits}/30 acertos')
    check(S, 'super efetivo ainda acerta Ghost',
          appmod._calc_pvp_attack(make_poke('Rattata', 30), _gastly, 'Bite', 18)['damage'] > 0)

    # Metronome vira move de DANO aleatório (nunca cai em "utilidade")
    _met = appmod._calc_pvp_attack(make_poke('Clefairy', 30), make_poke('Rattata', 30), 'Metronome', 15)
    check(S, 'Metronome resolve como ataque', not _met.get('is_status') and 'Metronome' in _met.get('message', ''))

    # Moves de dano fixo / Haze / Teleport / Splash têm efeito real
    _att_stats = {'ATK': 14, 'SPA': 14, 'CON': 12, 'level': 40, 'proficiency': 5, 'maxHp': 80}
    _tgt_stats = {'DEF': 12, 'level': 40}
    _ns = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('night shade'), _att_stats, _tgt_stats)
    _ns_exp = max(1, int(40 * appmod.bm_core.damage_scale(40)))
    check(S, 'Night Shade dano fixo = nível × escala', _ns['effect_type'] == 'fixed_damage'
          and _ns['damage'] == _ns_exp, f"{_ns['damage']} (esperado {_ns_exp})")
    _hz = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('haze'), _att_stats, _tgt_stats)
    check(S, 'Haze anula stages', _hz['effect_type'] == 'reset_stages')
    _tp = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('teleport'), _att_stats, _tgt_stats)
    check(S, 'Teleport foge (selvagem)', _tp['effect_type'] == 'flee')
    # TODOS os moves de status têm efeito (nenhum cai no limbo de "utilidade")
    import json as _json
    _all_moves = _json.load(open('server/data/moves.json'))
    _no_effect = [n for n, md in _all_moves.items()
                  if md.get('category') == 'status' and appmod.effects.auto_detect_move_effect(md) is None]
    check(S, 'nenhum move de status sem efeito', len(_no_effect) == 0, f'{len(_no_effect)} sem efeito')

    # Escalada de dano v2: dados do Power crescem com o nível (monotônico)
    import battle_math as bmm
    def _avg(ds):
        c, s = map(int, ds.split('d')); return c * (s + 1) / 2
    _avgs = [_avg(bmm.dice_for_power(80, lv)) for lv in (5, 15, 25, 35, 45, 55, 65, 75, 85)]
    check(S, 'dano escala monotônico com o nível', all(b >= a for a, b in zip(_avgs, _avgs[1:])),
          f'médias={_avgs}')
    check(S, 'Power maior = mais dados', _avg(bmm.dice_for_power(120, 30)) > _avg(bmm.dice_for_power(40, 30)))

    # Novas mecânicas: Pain Split, OHKO, stage_op, Endeavor, Nature's Madness
    _att_hp = dict(_att_stats, currentHp=20)
    _tgt_hp = dict(_tgt_stats, currentHp=100)
    _ps = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('pain split'), _att_hp, _tgt_hp)
    check(S, 'Pain Split divide os HPs', _ps['effect_type'] == 'fixed_damage'
          and _ps['damage'] == 40 and _ps['heal'] == 40)
    _en = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('endeavor'), _att_hp, _tgt_hp)
    check(S, 'Endeavor iguala HP do alvo ao seu', _en.get('damage') == 80)
    _fg = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('final gambit'), _att_hp, _tgt_hp)
    check(S, 'Final Gambit: dano = HP e desmaia junto',
          _fg.get('damage') == 20 and _fg.get('self_damage') == 20)
    _oh = [appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('guillotine'), _att_hp, _tgt_hp)
           for _ in range(80)]
    check(S, 'OHKO tem fatais E resistidos',
          any(r['effect_type'] == 'fixed_damage' for r in _oh) and any(r['effect_type'] == 'resisted' for r in _oh))
    _so = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('psych up'), _att_hp, _tgt_hp)
    check(S, 'Psych Up é stage_op copy', _so['effect_type'] == 'stage_op' and _so['op'] == 'copy')
    _tt = appmod.effects.process_status_move(appmod.MOVES_BY_NAME.get('topsy-turvy'), _att_hp, _tgt_hp)
    check(S, 'Topsy-Turvy é stage_op invert', _tt['op'] == 'invert')
    for _vm in ('Copycat', 'Mirror Move', 'Assist'):
        _vc = appmod._calc_pvp_attack(make_poke('Clefairy', 30), make_poke('Rattata', 30), _vm, 15)
        check(S, f'{_vm} resolve como ataque', not _vc.get('is_status') and _vm in _vc.get('message', ''))

    r = p1.post('/api/pokemon/battle-xp', json={'winner_level': 20, 'loser_level': 18, 'battle_type': 'wild'})
    check(S, 'XP de batalha calculado', (r.get_json() or {}).get('xp_gained', 0) > 0)

    # ══════════ 4a-bis. SHINY (+35% nos atributos base) + GEN 1 ══════════
    section('4a-bis. Shiny e limite Gen 1')
    S = 'Shiny/Gen1'
    _base = appmod.POKEMON_BY_NAME['bulbasaur']
    _norm = scaling.calculate_pokemon_stats(_base, 30)
    _shin = scaling.calculate_pokemon_stats(_base, 30, is_shiny=True)
    # v2: cada stat escalado parte do BASE STAT REAL ×1.35 (arredondado)
    import battle_math as bmm
    _ok_stats = all(
        _shin['stats'][k] == bmm.stat_at_level(int(round(_base['base_stats'][k] * 1.35)), 30)
        for k in ('ATK', 'DEF', 'SPA', 'SPD', 'SPE'))
    check(S, 'shiny: stats = escala(base_stats ×1.35)', _ok_stats,
          f"norm={_norm['stats']} shiny={_shin['stats']}")
    check(S, 'shiny: HP máximo derivado maior', _shin['maxHp'] > _norm['maxHp'],
          f"{_norm['maxHp']} → {_shin['maxHp']}")
    check(S, 'shiny: dano recebido cai (DEF maior no denominador)',
          _shin['stats']['DEF'] > _norm['stats']['DEF'])
    # flag no próprio dict também ativa o bônus (dicts de instância)
    _auto = scaling.calculate_pokemon_stats(dict(_base, is_shiny=True), 30)
    check(S, 'shiny: flag no dict ativa o bônus', _auto['stats'] == _shin['stats'])
    # bônus FIXO e não-acumulativo: recálculos repetidos dão SEMPRE o mesmo
    # valor e não mutam os base_stats da espécie
    _species_snapshot = dict(_base['base_stats'])
    _again = [scaling.calculate_pokemon_stats(_base, 30, is_shiny=True) for _ in range(5)]
    check(S, 'shiny: +35% fixo, não acumula em recálculos',
          all(a['stats'] == _shin['stats'] and a['maxHp'] == _shin['maxHp'] for a in _again))
    check(S, 'shiny: base_stats da espécie intactos após recálculos',
          _base['base_stats'] == _species_snapshot)

    # encontro selvagem shiny carrega flag e stats acrescidos (sem +2 CA legado)
    random.seed(4242)
    _found_shiny = None
    for _ in range(600):
        _e = appmod._build_random_encounter('route1', 'night', 40)
        if isinstance(_e, dict) and _e.get('is_shiny'):
            _found_shiny = _e
            break
    check(S, 'encontro shiny gerado carrega is_shiny no pokémon',
          _found_shiny is not None and _found_shiny['pokemon'].get('is_shiny') is True)
    if _found_shiny:
        _sp = appmod.POKEMON_BY_NAME[_found_shiny['pokemon']['name'].lower()]
        _ref = scaling.calculate_pokemon_stats(_sp, _found_shiny['level'], is_shiny=True)
        check(S, 'encontro shiny: stats/HP vêm do base ×1.35',
              _found_shiny['pokemon']['stats'] == _ref['stats']
              and _found_shiny['pokemon']['maxHp'] == _ref['maxHp'])

    # evolução PRESERVA is_shiny e recalcula com o bônus
    _char = make_poke('Charmander', 20, is_shiny=True,
                      evolutionInfo=appmod.POKEMON_BY_NAME['charmander'].get('evolutionInfo', ''))
    _evo, _evo_name = appmod.check_and_evolve_pokemon(_char, trainer_level=20)
    check(S, 'evolução preserva is_shiny', _evo is not None and _evo.get('is_shiny') is True,
          f'evo={_evo_name}')
    if _evo:
        _evo_ref = scaling.calculate_pokemon_stats(
            appmod.POKEMON_BY_NAME[_evo_name.lower()], _evo['level'], is_shiny=True)
        check(S, 'evolução shiny recalcula com ×1.35', _evo['stats'] == _evo_ref['stats'])

    # /api/pokemon/stats respeita is_shiny
    _rn = p1.post('/api/pokemon/stats', json={'number': 25, 'level': 30}).get_json()
    _rs = p1.post('/api/pokemon/stats', json={'number': 25, 'level': 30, 'is_shiny': True}).get_json()
    check(S, 'API /pokemon/stats aplica shiny', _rs['maxHp'] > _rn['maxHp']
          and all(_rs['stats'][k] >= _rn['stats'][k] for k in _rn['stats']))

    # 🎭 STATS DE HISTÓRIA (encontro manual do mestre): % por stat na API.
    # SÓ o mestre aplica stat_mods → usa o client do mestre (m).
    _rn2 = m.post('/api/pokemon/stats', json={'number': 25, 'level': 30}).get_json()
    _rm = m.post('/api/pokemon/stats', json={'number': 25, 'level': 30,
                  'stat_mods': {'HP': 300, 'ATK': 50, 'SPE': 9999, 'DEF': 100}}).get_json()
    check(S, 'stats de história: HP 300% triplica o máximo',
          _rm['maxHp'] == _rn2['maxHp'] * 3, f"{_rn2['maxHp']} → {_rm['maxHp']}")
    check(S, 'stats de história: ATK 50% cai pela metade',
          _rm['stats']['ATK'] == max(1, _rn2['stats']['ATK'] * 50 // 100))
    check(S, 'stats de história: clamp no teto de 500%',
          _rm['stats']['SPE'] == _rn2['stats']['SPE'] * 5)
    check(S, 'stats de história: 100% não conta como modificação',
          'DEF' not in (_rm.get('stat_mods') or {}) and 'HP' in (_rm.get('stat_mods') or {}))

    # mesa limitada à 1ª geração
    random.seed(77)
    _gen_ok = True
    for _mode in ('normal', 'dungeon', 'night'):
        for _ in range(25):
            _e = appmod._build_random_encounter('route1', _mode, 60)
            if isinstance(_e, dict) and _e['pokemon']['number'] > 151:
                _gen_ok = False
    check(S, 'caçadas geram só Gen 1 (≤151)', _gen_ok)

    # sprites shiny no lugar
    import os as _os
    _spr = [f for f in _os.listdir('static/sprites/shiny') if f.endswith('.gif')]
    check(S, '145 sprites shiny gen1 instalados', len(_spr) == 145, f'{len(_spr)} arquivos')
    check(S, 'sprite shiny acessível via rota estática',
          p1.get('/static/sprites/shiny/001.gif').status_code == 200)

    # ══════════ 4a-ter. SISTEMA v2: paridade, posturas, migração ══════════
    section('4a-ter. Sistema v2 (base stats reais)')
    S = 'Sistema v2'
    import battle_math as bmm
    import migrations as mig
    import statistics as _st

    # Paridade battle_math × referência independente (50 amostras)
    def _ref_stat(base, lv, tr=0):
        return (2 * base * lv) // 100 + 5 + tr
    def _ref_dmg(dice_total, atk, dfn, stab, eff, tax, lv):
        import math as _m
        r = max(0.5, min(2.0, atk / max(1, dfn)))
        d = dice_total * r * tax * (1.5 if stab else 1.0) * eff
        # escala global de dano crescente com o nível: batalhas de 8-15 turnos
        scale = bmm.DAMAGE_SCALE_BASE + bmm.DAMAGE_SCALE_PER_LEVEL * max(1, lv)
        return max(1, int(d * scale)) if eff > 0 else 0
    _par_ok = True
    random.seed(99)
    for _ in range(50):
        b_, lv_ = random.randint(20, 160), random.randint(1, 100)
        if bmm.stat_at_level(b_, lv_) != _ref_stat(b_, lv_):
            _par_ok = False
        dt, a_, d_ = random.randint(2, 60), random.randint(10, 200), random.randint(10, 200)
        st_, ef_, tx_ = random.random() < 0.5, random.choice([0, 0.5, 1, 2]), random.choice([1.0, 1.25, 1.5])
        if bmm.damage(dt, a_, d_, stab=st_, effectiveness=ef_, tax=tx_,
                      level=lv_) != _ref_dmg(dt, a_, d_, st_, ef_, tx_, lv_):
            _par_ok = False
    check(S, 'paridade battle_math × referência (50 amostras)', _par_ok)

    # Stats v2 batem com os jogos (Pikachu Nv50 sem IV/EV = 60/45/55/55/95)
    _pk50 = scaling.calculate_pokemon_stats(appmod.POKEMON_BY_NAME['pikachu'], 50)
    check(S, 'Pikachu Nv50 = jogos sem IV/EV',
          _pk50['stats'] == {'ATK': 60, 'DEF': 45, 'SPA': 55, 'SPD': 55, 'SPE': 95, 'HP': 40}
          and _pk50['maxHp'] == 95, str(_pk50['stats']))

    # v3: taxa de conexão observada ≈ ACC (Hydro Pump 80%) — poke fresco por
    # rolagem (senão o cooldown do POW 110 bloqueia as repetições)
    _hp_def = make_poke('Charizard', 50)
    _hits = 0
    for _ in range(600):
        _hp_atk = make_poke('Blastoise', 50)
        if appmod._calc_pvp_attack(_hp_atk, _hp_def, 'Hydro Pump')['hit']:
            _hits += 1
    check(S, 'v3: taxa de conexão ≈ ACC (Hydro Pump 80%)',
          0.72 <= _hits / 600 <= 0.88, f'{_hits/6:.1f}%')

    # v3: Resistência do defensor — DEF alta reduz o dano médio sentido e as
    # três faixas (cheio/metade/anulação) aparecem
    _att30 = make_poke('Rattata', 30)
    _frail, _wall = make_poke('Pikachu', 30), make_poke('Onix', 30)
    _dmg_frail, _dmg_wall, _outs = [], [], set()
    for _ in range(400):
        _a = dict(_att30)
        _r1 = appmod._calc_pvp_attack(_a, _frail, 'Tackle')
        _a2 = dict(_att30)
        _r2 = appmod._calc_pvp_attack(_a2, _wall, 'Tackle')
        _dmg_frail.append(_r1['damage']); _dmg_wall.append(_r2['damage'])
        _outs.add(_r1.get('outcome')); _outs.add(_r2.get('outcome'))
    check(S, 'v3: DEF alta reduz o dano médio sentido (Onix < Pikachu)',
          _st.mean(_dmg_wall) < _st.mean(_dmg_frail),
          f'{_st.mean(_dmg_frail):.1f}→{_st.mean(_dmg_wall):.1f}')
    check(S, 'v3: as 3 faixas da Resistência aparecem (cheio/metade/anulação)',
          {'full', 'half', 'negate'} <= _outs, str(_outs))
    # troca de Pokémon zera momentum/adaptação (cooldowns ficam)
    _bt = appmod.pvp.create_pvp_battle('street', 'a', 'b')
    _pk_sw = make_poke('Pikachu', 20)
    _pk_sw['_v3'] = {'cooldowns': {'hydro pump': 2}, 'last_move': 'tackle',
                     'streak': 3, 'momentum': 2}
    appmod.pvp.set_team(_bt, 'player1', [_pk_sw, make_poke('Rattata', 20)])
    appmod.pvp.set_team(_bt, 'player2', [make_poke('Onix', 20)])
    appmod.pvp.select_pokemon(_bt, 'player1', 0); appmod.pvp.select_pokemon(_bt, 'player2', 0)
    appmod.pvp.switch_pokemon(_bt, 'player1', 1)
    _stv3 = _bt['player1']['team'][0]['_v3']
    check(S, 'troca zera momentum/adaptação e MANTÉM cooldowns',
          _stv3['momentum'] == 0 and _stv3['streak'] == 0
          and _stv3['cooldowns'].get('hydro pump') == 2)

    # ── Migração v1→v2 ──
    _sp = appmod.POKEMON_BY_NAME['pikachu']
    _exp_v1 = mig._expected_v1_stats(_sp, 20, None, False)
    _v1 = {'name': 'Pikachu', 'number': 25, 'level': 20,
           'stats': dict(_exp_v1, SPE=_exp_v1['SPE'] + 3),   # 3 pontos antigos em SPE
           'maxHp': 60, 'currentHp': 30, 'hp': 60, 'is_shiny': False,
           'moves': ['Thunderbolt'], 'nickname': 'Zé'}
    check(S, 'migração v1→v2 roda', mig.migrate_pokemon_v2(_v1, appmod.POKEMON_BY_NAME, appmod.POKEMON_BY_NUMBER))
    check(S, 'migração: sv=2 e pontos antigos ×3 no mesmo stat',
          _v1['sv'] == 2 and _v1['training']['SPE'] == 9)
    check(S, 'migração: HP mantém a % (50%)', abs(_v1['currentHp'] - _v1['maxHp'] * 0.5) <= 1)
    check(S, 'migração: saldo derivado do budget',
          _v1['statPointsAvailable'] == bmm.training_budget(20) - 9)
    import copy as _cp
    _snap = _cp.deepcopy(_v1)
    check(S, 'migração idempotente', not mig.migrate_pokemon_v2(_v1, appmod.POKEMON_BY_NAME) and _v1 == _snap)
    _v1s = {'name': 'Pikachu', 'number': 25, 'level': 20, 'stats': {}, 'maxHp': 70,
            'currentHp': 70, 'is_shiny': True}
    mig.migrate_pokemon_v2(_v1s, appmod.POKEMON_BY_NAME)
    _refs = scaling.calculate_pokemon_stats(_sp, 20, is_shiny=True, training=_v1s['training'])
    check(S, 'migração preserva shiny ×1.35', _v1s['stats'] == _refs['stats'])

    # v3: dano fixo (Dragon Rage = 15+nível//4 bruto) passa pela Resistência
    # → cheio (20), metade (10) ou anulado (0) no Nv20
    _dr = appmod._calc_pvp_attack(make_poke('Charmander', 20), make_poke('Rattata', 20), 'Dragon Rage', 15)
    _dr_gross = 15 + 20 // 4
    check(S, 'v3: Dragon Rage fixo (bruto 20) resolve pela Resistência',
          _dr['hit'] and _dr['damage'] in (0, _dr_gross // 2, _dr_gross),
          f"{_dr['damage']} (esperado 0/{_dr_gross // 2}/{_dr_gross})")

    # ── Revisão de combate: potência variável, crítico por estágios, categoria ──
    # Return (potência variável) agora dá dano em vez de "mestre adjudica"
    _rt = appmod._calc_pvp_attack(make_poke('Pikachu', 30), make_poke('Rattata', 30), 'Return', 15)
    check(S, 'Return (potência variável) causa dano (não fica adjudicado)',
          _rt['hit'] and _rt['damage'] > 0, str(_rt.get('damage')))
    # v3: crítico por estágios no d100 — base 5%, Super Luck 15%, Night Slash
    # + Super Luck 25%, Focus Energy +2 estágios
    check(S, 'v3: chance de crítico por estágios (5/15/25%)',
          bmm.v3_crit_chance(0) == 5 and
          bmm.v3_crit_chance(bmm.crit_stage_for('X', 'Super Luck')) == 15 and
          bmm.v3_crit_chance(bmm.crit_stage_for('Night Slash', 'Super Luck')) == 25)
    # estatístico: Super Luck crita ~3× mais que o normal (N=800)
    _crits_sl, _crits_base = 0, 0
    for _ in range(800):
        _p = make_poke('Machamp', 40); _p['ability'] = 'Super Luck'
        if appmod._calc_pvp_attack(_p, make_poke('Snorlax', 40), 'Mega Punch').get('is_crit'):
            _crits_sl += 1
        if appmod._calc_pvp_attack(make_poke('Machamp', 40), make_poke('Snorlax', 40), 'Mega Punch').get('is_crit'):
            _crits_base += 1
    check(S, 'v3: Super Luck crita mais que o normal (~15% vs ~5%)',
          _crits_sl > _crits_base and 0.08 <= _crits_sl / 800 <= 0.22
          and _crits_base / 800 <= 0.10,
          f'{_crits_sl/8:.1f}% vs {_crits_base/8:.1f}%')
    # Magnitude recategorizado p/ físico (usa ATK, não SPA)
    check(S, 'Magnitude é físico (categoria corrigida)',
          (appmod.MOVES_BY_NAME.get('magnitude') or {}).get('category') == 'physical')

    # ── Custom EVs: Pontos de Potencial + Treinamento ──
    check(S, 'custo progressivo n(n+1)/2', bmm.stat_cost(10) == 55 and bmm.stat_cost(4) == 10)
    check(S, 'potencial = ⌊nv/2⌋ + evo + especial', bmm.potential_points(40, 12) == 32)
    check(S, 'treino estágio 3/3 = 2/nível', bmm.training_points(40, 3, 3) == 78)
    check(S, 'treino estágio 1/2 = 1.5/nível', bmm.training_points(20, 1, 2) == 28)
    check(S, 'orçamento Tyranitar Nv40 (potencial 32 + treino 78)',
          bmm.points_budget(40, 3, 3, evo_bonus=12) == 110)
    check(S, 'anti-min-max: stat em múltiplo de 5 sem par trava',
          bmm.stat_tier_locked('ATK', {'ATK': 5, 'DEF': 3}) is True and
          bmm.stat_tier_locked('ATK', {'ATK': 5, 'DEF': 5}) is False)
    # migração v3: reseta treino, rola evo bonus retroativo, saldo = orçamento
    _pp = {'name': 'Tyranitar', 'number': 248, 'level': 40, 'training': {'ATK': 20},
           'currentHp': 100, 'maxHp': 100}
    mig.migrate_pokemon_v2(_pp, appmod.POKEMON_BY_NAME, appmod.POKEMON_BY_NUMBER)
    mig.migrate_pokemon_pp(_pp, appmod.POKEMON_BY_NAME, appmod.POKEMON_BY_NUMBER)
    check(S, 'migração v3: pp=1, treino zerado, evo bonus retroativo (estágio 3 = 9)',
          _pp.get('pp') == 1 and sum(_pp['training'].values()) == 0 and
          _pp.get('potential_evo_bonus') == 9)
    check(S, 'migração v3 idempotente',
          not mig.migrate_pokemon_pp(_pp, appmod.POKEMON_BY_NAME, appmod.POKEMON_BY_NUMBER))
    _bud = mig.budget_for(_pp, appmod.POKEMON_BY_NAME['tyranitar'])
    check(S, 'migração v3: saldo = orçamento (treino zerado)',
          _pp['statPointsAvailable'] == _bud and _bud == bmm.points_budget(40, 3, 3, evo_bonus=9))
    # endpoint /player/team: sanitiza distribuição forjada (over-budget → clampa,
    # nunca rejeita) e respeita tier lock
    import copy as _cpev
    users = db.get_users()
    _team_backup = _cpev.deepcopy(users[u1]['trainer_data'].get('team', []))
    _pv = appmod.POKEMON_BY_NAME['pidgeot']  # estágio 3/3
    _forge = [{'name': 'Pidgeot', 'number': 18, 'level': 30, 'sv': 2, 'pp': 1,
               'potential_evo_bonus': 9, 'potential_special': 0, 'training_bonus': 0,
               'training': {'ATK': 50, 'DEF': 0, 'SPA': 0, 'SPD': 0, 'SPE': 0, 'HP': 0},
               'moves': ['Gust']}]
    users[u1]['trainer_data']['team'] = _cpev.deepcopy(_forge)
    db.save_users(users)
    r = p1.post('/player/team', json={'team': _forge})
    users = db.get_users(); _sv = users[u1]['trainer_data']['team'][0]
    _bud2 = mig.budget_for(_sv, _pv)
    check(S, 'save do time: distribuição forjada clampada ao orçamento Custom EVs',
          bmm.training_spent(_sv['training']) <= _bud2)
    check(S, 'save do time: anti-min-max respeitado (ATK all-in cai a 5 sem par)',
          _sv['training']['ATK'] == 5)
    # RENOMEAR não zera o treino (identidade por uid + fallback por número —
    # antes o `pp` era descartado no mismatch da chave (número, apelido) e a
    # migração re-rodava ZERANDO os Custom EVs; report da mesa 10/07)
    users = db.get_users()
    _tr_before = dict(users[u1]['trainer_data']['team'][0]['training'])
    _renamed = _cpev.deepcopy(users[u1]['trainer_data']['team'])
    _renamed[0]['nickname'] = 'Furacão'
    p1.post('/player/team', json={'team': _renamed})
    users = db.get_users(); _sv2 = users[u1]['trainer_data']['team'][0]
    check(S, 'renomear Pokémon NÃO zera o treino (Custom EVs preservados)',
          _sv2.get('training') == _tr_before and _sv2.get('nickname') == 'Furacão'
          and bool(_sv2.get('uid')))
    # restaura o time original do u1 para as próximas seções
    users = db.get_users()
    users[u1]['trainer_data']['team'] = _team_backup
    db.save_users(users)

    # ══════════ 4a-quater. ATRIBUTOS DO TREINADOR (6 novos + perícias) ══════════
    section('4a-quater. Atributos do treinador (Vínculo/Tática/... + perícias)')
    S = 'Atributos Treinador'
    import trainer_attrs as ta

    # migração automática old→new preservando o investimento
    users = db.get_users()
    _tr = users[u1]['trainer_data']
    import copy as _cp2
    _orig_level = _tr.get('level', 1)
    _orig_team = _cp2.deepcopy(_tr.get('team', []))
    for k in list(ta.ATTRIBUTES) + ['av', 'skill_profs']:
        _tr.pop(k, None)
    _tr.update({'str': 8, 'dex': 14, 'con': 18, 'int': 12, 'wis': 16, 'cha': 15, 'level': 5})
    db.save_users(users)
    r = p1.post('/player/trainer', json={})
    users = db.get_users(); _tr = users[u1]['trainer_data']
    check(S, 'migração old→new (wis→vinculo, cha→influencia, ...)',
          _tr.get('vinculo') == 16 and _tr.get('influencia') == 15 and
          _tr.get('determinacao') == 18 and _tr.get('agilidade') == 14 and
          _tr.get('tatica') == 8 and _tr.get('conhecimento') == 12 and _tr.get('av') == 2)

    # ── Point-buy dos atributos (base 10, teto 16, 20 pontos) ──
    # save válido: 16+16+10+10+10+10 = 12 pontos gastos
    r = p1.post('/player/trainer', json={
        'vinculo': 16, 'tatica': 16, 'conhecimento': 10,
        'agilidade': 10, 'influencia': 10, 'determinacao': 10})
    users = db.get_users(); _tr = users[u1]['trainer_data']
    check(S, 'point-buy válido salvo (vinculo=16, tatica=16)',
          r.status_code == 200 and _tr.get('vinculo') == 16 and _tr.get('tatica') == 16)
    # estoura o orçamento: 16,16,16,13 = 21 pontos → rejeita, não altera
    r = p1.post('/player/trainer', json={
        'vinculo': 16, 'tatica': 16, 'conhecimento': 16,
        'agilidade': 13, 'influencia': 10, 'determinacao': 10})
    users = db.get_users(); _tr = users[u1]['trainer_data']
    check(S, 'point-buy acima de 20 pontos rejeitado (400)',
          r.status_code == 400 and _tr.get('conhecimento') == 10)
    # passa do teto por atributo (17): rejeita
    r = p1.post('/player/trainer', json={
        'vinculo': 17, 'tatica': 10, 'conhecimento': 10,
        'agilidade': 10, 'influencia': 10, 'determinacao': 10})
    check(S, 'point-buy acima do teto 16 rejeitado (400)', r.status_code == 400)
    # abaixo da base (9): rejeita
    r = p1.post('/player/trainer', json={
        'vinculo': 9, 'tatica': 10, 'conhecimento': 10,
        'agilidade': 10, 'influencia': 10, 'determinacao': 10})
    check(S, 'point-buy abaixo da base 10 rejeitado (400)', r.status_code == 400)
    # QA LOOP 2: ficha NÃO migrada não pode driblar o point-buy pelos atributos
    # LEGADO (str/dex/... → o migrate promovia o valor do PAYLOAD a 20). A
    # migração agora roda ANTES do payload: usa só os legado JÁ SALVOS.
    users = db.get_users()
    _tr = users[u1]['trainer_data']
    for _k in ('vinculo', 'tatica', 'conhecimento', 'agilidade',
               'influencia', 'determinacao'):
        _tr.pop(_k, None)
    _tr.update({'av': None, 'str': 10, 'dex': 10, 'con': 10,
                'int': 10, 'wis': 10, 'cha': 10})   # ficha legada crua = tudo 10
    _tr.pop('av', None)
    db.save_users(users)
    r = p1.post('/player/trainer', json={'str': 20, 'dex': 20, 'con': 20,
                                         'int': 20, 'wis': 20, 'cha': 20})
    users = db.get_users(); _tr = users[u1]['trainer_data']
    check(S, 'exploit LOOP 2: atributos LEGADO no payload não driblam o point-buy',
          _tr.get('tatica') == 10 and _tr.get('influencia') == 10
          and _tr.get('vinculo') == 10)
    # restaura estado usado pelos testes de perícia abaixo (vínculo 16, det 18...)
    users = db.get_users()
    users[u1]['trainer_data'].update({'vinculo': 16, 'influencia': 15,
        'determinacao': 18, 'agilidade': 14, 'tatica': 8, 'conhecimento': 12})
    db.save_users(users)

    # /api/skill/list: 13 perícias e Sorte com metade do mod de Determinação
    r = p1.get('/api/skill/list')
    d = r.get_json() or {}
    _sk = {s['skill']: s for s in d.get('skills', [])}
    check(S, '13 perícias definidas', len(_sk) == 13, str(len(_sk)))
    check(S, 'Sorte = ½ mod DET (18→+4→+2)',
          _sk.get('Sorte', {}).get('bonus') == 2 and _sk.get('Sorte', {}).get('half_mod') is True)
    check(S, 'Afinidade usa Vínculo (16→+3)', _sk.get('Afinidade', {}).get('bonus') == 3)

    # proficiências: teto por nível (nível 5 → 3)
    r = p1.post('/player/trainer', json={'skill_profs':
        ['Sorte', 'Afinidade', 'Exploração', 'Coragem', 'Diplomacia']})
    users = db.get_users()
    check(S, 'teto de proficiências no nível 5 = 3',
          len(users[u1]['trainer_data']['skill_profs']) == 3)

    # teste de perícia: manual, com proficiência, chega ao mestre
    appmod._rate_store.clear()
    msio.get_received()
    r = p1.post('/api/skill/roll', json={'skill': 'Sorte', 'manual_roll': 12})
    d = r.get_json() or {}
    # Sorte proficiente no nível 5: ½ mod (2) + prof (3) = +5
    check(S, 'teste de Sorte: d20(12) + 2 + prof(3) = 17',
          d.get('total') == 17 and d.get('proficient') is True, str(d))
    check(S, 'perícia inválida rejeitada',
          p1.post('/api/skill/roll', json={'skill': 'Hackear'}).status_code == 400)
    _skr = recv(msio, 'skill_roll')
    check(S, 'mestre recebe o teste na caixa de rolagens',
          bool(_skr) and _skr[0]['args'][0].get('skill') == 'Sorte')

    # ── Rolagem de mesa (livre + a pedido do Mestre) ──
    appmod._rate_store.clear(); msio.get_received()
    # dado puro d20 físico (valor 17) sem bônus
    r = p1.post('/api/roll', json={'kind': 'die', 'die': 20, 'manual_roll': 17,
                                   'note': 'escalar o penhasco'})
    d = r.get_json() or {}
    check(S, 'rolagem livre de dado (d20 físico 17, sem bônus)',
          d.get('total') == 17 and d.get('bonus') == 0 and d.get('kind') == 'die')
    _fr = recv(msio, 'free_roll')
    check(S, 'mestre recebe a rolagem livre com a nota',
          bool(_fr) and _fr[0]['args'][0].get('note') == 'escalar o penhasco')
    # atributo com CD → marca sucesso/falha
    appmod._rate_store.clear()
    r = p1.post('/api/roll', json={'kind': 'attr', 'attr': 'determinacao',
                                   'manual_roll': 20, 'cd': 15})
    d = r.get_json() or {}
    check(S, 'rolagem de atributo com CD marca sucesso',
          d.get('cd') == 15 and d.get('success') is True and d.get('total') >= 20)
    check(S, 'rolagem com tipo inválido rejeitada',
          p1.post('/api/roll', json={'kind': 'xyz'}).status_code == 400)
    # Mestre pede um teste ao jogador (chega via roll_request no socket do p1)
    s1.get_received()
    r = m.post('/master/request-roll', json={'player_id': u1, 'kind': 'skill',
                                             'target': 'Coragem', 'note': 'enfrentar o medo', 'cd': 12})
    check(S, 'mestre pede teste (200)', r.status_code == 200)
    _rr = recv(s1, 'roll_request')
    check(S, 'jogador recebe o pedido de teste do mestre',
          bool(_rr) and _rr[0]['args'][0].get('target') == 'Coragem' and _rr[0]['args'][0].get('cd') == 12)
    check(S, 'pedir teste com perícia inválida rejeitado',
          m.post('/master/request-roll', json={'player_id': u1, 'kind': 'skill', 'target': 'Nope'}).status_code == 400)

    # caçada agora usa 🧭 Exploração (Agilidade 14 → +2, proficiente → +5)
    m.post('/master/hunts', json={'player_id': u1, 'action': 'reset'})
    appmod._rate_store.clear()
    r = p1.post('/api/hunt/roll', json={'manual_roll': 10})
    d = r.get_json() or {}
    check(S, 'caçada = Exploração: d20(10) + 2 + prof(3) = 15',
          d.get('total') == 15 and d.get('skill') == 'Exploração', str(d))

    # loja usa 👑 Influência (15 → -10% compra)
    users = db.get_users(); users[u1]['trainer_data']['money'] = 5000; db.save_users(users)
    r = p1.post('/api/shop/buy', json={'item_id': 'poke-ball', 'qty': 1})
    d = r.get_json() or {}
    check(S, 'loja desconta pela Influência (200 → 180)',
          d.get('unit_price') == 180, str(d.get('unit_price')))

    # iniciativa: mod(♟️ Tática)//2 estampado nos Pokémon do treinador
    _poke_i = make_poke('Pikachu', 10)
    _b = appmod._stamp_tatica([_poke_i], {'tatica': 18, 'av': 2, 'level': 5})
    check(S, 'Tática 18 (+4) → +2 de iniciativa estampado',
          _b == 2 and _poke_i['trainer_init_bonus'] == 2)
    check(S, 'sem treinador (NPC/selvagem) → sem bônus',
          appmod._stamp_tatica([make_poke('Rattata', 5)], None) == 0)
    _rolls = [appmod.pvp.roll_initiative(_poke_i) for _ in range(40)]
    check(S, 'roll_initiative devolve (d100 natural, SPE_eff, tática)',
          all(1 <= n <= 100 for n, _, _ in _rolls)
          and all(s == _poke_i['stats']['SPE'] for _, s, _ in _rolls)
          and all(t == 2 for _, _, t in _rolls))
    _spe_b = bmm.initiative_bonus(_poke_i['stats']['SPE'])
    check(S, 'initiative_bonus (d100) = SPE_eff inteiro',
          _spe_b == _poke_i['stats']['SPE'])
    # initiative_winner (d100): totais, upset ≥96 vs ≤5 e desempates
    _w, _ta, _tb, _up = bmm.initiative_winner(50, 50, 50, 100)
    check(S, 'iniciativa: empate de natural → mais rápido vence',
          _w == 'b' and _ta == 100 and _tb == 150 and not _up)
    _w, _ta, _tb, _up = bmm.initiative_winner(97, 3, 30, 200)
    check(S, 'iniciativa: upset — lento com ≥96 vence rápido com ≤5',
          _w == 'a' and _up is True)
    _w, _, _, _up = bmm.initiative_winner(3, 97, 30, 200)
    check(S, 'iniciativa: natural alto do RÁPIDO não é upset',
          _w == 'b' and _up is False)
    _w, _, _, _up = bmm.initiative_winner(97, 3, 200, 30)
    check(S, 'iniciativa: upset na direção errada não dispara',
          _w == 'a' and _up is False)
    check(S, 'iniciativa: 96/5 são os limiares exatos do upset',
          bmm.initiative_winner(96, 5, 30, 200)[3] is True
          and bmm.initiative_winner(95, 5, 30, 200)[3] is False
          and bmm.initiative_winner(96, 6, 30, 200)[3] is False)
    _w, _ta, _tb, _ = bmm.initiative_winner(75, 50, 50, 75)
    check(S, 'iniciativa: empate de total → maior SPE primeiro',
          _ta == _tb == 125 and _w == 'b')
    check(S, 'iniciativa: empate completo → a (jogador/player1)',
          bmm.initiative_winner(50, 50, 60, 60)[0] == 'a')
    check(S, 'iniciativa: tática entra como extra (×5 na escala d100)',
          bmm.initiative_winner(50, 50, 60, 60, extra_a=2)[0] == 'a'
          and bmm.initiative_winner(50, 50, 60, 60, extra_a=2)[1]
              == bmm.initiative_winner(50, 50, 60, 60)[1] + 10
          and bmm.initiative_winner(50, 50, 60, 60, extra_b=2)[0] == 'b')

    # ── Caminho do Treinador (4 caminhos, marcos 3/6/10) ──
    def _afinidade():
        d = p1.get('/api/skill/list').get_json() or {}
        return {s['skill']: s['bonus'] for s in d.get('skills', [])}.get('Afinidade')
    _before = _afinidade()
    _ps = p1.get('/player/path').get_json() or {}
    check(S, 'caminho desbloqueado no nível 2 e ainda sem escolha',
          _ps.get('unlocked') is True and _ps.get('path') is None)
    r = p1.post('/player/path', json={'action': 'choose_path', 'path': 'guardiao'})
    check(S, 'escolher Caminho do Guardião', r.status_code == 200 and
          (r.get_json() or {}).get('path') == 'guardiao')
    check(S, 'caminho é permanente (re-escolha rejeitada)',
          p1.post('/player/path', json={'action': 'choose_path', 'path': 'estrategista'}).status_code == 400)
    # marco de nível 6 travado com treinador nível 5
    check(S, 'talento de nível 6 travado no nível 5',
          p1.post('/player/path', json={'action': 'choose_ability', 'milestone': 6, 'ability_id': 'reabilitacao'}).status_code == 400)
    # Empatia (nível 3) = +1 Afinidade, aplicado na hora
    r = p1.post('/player/path', json={'action': 'choose_ability', 'milestone': 3, 'ability_id': 'empatia'})
    check(S, 'escolher Empatia (nível 3)', r.status_code == 200)
    check(S, 'Empatia aplica +1 Afinidade automaticamente na perícia',
          _afinidade() == (_before or 0) + 1, f'{_before} -> {_afinidade()}')
    check(S, 'talento do marco é permanente (re-escolha rejeitada)',
          p1.post('/player/path', json={'action': 'choose_ability', 'milestone': 3, 'ability_id': 'empatia'}).status_code == 400)
    # limpa o caminho p/ não contaminar as próximas seções
    users = db.get_users()
    users[u1]['trainer_data'].pop('path', None)
    users[u1]['trainer_data'].pop('path_abilities', None)
    db.save_users(users)

    # ficha 100% v2: save do time recalcula stats e some com chaves D&D
    users = db.get_users()
    _team_junk = [{'name': 'Pikachu', 'number': 25, 'level': 10, 'sv': 2,
                   'stats': {'ATK': 999, 'DEF': 1, 'SPA': 999, 'SPD': 1, 'SPE': 999, 'HP': 999},
                   'maxHp': 9999, 'currentHp': 9999, 'training': {'ATK': 5},
                   'ac': 13, 'hitDice': 'd6', 'savingThrows': 'Dexterity',
                   'moves': ['Thunder Shock']}]
    r = p1.post('/player/team', json={'team': _team_junk})
    users = db.get_users()
    _saved = users[u1]['trainer_data']['team'][0]
    _ref = scaling.calculate_pokemon_stats(appmod.POKEMON_BY_NAME['pikachu'], 10,
                                           training=_saved['training'])
    check(S, 'save do time: stats recalculados no servidor (cliente não manda)',
          _saved['stats'] == _ref['stats'] and _saved['maxHp'] == _ref['maxHp'])
    check(S, 'save do time: currentHp clampado ao máximo',
          _saved['currentHp'] == _saved['maxHp'])
    check(S, 'save do time: chaves D&D (ac/hitDice/savingThrows) removidas',
          all(k not in _saved for k in ('ac', 'hitDice', 'savingThrows')))

    # restaura o estado do u1 para as seções seguintes
    users = db.get_users()
    users[u1]['trainer_data']['team'] = _orig_team
    users[u1]['trainer_data']['level'] = _orig_level
    db.save_users(users)

    # ══════════ 4b. BATALHA EM DUPLA (2v1 / 2v2) ══════════
    section('4b. Batalha em dupla (grupo)')
    S = 'Batalha em Dupla'
    # jogador não pode iniciar
    r = p1.post('/master/group-hunt', json={'player_ids': [u1, u2]})
    check(S, 'jogador bloqueado em group-hunt', r.status_code == 403)
    # precisa de 2 jogadores
    r = m.post('/master/group-hunt', json={'player_ids': [u1]})
    check(S, 'exige 2 jogadores', r.status_code == 400)

    clients = {u1: s1, u2: s2}

    def drive_group(view, tag):
        """Conduz a batalha até terminar; retorna o estado final."""
        for c in (s1, s2, msio):
            c.get_received()
        guard = 0
        # pós-rebalance (8-15 turnos), batalhas em grupo levam bem mais ações
        while view and view.get('phase') == 'active' and guard < 600:
            guard += 1
            turn = next((c for c in view['combatants'] if c['cid'] == view['turn_cid']), None)
            if not turn or turn['side'] != 'ally':
                break  # com AUTO ligado os selvagens já jogaram; só aliados esperam ação
            cli = clients.get(str(turn['player_id']))
            alive_wild = next((c['cid'] for c in view['combatants']
                               if c['side'] == 'wild' and not c['fainted']), None)
            cli.emit('group_battle_action', {'battle_id': view['id'],
                     'move_name': dmg_move(turn), 'target_cid': alive_wild})
            # captura o estado resultante (update ou end)
            pkts = cli.get_received()
            newv = None
            for p in pkts:
                if p['name'] in ('group_battle_update', 'group_battle_end') and p.get('args'):
                    newv = p['args'][0]
            for c in (s1, s2, msio):
                c.get_received()
            view = newv or view
        return view

    # 2v1: um selvagem forte
    r = m.post('/master/group-hunt', json={'player_ids': [u1, u2], 'wild_count': 1,
                                           'hunt_mode': 'normal', 'route_id': 'route1'})
    d = r.get_json() or {}
    v = d.get('battle')
    check(S, '2v1 criada', r.status_code == 200 and v and v['mode'] == '2v1')
    check(S, '2v1 tem 3 combatentes', v and len(v['combatants']) == 3)
    check(S, 'jogadores recebem group_battle_start', bool(recv(s1, 'group_battle_start')))
    final = drive_group(v, '2v1')
    check(S, '2v1 terminou com vencedor', final and final.get('phase') == 'finished'
          and final.get('winner') in ('ally', 'wild'), f"{final and final.get('phase')}")

    # 2v2: dois selvagens
    for c in (s1, s2, msio):
        c.get_received()
    r = m.post('/master/group-hunt', json={'player_ids': [u1, u2], 'wild_count': 2,
                                           'hunt_mode': 'dungeon', 'route_id': 'route1'})
    v = (r.get_json() or {}).get('battle')
    check(S, '2v2 criada', v and v['mode'] == '2v2' and len(v['combatants']) == 4)
    final = drive_group(v, '2v2')
    check(S, '2v2 terminou com vencedor', final and final.get('phase') == 'finished', f"{final and final.get('phase')}")

    # ── AUTO OFF: selvagem NÃO joga sozinho; o mestre destrava com o botão ──
    msio.emit('set_auto_mode', {'enabled': False}); recv(msio)
    for c in (s1, s2, msio):
        c.get_received()
    r = m.post('/master/group-hunt', json={'player_ids': [u1, u2], 'wild_count': 1,
                                           'hunt_mode': 'normal', 'route_id': 'route1'})
    _st1 = recv(s1, 'group_battle_start')
    v3 = _st1[-1]['args'][0] if _st1 else None
    check(S, 'AUTO OFF: broadcast expõe wild_auto=False',
          v3 is not None and v3.get('wild_auto') is False)
    guard3 = 0
    while v3 and v3['phase'] == 'active' and guard3 < 60:
        guard3 += 1
        _t = next((c for c in v3['combatants'] if c['cid'] == v3['turn_cid']), None)
        if not _t or _t['side'] == 'wild':
            break
        _cli = clients[str(_t['player_id'])]
        _aw = next((c['cid'] for c in v3['combatants'] if c['side'] == 'wild' and not c['fainted']), None)
        _cli.emit('group_battle_action', {'battle_id': v3['id'],
                  'move_name': dmg_move(_t), 'target_cid': _aw})
        for p in _cli.get_received():
            if p['name'] in ('group_battle_update', 'group_battle_end') and p.get('args'):
                v3 = p['args'][0]
        for c in (s1, s2, msio):
            c.get_received()
    _t = next((c for c in v3['combatants'] if c['cid'] == v3['turn_cid']), None) if v3 else None
    check(S, 'AUTO OFF: batalha espera na vez do selvagem',
          v3 and v3['phase'] == 'active' and _t and _t['side'] == 'wild')
    # monitor do mestre rehidrata via /master/battles/active
    r = m.get('/master/battles/active')
    check(S, 'rehidratação: group_battles no /master/battles/active',
          any(g.get('id') == v3['id'] for g in (r.get_json() or {}).get('group_battles', [])))
    # botão do mestre → group_wild_turn destrava (selvagem joga)
    _log_before = len(v3.get('log') or [])
    msio.emit('group_wild_turn', {'battle_id': v3['id']})
    v_after = None
    for p in msio.get_received():
        if p['name'] in ('group_battle_update', 'group_battle_end') and p.get('args'):
            v_after = p['args'][0]
    _ta = next((c for c in v_after['combatants'] if c['cid'] == v_after['turn_cid']), None) if v_after else None
    check(S, 'AUTO OFF: group_wild_turn do mestre destrava a batalha',
          v_after is not None and (v_after['phase'] == 'finished'
                                   or (_ta and _ta['side'] == 'ally')
                                   or len(v_after.get('log') or []) > _log_before))
    msio.emit('set_auto_mode', {'enabled': True}); recv(msio)
    appmod.ACTIVE_GROUP_BATTLES.pop(v3['id'], None)
    for c in (s1, s2, msio):
        c.get_received()

    # ══════════ 5. XP & EVOLUÇÃO ══════════
    section('5. XP, level-up e evoluções')
    S = 'XP/Evolução'
    r = m.post('/master/xp', json={'player_id': u2, 'xp': 2500})
    check(S, 'XP de treinador', r.status_code == 200)
    r = m.post('/master/pokemon-xp', json={'player_id': u1, 'pokemon_idx': 0, 'xp': 4000})
    check(S, 'XP direto no pokémon (tabela real)', (r.get_json() or {}).get('leveled_up'))

    # Evolução por NÍVEL DO POKÉMON (escala canon = 5e×5): Bulbasaur Nv15 → Ivysaur
    users = db.get_users()
    users[u1]['trainer_data']['team'].append(make_poke('Bulbasaur', 15, is_shiny=True, nickname='Bulbi'))
    db.save_users(users)
    idx = len(users[u1]['trainer_data']['team']) - 1
    s2.get_received(); msio.get_received()
    r = p1.post('/player/level-evolve', json={'slot': idx})
    d = r.get_json() or {}
    _evo = d.get('pokemon') or {}
    check(S, 'nível do Pokémon: Bulbasaur Nv15 → Ivysaur',
          d.get('evolved') and _evo.get('name') == 'Ivysaur', str(d)[:120])
    check(S, 'evoluído preserva shiny/nickname + immunities e stats recalculados',
          _evo.get('is_shiny') is True and _evo.get('nickname') == 'Bulbi'
          and 'immunities' in _evo and 'phys_ac' in _evo
          and (_evo.get('stats') or {}).get('HP', 0) > 0)
    _f2 = recv(s2, 'evolution_focus')
    _fm = recv(msio, 'evolution_focus')
    check(S, 'evolution_focus: outro jogador E mestre recebem (com shiny)',
          _f2 and _fm and _f2[0]['args'][0].get('shiny') is True
          and _f2[0]['args'][0].get('new_name') == 'Ivysaur')

    users = db.get_users()
    users[u1]['trainer_data']['team'].append(make_poke('Charmander', 14))
    db.save_users(users)
    idx = len(users[u1]['trainer_data']['team']) - 1
    d = p1.post('/player/level-evolve', json={'slot': idx}).get_json() or {}
    check(S, 'abaixo do limiar (14 < 15) não evolui', not d.get('evolved'))

    # espécie com pedra no texto NÃO evolui de graça por nível
    users = db.get_users()
    users[u1]['trainer_data']['team'].append(make_poke('Pikachu', 60))
    db.save_users(users)
    idx = len(users[u1]['trainer_data']['team']) - 1
    d = p1.post('/player/level-evolve', json={'slot': idx}).get_json() or {}
    check(S, 'ramo com pedra não vira evolução por nível (Pikachu Nv60)', not d.get('evolved'))
    users = db.get_users()
    users[u1]['trainer_data']['bag'].append({'name': 'Thunder Stone', 'qty': 1})
    db.save_users(users)
    r = p1.post('/player/use-stone', json={'pokemon_idx': idx, 'item_name': 'Thunder Stone'})
    d = r.get_json() or {}
    check(S, 'evolução por pedra (Pikachu→Raichu)',
          (d.get('ok') or d.get('success')) and 'Raichu' in str(d), f'{d}')
    check(S, 'pedra usa o builder único (immunities presentes no evoluído)',
          'immunities' in (d.get('pokemon') or {})
          and 'phys_ac' in (d.get('pokemon') or {}))

    # pedra errada → 400 e NÃO consome item
    users = db.get_users()
    users[u1]['trainer_data']['team'].append(make_poke('Eevee', 10))
    users[u1]['trainer_data']['bag'].append({'name': 'Dawn Stone', 'qty': 1})
    db.save_users(users)
    idx = len(users[u1]['trainer_data']['team']) - 1
    r = p1.post('/player/use-stone', json={'pokemon_idx': idx, 'item_name': 'Dawn Stone'})
    _bag = [b for b in db.get_users()[u1]['trainer_data']['bag'] if b.get('name') == 'Dawn Stone']
    check(S, 'pedra errada → 400 sem consumir', r.status_code == 400 and _bag and _bag[0]['qty'] == 1)

    # Tabela tudo-pedra: Eevee, Gloom (chaves mortas consertadas), Tyrogue, ex-amizade/move
    check(S, 'Eevee: Sun→Espeon, Moon→Umbreon, Shiny→Sylveon',
          scaling.get_special_evolution('Eevee', 'Sun Stone') == ('Espeon', True)
          and scaling.get_special_evolution('Eevee', 'Moon Stone') == ('Umbreon', True)
          and scaling.get_special_evolution('Eevee', 'Shiny Stone') == ('Sylveon', True))
    check(S, 'Gloom: Leaf→Vileplume, Sun→Bellossom',
          scaling.get_special_evolution('Gloom', 'Leaf Stone') == ('Vileplume', True)
          and scaling.get_special_evolution('Gloom', 'Sun Stone') == ('Bellossom', True))
    check(S, 'Tyrogue: Sun/Moon/Dawn → Hitmonlee/chan/top',
          scaling.get_special_evolution('Tyrogue', 'Sun Stone') == ('Hitmonlee', True)
          and scaling.get_special_evolution('Tyrogue', 'Moon Stone') == ('Hitmonchan', True)
          and scaling.get_special_evolution('Tyrogue', 'Dawn Stone') == ('Hitmontop', True))
    check(S, 'ex-amizade/move viraram pedra (Golbat/Lickitung/Riolu)',
          scaling.get_special_evolution('Golbat', 'Dusk Stone') == ('Crobat', True)
          and scaling.get_special_evolution('Lickitung', 'Moon Stone') == ('Lickilicky', True)
          and scaling.get_special_evolution('Riolu', 'Dawn Stone') == ('Lucario', True))
    check(S, 'condições antigas (amizade/move) não evoluem mais nada',
          scaling.get_special_evolution('Golbat', battle_wins=99) == (None, False)
          and scaling.get_special_evolution('Lickitung', moves=['Rollout']) == (None, False))
    check(S, 'endpoint de amizade removido (404)',
          p1.post('/player/friendship-evolve', json={'pokemon_idx': 0}).status_code == 404)

    # Recompensas de batalha server-side: XP + battle_wins por SLOT + evolução + foco
    users = db.get_users()
    users[u1]['trainer_data']['team'] = [
        make_poke('Squirtle', 14, nickname='A'),
        make_poke('Squirtle', 14, nickname='B',
                  totalXp=scaling.total_xp_for_level(14)),
    ]
    db.save_users(users)
    gs = gstate()
    gs['active_encounters'][u1] = {
        'player_id': u1, 'level': 30,
        'pokemon': {'name': 'Rattata', 'number': 19, 'hp': 30, 'level': 30},
        'player_pokemon_idx': 1,
        'player_pokemon': users[u1]['trainer_data']['team'][1],
        'battle_state': {'turn': 'player', 'round': 3, 'wild_hp_current': 0,
                         'wild_hp_max': 30, 'player_hp_current': 20,
                         'player_hp_max': 30, 'initiative_rolled': True},
    }
    db.save_game_state(gs, TID)
    s1.get_received(); s2.get_received(); msio.get_received()
    s1.emit('end_encounter', {'result': 'defeated'})
    _r1 = recv(s1)
    _rw = [p for p in _r1 if p['name'] == 'battle_rewards']
    check(S, 'battle_rewards: XP server-side no slot certo',
          _rw and _rw[0]['args'][0].get('slot') == 1
          and _rw[0]['args'][0].get('xp_gained', 0) > 0,
          str([p['name'] for p in _r1]))
    team = db.get_users()[u1]['trainer_data']['team']
    check(S, 'battle_wins/XP no índice 1 (não vaza pro homônimo do slot 0)',
          team[1].get('battle_wins') == 1 and team[1].get('totalXp', 0) > 0
          and team[0].get('battle_wins', 0) == 0 and team[0].get('totalXp', 0) == 0)
    check(S, 'level-up + evolução server-side no fim da batalha (Squirtle→Wartortle)',
          team[1].get('name') == 'Wartortle' and team[1].get('level', 0) >= 15,
          f"{team[1].get('name')} Nv{team[1].get('level')}")
    _f2 = recv(s2, 'evolution_focus')
    check(S, 'evolution_focus da batalha chega à mesa (source=battle)',
          _f2 and _f2[0]['args'][0].get('source') == 'battle')
    s1.emit('end_encounter', {'result': 'defeated'})
    recv(s1)
    check(S, 'sem encontro ativo não há recompensa (anti-farm)',
          db.get_users()[u1]['trainer_data']['team'][1].get('battle_wins') == 1)

    r = p1.post('/player/pokemon-center', json={})
    check(S, 'centro pokémon cura o time', r.status_code == 200)

    # ══════════ 6. MOVES/STATUS/HABILIDADES ══════════
    section('6. Moves, status e habilidades')
    S = 'Moves/Status/Hab.'
    r = p1.get('/api/pokemon/6/learnset')
    d = r.get_json() or {}
    check(S, 'learnset com níveis/TM/abilities', d.get('all') and d.get('tm') and d.get('abilities'))
    check(S, 'habilidade com nome real (não "Resistances")',
          all(a['name'] != 'Resistances' for a in d.get('abilities', [])))
    r = p1.post('/api/process-status-move', json={
        'move_name': 'Thunder Wave',
        'attacker_stats': {'ATK': 16, 'SPA': 14, 'level': 20, 'proficiency': 3, 'maxHp': 50},
        'target_stats': {'DEF': 10, 'SPD': 10, 'SPE': 10, 'level': 20}})
    _twmsg = (r.get_json() or {}).get('message', '')
    check(S, 'status move processado por ACC no d100 (v3)',
          'd100' in _twmsg and ('ACC' in _twmsg or 'certeiro' in _twmsg), _twmsg)
    r = p1.post('/api/check-status', json={'action': 'turn_start',
                                           'pokemon_status': {'condition': 'badly_poisoned', 'turns_active': 0},
                                           'max_hp': 40})
    check(S, 'dano de veneno por turno', (r.get_json() or {}).get('damage', 0) >= 1)
    import abilities as ab
    res = ab.check_defender_ability('Levitate', 'ground', 20, 30, 30)
    check(S, 'imunidade por habilidade (Levitate)', res['blocked'])
    check(S, 'STAB boost Blaze a 25% HP', ab.stab_multiplier('Blaze', 'fire', 5, 40) == 2)
    r = p1.post('/api/moves/batch', json={'moves': ['Ember', 'Growl']})
    check(S, 'batch de moves', len(r.get_json() or {}) == 2)
    check(S, 'batch traz power_num/accuracy canônicos (linha mecânica da UI)',
          (r.get_json() or {}).get('Ember', {}).get('power_num') == 40)

    # ── Fidelidade de efeitos (v3.1): Static, Solar Power, Strength Sap ──
    _static_hits = [ab.check_contact_ability('Static', 3) for _ in range(300)]
    _static_hits = [h for h in _static_hits if h]
    check(S, 'Static PARALISA em contato (30%, sem dano)',
          _static_hits and all(h['status'] == 'paralisado' and h['damage'] == 0
                               for h in _static_hits)
          and 45 <= len(_static_hits) <= 140, f'{len(_static_hits)}/300')
    _sp_sun = ab.stat_multiplier_for({'ability': 'Solar Power', '_weather': 'sun'}, 'SPA')
    _sp_dry = ab.stat_multiplier_for({'ability': 'Solar Power'}, 'SPA')
    check(S, 'Solar Power: SpA ×1,5 SÓ sob Sol', _sp_sun == 1.5 and _sp_dry == 1.0)
    _fld_sun = {'field': {'weather': 'sun', 'weather_left': 3}}
    _d, _m = appmod._field_chip(_fld_sun, {'ability': 'Solar Power', 'types': ['Grass']}, 80, 'X')
    check(S, 'Solar Power: custa ⌊HP/8⌋ por rodada sob Sol',
          _d == -10 and 'Solar Power' in (_m or ''))
    _ss = appmod.effects.process_status_move(
        {'name': 'Strength Sap', 'category': 'status'},
        {'maxHp': 100, '_v3': {}}, {'ATK': 60, 'level': 30})
    check(S, 'Strength Sap: cura = ATK do alvo + ATK do alvo −1 (com recarga)',
          _ss.get('heal') == 60 and _ss.get('stat_changes') == {'ATK': -1}
          and _ss.get('effect_type') == 'debuff' and _ss.get('cooldown') == 3)
    # retorno decrescente também vale para drain_stat_heal (anti heal-stall)
    _ss_v3 = {'_v3': {}}
    _s1 = appmod.effects.process_status_move(
        {'name': 'Strength Sap', 'category': 'status'},
        dict({'maxHp': 100}, **_ss_v3), {'ATK': 60, 'level': 30})
    _ss_v3['_v3'].get('cooldowns', {}).clear()   # espera a recarga passar
    _s2 = appmod.effects.process_status_move(
        {'name': 'Strength Sap', 'category': 'status'},
        dict({'maxHp': 100}, **_ss_v3), {'ATK': 60, 'level': 30})
    check(S, 'Strength Sap decai: 60 → 30 (heal_uses compartilhado)',
          _s1.get('heal') == 60 and _s2.get('heal') == 30
          and _ss_v3['_v3'].get('heal_uses') == 2)
    _se = appmod.effects.process_status_move(
        {'name': 'Strength Sap', 'category': 'status'},
        {'maxHp': 200, '_v3': {}}, {'ATK': 60, 'ATK_eff': 90, 'level': 30})
    check(S, 'Strength Sap usa ATK EFETIVO do alvo quando o caller passa',
          _se.get('heal') == 90)
    # imunidade a status de CONTATO: Elétrico não paralisa; Limber idem
    check(S, 'contact_status_blocked: Elétrico/Limber imunes à paralisia de Static',
          appmod.effects.contact_status_blocked({'types': ['Electric']}, 'paralisado')
          and appmod.effects.contact_status_blocked(
              {'types': ['Normal'], 'ability': 'Limber'}, 'paralisado')
          and not appmod.effects.contact_status_blocked({'types': ['Normal']}, 'paralisado'))
    # dreno POW≤50 (Mega Drain) tem recarga de sustain → NÃO serve de filler
    check(S, 'filler de moveset ignora drenos (Mega Drain tem recarga)',
          not appmod._move_sem_recarga('Mega Drain')
          and appmod._move_sem_recarga('Ember')
          and 'Ember' in appmod._ensure_filler_move(['Mega Drain', 'Giga Drain'],
                                                    ['Mega Drain', 'Ember', 'Giga Drain']))
    check(S, 'v3_decayed_heal: 50 → 25 → 12 (fonte única motor+gates)',
          bmm.v3_decayed_heal(50, 0) == 50 and bmm.v3_decayed_heal(50, 1) == 25
          and bmm.v3_decayed_heal(50, 2) == 12)
    check(S, 'batch traz drain canônico (recarga real no tooltip)',
          (p1.post('/api/moves/batch', json={'moves': ['Mega Drain']})
           .get_json() or {}).get('Mega Drain', {}).get('drain') == 50)
    _et = appmod.effects.auto_detect_move_effect({'name': 'Electric Terrain',
                                                  'category': 'status'})
    check(S, 'Electric Terrain é TERRENO (chave duplicada removida)',
          (_et or {}).get('type') == 'terrain' and (_et or {}).get('terrain') == 'electric')
    check(S, 'Infestation/Magma Storm prendem (auditoria de efeitos)',
          appmod.effects.check_status_on_hit('Infestation', 50, 10)[0] == 'trapped'
          and appmod.effects.check_status_on_hit('Magma Storm', 50, 10)[0] == 'trapped')

    # ── Habilidades passivas (expansão): 100% conhecidas + mecânicas ──
    _names = set()
    for _p in appmod.POKEMON_DB:
        for _a in (_p.get('abilities') or []):
            _names.add(_a['name'] if isinstance(_a, dict) else _a)
        for _k in ('ability', 'hiddenAbility'):
            _av = _p.get(_k)
            if isinstance(_av, dict) and _av.get('name'):
                _names.add(_av['name'])
    _unknown = [n for n in _names if n and not ab.is_known_ability(n)]
    check(S, 'TODAS as habilidades das espécies são conhecidas (0 sem descrição)',
          len(_unknown) == 0, str(_unknown[:8]))
    # stat-mult via effective_stat (Huge Power dobra ATK)
    check(S, 'Huge Power dobra o ATK efetivo',
          appmod.effects.effective_stat({'ability': 'Huge Power', 'stats': {'ATK': 100}, 'stat_stages': {}}, 'ATK') == 200)
    check(S, 'Fur Coat dobra a DEF efetiva',
          appmod.effects.effective_stat({'ability': 'Fur Coat', 'stats': {'DEF': 80}, 'stat_stages': {}}, 'DEF') == 160)
    # damage-mult no cálculo real (Iron Fist em soco) — estatístico (v3 tem
    # variância de dados + faixas de Resistência)
    import statistics as _stif
    _di_l, _dn_l = [], []
    for _ in range(300):
        _pi = make_poke('Hitmonchan', 40); _pi['ability'] = 'Iron Fist'
        _di_l.append(appmod._calc_pvp_attack(_pi, make_poke('Snorlax', 40), 'Fire Punch', 20)['damage'])
        _dn_l.append(appmod._calc_pvp_attack(make_poke('Hitmonchan', 40), make_poke('Snorlax', 40), 'Fire Punch', 20)['damage'])
    check(S, 'Iron Fist aumenta o dano médio de socos',
          _stif.mean(_di_l) > _stif.mean(_dn_l),
          f"{_stif.mean(_di_l):.1f} vs {_stif.mean(_dn_l):.1f}")
    # imunidade de status (Limber ignora paralisia; Water Veil ignora queimadura)
    check(S, 'Limber é imune a paralisia',
          ab.is_status_immune({'ability': 'Limber'}, 'paralisado') and
          not ab.is_status_immune({'ability': 'Limber'}, 'queimado'))
    _sk, _inf = appmod.effects.check_status_on_hit('Thunder Wave', 15, 5, defender={'ability': 'Limber'})
    check(S, 'on-hit respeita imunidade (Thunder Wave em Limber)', _inf is False)
    # crítico bloqueado por Shell Armor
    _pa = make_poke('Machamp', 40); _def = make_poke('Cloyster', 40); _def['ability'] = 'Shell Armor'
    _cc = appmod._calc_pvp_attack(_pa, _def, 'Karate Chop', 20)  # nat 20 seria crit
    check(S, 'Shell Armor bloqueia crítico (nat 20 não crita)', _cc.get('is_crit') is False)
    check(S, 'API /api/abilities lista descrições',
          len((p1.get('/api/abilities').get_json() or {}).get('descriptions', {})) > 100)

    # ══════════ 7. PVP JOGADOR vs JOGADOR ══════════
    section('7. PvP jogador vs jogador')
    S = 'PvP P2P'
    s1.emit('pvp_join_arena', {})
    arena = recv(s1, 'pvp_arena_players')
    lst = arena[0]['args'][0] if arena else []
    check(S, 'arena lista jogadores da mesa', any(x['id'] == u2 for x in lst))
    s1.emit('pvp_challenge', {'target_id': u2, 'mode': 'street'})
    recv(s1)
    got = recv(s2, 'pvp_challenge_received')
    check(S, 'desafio chega ao alvo', bool(got))
    s2.emit('pvp_accept', {'challenger_id': u1, 'mode': 'street'})
    created2 = recv(s2, 'pvp_battle_created')
    created1 = recv(s1, 'pvp_battle_created')
    check(S, 'batalha criada p/ ambos', bool(created1) and bool(created2))
    battle = None
    if created1:
        bid = created1[0]['args'][0]['battle_id']
        s1.emit('pvp_select_pokemon', {'battle_id': bid, 'pokemon_idx': 0}); recv(s1)
        s2.emit('pvp_select_pokemon', {'battle_id': bid, 'pokemon_idx': 0})
        recv(s2); recv(s1)
        battle = appmod.ACTIVE_PVP.get(bid)
        check(S, 'seleção às cegas inicia batalha', battle and battle['phase'] == 'battle')
    if battle:
        # bug reportado: time SEM currentHp deve poder trocar
        atk_key = battle['turn']
        for pk in battle[atk_key]['team']:
            pk.pop('currentHp', None)
        atk_sio = s1 if battle[atk_key]['id'] == u1 else s2
        atk_sio.emit('pvp_switch', {'battle_id': bid, 'pokemon_idx': 1})
        recv(s1); recv(s2)
        check(S, 'troca voluntária funciona mesmo sem currentHp (bug reportado)',
              battle[atk_key]['active_idx'] == 1, f"active_idx={battle[atk_key]['active_idx']}")
        def_key = battle['turn']  # após a troca o turno passou
        other_key = 'player2' if def_key == 'player1' else 'player1'
        # troca fora do turno recusada
        off_sio = s1 if battle[other_key]['id'] == u1 else s2
        before = battle[other_key]['active_idx']
        off_sio.emit('pvp_switch', {'battle_id': bid, 'pokemon_idx': 0})
        errs = recv(off_sio, 'pvp_error')
        check(S, 'troca fora do turno é recusada',
              battle[other_key]['active_idx'] == before and bool(errs),
              f"idx {before}→{battle[other_key]['active_idx']}, errs={len(errs)}")
        for _ in range(400):
            if battle['phase'] != 'battle':
                break
            # troca forçada: qualquer lado com ativo desmaiado troca primeiro
            forced_done = False
            for k in ('player1', 'player2'):
                sd = battle[k]
                if pvp_hp(sd['team'][sd['active_idx']]) <= 0:
                    alive = [i for i, q in enumerate(sd['team']) if pvp_hp(q) > 0]
                    if not alive:
                        forced_done = True
                        break
                    ss = s1 if sd['id'] == u1 else s2
                    ss.emit('pvp_switch', {'battle_id': bid, 'pokemon_idx': alive[0]})
                    recv(s1); recv(s2)
                    forced_done = True
            if forced_done:
                continue
            tk = battle['turn']
            tsio = s1 if battle[tk]['id'] == u1 else s2
            poke = battle[tk]['team'][battle[tk]['active_idx']]
            # v3: escolhe um golpe de DANO fora de cooldown (senão o handler
            # recusa sem consumir o turno e o loop travaria)
            _mv = dmg_move(poke)
            if appmod._v3_cooldown_left(poke, _mv) > 0:
                _avail = [mv for mv in (poke.get('moves') or [])
                          if appmod._v3_cooldown_left(poke, mv) <= 0]
                _mv = (_avail or ['Tackle'])[0]
            tsio.emit('pvp_attack', {'battle_id': bid, 'move_name': _mv})
            recv(s1); recv(s2)
        check(S, 'batalha P2P termina com vencedor',
              battle['phase'] == 'finished' and battle.get('winner'), f"fase={battle['phase']}")

    # ══════════ 8. PVP vs NPC ══════════
    section('8. PvP vs NPC (desafio direto + trocas)')
    S = 'PvP vs NPC'
    give_team(u1, [('Charmander', 20), ('Squirtle', 18), ('Pidgey', 15)])
    r = m.post('/master/npcs/generate', json={'npc_class': 'Trainer', 'level': 15, 'team_size': 2})
    npc = r.get_json()
    check(S, 'NPC gerado com time/stats/moves',
          all(q.get('moves') and q.get('stats', {}).get('ATK') for q in npc['team']))
    # Determinístico: NPC só com move de dano (espécie sorteada pode vir com
    # apenas Harden/Recover — DEF ×4 + dano mínimo = batalha interminável)
    for q in npc['team']:
        q['moves'] = ['Tackle']
    db.save_npc(npc, TID)
    s1.emit('pvp_join_arena', {})
    lst = recv(s1, 'pvp_arena_players')[0]['args'][0]
    check(S, 'NPC aparece na arena p/ desafio', any(x.get('is_npc') and x['id'] == npc['id'] for x in lst))
    s1.emit('pvp_challenge', {'target_id': npc['id'], 'mode': 'street'})
    created = recv(s1, 'pvp_battle_created')
    check(S, 'desafio a NPC cria batalha na hora', bool(created))
    if created:
        bid = created[0]['args'][0]['battle_id']
        s1.emit('pvp_select_pokemon', {'battle_id': bid, 'pokemon_idx': 0}); recv(s1)
        battle = appmod.ACTIVE_PVP.get(bid)
        check(S, 'NPC auto-seleciona e batalha inicia', battle and battle['phase'] == 'battle')
        if battle:
            switched = False
            for _ in range(10):
                if battle['phase'] != 'battle':
                    break
                if battle['turn'] == 'player1':
                    target_idx = 1 if battle['player1']['active_idx'] != 1 else 2
                    s1.emit('pvp_switch', {'battle_id': bid, 'pokemon_idx': target_idx})
                    recv(s1)
                    if battle['player1']['active_idx'] == target_idx:
                        switched = True
                        break
                else:
                    appmod.handle_npc_turn(battle, 'player2')
            check(S, 'jogador consegue TROCAR pokémon vs NPC (bug reportado)', switched)
            # pós-rebalance (batalhas 8-15 turnos), o 3v3 leva bem mais ações
            for _ in range(900):
                if battle['phase'] != 'battle':
                    break
                p1side = battle['player1']
                if pvp_hp(p1side['team'][p1side['active_idx']]) <= 0:
                    alive = [i for i, q in enumerate(p1side['team']) if pvp_hp(q) > 0]
                    if not alive:
                        break
                    s1.emit('pvp_switch', {'battle_id': bid, 'pokemon_idx': alive[0]})
                    recv(s1)
                    continue
                if battle['turn'] == 'player1':
                    poke = p1side['team'][p1side['active_idx']]
                    s1.emit('pvp_attack', {'battle_id': bid,
                                           'move_name': dmg_move(poke),
                                           'attack_roll': random.randint(1, 20)})
                    recv(s1)
                else:
                    appmod.handle_npc_turn(battle, 'player2')
            check(S, 'batalha vs NPC termina', battle['phase'] == 'finished', f"fase={battle['phase']}")

    # ══════════ 8b. MOVES DE STATUS + TROCA FORÇADA (bugs reportados) ══════════
    section('8b. Status moves sem dano + troca forçada vs NPC')
    S = 'Status/Troca vs NPC'

    # Auditoria de dados canônicos
    mv = appmod.MOVES_DB
    check(S, 'nenhum status com baseDamage',
          not [k for k, v in mv.items() if v.get('category') == 'status' and v.get('baseDamage')])
    check(S, 'Nightmare virou status', mv.get('Nightmare', {}).get('category') == 'status')
    check(S, 'Accelerock é physical com dado',
          mv.get('Accelerock', {}).get('category') == 'physical' and mv.get('Accelerock', {}).get('baseDamage'))
    dmg_moves = [k for k, v in mv.items() if v.get('category') in ('physical', 'special')]
    import re as _re8b
    no_dice = [k for k in dmg_moves if not _re8b.match(r'\d+d\d+', str(mv[k].get('baseDamage', '')))]
    check(S, 'todo move de dano tem dado (exceto dano variável)', len(no_dice) <= 25, f'{len(no_dice)} sem dado')

    # _calc_pvp_attack nunca dá dano a um move de status
    poke_a = {'level': 20, 'stats': {'ATK': 16}, 'types': ['Normal']}
    poke_d = {'level': 18, 'stats': {'DEF': 12}}
    calc_growl = appmod._calc_pvp_attack(poke_a, poke_d, 'Growl')
    check(S, 'Growl = 0 dano no calc', calc_growl['damage'] == 0 and calc_growl.get('is_status'))
    # attack_roll fixo: sem ele o d20 do servidor pode tirar nat 1 (~5% flake)
    calc_hit = appmod._calc_pvp_attack(dict(poke_a, level=30, stats={'ATK': 30}),
                                       dict(poke_d, stats={'DEF': 8}), 'Tackle', 15)
    check(S, 'move de dano ainda dá dano', calc_hit['damage'] > 0)

    # v2: acerto é FIXO por move (d20 vs Accuracy) — não existe mais CA
    import battle_math as bmm
    check(S, 'accuracy 100 erra só no nat 1',
          bmm.roll_hits(2, 100) and not bmm.roll_hits(1, 100))
    check(S, 'accuracy 80 erra com d20 ≤ 4',
          not bmm.roll_hits(4, 80) and bmm.roll_hits(5, 80))
    check(S, 'move que não erra (Swift) acerta até no nat 1',
          bmm.roll_hits(1, None))
    check(S, 'nat 20 sempre acerta (mesmo Fissure 30%)', bmm.roll_hits(20, 30))
    check(S, 'limiar: 90→2, 70→6, 55→9, 30→14',
          [bmm.miss_threshold(a) for a in (90, 70, 55, 30)] == [2, 6, 9, 14])

    # Batalha PvP vs NPC nova para os testes de status/troca
    give_team(u1, [('Charmander', 20), ('Squirtle', 18)])
    users = db.get_users()
    users[u1]['trainer_data']['team'][0]['moves'] = ['Growl', 'Ember']
    db.save_users(users)
    r = m.post('/master/npcs/generate', json={'npc_class': 'Trainer', 'level': 14, 'team_size': 1})
    npc2 = r.get_json()
    s1.get_received(); msio.get_received()
    s1.emit('pvp_challenge', {'target_id': npc2['id'], 'mode': 'street'})
    c2 = recv(s1, 'pvp_battle_created')
    if c2:
        bid2 = c2[0]['args'][0]['battle_id']
        s1.emit('pvp_select_pokemon', {'battle_id': bid2, 'pokemon_idx': 0}); s1.get_received()
        b2 = appmod.ACTIVE_PVP.get(bid2)
        if b2 and b2['phase'] == 'battle':
            # força turno do jogador e Charmander (com Growl) ativo
            b2['turn'] = 'player1'; b2['player1']['active_idx'] = 0
            opp = b2['player2']['team'][b2['player2']['active_idx']]
            opp['currentHp'] = opp.get('maxHp', 30)
            hp_before = opp['currentHp']
            s1.get_received()
            s1.emit('pvp_attack', {'battle_id': bid2, 'move_name': 'Growl'})
            s1.get_received()
            opp2 = b2['player2']['team'][b2['player2']['active_idx']]
            check(S, 'Growl não causou dano ao NPC (bug reportado)',
                  pvp_hp(opp2) >= hp_before, f'{hp_before}→{pvp_hp(opp2)}')
            check(S, 'log registra status_move',
                  any(l.get('type') == 'status_move' for l in b2.get('log', [])))

            # troca forçada: ativo do jogador desmaiado quando chega o turno do NPC.
            # Era aqui que o NPC retornava em silêncio (stall) e o cliente não
            # recebia o aviso de troca (botão sumia). Deterministico: HP = 0.
            b2['turn'] = 'player2'
            b2['player1']['team'][b2['player1']['active_idx']]['currentHp'] = 0
            s1.get_received()
            appmod.handle_npc_turn(b2, 'player2')
            got_switch = recv(s1, 'pvp_must_switch')
            check(S, 'NPC não trava com defensor desmaiado; avisa troca (bug reportado)',
                  bool(got_switch))
            st = appmod.pvp.get_battle_state_for_player(b2, 'player1')
            check(S, 'state.must_switch = True', st.get('must_switch') is True)
            # troca forçada fora do turno funciona
            alive_idx = next((i for i, q in enumerate(b2['player1']['team'])
                              if i != b2['player1']['active_idx'] and pvp_hp(q) > 0), None)
            if alive_idx is not None:
                s1.emit('pvp_switch', {'battle_id': bid2, 'pokemon_idx': alive_idx}); s1.get_received()
                check(S, 'troca forçada off-turn funciona', b2['player1']['active_idx'] == alive_idx)
            # master force com defensor desmaiado re-emite must_switch (não trava)
            b2['turn'] = 'player2'
            b2['player1']['team'][b2['player1']['active_idx']]['currentHp'] = 0
            s1.get_received()
            msio.emit('master_force_npc_action', {'battle_id': bid2, 'player_key': 'player2'})
            check(S, 'master force não trava (re-emite must_switch)',
                  bool(recv(s1, 'pvp_must_switch')))

    # Grupo: status move não causa dano
    give_team(u1, [('Charmander', 20)]); give_team(u2, [('Squirtle', 20)])
    users = db.get_users()
    users[u1]['trainer_data']['team'][0]['moves'] = ['Growl', 'Ember']
    db.save_users(users)
    for c in (s1, s2, msio):
        c.get_received()
    r = m.post('/master/group-hunt', json={'player_ids': [u1, u2], 'wild_count': 1,
                                           'hunt_mode': 'normal', 'route_id': 'route1'})
    gb2 = (r.get_json() or {}).get('battle')
    if gb2 and gb2['id'] in appmod.ACTIVE_GROUP_BATTLES:
        gbattle = appmod.ACTIVE_GROUP_BATTLES[gb2['id']]
        # acha um aliado do u1 no turno e um selvagem vivo
        wild = next((c for c in gbattle['combatants'].values() if c['side'] == 'wild'), None)
        ally = next((c for c in gbattle['combatants'].values()
                     if c['side'] == 'ally' and str(c['player_id']) == u1), None)
        if wild and ally:
            gbattle['turn_idx'] = gbattle['order'].index(ally['cid'])
            wild_hp_before = wild['hp']
            s1.emit('group_battle_action', {'battle_id': gb2['id'],
                                            'move_name': 'Growl', 'target_cid': wild['cid']})
            s1.get_received()
            check(S, 'grupo: Growl não dana o selvagem', wild['hp'] >= wild_hp_before)

    # Motor de efeitos data-driven cobre status canônicos e on-hit
    check(S, 'auto_detect cobre status canônico (Sand Attack)',
          appmod.effects.auto_detect_move_effect({'name': 'Sand Attack', 'description': ''}) is not None)
    scald_hit = appmod.effects.MOVE_EFFECTS_DATA.get('scald', {}).get('on_hit', {})
    check(S, 'Scald mapeia queimado on-hit (dados canônicos)',
          scald_hit.get('status') == 'queimado')

    # ── Stat stages v2: MULTIPLICATIVOS (regra oficial ±6) ──
    fx = appmod.effects
    import battle_math as bmm
    import statistics as _st
    att = {'level': 20, 'stats': {'ATK': 40}, 'types': ['Normal']}
    dfn = {'level': 18, 'stats': {'DEF': 40, 'SPD': 40, 'SPE': 40}}
    fx.apply_stat_changes(dfn, {'DEF': -2}); fx.apply_stat_changes(dfn, {'DEF': -2})
    check(S, 'DEF-2 empilha (stage -4)', dfn['stat_stages']['DEF'] == -4)
    check(S, 'stage -4 = DEF efetiva ×1/3', fx.effective_stat(dfn, 'DEF') == max(1, int(40 * 2 / 6)))
    d_clean = _st.mean(appmod._calc_pvp_attack(att, {'level': 18, 'stats': {'DEF': 40}}, 'Tackle', 15)['damage'] for _ in range(200))
    d_deb = _st.mean(appmod._calc_pvp_attack(att, dfn, 'Tackle', 15)['damage'] for _ in range(200))
    check(S, 'DEF-down AUMENTA o dano recebido (v2)', d_deb > d_clean, f'{d_clean:.1f}→{d_deb:.1f}')
    for _ in range(3):
        fx.apply_stat_changes(dfn, {'DEF': -4})
    check(S, 'stage limita em -6', dfn['stat_stages']['DEF'] == -6)
    # ATK+2 dobra o stat efetivo (×2 oficial)
    ab_ = {'stats': {'ATK': 40}}
    fx.apply_stat_changes(ab_, {'ATK': 2})
    check(S, 'ATK+2 = stat efetivo ×2', fx.effective_stat(ab_, 'ATK') == 80)
    # attack_roll stage desloca o d20 no acerto
    check(S, 'attack_roll -3 transforma acerto em erro (Acc 80, d20 7)',
          bmm.roll_hits(7, 80, 0, 0) and not bmm.roll_hits(7, 80, -3, 0))
    check(S, 'evasão +3 do alvo também', not bmm.roll_hits(7, 80, 0, 3))
    # v3: queimadura corta o COMPONENTE físico pela metade — visível com um
    # atacante de ATK alto (componente domina o bruto)
    _big = {'level': 40, 'stats': {'ATK': 400, 'SPE': 50}, 'types': []}
    _tgt = {'level': 40, 'stats': {'DEF': 40, 'SPE': 40}}
    d_hot = _st.mean(appmod._calc_pvp_attack(dict(_big), _tgt, 'Tackle')['damage'] for _ in range(300))
    d_burn = _st.mean(appmod._calc_pvp_attack(
        dict(_big, status={'condition': 'queimado'}), _tgt, 'Tackle')['damage'] for _ in range(300))
    check(S, 'v3: queimado corta o Componente físico (dano cai forte)',
          d_burn < d_hot * 0.75, f'{d_hot:.1f}→{d_burn:.1f}')
    # paralisia corta SPE efetiva pela metade
    para = {'stats': {'SPE': 60}, 'status': {'condition': 'paralisado'}}
    check(S, 'paralisado: SPE efetiva ×0.5', fx.effective_stat(para, 'SPE') == 30)

    # restaura o time do u1 para as seções seguintes (PC etc.)
    give_team(u1, [('Charmander', 20), ('Squirtle', 18), ('Pidgey', 15)])

    # ══════════ 9. NPCs & PROGRESSÃO ══════════
    section('9. NPCs: CRUD e progressão diária')
    S = 'NPCs'
    r = m.post('/master/npcs', json={'name': 'Rival Rev', 'npc_class': 'Rival', 'level': 10,
                                     'team': [], 'growth_rate': 'fast', 'progression_enabled': True})
    nid = (r.get_json() or {}).get('id')
    check(S, 'criar NPC manual', bool(nid))
    r = m.put(f'/master/npcs/{nid}', json={'name': 'Rival Editado', 'growth_rate': 'slow'})
    check(S, 'editar NPC (incl. ritmo)', (r.get_json() or {}).get('name') == 'Rival Editado')
    m.put(f"/master/npcs/{npc['id']}", json={'progression_enabled': True, 'growth_rate': 'fast'})
    npc_before = next(n for n in db.get_npcs(TID) if n['id'] == npc['id'])
    lv_before = [q['level'] for q in npc_before['team']]
    m.post('/master/calendar/advance', json={'days': 10})
    npc_after = next(n for n in db.get_npcs(TID) if n['id'] == npc['id'])
    check(S, 'NPC progride com os dias (diário)', len(npc_after.get('diary', [])) >= 9,
          f"{len(npc_after.get('diary', []))} entradas")
    check(S, 'níveis do NPC sobem', sum(q['level'] for q in npc_after['team']) > sum(lv_before),
          f"{lv_before} → {[q['level'] for q in npc_after['team']]}")
    r = m.delete(f'/master/npcs/{nid}')
    check(S, 'deletar NPC', not any(n['id'] == nid for n in db.get_npcs(TID)))

    # ══════════ 10. QUESTS ══════════
    section('10. Quests')
    S = 'Quests'
    r = m.post('/master/quests', json={'title': 'Quest Rev', 'city': 'Pallet', 'description': 'x',
                                       'category': 'main', 'xp_reward': 100, 'money_reward': 50,
                                       'objectives': [{'text': 'obj1', 'done': False}],
                                       'assigned_to': [u1]})
    q = r.get_json() or {}
    check(S, 'criar quest', 'id' in q)
    r = p1.post(f"/quests/{q.get('id')}/objectives/0/toggle", json={})
    check(S, 'jogador marca objetivo', r.status_code == 200)
    money_before = db.get_users()[u1]['trainer_data'].get('money', 0)
    r = m.post(f"/master/quests/{q.get('id')}/complete", json={'player_id': u1})
    check(S, 'completar quest', r.status_code == 200)
    money_after = db.get_users()[u1]['trainer_data'].get('money', 0)
    check(S, 'recompensa em dinheiro entregue', money_after == money_before + 50,
          f'{money_before}→{money_after}')
    r = m.delete(f"/master/quests/{q.get('id')}")
    check(S, 'deletar quest', r.status_code == 200)

    # ══════════ 11. LOJA ══════════
    section('11. Loja & economia')
    S = 'Loja'
    r = p1.get('/api/shop')
    shop = r.get_json()
    items = shop if isinstance(shop, list) else (shop or {}).get('items', [])
    check(S, 'catálogo carrega', bool(items))
    item0 = items[0] if items else {}
    money_before = db.get_users()[u1]['trainer_data'].get('money', 0)
    r = p1.post('/api/shop/buy', json={'item_id': item0.get('id'), 'item_name': item0.get('name'), 'qty': 1})
    d = r.get_json() or {}
    money_after = db.get_users()[u1]['trainer_data'].get('money', 0)
    check(S, 'compra debita dinheiro e adiciona item',
          d.get('success') and money_after < money_before, f'{d}')
    r = p1.post('/api/shop/sell', json={'item_name': item0.get('name'), 'qty': 1})
    d2 = r.get_json() or {}
    check(S, 'venda credita dinheiro', d2.get('success') and
          db.get_users()[u1]['trainer_data'].get('money', 0) > money_after, f'{d2}')
    r = p1.post('/api/shop/buy', json={'item_id': item0.get('id'), 'qty': 999999})
    check(S, 'compra sem dinheiro é recusada', not (r.get_json() or {}).get('success'))

    # ══════════ 12. PC ══════════
    section('12. PC — pokémon e itens')
    S = 'PC'
    team_len = len(db.get_users()[u1]['trainer_data']['team'])
    r = p1.post('/player/pc/deposit', json={'team_idx': team_len - 1})
    d = r.get_json() or {}
    check(S, 'depositar pokémon', d.get('ok') or d.get('success'), f'{list(d.keys())}')
    r = p1.get('/player/pc')
    box = r.get_json() or []
    check(S, 'listar PC', isinstance(box, list) and len(box) >= 1, f'{type(box).__name__}')
    r = p1.post('/player/pc/withdraw', json={'pc_idx': 0})
    d = r.get_json() or {}
    check(S, 'retirar pokémon', d.get('ok') or d.get('success'), f'{list(d.keys())}')
    # QA LOOP 4: índice não-int no PC não derruba a request com 500
    for _ep, _body in (('/player/pc/deposit', {'team_idx': 'x'}),
                       ('/player/pc/withdraw', {'pc_idx': 'x'}),
                       ('/player/pc/swap', {'team_idx': 'x', 'pc_idx': 0})):
        _r = p1.post(_ep, json=_body)
        check(S, f'{_ep} com índice string não crasha (nunca 500)',
              _r.status_code < 500, f'status {_r.status_code}')
    r = p1.post('/player/pc/items/deposit', json={'item_name': 'Potion', 'qty': 1})
    d = r.get_json() or {}
    check(S, 'depositar item', d.get('ok') or d.get('success'), f'{d}')
    r = p1.post('/player/pc/items/withdraw', json={'item_name': 'Potion', 'qty': 1})
    d = r.get_json() or {}
    check(S, 'retirar item', d.get('ok') or d.get('success'), f'{d}')

    # ══════════ 13. TRANSFERÊNCIAS ══════════
    section('13. Transferências entre jogadores')
    S = 'Transferências'
    m1_ = db.get_users()[u1]['trainer_data'].get('money', 0)
    m2_ = db.get_users()[u2]['trainer_data'].get('money', 0)
    r = p1.post('/player/transfer', json={'target_id': u2, 'money': 100, 'items': [], 'pokemon_idxs': []})
    d = r.get_json() or {}
    ok_money = (db.get_users()[u1]['trainer_data'].get('money', 0) == m1_ - 100 and
                db.get_users()[u2]['trainer_data'].get('money', 0) == m2_ + 100)
    check(S, 'transferir dinheiro', d.get('success') and ok_money, f'{d}')
    r = p1.post('/player/transfer', json={'target_id': u2, 'money': 10 ** 9, 'items': [], 'pokemon_idxs': []})
    check(S, 'transferência maior que saldo é recusada', not (r.get_json() or {}).get('success'))

    # ══════════ 14. TORNEIO ══════════
    section('14. Torneio')
    S = 'Torneio'
    r = m.post('/master/tournament', json={'name': 'Copa Rev', 'max_participants': 4,
                                           'prizes': {'first': {'money': 1000}}})
    d = r.get_json() or {}
    tid_t = d.get('id') or (d.get('tournament') or {}).get('id')
    check(S, 'criar torneio', bool(tid_t), f'{d}')
    if tid_t:
        ok_add = True
        for pid in (u1, u2):
            r = m.post(f'/master/tournament/{tid_t}/participants', json={'player_id': pid})
            ok_add &= r.status_code == 200
        r = m.post(f'/master/tournament/{tid_t}/participants', json={'type': 'npc', 'npc_id': npc['id']})
        ok_add &= r.status_code == 200
        check(S, 'adicionar jogadores e NPC', ok_add)
        r = m.post(f'/master/tournament/{tid_t}/start', json={})
        check(S, 'iniciar torneio', r.status_code == 200)
        r = m.get(f'/master/tournament/{tid_t}/bracket')
        bracket = (r.get_json() or {}).get('bracket', [])
        check(S, 'bracket disponível', bool(bracket))
        if bracket:
            match = next((mt for mt in bracket
                          if mt.get('player1') and mt.get('player2') and not mt.get('winner')), None)
            if match:
                wid = match['player1']['id']
                r = m.post(f"/master/tournament/{tid_t}/match/{match['id']}/result",
                           json={'winner_id': wid})
                check(S, 'definir vencedor de partida', r.status_code == 200)
            else:
                check(S, 'definir vencedor de partida', True, 'byes resolveram tudo')

    # ══════════ 15. GINÁSIOS & LIGA ══════════
    section('15. Ginásios & Liga')
    S = 'Ginásios/Liga'
    r = m.post('/api/gyms', json={'name': 'Ginásio Rev', 'badge_name': 'Insígnia Rocha',
                                  'type': 'Rock', 'leader_name': npc['name'],
                                  'leader_npc_id': npc['id']})
    gym = r.get_json() or {}
    gid = gym.get('id') or (gym.get('gym') or {}).get('id')
    check(S, 'criar ginásio', bool(gid), f'{gym}')
    r = p1.get('/api/gyms')
    check(S, 'listar ginásios', r.status_code == 200 and bool(r.get_json()))
    if gid:
        r = m.put(f'/api/gyms/{gid}', json={'name': 'Ginásio Rev 2'})
        check(S, 'editar ginásio', r.status_code == 200)
    r = m.post('/api/league/slots', json={'slots': [{'npc_id': npc['id'], 'role': 'elite1'}]})
    check(S, 'configurar slots da liga', r.status_code == 200)
    r = p1.get('/api/league')
    check(S, 'jogador vê a liga', r.status_code == 200)

    # ══════════ 16. MEGA / POKÉDEX / EXTRAS ══════════
    section('16. Mega, Pokédex e extras')
    S = 'Extras'
    r = p1.get('/api/mega/charizard')
    check(S, 'dados de mega evolução', r.status_code == 200 and bool(r.get_json()))
    r = p1.post('/player/pokedex/register', json={'pokemon_number': 150})
    d = r.get_json() or {}
    check(S, 'registrar na pokédex dá XP', d.get('success') and d.get('xp_gained') == 10, f'{d}')
    r = p1.post('/player/pokedex/register', json={'pokemon_number': 150})
    check(S, 'registro duplicado não repete XP', (r.get_json() or {}).get('already_registered'))
    for route in ('/api/natures', '/api/items', '/api/maps', '/api/players', '/api/status-effects'):
        r = p1.get(route)
        check(S, f'GET {route}', r.status_code == 200)
    r = p1.get('/api/pokemon?search=pikachu')
    check(S, 'busca de pokémon', any(x['name'] == 'Pikachu' for x in (r.get_json() or [])))
    r = m.get('/health')
    check(S, 'healthcheck', (r.get_json() or {}).get('status') == 'ok')

    section('17. Sistema v3 — cooldown/momentum/clima/casos especiais')
    S = 'Sistema v3'
    import battle_math as bm
    import status_effects as se

    def fresh(species, level, **kw):
        p = make_poke(species, level, **kw)
        p.pop('_v3', None)
        return p

    # Cooldown: POW 110 (Fire Blast, degrau 96-110) → 2 rodadas; 2º uso
    # imediato é bloqueado sem gastar o turno
    char = fresh('Charizard', 50)
    blast = fresh('Blastoise', 50)
    r1 = appmod._calc_attack_core(char, blast, 'Fire Blast', attack_roll=10, field={})
    check(S, 'Fire Blast (POW 110) entra em cooldown 2', r1.get('cooldown') == 2
          and appmod._v3_cooldown_left(char, 'Fire Blast') == 2, f"{r1.get('cooldown')}")
    r2 = appmod._calc_attack_core(char, blast, 'Fire Blast', attack_roll=10, field={})
    check(S, 'golpe em cooldown é bloqueado sem gastar turno',
          r2.get('blocked') and r2.get('cooldown_left') == 2)
    appmod._calc_attack_core(char, blast, 'Ember', attack_roll=10, field={})
    check(S, 'cooldown decrementa por ação própria',
          appmod._v3_cooldown_left(char, 'Fire Blast') == 1,
          f"{appmod._v3_cooldown_left(char, 'Fire Blast')}")

    # Momentum: variar +1 (máx 3); repetir zera
    # (rotação termina em Ember, POW 40 sem recarga, para o repeat não ser
    # bloqueado pela recarga dos POW ≥ 70)
    c2, b2 = fresh('Charizard', 50), fresh('Blastoise', 50)
    for mv in ('Wing Attack', 'Slash', 'Ember', 'Wing Attack', 'Slash', 'Ember'):
        appmod._calc_attack_core(c2, b2, mv, attack_roll=10, field={})
    check(S, 'momentum acumula variando (máx 3)', c2['_v3']['momentum'] == 3,
          f"{c2['_v3']['momentum']}")
    appmod._calc_attack_core(c2, b2, 'Ember', attack_roll=10, field={})
    check(S, 'repetir o golpe zera o momentum', c2['_v3']['momentum'] == 0)

    # Adaptação: 3ª repetição consecutiva → defensor +2 na Resistência
    c3, b3 = fresh('Charizard', 50), fresh('Blastoise', 50)
    appmod._calc_attack_core(c3, b3, 'Ember', attack_roll=10, field={})
    appmod._calc_attack_core(c3, b3, 'Ember', attack_roll=10, field={})
    r3 = appmod._calc_attack_core(c3, b3, 'Ember', attack_roll=10, field={})
    check(S, 'adaptação na 3ª repetição (+10 na Resistência d100)',
          'adaptação +10' in (r3.get('log') or ''), (r3.get('log') or '')[:90])

    # Clima: Sol → Thunder ACC 50; Chuva → Surf +1 dado; Névoa −10
    c4, b4 = fresh('Charizard', 50), fresh('Blastoise', 50)
    r4 = appmod._calc_attack_core(c4, b4, 'Thunder', attack_roll=51,
                                  field={'weather': 'sun'})
    check(S, 'Thunder no Sol tem ACC 50 (erra com 51)', not r4.get('hit'))
    b5 = fresh('Blastoise', 50)
    r5 = appmod._calc_attack_core(b5, fresh('Charizard', 50), 'Surf',
                                  attack_roll=95, field={'weather': 'rain'})
    check(S, 'Surf na chuva ganha +1 dado', 'clima +1d' in (r5.get('log') or ''))
    check(S, 'ACC de clima: Névoa −10',
          bm.v3_weather_acc('fog', 'Ember', 100) == 90)

    # Chip de clima: areia fere Charizard, poupa Pedra/Terra/Aço
    chip, _ = appmod._field_chip({'field': {'weather': 'sandstorm', 'terrain': None}},
                                 c4, 120, 'X')
    chip_onix, _ = appmod._field_chip({'field': {'weather': 'sandstorm', 'terrain': None}},
                                      fresh('Onix', 30), 120, 'X')
    check(S, 'chip de areia: ⌊120/16⌋=7 e Onix imune', chip == -7 and chip_onix == 0,
          f'{chip}/{chip_onix}')

    # Terreno: Psychic bloqueia prioridade; Grassy amortece Earthquake
    c6 = fresh('Charizard', 50)
    c6['types'] = ['fire']   # sem flying: alvo no chão fica protegido
    r6 = appmod._calc_attack_core(fresh('Blastoise', 50), c6, 'Quick Attack',
                                  attack_roll=10, field={'terrain': 'psychic'})
    check(S, 'Psychic Terrain bloqueia golpe de prioridade',
          'Psychic Terrain' in (r6.get('log') or ''))
    check(S, 'Grassy Terrain amortece Earthquake',
          bm.v3_terrain_dice_delta('grassy', 'ground', 'earthquake') == -1)

    # Protect: bloqueia e a corrente decai 100→50
    b7 = fresh('Blastoise', 50)
    st7 = appmod._v3_side_state(b7)
    sres = se.process_status_move({'name': 'Protect', 'category': 'status'},
                                  dict(b7['stats'], level=50, maxHp=120,
                                       currentHp=120, _v3=st7),
                                  dict(c4['stats'], level=50, currentHp=120))
    check(S, 'Protect ativa a proteção', sres['effect_type'] == 'protect'
          and st7.get('protected') is True)
    r7 = appmod._calc_attack_core(fresh('Charizard', 50), b7, 'Ember',
                                  attack_roll=10, field={})
    check(S, 'golpe é bloqueado pelo Protect (consome a proteção)',
          r7.get('protected') and st7.get('protected') is False)
    check(S, 'corrente do Protect decai 100→50→25',
          bm.v3_protect_chance(0) == 100 and bm.v3_protect_chance(1) == 50
          and bm.v3_protect_chance(2) == 25)

    # Multi-hit: Double Kick = 2 hits, 1 Resistência
    r8 = appmod._calc_attack_core(fresh('Blastoise', 50), fresh('Snorlax', 50),
                                  'Double Kick', attack_roll=10, field={})
    check(S, 'Double Kick rola 2 hits', '2 hits' in (r8.get('log') or ''),
          (r8.get('log') or '')[:80])

    # Recoil e dreno derivados do dano final
    ok_rec = ok_drn = False
    for _ in range(20):
        rr = appmod._calc_attack_core(fresh('Blastoise', 50), fresh('Snorlax', 50),
                                      'Take Down', attack_roll=10, field={})
        if rr.get('damage', 0) > 0:
            ok_rec = rr.get('recoil') == max(1, rr['damage'] // 3)
            break
    for _ in range(20):
        rd = appmod._calc_attack_core(fresh('Venusaur', 50), fresh('Blastoise', 50),
                                      'Giga Drain', attack_roll=10, field={})
        if rd.get('damage', 0) > 0:
            ok_drn = rd.get('drain_heal') == max(1, rd['damage'] // 2)
            break
    check(S, 'recoil = ⌊dano/3⌋ (Take Down)', ok_rec)
    check(S, 'dreno = ⌊dano/2⌋ (Giga Drain)', ok_drn)

    # Carga: Solar Beam carrega 1 rodada; no Sol dispara direto
    v9 = fresh('Venusaur', 50)
    r9 = appmod._calc_attack_core(v9, fresh('Blastoise', 50), 'Solar Beam',
                                  attack_roll=10, field={})
    r9b = appmod._calc_attack_core(v9, fresh('Blastoise', 50), 'Solar Beam',
                                   attack_roll=10, field={})
    check(S, 'Solar Beam: carrega e dispara na 2ª rodada',
          r9.get('charging') and not r9b.get('charging') and r9b.get('hit') is not None)
    v9c = fresh('Venusaur', 50)
    r9c = appmod._calc_attack_core(v9c, fresh('Blastoise', 50), 'Solar Beam',
                                   attack_roll=10, field={'weather': 'sun'})
    check(S, 'Solar Beam no Sol dispara direto', not r9c.get('charging'))

    # OHKO: ACC 30 + Resistência d100 vs TN 110 (nunca vira certeza)
    ko = resisted = 0
    for _ in range(200):
        ro = se.process_status_move({'name': 'Fissure', 'category': 'status'},
                                    dict(c4['stats'], level=50, currentHp=120),
                                    dict(fresh('Blastoise', 50)['stats'],
                                         level=50, currentHp=120))
        if ro.get('effect_type') == 'fixed_damage':
            ko += 1
        elif 'RESISTE' in (ro.get('message') or ''):
            resisted += 1
    check(S, 'OHKO: raro e resistível (ACC30 × Resistência d100/TN110)',
          0 < ko < 70 and resisted > 0, f'ko={ko} resist={resisted}')

    # Campo expira quando a duração zera
    fbox = {'field': {'weather': 'rain', 'weather_left': 1,
                      'terrain': None, 'terrain_left': 0}}
    msgs = appmod._field_tick(fbox)
    check(S, 'clima expira (tick zera e avisa)',
          fbox['field']['weather'] is None and bool(msgs))

    # Rain Dance / Grassy Terrain → effect_type 'field'
    rw = se.process_status_move({'name': 'Rain Dance', 'category': 'status'},
                                dict(c4['stats'], level=50, maxHp=120, currentHp=120),
                                dict(b4['stats'], level=50, currentHp=120))
    rt = se.process_status_move({'name': 'Grassy Terrain', 'category': 'status'},
                                dict(c4['stats'], level=50, maxHp=120, currentHp=120),
                                dict(b4['stats'], level=50, currentHp=120))
    check(S, 'Rain Dance/Grassy Terrain viram efeito de campo',
          rw.get('effect_type') == 'field' and rw.get('field_value') == 'rain'
          and rt.get('effect_type') == 'field' and rt.get('field_value') == 'grassy')

    # ── ACC 100 vs ACC ∞ (spec de precisão) ──
    # ACC 100 ainda sofre evasão: Double Team +2 → ACC efetivo 80
    b10 = fresh('Blastoise', 50)
    b10['stat_stages'] = {'AC': 2}
    r10 = appmod._calc_attack_core(fresh('Charizard', 50), b10, 'Flamethrower',
                                   attack_roll=85, field={})
    check(S, 'ACC 100 não é garantido (evasão +2 → erra com 85)', not r10.get('hit'))

    # Certeiro: componente CHEIO (sem os antigos 60%) e ×0,90 no dano final
    c10 = fresh('Charizard', 50)
    _comp_cheio = max(1, int(c10['stats']['ATK']) // bmm.V3_STATUS_DIVISOR)
    r10b = appmod._calc_attack_core(c10, fresh('Blastoise', 50), 'Aerial Ace',
                                    attack_roll=None, field={})
    check(S, 'certeiro usa componente cheio (⌊ATK/divisor⌋ sem redução)',
          f'comp {_comp_cheio}' in (r10b.get('log') or ''),
          (r10b.get('log') or '')[:70])
    ok_mult = all('×0,9' in (rr.get('log') or '') or rr.get('damage', 0) == 0
                  for rr in (appmod._calc_attack_core(fresh('Charizard', 50),
                                                      fresh('Blastoise', 50),
                                                      'Aerial Ace', field={})
                             for _ in range(15)))
    check(S, 'certeiro aplica ×0,90 no dano final', ok_mult)

    # Certeiro NÃO atravessa imunidade de tipo (Swift normal vs fantasma)
    gas = fresh('Gastly', 30)
    r11 = appmod._calc_attack_core(fresh('Charizard', 50), gas, 'Swift', field={})
    check(S, 'certeiro não atravessa imunidade (Swift vs fantasma)',
          r11.get('outcome') == 'immune' and r11.get('damage') == 0)
    check(S, 'imunidade é checada ANTES do d100',
          'd100' not in (r11.get('log') or ''))

    # Certeiro NÃO atravessa Protect
    b11 = fresh('Blastoise', 50)
    appmod._v3_side_state(b11)['protected'] = True
    r12 = appmod._calc_attack_core(fresh('Charizard', 50), b11, 'Aerial Ace', field={})
    check(S, 'certeiro não atravessa Protect', bool(r12.get('protected')))

    # Semi-invulnerabilidade: Fly deixa fora de alcance; Thunder fura; 2ª rodada ataca
    c12 = fresh('Charizard', 50)
    rf = appmod._calc_attack_core(c12, fresh('Blastoise', 50), 'Fly', field={})
    check(S, 'Fly: 1ª rodada prepara e fica invulnerável',
          rf.get('charging') and c12['_v3'].get('invulnerable') == 'no ar')
    rtk = appmod._calc_attack_core(fresh('Blastoise', 50), c12, 'Tackle',
                                   attack_roll=10, field={})
    check(S, 'alvo no ar não é alcançado (nem por ACC 100)',
          not rtk.get('hit') and 'não alcança' in (rtk.get('log') or ''))
    rth = appmod._calc_attack_core(fresh('Blastoise', 50), c12, 'Thunder',
                                   attack_roll=5, field={})
    check(S, 'Thunder fura a invulnerabilidade do Fly',
          int(rth.get('attack_roll') or 0) > 0)
    rf2 = appmod._calc_attack_core(c12, fresh('Blastoise', 50), 'Fly',
                                   attack_roll=10, field={})
    check(S, 'Fly: 2ª rodada ataca e sai da invulnerabilidade',
          not rf2.get('charging') and not c12['_v3'].get('invulnerable'))
    check(S, 'Earthquake fura quem usou Dig (tabela de exceções)',
          bm.v3_pierces_invuln('no subsolo', 'Earthquake')
          and not bm.v3_pierces_invuln('no ar', 'Tackle'))

    section('18. Presentes do Mestre & economia dos NPCs')
    S = 'Presentes/NPCs'

    # NPC gerado nasce com ₽3000 + itens básicos
    r = m.post('/master/npcs/generate', json={'npc_class': 'Trainer', 'level': 12,
                                              'team_size': 1})
    npc_e = r.get_json() or {}
    check(S, 'NPC gerado nasce com ₽3000', npc_e.get('money') == 3000)
    _bagnames = [b.get('name') for b in (npc_e.get('bag') or [])]
    check(S, 'NPC gerado tem itens básicos (Pokébola/Poção)',
          'Pokébola' in _bagnames and 'Poção' in _bagnames, f'{_bagnames}')

    # NPC ANTIGO (sem money/bag) é migrado ao listar
    old_npc = {'id': 'npcvelho1', 'name': 'Veterano', 'npc_class': 'Trainer',
               'level': 8, 'team': [], 'notes': '', 'diary': []}
    db.save_npc(old_npc, TID)
    r = m.get('/master/npcs')
    got = next((n for n in (r.get_json() or []) if n['id'] == 'npcvelho1'), {})
    check(S, 'NPC antigo ganha economia na migração',
          got.get('money') == 3000 and bool(got.get('bag')))

    # Espólio de rua sai do bolso REAL do NPC (antes ia/vinha do vazio)
    loot_money, loot_items = pvp.calculate_street_loot(got)
    check(S, 'loot de rua do NPC: 25% de ₽3000 = ₽750 + itens',
          loot_money == 750 and len(loot_items) >= 1, f'{loot_money}/{loot_items}')

    # 🎁 Mestre dá item do catálogo + dinheiro
    _money_antes = db.get_users()[u1]['trainer_data'].get('money', 0)
    r = m.post('/master/give-item', json={'player_id': u1, 'item_name': 'Poção',
                                          'qty': 3, 'money': 500,
                                          'note': 'recompensa da quest'})
    d = r.get_json() or {}
    t1 = db.get_users()[u1]['trainer_data']
    _pocao = next((b for b in t1.get('bag', []) if b.get('name') == 'Poção'), {})
    check(S, 'mestre dá 3x Poção + ₽500 (vai pra ficha)',
          d.get('ok') and _pocao.get('qty', 0) >= 3
          and t1.get('money') == _money_antes + 500)

    # 🎁 Item de HISTÓRIA (fora do catálogo) também entra na bolsa
    r = m.post('/master/give-item', json={'player_id': u1, 'item_name': 'Chave Antiga',
                                          'qty': 1, 'description': 'Abre a ruína.'})
    t1 = db.get_users()[u1]['trainer_data']
    check(S, 'item de história (nome livre) entra na bolsa',
          any(b.get('name') == 'Chave Antiga' for b in t1.get('bag', [])))
    # ...mas item de história NÃO é vendável na loja
    r = p1.post('/api/shop/sell', json={'item_name': 'Chave Antiga', 'qty': 1})
    check(S, 'item de história não é vendável', r.status_code == 400)

    # 🎁 Mestre dá um Pokémon específico (quest/campeonato)
    _team_antes = len(db.get_users()[u1]['trainer_data'].get('team', []))
    r = m.post('/master/give-pokemon', json={'player_id': u1, 'species': 'Eevee',
                                             'level': 18, 'shiny': True,
                                             'nickname': 'Presente'})
    d = r.get_json() or {}
    t1 = db.get_users()[u1]['trainer_data']
    dest = t1['team'] if _team_antes < 6 else t1.get('pc', [])
    given = next((p for p in dest if p.get('nickname') == 'Presente'), {})
    check(S, 'mestre dá Eevee shiny Nv.18 (time ou PC)',
          d.get('ok') and given.get('name') == 'Eevee'
          and given.get('level') == 18 and given.get('is_shiny') is True,
          f"{d.get('destination')}")
    check(S, 'Pokémon dado tem moves e stats escalados',
          bool(given.get('moves')) and (given.get('stats') or {}).get('ATK', 0) > 0)
    r = m.post('/master/give-pokemon', json={'player_id': u1, 'species': 'NãoExiste'})
    check(S, 'espécie inexistente é recusada (404)', r.status_code == 404)
    # jogador comum não pode usar os endpoints de presente
    r = p1.post('/master/give-item', json={'player_id': u1, 'money': 99999})
    check(S, 'jogador não pode se auto-presentear', r.status_code == 403)

    section('19. Captura com time cheio → PC + movesets dos selvagens')
    S = 'PC/Selvagens'

    # Captura exige encontro ATIVO com o selvagem enfraquecido (espécie/nível/
    # shiny vêm do encontro, não do payload). Semeia um encontro de Pidgey Nv12.
    def _seed_capture_encounter(number=16, level=12, shiny=False, wild_hp=5, wild_max=40):
        _gs = gstate()
        _gs.setdefault('active_encounters', {})[str(u1)] = {
            'player_id': str(u1),
            'pokemon': {'name': 'Pidgey', 'number': number, 'level': level},
            'level': level, 'is_shiny': shiny,
            'battle_state': {'wild_hp_current': wild_hp, 'wild_hp_max': wild_max},
        }
        db.save_game_state(_gs, TID)

    _seed_capture_encounter()
    _pc_antes = len(db.get_users()[u1]['trainer_data'].get('pc', []))
    r = p1.post('/player/pc/capture', json={'pokemon': {
        'name': 'Pidgey', 'number': 16, 'level': 12,
        'moves': ['Tackle', 'Gust'], 'currentHp': 5, 'is_shiny': False}})
    d = r.get_json() or {}
    t1 = db.get_users()[u1]['trainer_data']
    stored = (t1.get('pc') or [])[-1] if t1.get('pc') else {}
    check(S, 'captura com time cheio vai pro PC', d.get('ok')
          and len(t1.get('pc', [])) == _pc_antes + 1
          and stored.get('name') == 'Pidgey' and stored.get('level') == 12)
    check(S, 'stats do capturado são recalculados no servidor',
          (stored.get('stats') or {}).get('ATK', 0) > 0
          and stored.get('maxHp', 0) > 0
          and stored.get('currentHp') == 5)
    # SEGURANÇA: espécie/nível do PAYLOAD são ignorados — vale o ENCONTRO.
    # Forjar Mewtwo Nv100 no payload → captura o Pidgey Nv12 do encontro.
    _seed_capture_encounter()
    r = p1.post('/player/pc/capture', json={'pokemon': {
        'name': 'Mewtwo', 'number': 150, 'level': 100}})
    _forged = (db.get_users()[u1]['trainer_data'].get('pc') or [])[-1]
    check(S, 'captura ignora espécie/nível forjados (usa o encontro)',
          _forged.get('name') == 'Pidgey' and _forged.get('level') == 12)
    # sem encontro ativo → captura negada
    _gs = gstate(); _gs['active_encounters'].pop(str(u1), None); db.save_game_state(_gs, TID)
    r = p1.post('/player/pc/capture', json={'pokemon': {
        'name': 'Pidgey', 'number': 16, 'level': 12}})
    check(S, 'captura sem encontro ativo é negada', r.status_code == 400)
    # selvagem em HP cheio não pode ser capturado
    _seed_capture_encounter(wild_hp=40, wild_max=40)
    r = p1.post('/player/pc/capture', json={'pokemon': {'name': 'Pidgey', 'number': 16, 'level': 12}})
    check(S, 'captura de selvagem em HP cheio é negada', r.status_code == 400)
    _gs = gstate(); _gs['active_encounters'].pop(str(u1), None); db.save_game_state(_gs, TID)

    # Movesets dos selvagens: qualidade garantida + variedade + TMs no Nv≥25
    _enc_sets = []
    for _ in range(12):
        enc = appmod._build_random_encounter(
            next(iter(appmod.ROUTES_DATA.keys())), 'normal', 60)
        if enc:
            _enc_sets.append((enc['pokemon']['name'], tuple(enc['wild_moves'])))

    def _wm_power(m):
        return int(appmod.canon_move(m).get('power') or 0) or \
            int(appmod.bm_core.VARIABLE_POWER.get(m.lower(), 0))
    check(S, 'todo selvagem tem ao menos 1 golpe de dano',
          all(any(_wm_power(m) > 0 for m in mv) for _, mv in _enc_sets))
    check(S, 'selvagens de nível alto têm golpe FORTE (POW ≥ 60)',
          sum(1 for _, mv in _enc_sets
              if any(_wm_power(m) >= 60 for m in mv)) >= len(_enc_sets) * 0.7,
          f'{sum(1 for _, mv in _enc_sets if any(_wm_power(m) >= 60 for m in mv))}/{len(_enc_sets)}')
    # variedade: mesma espécie não repete SEMPRE o mesmo moveset
    from collections import Counter as _Counter
    _by_species = {}
    for nm, mv in _enc_sets:
        _by_species.setdefault(nm, set()).add(mv)
    _repeat_ok = (any(len(v) > 1 for v in _by_species.values())
                  or all(len([1 for n, _ in _enc_sets if n == k]) == 1
                         for k in _by_species))
    check(S, 'moveset varia entre encontros da mesma espécie', _repeat_ok)

    section('20. Auditoria de moves (tabela do tester): Leech Seed & cia')
    S = 'Moves canônicos'
    import status_effects as se_mod

    # Leech Seed vira condição 'seeded' (não é mais cura instantânea!)
    # ACC 90 → o d100 interno pode errar; re-rola até conectar (o teste é
    # sobre O QUE acontece ao acertar, não sobre a taxa de acerto).
    _venu = fresh('Venusaur', 50)
    _lax = fresh('Snorlax', 50)
    for _ in range(50):
        rs = se_mod.process_status_move({'name': 'Leech Seed', 'category': 'status'},
                                        dict(_venu['stats'], level=50, maxHp=120, currentHp=120),
                                        dict(_lax['stats'], level=50, currentHp=120))
        if rs.get('status_applied'):
            break
    check(S, 'Leech Seed aplica semente (sem cura instantânea)',
          rs.get('status_applied') == 'seeded' and not rs.get('heal'))
    check(S, 'tipo Grama é imune à semente',
          se_mod.type_blocks_status(['grass'], 'seeded')
          and not se_mod.type_blocks_status(['normal'], 'seeded'))

    # Rest (canon): cura total + o USUÁRIO adormece; Insomnia → falha
    _rest = se_mod.process_status_move({'name': 'Rest', 'category': 'status'},
                                       {'maxHp': 100, 'currentHp': 10, '_v3': {}}, {})
    check(S, 'Rest cura total e ADORMECE o usuário (self_status)',
          _rest.get('heal') == 100 and _rest.get('self_status') == 'dormindo'
          and 'ADORMECEU' in _rest.get('message', ''))
    _rest2 = se_mod.process_status_move({'name': 'Rest', 'category': 'status'},
                                        {'maxHp': 100, 'ability': 'Insomnia', '_v3': {}}, {})
    check(S, 'Rest FALHA com Insomnia (sem cura de graça)',
          _rest2.get('success') is False and not _rest2.get('heal'))
    # learnsets reportados pela mesa (10/07)
    _pw = appmod.POKEMON_BY_NAME['poliwag']
    check(S, 'Poliwag inicia com Water Gun e Hypnosis',
          {'Water Gun', 'Hypnosis'} <= set(_pw.get('startingMoves') or [])
          and 'Water Gun' not in (_pw.get('levelMoves') or {}).get('2', []))
    check(S, 'Machop oferece Low Kick nos iniciais',
          'Low Kick' in (appmod.POKEMON_BY_NAME['machop'].get('startingMoves') or []))

    # Trap (Wrap/Bind/...): condição trapped, ⌊HP/16⌋ por 4 turnos
    _sk, _ok = se_mod.check_status_on_hit('Wrap', 50, 10, defender=_lax)
    check(S, 'Wrap prende (trapped) ao acertar', _sk == 'trapped' and _ok)
    _st = {'condition': 'trapped', 'turns_active': 0}
    _removed, _i, _dmg = False, 0, 0
    for _i in range(5):
        _, _dmg, _, _rem = se_mod.process_turn_start(_st, 160)
        if _rem:
            _removed = True
            break
    check(S, 'trapped: ⌊160/16⌋=10 por turno e expira no 4º',
          _removed and _i + 1 == 4 and _dmg == 10, f'turno={_i+1} dmg={_dmg}')

    # Rampage: Outrage deixa o PRÓPRIO usuário confuso
    _drag = fresh('Dragonite', 50)
    for _ in range(10):
        ro = appmod._calc_attack_core(_drag, fresh('Snorlax', 50), 'Outrage',
                                      attack_roll=10, field={})
        if ro.get('damage', 0) > 0:
            break
    check(S, 'Outrage: usuário fica confuso após atacar',
          ro.get('self_status') == 'confuso')

    # Crash: High Jump Kick errado machuca o usuário (⌊HPmáx/8⌋ via recoil)
    rc = appmod._calc_attack_core(fresh('Hitmonlee', 50), fresh('Snorlax', 50),
                                  'High Jump Kick', attack_roll=99,
                                  atk_max_hp=120, field={})
    check(S, 'High Jump Kick: crash de 15 no erro',
          not rc.get('hit') and rc.get('recoil') == 15)

    # Explosion: o usuário desmaia
    re_ = appmod._calc_attack_core(fresh('Electrode', 50), fresh('Snorlax', 50),
                                   'Explosion', attack_roll=10, field={})
    check(S, 'Explosion: self_ko (usuário desmaia)', re_.get('self_ko') is True)

    # Stat drop canônico on-hit: Overheat −2 SPA no PRÓPRIO usuário (100%)
    _arc = fresh('Arcanine', 50)
    for _ in range(10):
        rov = appmod._calc_attack_core(_arc, fresh('Snorlax', 50), 'Overheat',
                                       attack_roll=10, field={})
        if rov.get('damage', 0) > 0:
            break
        _arc = fresh('Arcanine', 50)
    check(S, 'Overheat: −2 SpA no usuário (recuo canônico)',
          (_arc.get('stat_stages') or {}).get('SPA') == -2)

    # Rapid Spin limpa semente/prisão do usuário
    _bl = fresh('Blastoise', 50)
    _sts = {'condition': 'seeded', 'turns_active': 2}
    for _ in range(10):
        rr2 = appmod._calc_attack_core(_bl, fresh('Snorlax', 50), 'Rapid Spin',
                                       attack_roll=10, attacker_status=_sts, field={})
        if rr2.get('damage', 0) > 0:
            break
    check(S, 'Rapid Spin limpa a semente do usuário', not _sts)

    # Rain Dance / Sunny Day existem no moves.json e viram campo
    check(S, 'Rain Dance e Sunny Day agora existem no moves.json',
          'rain dance' in appmod.MOVES_BY_NAME and 'sunny day' in appmod.MOVES_BY_NAME)
    rrd = se_mod.process_status_move(appmod.MOVES_BY_NAME['sunny day'],
                                     dict(_venu['stats'], level=50, maxHp=120, currentHp=120),
                                     dict(_lax['stats'], level=50, currentHp=120))
    check(S, 'Sunny Day resolve para efeito de campo (sol)',
          rrd.get('effect_type') == 'field' and rrd.get('field_value') == 'sun')

    # ══════════ COOLDOWN DE SUSTAIN (dreno / cura instantânea) ══════════
    section('Cooldown de dreno/cura instantânea')
    S = 'Sustain/Recarga'
    check(S, 'Giga Drain (POW 75, dreno) → recarga 1', appmod.bm_core.v3_move_cooldown(75, 50) == 1)
    check(S, 'Absorb (POW 20, dreno) → recarga 1', appmod.bm_core.v3_move_cooldown(20, 50) == 1)
    check(S, 'Dream Eater (POW 100, dreno) → recarga 2', appmod.bm_core.v3_move_cooldown(100, 50) == 2)
    check(S, 'POW 90 sem dreno segue a Tabela Mestra (1)', appmod.bm_core.v3_move_cooldown(90, 0) == 1)
    check(S, 'Hyper Beam (150) mantém recarga 3', appmod.bm_core.v3_move_cooldown(150, 0) == 3)
    # recarga por POW só a partir do degrau 70-80 (jogabilidade de mesa)
    check(S, 'recarga por POW: 55-65 livre, degrau 70-80 tem recarga 1',
          bmm.v3_cooldown(60) == 0 and bmm.v3_cooldown(65) == 0
          and bmm.v3_cooldown(70) == 1 and bmm.v3_cooldown(80) == 1)
    check(S, 'dados novos dos degraus altos: 120→5d6, 135→6d6, 150→4d10',
          bmm.v3_dice_base(120) == (5, 6) and bmm.v3_dice_base(135) == (6, 6)
          and bmm.v3_dice_base(150) == (4, 10))
    # RODADA DE FÔLEGO: moveset todo em recarga destrava sozinho
    _fol = {'name': 'Preso', 'moves': ['Fire Blast', 'Hyper Beam'],
            '_v3': {'cooldowns': {'fire blast': 2, 'hyper beam': 1}}}
    check(S, 'sem_opcao detecta moveset todo em recarga',
          appmod._v3_sem_opcao(_fol)
          and not appmod._v3_sem_opcao({'name': 'X', 'moves': ['Ember'],
                                        '_v3': {'cooldowns': {}}}))
    _msg_fol = appmod._v3_folego(_fol)
    check(S, 'fôlego: recargas caem 1 e o moveset destrava',
          'fôlego' in _msg_fol
          and _fol['_v3']['cooldowns'] == {'fire blast': 1}
          and not appmod._v3_sem_opcao(_fol))
    check(S, 'sem_opcao conta a recarga-bucket para golpes de cura',
          appmod._v3_sem_opcao({'name': 'H', 'moves': ['Recover'],
                                '_v3': {'cooldowns': {appmod.effects.HEAL_SUSTAIN_KEY: 2}}}))
    check(S, 'cura de metade/total → recarga 3 (jogo de 4-6 turnos); um quarto → 1',
          appmod.bm_core.v3_heal_cooldown('half') == 3 and appmod.bm_core.v3_heal_cooldown('full') == 3
          and appmod.bm_core.v3_heal_cooldown('quarter') == 1)
    # detecção pela MECÂNICA (drain canônico), sem lista fixa
    check(S, 'dreno detectado no dado canônico (giga drain: drain>0)',
          int(appmod.canon_move('giga drain').get('drain') or 0) > 0)
    # fluxo real: usar → bloquear → outro golpe destrava
    _susA = make_poke('Venusaur', 30)
    _susD = make_poke('Snorlax', 30)
    _r1 = appmod._calc_attack_core(_susA, _susD, 'Giga Drain')
    check(S, 'Giga Drain conecta e anuncia recarga 1',
          _r1.get('cooldown') == 1 and _susA['_v3']['cooldowns'].get('giga drain') == 1)
    _r2 = appmod._calc_attack_core(_susA, _susD, 'Giga Drain')
    check(S, 'reuso imediato é BLOQUEADO (não cicla cura todo turno)',
          _r2.get('blocked') is True)
    _r3 = appmod._calc_attack_core(_susA, _susD, 'Vine Whip')
    check(S, 'outro golpe passa e a recarga expira (1 ação = 1 rodada)',
          _r3.get('hit') and 'giga drain' not in _susA['_v3']['cooldowns'])
    # cura instantânea de status (Recover): recarga 3, bloqueio sem consumir
    _v3h = {}
    _md_rec = appmod.MOVES_BY_NAME.get('recover') or {'name': 'Recover'}
    _h1 = appmod.effects.process_status_move(_md_rec, {'maxHp': 100, '_v3': _v3h}, {})
    check(S, 'Recover cura metade e entra em recarga 3',
          _h1.get('heal') == 50 and _h1.get('cooldown') == 3)
    _h2 = appmod.effects.process_status_move(_md_rec, {'maxHp': 100, '_v3': _v3h}, {})
    check(S, 'Recover em recarga é bloqueado com a mensagem canônica',
          _h2.get('blocked') is True and 'recarga' in _h2.get('message', ''))
    # retorno DECRESCENTE anti-stall: 2ª cura na mesma batalha vale metade
    _v3h['cooldowns'].pop(appmod.effects.HEAL_SUSTAIN_KEY, None)
    _h3 = appmod.effects.process_status_move(_md_rec, {'maxHp': 100, '_v3': _v3h}, {})
    _v3h['cooldowns'].pop(appmod.effects.HEAL_SUSTAIN_KEY, None)
    _h4 = appmod.effects.process_status_move(_md_rec, {'maxHp': 100, '_v3': _v3h}, {})
    check(S, 'cura decrescente: 50 → 25 → 12 na mesma batalha (anti-loop)',
          _h3.get('heal') == 25 and _h4.get('heal') == 12
          and 'decrescente' in _h3.get('message', ''))
    appmod._v3_new_battle([{'_v3': _v3h}])
    check(S, 'batalha nova zera o retorno decrescente',
          'heal_uses' not in _v3h)
    check(S, 'Leech Seed drena ⌊HP/16⌋ (régua nova de DoT)',
          appmod.effects.seed_drain(160) == 10 and appmod.effects.seed_drain(320) == 20)
    # exceção: cura GRADUAL não ganha recarga (Leech Seed é condição por turno)
    _md_ls = appmod.MOVES_BY_NAME.get('leech seed') or {'name': 'Leech Seed'}
    _dls = appmod.effects.auto_detect_move_effect(_md_ls)
    check(S, 'exceção: Leech Seed (gradual) não é heal_self',
          (_dls or {}).get('type') != 'heal_self')
    # IA: selvagem/NPC não escolhe golpe em recarga
    _susA['_v3']['cooldowns']['giga drain'] = 2
    _susA['moves'] = ['Giga Drain', 'Vine Whip']
    _pick = appmod._npc_pick_move(_susA, _susD)
    check(S, 'IA evita golpe em recarga na escolha', _pick[0].lower() != 'giga drain')

    # ══════════ MIGRAÇÃO 5e→v3 DOS MOVES (Curse, estágios canônicos, d100) ══════════
    section('Migração 5e→v3 dos moves')
    S = 'Migração 5e→v3'
    _mdc = appmod.MOVES_BY_NAME.get('curse') or {'name': 'Curse'}
    _cg = appmod.effects.process_status_move(_mdc, {'maxHp': 100, 'types': ['Ghost'], '_v3': {}}, {})
    check(S, 'Curse (Fantasma): amaldiçoa o alvo e sacrifica ⌊HPmáx/2⌋',
          _cg.get('status_applied') == 'amaldicoado' and _cg.get('self_damage') == 50)
    _cn = appmod.effects.process_status_move(_mdc, {'maxHp': 100, 'types': ['Water'], '_v3': {}}, {})
    check(S, 'Curse (não-Fantasma): +1 ATK, +1 DEF, −1 SPE',
          _cn.get('stat_changes') == {'ATK': 1, 'DEF': 1, 'SPE': -1})
    _ok5, _dmg5, _msgs5, _rem5 = appmod.effects.process_turn_start(
        {'condition': 'amaldicoado', 'turns_active': 1}, 100)
    check(S, 'maldição tica ⌊HPmáx/4⌋ por rodada', _dmg5 == 25)
    # DoT escalonado (decisão do usuário): burn/toxic começam 1/16 e evoluem
    # (2/16, 3/16…) com TETO de ⌊HP/4⌋ por turno
    for _cond5 in ('queimado', 'badly_poisoned'):
        _t1 = appmod.effects.process_turn_start({'condition': _cond5, 'turns_active': 0}, 160)[1]
        _t2 = appmod.effects.process_turn_start({'condition': _cond5, 'turns_active': 1}, 160)[1]
        _t9 = appmod.effects.process_turn_start({'condition': _cond5, 'turns_active': 8}, 160)[1]
        check(S, f'{_cond5}: escala 1/16 → 2/16 com teto ¼ (10/20/40 de HP160)',
              _t1 == 10 and _t2 == 20 and _t9 == 40, f'{_t1}/{_t2}/{_t9}')
    # estágios canônicos multi-stat (Bulbapedia/pokemondb)
    for _mv5, _esp5 in (('dragon dance', {'ATK': 1, 'SPE': 1}),
                        ('calm mind', {'SPA': 1, 'SPD': 1}),
                        ('swords dance', {'ATK': 2}),
                        ('shell smash', {'ATK': 2, 'SPA': 2, 'SPE': 2, 'DEF': -1, 'SPD': -1})):
        _r5 = appmod.effects.process_status_move(
            appmod.MOVES_BY_NAME.get(_mv5), {'maxHp': 100, '_v3': {}}, {})
        check(S, f'{_mv5}: estágios canônicos', _r5.get('stat_changes') == _esp5,
              str(_r5.get('stat_changes')))
    # dormir/congelar resolvem por d100 (Pokémon nunca rola d20)
    _slept = appmod.effects.process_turn_start({'condition': 'dormindo', 'turns_active': 1}, 100)
    check(S, 'checagem de acordar usa d100', any('d100' in m for m in _slept[2]))
    check(S, 'nenhuma mensagem de status usa d20', not any('d20' in m for m in _slept[2]))
    # Sheer Cold virou OHKO (como Fissure/Guillotine/Horn Drill)
    _sc5 = appmod.effects.auto_detect_move_effect(appmod.MOVES_BY_NAME.get('sheer cold'))
    check(S, 'Sheer Cold é OHKO (não congelamento)', (_sc5 or {}).get('type') == 'ohko')
    # AUDITORIA AUTOMÁTICA: zero resíduo 5e nos dados e no motor de efeitos
    import re as _re5
    import json as _json5
    _t5e = _re5.compile(r'CD ?\d+|[Ss]alvaguarda|Sabedoria|Constituição|Destreza|Carisma|d20|proficiência|DC ?\d+')
    _sujos = [n for n, m in (appmod.MOVES_DB or {}).items()
              if isinstance(m, dict) and _t5e.search(str(m.get('description', '')))]
    check(S, 'nenhuma descrição de move com termos 5e', not _sujos, str(_sujos[:6]))
    _mfx5 = _json5.load(open('server/data/move_effects.json'))
    _saves5 = [n for n, v in _mfx5.items()
               if isinstance((v or {}).get('effect'), dict) and 'save' in v['effect']]
    check(S, "nenhum campo 'save' (5e) no move_effects.json", not _saves5, str(_saves5[:6]))
    _src5 = open('status_effects.py').read()
    check(S, "nenhum campo 'save' nas tabelas do motor", "'save':" not in _src5)
    # d100 TOTAL no combate de Pokémon: zero d20 no motor de efeitos e no
    # núcleo matemático (o d20 que resta no app.py é perícia de TREINADOR —
    # /api/roll, caçada, testes de atributo — fora do combate).
    check(S, 'zero d20 no motor de efeitos (combate 100% d100)',
          _src5.count('randint(1, 20)') == 0)
    _srcbm = open('battle_math.py').read()
    check(S, 'zero d20 no núcleo matemático v3',
          _srcbm.count('randint(1, 20)') == 0)

    # ────────────────────────── RELATÓRIO ──────────────────────────
    print('\n' + '═' * 62)
    print('📊 SCORECARD FINAL')
    print('═' * 62)
    total_ok = total_all = 0
    for system, checks in RESULTS.items():
        ok = sum(1 for _, o, _ in checks if o)
        n = len(checks)
        total_ok += ok
        total_all += n
        pct = 100 * ok / n
        bar = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
        print(f'  {system:24s} {bar} {ok:>2}/{n:<2} ({pct:.0f}%)')
    print('─' * 62)
    print(f'  TOTAL: {total_ok}/{total_all} ({100 * total_ok / total_all:.0f}%)')
    print('\nFalhas detalhadas:')
    any_fail = False
    for system, checks in RESULTS.items():
        for name, o, note in checks:
            if not o:
                any_fail = True
                print(f'  ❌ [{system}] {name}{" — " + note if note else ""}')
    if not any_fail:
        print('  (nenhuma)')


if __name__ == '__main__':
    main()
