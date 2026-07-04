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
    r = register(m, 'gm_rev', 'master')
    check(S, 'registro de mestre', r.status_code in (200, 302))
    check(S, 'login mestre', login(m, 'gm_rev').status_code == 302)
    mid = uid_of('gm_rev')
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
    r = p1.post('/api/pokemon/battle-xp', json={'winner_level': 20, 'loser_level': 18, 'battle_type': 'wild'})
    check(S, 'XP de batalha calculado', (r.get_json() or {}).get('xp_gained', 0) > 0)

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
        while view and view.get('phase') == 'active' and guard < 120:
            guard += 1
            turn = next((c for c in view['combatants'] if c['cid'] == view['turn_cid']), None)
            if not turn or turn['side'] != 'ally':
                break  # com AUTO ligado os selvagens já jogaram; só aliados esperam ação
            cli = clients.get(str(turn['player_id']))
            alive_wild = next((c['cid'] for c in view['combatants']
                               if c['side'] == 'wild' and not c['fainted']), None)
            cli.emit('group_battle_action', {'battle_id': view['id'],
                     'move_name': (turn['moves'] or ['Tackle'])[0], 'target_cid': alive_wild})
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

    # ══════════ 5. XP & EVOLUÇÃO ══════════
    section('5. XP, level-up e evoluções')
    S = 'XP/Evolução'
    r = m.post('/master/xp', json={'player_id': u2, 'xp': 2500})
    check(S, 'XP de treinador', r.status_code == 200)
    team2 = db.get_users()[u2]['trainer_data']['team']
    check(S, 'time nivela + evolui por nível',
          any(p['name'] in ('Ivysaur', 'Venusaur') for p in team2), f"{[p['name'] for p in team2]}")
    r = m.post('/master/pokemon-xp', json={'player_id': u1, 'pokemon_idx': 0, 'xp': 4000})
    check(S, 'XP direto no pokémon (tabela real)', (r.get_json() or {}).get('leveled_up'))
    users = db.get_users()
    users[u1]['trainer_data']['bag'].append({'name': 'Thunder Stone', 'qty': 1})
    users[u1]['trainer_data']['team'].append(make_poke('Pikachu', 20))
    db.save_users(users)
    idx = len(users[u1]['trainer_data']['team']) - 1
    r = p1.post('/player/use-stone', json={'pokemon_idx': idx, 'item_name': 'Thunder Stone'})
    d = r.get_json() or {}
    check(S, 'evolução por pedra (Pikachu→Raichu)',
          (d.get('ok') or d.get('success')) and 'Raichu' in str(d), f'{d}')
    users = db.get_users()
    users[u1]['trainer_data']['team'].append(make_poke('Golbat', 30, battle_wins=10))
    db.save_users(users)
    idx = len(users[u1]['trainer_data']['team']) - 1
    r = p1.post('/player/friendship-evolve', json={'pokemon_idx': idx})
    d = r.get_json() or {}
    check(S, 'evolução por amizade (Golbat→Crobat)',
          (d.get('ok') or d.get('success')) and 'Crobat' in str(d), f'{list(d.keys())}')
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
    check(S, 'status move processado com CD', 'CD' in (r.get_json() or {}).get('message', ''))
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
        for _ in range(200):
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
            tsio.emit('pvp_attack', {'battle_id': bid,
                                     'move_name': (poke.get('moves') or ['Tackle'])[0],
                                     'attack_roll': random.randint(1, 20)})
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
            for _ in range(250):
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
                                           'move_name': (poke.get('moves') or ['Tackle'])[0],
                                           'attack_roll': random.randint(1, 20)})
                    recv(s1)
                else:
                    appmod.handle_npc_turn(battle, 'player2')
            check(S, 'batalha vs NPC termina', battle['phase'] == 'finished', f"fase={battle['phase']}")

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
