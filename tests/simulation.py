"""
Simulação de sessão longa de RPG — mestre + jogadores + NPCs + selvagens.

Simula horas de jogo real: centenas de encontros selvagens com batalhas
turno a turno, moves de status, capturas, XP, evolução, batalhas PvP
contra NPCs com IA autônoma e verificação de invariantes a cada passo.

Uso:
    DATABASE_URL=postgresql://postgres@127.0.0.1:5433/pokemon_sim python tests/simulation.py [n_batalhas]

Requer um PostgreSQL vazio/descartável (NÃO use o banco de produção).
"""
import os
import sys
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

if not os.environ.get('DATABASE_URL'):
    print('ERRO: defina DATABASE_URL para um banco de teste descartável.')
    sys.exit(1)

import app as appmod
from app import app, socketio
import database as db
import pokemon_scaling as scaling
import status_effects as effects
import pvp_battle as pvp

random.seed()

N_BATTLES = int(sys.argv[1]) if len(sys.argv) > 1 else 200

ERRORS = []
TABLE_ID = 'default'
MASTER_HTTP = None   # test client do mestre (avança o dia quando as caçadas acabam)

STATS = {
    'battles': 0, 'rounds': 0, 'player_wins': 0, 'wild_wins': 0, 'captures': 0,
    'status_applied_on_hit': 0, 'status_moves_used': 0, 'status_moves_applied': 0,
    'evolutions': 0, 'pvp_battles': 0, 'pvp_npc_wins': 0, 'level_ups': 0,
    'wild_status_skips': 0, 'hunt_fails': 0, 'ambushes': 0, 'days_advanced': 0,
}


def advance_day(days=1):
    """Mestre avança o calendário (reseta caçadas, processa NPCs, eventos)."""
    r = MASTER_HTTP.post('/master/calendar/advance', json={'days': days})
    check(r.status_code == 200, f'calendar/advance falhou: {r.status_code}')
    STATS['days_advanced'] += days
    return r.get_json()


def check(cond, msg):
    if not cond:
        ERRORS.append(msg)
        print(f'  ❌ INVARIANTE VIOLADA: {msg}')


def register_and_login(client, username, role, invite=None):
    data = {'username': username, 'password': 'senha123', 'role': role}
    if invite:
        data['invite_code'] = invite
    client.post('/register', data=data)
    client.post('/login', data={'username': username, 'password': 'senha123'})


def get_uid(username):
    for uid, u in db.get_users().items():
        if u['username'] == username:
            return uid
    return None


def give_starter(uid, species, level):
    users = db.get_users()
    trainer = users[uid]['trainer_data']
    base = appmod.POKEMON_BY_NAME[species.lower()]
    scaled = scaling.calculate_pokemon_stats(base, level)
    moves = list(base.get('startingMoves', []))
    for lv, ms in (base.get('levelMoves') or {}).items():
        if int(lv) * 5 <= level:
            moves.extend(ms)
    moves = [m for m in moves if m.lower() in appmod.MOVES_BY_NAME][-4:] or ['Tackle']
    trainer['team'] = [{
        'name': base['name'], 'number': base['number'], 'level': level,
        'types': base['types'], 'maxHp': scaled['maxHp'], 'currentHp': scaled['hp'],
        'hp': scaled['hp'], 'ac': scaled['ac'], 'stats': scaled['stats'],
        'proficiency': scaled['proficiency'], 'stab': scaled['stab'],
        'moves': moves,
        'vulnerabilities': base.get('vulnerabilities', []),
        'resistances': base.get('resistances', []),
        'immunities': base.get('immunities', []),
        'ability': (base.get('ability') or {}).get('name', ''),
        'evolutionInfo': base.get('evolutionInfo', ''),
        'xp': 0, 'totalXp': 0, 'battle_wins': 0,
    }]
    trainer['bag'] = [{'name': 'Pokébola', 'qty': 999}]
    trainer['level'] = max(1, level // 5)
    trainer['wis'] = 14   # ajuda o teste de Sobrevivência na simulação
    users[uid]['trainer_data'] = trainer
    db.save_users(users)


def wild_battle(http, sio, uid, username, battle_no):
    """Simula uma batalha selvagem completa turno a turno."""
    users = db.get_users()
    team = users[uid]['trainer_data']['team']
    poke = team[0]
    player_level = poke['level']

    # ── Teste de caçada MANUAL: o jogador rola o d20 (gasta 1 tentativa) ──
    roll = http.post('/api/hunt/roll', json={})
    if roll.status_code == 429:
        appmod._rate_store.clear()
        roll = http.post('/api/hunt/roll', json={})
    if roll.status_code == 403:
        # Sem caçadas hoje → mestre avança o dia e tenta de novo
        body = roll.get_json()
        check(body.get('used', 0) >= 6, '403 sem o contador de caçadas esgotado')
        advance_day(1)
        roll = http.post('/api/hunt/roll', json={})
    check(roll.status_code == 200, f'hunt/roll falhou: {roll.status_code}')
    rj = roll.get_json()
    check(1 <= rj.get('roll', 0) <= 20, 'd20 fora do intervalo')
    check(rj.get('total') == rj['roll'] + rj['skill_mod'], 'total do teste inconsistente')

    # invariante do gate: contador dentro do limite
    state = db.get_game_state(TABLE_ID)
    hentry = (state.get('hunts') or {}).get(uid, {})
    limit = 6 + int(hentry.get('bonus', 0))
    check(hentry.get('used', 0) <= limit, 'contador de caçadas acima do limite')

    # ── O mestre libera a caçada aleatória para este jogador ──
    hunt_mode = random.choice(['normal', 'normal', 'dungeon'])
    rel = MASTER_HTTP.post('/master/hunt/random', json={
        'player_id': uid, 'hunt_mode': hunt_mode, 'route_id': 'route1'})
    check(rel.status_code == 200, f'master/hunt/random falhou: {rel.status_code}')
    enc = rel.get_json().get('encounter', {})
    check(enc.get('found') is True, 'encontro liberado sem found=True')
    check(1 <= enc.get('level', 0) <= 100, 'nível do encontro fora de 1-100')
    if enc.get('ambush'):
        STATS['ambushes'] += 1

    wild = enc['pokemon']

    sio.emit('start_encounter', {
        'pokemon': wild, 'level': enc['level'], 'is_shiny': enc['is_shiny'],
        'route_id': 'route1', 'player_pokemon': poke['name'],
        'player_pokemon_idx': 0, 'wild_moves': enc['wild_moves']})
    received = sio.get_received()

    state = db.get_game_state(TABLE_ID)
    encounter = state['active_encounters'].get(uid)
    check(encounter is not None, 'encontro não registrado no game_state')
    if not encounter:
        return
    bs = encounter['battle_state']
    check(bs['initiative_rolled'], 'iniciativa não foi rolada automaticamente (WILD_AUTO_MODE)')
    check(bs['turn'] in ('player', 'wild'), f'turno inválido: {bs["turn"]}')

    wild_hp_max = bs['wild_hp_max']
    player_hp_max = bs['player_hp_max']
    player_moves = poke['moves']
    wild_status = None
    rounds = 0

    for _ in range(60):  # limite de segurança de turnos
        state = db.get_game_state(TABLE_ID)
        encounter = state['active_encounters'].get(uid)
        if not encounter:
            break
        bs = encounter['battle_state']

        check(bs['wild_hp_current'] <= wild_hp_max, 'HP do selvagem acima do máximo')
        check(bs['player_hp_current'] <= player_hp_max, 'HP do jogador acima do máximo')
        check(bs['wild_hp_current'] >= -30, 'HP do selvagem abaixo do piso de -30')
        check(bs['player_hp_current'] >= -30, 'HP do jogador abaixo do piso de -30')

        if bs['wild_hp_current'] <= 0:
            STATS['player_wins'] += 1
            # tenta captura ou encerra
            if random.random() < 0.5:
                STATS['captures'] += 1
                sio.emit('end_encounter', {'result': 'caught'})
            else:
                sio.emit('end_encounter', {'result': 'defeated',
                                           'active_pokemon_name': poke['name']})
            sio.get_received()
            break
        if bs['player_hp_current'] <= 0:
            STATS['wild_wins'] += 1
            sio.emit('end_encounter', {'result': 'fainted'})
            sio.get_received()
            break

        rounds += 1
        if bs['turn'] == 'player':
            move = random.choice(player_moves)
            mdata = appmod.MOVES_BY_NAME.get(move.lower(), {})
            if mdata.get('category') == 'status' or not mdata.get('baseDamage'):
                # move de status via API (como o cliente faz)
                STATS['status_moves_used'] += 1
                r = http.post('/api/process-status-move', json={
                    'move_name': move,
                    'attacker_stats': dict(poke['stats'], level=poke['level'],
                                           proficiency=poke['proficiency'],
                                           maxHp=poke['maxHp']),
                    'target_stats': dict(wild.get('stats', {}), level=enc['level'])})
                check(r.status_code == 200, f'process-status-move {move}: {r.status_code}')
                res = r.get_json()
                check('message' in res, f'status move {move} sem message')
                if res.get('status_applied'):
                    STATS['status_moves_applied'] += 1
                sio.emit('battle_action', {
                    'action_by': 'player', 'action_type': 'status', 'move_name': move,
                    'damage': 0, 'status_effect': res.get('status_applied'),
                    'message': res.get('message', '')})
            else:
                sio.emit('battle_action', {
                    'action_by': 'player', 'action_type': 'attack', 'move_name': move,
                    'attack_roll': random.randint(1, 20)})
            recv = sio.get_received()
            for pkt in recv:
                if pkt['name'] == 'battle_update':
                    d = pkt['args'][0]
                    sc = d.get('server_calc') or {}
                    if sc.get('status_inflicted'):
                        STATS['status_applied_on_hit'] += 1
                    if sc.get('hit'):
                        check(d['damage'] >= 0, 'dano negativo')
        else:
            # turno do selvagem — simula a IA do cliente com dano server-like
            state = db.get_game_state(TABLE_ID)
            encounter = state['active_encounters'][uid]
            bs = encounter['battle_state']
            wild_status = bs.get('wild_status')
            wild_dmg = 0
            pre_dmg = 0
            if wild_status:
                can_act, dmg, msgs, removed = effects.process_turn_start(
                    wild_status, wild_hp_max)
                pre_dmg = dmg
                if removed:
                    sio.emit('status_resolved', {'target': 'wild'})
                    sio.get_received()
                if not can_act:
                    STATS['wild_status_skips'] += 1
                    sio.emit('battle_action', {
                        'action_by': 'master', 'action_type': 'pass',
                        'move_name': 'Status impediu', 'damage': 0,
                        'wild_status_damage': pre_dmg, 'message': 'não agiu'})
                    sio.get_received()
                    continue
            # ataque simples do selvagem
            wmoves = encounter.get('wild_moves') or ['Tackle']
            wmove = random.choice(wmoves)
            wdata = appmod.MOVES_BY_NAME.get(wmove.lower(), {})
            if wdata.get('baseDamage'):
                calc = appmod._calc_pvp_attack(
                    dict(wild, level=enc['level']), poke, wmove)
                wild_dmg = calc['damage']
            sio.emit('battle_action', {
                'action_by': 'master', 'action_type': 'attack', 'move_name': wmove,
                'damage': wild_dmg, 'wild_status_damage': pre_dmg,
                'message': 'wild attack'})
            sio.get_received()

    else:
        # loop não terminou — força encerramento
        sio.emit('end_encounter', {'result': 'fled'})
        sio.get_received()

    STATS['battles'] += 1
    STATS['rounds'] += rounds

    # XP pós-batalha (como o cliente): vitória dá XP ao pokémon via master route
    state = db.get_game_state(TABLE_ID)
    check(uid not in state['active_encounters'], 'encontro não foi limpo ao terminar')


def pvp_npc_battle(master_http, master_sio, player_sio, uid):
    """NPC desafia o jogador; jogador ataca, NPC age sozinho (IA servidor)."""
    r = master_http.post('/master/npcs/generate', json={
        'npc_class': 'Trainer', 'level': 12, 'team_size': 2})
    check(r.status_code == 200, f'generate_npc: {r.status_code}')
    npc = r.get_json()
    for p in npc['team']:
        check(p.get('moves'), f'NPC pokemon {p["name"]} sem moves')
        check(p.get('maxHp', 0) > 0, f'NPC pokemon {p["name"]} sem HP')
        check(p.get('stats', {}).get('ATK') is not None, 'NPC sem stats novos')

    master_sio.emit('master_pvp_challenge', {
        'npc_id': npc['id'], 'target_id': uid, 'mode': 'street'})
    master_sio.get_received()
    recv = player_sio.get_received()
    battle_id = None
    for pkt in recv:
        if pkt['name'] == 'pvp_battle_created':
            battle_id = pkt['args'][0]['battle_id']
    check(battle_id is not None, 'pvp_battle_created não recebido pelo jogador')
    if not battle_id:
        return

    player_sio.emit('pvp_select_pokemon', {'battle_id': battle_id, 'pokemon_idx': 0})
    player_sio.get_received()

    battle = appmod.ACTIVE_PVP.get(battle_id)
    check(battle is not None, 'batalha PVP não está ativa')
    if not battle:
        return
    check(battle['phase'] == 'battle', f'fase inesperada: {battle["phase"]}')

    users = db.get_users()
    moves = users[uid]['trainer_data']['team'][0]['moves']

    for _ in range(80):
        battle = appmod.ACTIVE_PVP.get(battle_id)
        if not battle or battle['phase'] != 'battle':
            break
        for key in ('player1', 'player2'):
            side = battle[key]
            active = side['team'][side['active_idx']]
            check(active.get('currentHp', 0) <= active.get('maxHp', 20),
                  'PVP: HP acima do máximo')
        if battle['turn'] == 'player2':  # jogador humano
            player_sio.emit('pvp_attack', {
                'battle_id': battle_id, 'move_name': random.choice(moves),
                'attack_roll': random.randint(1, 20)})
            player_sio.get_received()
        else:
            # NPC é acionado automaticamente pelo servidor após ações do jogador;
            # se por algum motivo ficou pendente, força via master
            appmod.handle_npc_turn(battle, 'player1')
    battle = appmod.ACTIVE_PVP.get(battle_id)
    if battle and battle['phase'] == 'battle':
        player_sio.emit('pvp_forfeit', {'battle_id': battle_id})
        player_sio.get_received()
        battle['phase'] = 'finished'
    STATS['pvp_battles'] += 1
    if battle and battle.get('winner') == 'player1':
        STATS['pvp_npc_wins'] += 1


def main():
    print(f'🎲 Simulando sessão longa: {N_BATTLES} batalhas selvagens + PvP com NPCs\n')

    app.config['TESTING'] = True

    master_http = app.test_client()
    p1_http = app.test_client()
    p2_http = app.test_client()

    register_and_login(master_http, 'mestre_sim', 'master')
    master_uid = get_uid('mestre_sim')
    tables = db.get_tables_for_master(master_uid)
    invite = tables[0]['invite_code']

    global TABLE_ID, MASTER_HTTP
    TABLE_ID = tables[0]['id']
    MASTER_HTTP = master_http

    register_and_login(p1_http, 'jogador1', 'player', invite)
    register_and_login(p2_http, 'jogador2', 'player', invite)
    p1_uid, p2_uid = get_uid('jogador1'), get_uid('jogador2')

    give_starter(p1_uid, 'Charmander', 12)
    give_starter(p2_uid, 'Squirtle', 15)

    # ---- Setup do calendário: NPC com progressão + evento futuro ----
    r = master_http.post('/master/npcs/generate', json={
        'npc_class': 'Trainer', 'level': 10, 'team_size': 2,
        'progression_enabled': True, 'growth_rate': 'fast'})
    check(r.status_code == 200, f'NPC de progressão: {r.status_code}')
    prog_npc_id = r.get_json()['id']
    prog_npc_levels = [p['level'] for p in r.get_json()['team']]

    r = master_http.post('/master/calendar/events', json={
        'title': 'Torneio da Simulação', 'city': 'Hammerlocke',
        'day': 4, 'month': 1, 'year': 1, 'notify_days_before': 2,
        'description': 'Evento de teste'})
    check(r.status_code == 200, f'criar evento: {r.status_code}')
    event_id = r.get_json()['id']

    master_sio = socketio.test_client(app, flask_test_client=master_http)
    p1_sio = socketio.test_client(app, flask_test_client=p1_http)
    p2_sio = socketio.test_client(app, flask_test_client=p2_http)
    for c in (master_sio, p1_sio, p2_sio):
        c.get_received()

    # ---- Fase 1: muitas batalhas selvagens (jogadores alternando) ----
    for i in range(N_BATTLES):
        appmod._rate_store.clear()  # evita rate-limit da simulação acelerada
        uid, http, sio, name = random.choice([
            (p1_uid, p1_http, p1_sio, 'jogador1'),
            (p2_uid, p2_http, p2_sio, 'jogador2')])
        wild_battle(http, sio, uid, name, i)
        if (i + 1) % 25 == 0:
            print(f'  ... {i+1}/{N_BATTLES} batalhas '
                  f'(V:{STATS["player_wins"]} D:{STATS["wild_wins"]} '
                  f'capturas:{STATS["captures"]} status-on-hit:{STATS["status_applied_on_hit"]})')

    # ---- Fase 2: XP em massa → level up + evolução ----
    print('\n📈 Testando XP/level-up/evolução via mestre...')
    for uid in (p1_uid, p2_uid):
        before = db.get_users()[uid]['trainer_data']['team'][0]
        old_name, old_level = before['name'], before['level']
        r = master_http.post('/master/xp', json={'player_id': uid, 'xp': 2000})
        check(r.status_code == 200, f'/master/xp: {r.status_code}')
        r2 = master_http.post('/master/pokemon-xp', json={
            'player_id': uid, 'pokemon_idx': 0, 'xp': 5000})
        check(r2.status_code == 200, f'/master/pokemon-xp: {r2.status_code}')
        after = db.get_users()[uid]['trainer_data']['team'][0]
        if after['level'] > old_level:
            STATS['level_ups'] += 1
        if after['name'] != old_name:
            STATS['evolutions'] += 1
            check(after.get('immunities') is not None, 'evolução perdeu immunities')
            check(after.get('totalXp', 0) > 0, 'evolução perdeu totalXp')
            print(f'  🎉 {old_name} evoluiu para {after["name"]} (Nv.{after["level"]})')
        check(after.get('stats', {}).get('ATK') is not None,
              'level-up não recalculou stats novos')

    # ---- Fase 3: escala de dano por nível ----
    print('\n⚔️ Verificando aumento de dano por nível...')
    for lv_low, lv_high in [(5, 25), (25, 60), (60, 95)]:
        d_low = appmod._get_scaled_dice('2d6', lv_low)
        d_high = appmod._get_scaled_dice('2d6', lv_high)
        n_low = int(d_low.split('d')[0])
        n_high = int(d_high.split('d')[0])
        check(n_high >= n_low, f'dano não cresce: Nv{lv_low}={d_low} vs Nv{lv_high}={d_high}')
        print(f'  Nv.{lv_low}: 2d6 → {d_low} | Nv.{lv_high}: 2d6 → {d_high}')
    check(appmod._get_scaled_dice('1d6', 10) == scaling.get_scaled_damage_dice('1d6', 10),
          'servidor e scaling.py divergem na escala de dados')

    # ---- Fase 4: PvP contra NPC com IA autônoma ----
    print('\n🤖 Batalhas PvP contra NPCs (IA autônoma)...')
    for _ in range(5):
        pvp_npc_battle(master_http, master_sio, p1_sio, p1_uid)

    # ---- Fase 4b: calendário, caçadas e progressão de NPCs ----
    print('\n📅 Testando calendário, caçadas e progressão de NPCs...')
    state = db.get_game_state(TABLE_ID)
    cal_before = state.get('calendar') or {'day': 1, 'month': 1, 'year': 1}

    # rollover de mês: avança 30 dias de uma vez
    res = advance_day(30)
    cal_after = res['calendar']
    abs_before = (cal_before['year']-1)*360 + (cal_before['month']-1)*30 + cal_before['day']
    abs_after = (cal_after['year']-1)*360 + (cal_after['month']-1)*30 + cal_after['day']
    check(abs_after - abs_before == 30, f'avanço de 30 dias inconsistente: {cal_before} → {cal_after}')
    check(1 <= cal_after['day'] <= 30 and 1 <= cal_after['month'] <= 12, 'data fora dos limites')

    # caçadas zeradas após o advance
    state = db.get_game_state(TABLE_ID)
    check(state.get('hunts') == {}, 'hunts não foram zeradas no advance')

    # evento já deve ter passado (dia 4 do mês 1)
    r = p1_http.get('/api/calendar')
    evs = {e['id']: e for e in r.get_json()['events']}
    check(event_id in evs, 'evento sumiu do calendário')
    check(evs[event_id]['days_until'] <= 0, 'evento deveria estar no passado após 30+ dias')

    # NPC com progressão: diário cresceu e níveis subiram (fast, ~30 dias)
    npc = next((n for n in db.get_npcs(TABLE_ID) if n['id'] == prog_npc_id), None)
    check(npc is not None, 'NPC de progressão sumiu')
    if npc:
        diary_days = STATS['days_advanced']
        check(len(npc.get('diary', [])) >= min(30, diary_days) * 0.9,
              f'diário do NPC muito curto: {len(npc.get("diary", []))} entradas p/ {diary_days} dias')
        for i, p in enumerate(npc.get('team', [])):
            check(p['level'] >= prog_npc_levels[i] if i < len(prog_npc_levels) else True,
                  'nível do pokémon do NPC regrediu')
            check(p['level'] <= 100, 'nível do NPC passou de 100')
            check(p.get('stats', {}).get('ATK') is not None, 'stats do NPC não re-escalados')
        grew = any(p['level'] > prog_npc_levels[i]
                   for i, p in enumerate(npc.get('team', [])) if i < len(prog_npc_levels))
        check(grew, 'NPC fast não progrediu nenhum nível em ~30 dias (esperado ~+30)')
        print(f'  NPC treinou: níveis {prog_npc_levels} → {[p["level"] for p in npc.get("team", [])]}'
              f' | diário: {len(npc.get("diary", []))} entradas')

    # /master/hunts: grant aumenta o limite; reset zera o uso
    r = master_http.post('/master/hunts', json={'player_id': p1_uid, 'action': 'grant', 'amount': 2})
    check(r.status_code == 200 and r.get_json()['limit'] == 8, 'grant não elevou o limite p/ 8')
    r = p1_http.post('/api/hunt/roll', json={})
    check(r.status_code == 200, 'rolagem de caçada após grant falhou')
    r = master_http.post('/master/hunts', json={'player_id': p1_uid, 'action': 'reset'})
    check(r.status_code == 200 and r.get_json()['used'] == 0, 'reset não zerou o contador')

    # /api/hunts/status coerente
    r = p1_http.get('/api/hunts/status')
    st = r.get_json()
    check(r.status_code == 200 and st['used'] == 0 and st['limit'] >= 6, 'hunts/status incoerente')

    # teste MANUAL: a rolagem envia o total ao mestre (sem gerar encontro sozinho)
    appmod._rate_store.clear()
    r = p1_http.post('/api/hunt/roll', json={'manual_roll': 17})
    rj = r.get_json()
    check(r.status_code == 200 and rj['roll'] == 17 and rj['manual'] is True,
          'rolagem manual (dado físico) não respeitou o valor informado')
    check('found' not in rj and 'pokemon' not in rj, 'hunt/roll não deveria gerar encontro')

    # o mestre libera uma caçada aleatória → encontro chega pronto
    r = master_http.post('/master/hunt/random', json={
        'player_id': p1_uid, 'hunt_mode': 'dungeon_night', 'route_id': 'route1'})
    rj = r.get_json()
    check(r.status_code == 200 and rj.get('encounter', {}).get('found') is True,
          'master/hunt/random não gerou encontro')
    check(rj['encounter']['hunt_mode'] == 'dungeon_night', 'hunt_mode não respeitado na caçada aleatória')

    # anti-fadiga: esgota as caçadas e confirma 403 na rolagem
    blocked = False
    for _ in range(st['limit'] + 4):
        appmod._rate_store.clear()
        r = p1_http.post('/api/hunt/roll', json={})
        if r.status_code == 403:
            blocked = True
            break
    check(blocked, 'limite de caçadas não bloqueou a rolagem após esgotar as tentativas')
    advance_day(1)  # limpa para as fases seguintes

    # ---- Fase 5: moves de status em amostra ampla ----
    print('\n✨ Testando amostra de moves de status...')
    status_sample = [k for k, v in appmod.MOVES_DB.items()
                     if v.get('category') == 'status'][:80]
    detected = 0
    for mv in status_sample:
        r = p1_http.post('/api/process-status-move', json={
            'move_name': mv,
            'attacker_stats': {'ATK': 16, 'SPA': 14, 'level': 20, 'proficiency': 3, 'maxHp': 50},
            'target_stats': {'DEF': 12, 'SPD': 12, 'SPE': 12, 'level': 20}})
        check(r.status_code == 200, f'status move {mv} retornou {r.status_code}')
        res = r.get_json()
        if res.get('effect_type') not in ('utility',):
            detected += 1
    print(f'  {detected}/{len(status_sample)} moves de status com efeito detectado')
    check(detected >= len(status_sample) * 0.5,
          f'menos da metade dos status moves tem efeito ({detected}/{len(status_sample)})')

    # ---- Relatório ----
    print('\n' + '=' * 60)
    print('📊 RELATÓRIO DA SIMULAÇÃO')
    print('=' * 60)
    for k, v in STATS.items():
        print(f'  {k}: {v}')
    avg = STATS['rounds'] / max(1, STATS['battles'])
    print(f'  média de rounds/batalha: {avg:.1f}')
    print(f'\n{"✅ NENHUMA" if not ERRORS else "❌ " + str(len(ERRORS))} invariante(s) violada(s)')
    if ERRORS:
        uniq = sorted(set(ERRORS))
        for e in uniq[:20]:
            print(f'   - {e} (x{ERRORS.count(e)})')
        sys.exit(1)
    print('Simulação concluída com sucesso.')


if __name__ == '__main__':
    main()
